"""
Draft board caching (2026-10-19 slowdown fix).

Root cause this module exists for: GET /drafts/{id}/state rebuilt the
ENTIRE undrafted player pool (~6,500 full Player ORM rows, including every
player's week_stats/projected_stats JSON) on every poll, re-scored every
player twice with calculate_player_score, shipped each player's raw stats
blob (~10 MB of JSON per response) and then ran FastAPI's jsonable_encoder
over all of it -- ~2 s of synchronous CPU on the single event loop per
poll. The draft room polls every 1.2 s while a CPU team is on the clock,
with no in-flight guard, so two open draft rooms were enough for polls to
overlap, the loop to saturate (p95 30 s, /state up to 70 s), every other
request (auth, notifications, leagues) to queue behind them, and the
SQLAlchemy pool (5 + 10) to run dry -- which in turn starved the draft
watchdog itself ("QueuePool limit ... reached") so CPU picks and expired
clocks stalled. The CPU pick path (get_ai_mock_pick) had the same shape:
~1 s of full-pool loading + ranking per pick.

What's cached here, and why each key is valid:

* PlayerCatalog -- every draftable player's display fields, rank and the
  season/projected points under ONE scoring config, pre-sorted. None of
  that depends on which players have been drafted (rank_by_id was already
  computed over available + drafted = the whole eligible pool), so it's
  built once per (scoring config, player-pool signature) and refreshed
  every CATALOG_TTL_S for injury/team changes from the hourly sync. It is
  built from plain column tuples in a worker thread, never on the loop.

* Encoded state -- the full JSON body of /state for one draft, keyed by
  everything that can change it (pick count, clock, pause, teams, catalog
  version). Every viewer sees the same state, so N clients polling cost
  one build + encode per pick instead of N. Builds are single-flight per
  draft (an asyncio.Lock), and the body is stored pre-gzipped with an
  ETag so unchanged polls are 304s.

In-process only, like the existing _rank_cache: a redeploy just rebuilds
on the next request.
"""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import Player
from app.services.scoring_engine import calculate_player_score
from app.services.sleeper_sync import (
    effective_season_stats,
    headline_stats as compute_headline_stats,
    sleeper_avatar_url,
)

CATALOG_TTL_S = 300.0
# Encoded-state cache: drafts not polled for this long are evicted.
STATE_IDLE_EVICT_S = 600.0
STATE_CACHE_MAX_DRAFTS = 64

_POS_ORDER = ["RB", "WR", "QB", "TE", "K", "DEF", "DB", "DL", "LB"]

# Only what the catalog needs -- NOT week_stats/projected_stats, the two
# biggest JSON columns, which the draft board never shows.
_CATALOG_COLUMNS = (
    Player.id, Player.first_name, Player.last_name, Player.position, Player.team,
    Player.age, Player.number, Player.sleeper_id, Player.bye_week, Player.injury_status,
    Player.fantasy_positions, Player.search_rank, Player.stats, Player.stats_year,
    Player.last_season_stats, Player.last_season_year,
)


def scoring_key(scoring_config: Optional[dict]) -> str:
    return hashlib.sha1(json.dumps(scoring_config or {}, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class PlayerCatalog:
    version: str
    built_at: float
    # Sorted by the draft board's display order: (rank, position, last name).
    entries: list[dict]
    # id -> index into entries
    index: dict[str, int]
    rank_by_id: dict[str, int]
    # Lightweight CPU-pick records in rank order: (id, position, team, age)
    cpu_records: list[tuple] = field(default_factory=list)


_catalogs: dict[str, PlayerCatalog] = {}
_catalog_locks: dict[str, asyncio.Lock] = {}


def clear_caches() -> None:
    """Drop every cached catalog/state (tests; also safe at any time)."""
    _catalogs.clear()
    _catalog_locks.clear()
    _state_cache.clear()
    _state_locks.clear()


async def _pool_signature(db: AsyncSession, positions: set[str]) -> str:
    """Cheap fingerprint of the eligible pool: changes when players are
    added/removed (new sync, different database). Attribute changes from the
    hourly sync are picked up by CATALOG_TTL_S instead."""
    row = (await db.execute(
        select(func.count(Player.id), func.max(Player.id), func.min(Player.id))
        .where(Player.position.in_(positions))
    )).one()
    return f"{row[0]}:{row[1]}:{row[2]}"


def _build_catalog(rows: list[tuple], scoring_config: dict, version: str) -> PlayerCatalog:
    """Pure CPU work over plain tuples -- safe to run in a worker thread."""
    # Imported here to avoid a circular import (draft_manager imports us).
    from app.services.draft_manager import build_rank_by_id, get_rank_score

    players = [
        SimpleNamespace(
            id=r[0], first_name=r[1], last_name=r[2], position=r[3], team=r[4], age=r[5],
            number=r[6], sleeper_id=r[7], bye_week=r[8], injury_status=r[9],
            fantasy_positions=r[10], search_rank=r[11], stats=r[12], stats_year=r[13],
            last_season_stats=r[14], last_season_year=r[15],
        )
        for r in rows
    ]
    # Deterministic input order (the old per-poll query's ORDER BY) so
    # equal-score fallback ranks break ties the same way every build.
    _qpri = {v: i for i, v in enumerate(["RB", "WR", "QB", "TE", "K", "DEF"])}
    players.sort(key=lambda p: (_qpri.get(p.position, 99), p.last_name or "", p.id))
    rank_by_id = build_rank_by_id(players, scoring_config)

    def sort_key(p) -> tuple:
        pos_idx = _POS_ORDER.index(p.position) if p.position in _POS_ORDER else 99
        return (get_rank_score(p, rank_by_id), pos_idx, p.last_name or "")

    players.sort(key=sort_key)
    entries: list[dict] = []
    for p in players:
        stats, year = effective_season_stats(p)
        entries.append({
            "id": p.id,
            "full_name": f"{p.first_name} {p.last_name}",
            "first_name": p.first_name,
            "last_name": p.last_name,
            "position": p.position,
            "team": p.team or "FA",
            "age": p.age,
            "number": p.number,
            "avatar_url": sleeper_avatar_url(p.sleeper_id),
            "sleeper_id": p.sleeper_id,
            "bye_week": p.bye_week,
            "injury_status": p.injury_status,
            "fantasy_positions": p.fantasy_positions,
            "rank_score": get_rank_score(p, rank_by_id),
            "headline_stats": compute_headline_stats(p.position, stats),
            "season_points": calculate_player_score(stats, scoring_config, p.position),
            "season_points_year": year,
            "projected_points": calculate_player_score(p.last_season_stats or {}, scoring_config, p.position),
            # Raw team for CPU free-agent check (display "team" is "FA"-filled).
            "_raw_team": p.team,
        })
    index = {e["id"]: i for i, e in enumerate(entries)}
    cpu_records = [(e["id"], e["position"], e["_raw_team"], e["age"]) for e in entries]
    return PlayerCatalog(version=version, built_at=time.monotonic(), entries=entries,
                         index=index, rank_by_id=rank_by_id, cpu_records=cpu_records)


async def get_catalog(db: AsyncSession, scoring_config: Optional[dict], positions: set[str]) -> PlayerCatalog:
    skey = scoring_key(scoring_config)
    sig = await _pool_signature(db, positions)
    version = f"{skey}:{sig}"
    cat = _catalogs.get(skey)
    if cat and cat.version == version and time.monotonic() - cat.built_at < CATALOG_TTL_S:
        return cat
    lock = _catalog_locks.setdefault(skey, asyncio.Lock())
    async with lock:
        cat = _catalogs.get(skey)
        if cat and cat.version == version and time.monotonic() - cat.built_at < CATALOG_TTL_S:
            return cat
        rows = (await db.execute(select(*_CATALOG_COLUMNS).where(Player.position.in_(positions)))).all()
        rows = [tuple(r) for r in rows]
        cat = await asyncio.to_thread(_build_catalog, rows, scoring_config or {}, version)
        # A distinct object per build -- built_at keeps state-cache keys unique
        # even when the version string is unchanged after a TTL refresh.
        _catalogs[skey] = cat
        return cat


def public_entry(entry: dict, pos_rank: int) -> dict:
    out = {k: v for k, v in entry.items() if not k.startswith("_")}
    out["pos_rank"] = pos_rank
    return out


def pick_player_view(entry: dict) -> dict:
    """The (smaller) player shape the picks list has always carried."""
    return {
        "id": entry["id"],
        "full_name": entry["full_name"],
        "position": entry["position"],
        "team": entry["team"],
        "number": entry["number"],
        "age": entry["age"],
        "bye_week": entry["bye_week"],
        "injury_status": entry["injury_status"],
        "fantasy_positions": entry["fantasy_positions"],
        "avatar_url": entry["avatar_url"],
        "rank_score": entry["rank_score"],
        # pos_rank only ever described rank among still-available players.
        "pos_rank": 0,
        "headline_stats": entry["headline_stats"],
        "season_points": entry["season_points"],
        "season_points_year": entry["season_points_year"],
    }


# ─── Encoded /state cache ───────────────────────────────────────────────

@dataclass
class EncodedState:
    key: tuple
    etag: str
    body: bytes
    gzipped: bytes
    last_access: float


_state_cache: dict[str, EncodedState] = {}
_state_locks: dict[str, asyncio.Lock] = {}


def state_lock(draft_id: str) -> asyncio.Lock:
    return _state_locks.setdefault(draft_id, asyncio.Lock())


def cached_state(draft_id: str, key: tuple) -> Optional[EncodedState]:
    hit = _state_cache.get(draft_id)
    if hit and hit.key == key:
        hit.last_access = time.monotonic()
        return hit
    return None


def _encode(state: dict) -> tuple[bytes, bytes]:
    body = json.dumps(state, separators=(",", ":"), default=str).encode()
    return body, gzip.compress(body, compresslevel=5)


async def store_state(draft_id: str, key: tuple, state: dict) -> EncodedState:
    body, gz = await asyncio.to_thread(_encode, state)
    etag = '"' + hashlib.sha1(repr(key).encode()).hexdigest() + '"'
    enc = EncodedState(key=key, etag=etag, body=body, gzipped=gz, last_access=time.monotonic())
    _state_cache[draft_id] = enc
    _evict_idle()
    return enc


def _evict_idle() -> None:
    now = time.monotonic()
    stale = [d for d, e in _state_cache.items() if now - e.last_access > STATE_IDLE_EVICT_S]
    for d in stale:
        _state_cache.pop(d, None)
        _state_locks.pop(d, None)
    if len(_state_cache) > STATE_CACHE_MAX_DRAFTS:
        for d, _ in sorted(_state_cache.items(), key=lambda kv: kv[1].last_access)[: len(_state_cache) - STATE_CACHE_MAX_DRAFTS]:
            _state_cache.pop(d, None)
            _state_locks.pop(d, None)


def invalidate_state(draft_id: str) -> None:
    _state_cache.pop(draft_id, None)


def catalog_token(cat: PlayerCatalog) -> tuple:
    return (cat.version, cat.built_at)

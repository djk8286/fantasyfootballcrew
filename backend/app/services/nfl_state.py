"""The last NFL season type the server saw from Sleeper's /state/nfl.

scheduler.fetch_nfl_state records every response here (the stats sync
fetches it every tick, in season or not), so GET /nfl/sync-status can
report the season type without its own call to Sleeper. In memory, per
process, like the scheduler that fills it: after a restart it reads None
until the first fetch, and the freshness chip then shows as usual.
"""
import time
from typing import Any, Optional

SEASON_TYPES = frozenset({"pre", "regular", "post", "off"})
# The stats sync runs every 2 minutes. A value much older than that means
# the scheduler stopped, so stop trusting it.
MAX_AGE_S = 30 * 60

_latest: Optional[tuple[Optional[str], float]] = None


def normalize_season_type(value: Any) -> Optional[str]:
    """A known season type, or None for anything else Sleeper might send."""
    return value if isinstance(value, str) and value in SEASON_TYPES else None


def record_nfl_state(state: Any) -> None:
    global _latest
    raw = state.get("season_type") if isinstance(state, dict) else None
    _latest = (normalize_season_type(raw), time.monotonic())


def latest_season_type(now: Optional[float] = None) -> Optional[str]:
    if _latest is None:
        return None
    season_type, at = _latest
    if (now if now is not None else time.monotonic()) - at > MAX_AGE_S:
        return None
    return season_type


def reset_nfl_state() -> None:
    global _latest
    _latest = None

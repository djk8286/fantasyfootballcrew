"""Starting slots for a lineup: which slots a league has, which positions
each slot accepts, and placing a set of starters into them.

A slot lineup is a list of {"slot": "RB", "player_id": "..." | None} in
league slot order, one entry per starting slot. None is an empty slot."""
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from app.services.scoring_engine import FLEX_ELIGIBLE, IDP_FLEX_ELIGIBLE, SUPERFLEX_ELIGIBLE

SLOT_ORDER = ("QB", "RB", "WR", "TE", "FLEX", "SUPERFLEX", "K", "DEF", "DL", "LB", "DB", "IDP_FLEX")

SLOT_ELIGIBLE: Dict[str, frozenset] = {
    "QB": frozenset({"QB"}),
    "RB": frozenset({"RB"}),
    "WR": frozenset({"WR"}),
    "TE": frozenset({"TE"}),
    "FLEX": frozenset(FLEX_ELIGIBLE),
    "SUPERFLEX": frozenset(SUPERFLEX_ELIGIBLE),
    "K": frozenset({"K"}),
    "DEF": frozenset({"DEF"}),
    "DL": frozenset({"DL"}),
    "LB": frozenset({"LB"}),
    "DB": frozenset({"DB"}),
    "IDP_FLEX": frozenset(IDP_FLEX_ELIGIBLE),
}

# Flex slots in the order a leftover starter tries them: the narrowest
# first, so a RB never takes the SUPERFLEX a QB needs.
_FLEX_ORDER = ("FLEX", "IDP_FLEX", "SUPERFLEX")

Slots = List[Dict[str, Optional[str]]]


class LineupError(ValueError):
    pass


def expand_slots(roster_slots: Dict[str, int]) -> List[str]:
    return [slot for slot in SLOT_ORDER for _ in range(max(0, int(roster_slots.get(slot, 0) or 0)))]


def eligible(slot: str, position: Optional[str]) -> bool:
    return bool(position) and position in SLOT_ELIGIBLE.get(slot, frozenset())


def starters_of(slots: Slots) -> List[str]:
    return [s["player_id"] for s in slots if s["player_id"]]


def place_starters(
    starters: Sequence[str], positions: Dict[str, str], roster_slots: Dict[str, int],
) -> Tuple[Slots, List[str]]:
    """Put starters into the league's slots: each into its own position's
    slot first, then the flex slots. Returns the slots and any starters
    that didn't fit, in their original order."""
    slots: Slots = [{"slot": name, "player_id": None} for name in expand_slots(roster_slots)]

    def take(pid: str, names: Sequence[str]) -> bool:
        for name in names:
            for entry in slots:
                if entry["slot"] == name and entry["player_id"] is None and eligible(name, positions.get(pid)):
                    entry["player_id"] = pid
                    return True
        return False

    left = [pid for pid in dict.fromkeys(starters) if not take(pid, [positions.get(pid) or ""])]
    # QBs claim SUPERFLEX before skill players can, since it's their only flex.
    left = [pid for pid in left if not (positions.get(pid) == "QB" and take(pid, ["SUPERFLEX"]))]
    left = [pid for pid in left if not take(pid, _FLEX_ORDER)]
    return slots, left


def validate_slots(submitted: Sequence[Dict[str, Optional[str]]], positions: Dict[str, str],
                   names: Dict[str, str], roster_slots: Dict[str, int]) -> Slots:
    """A client's slot assignments, checked against the league's slots and
    each player's position, returned in league slot order. positions holds
    every rostered player; names is for error messages."""
    slots: Slots = [{"slot": name, "player_id": None} for name in expand_slots(roster_slots)]
    seen = set()
    for entry in submitted:
        slot, pid = entry.get("slot"), entry.get("player_id")
        if not pid:
            continue
        if pid not in positions:
            raise LineupError(f"Player {pid} isn't on this roster.")
        if pid in seen:
            raise LineupError(f"{names.get(pid, pid)} is in two slots.")
        if not eligible(slot or "", positions[pid]):
            raise LineupError(f"{names.get(pid, pid)} ({positions[pid]}) can't play {slot}.")
        free = next((e for e in slots if e["slot"] == slot and e["player_id"] is None), None)
        if free is None:
            raise LineupError(f"This league has no open {slot} slot for {names.get(pid, pid)}.")
        free["player_id"] = pid
        seen.add(pid)
    return slots


@dataclass(frozen=True)
class PlayerState:
    name: str
    injury_status: Optional[str]
    inactive: bool
    on_bye: bool


def lineup_issues(slots: Slots, players: Dict[str, PlayerState], unplaced: Sequence[str] = ()) -> List[dict]:
    """What will cost points: empty slots, starters ruled out or on bye,
    and starters that don't fit any slot (a lineup saved before slots)."""
    issues = []
    for i, entry in enumerate(slots):
        pid = entry["player_id"]
        if pid is None:
            issues.append({"kind": "empty", "slot": entry["slot"], "slot_index": i, "player_id": None,
                           "message": f"Your {entry['slot']} slot is empty."})
            continue
        p = players.get(pid)
        if p is None:
            continue
        if p.on_bye:
            issues.append({"kind": "bye", "slot": entry["slot"], "slot_index": i, "player_id": pid,
                           "message": f"{p.name} is on bye and won't score."})
        elif p.inactive:
            issues.append({"kind": "out", "slot": entry["slot"], "slot_index": i, "player_id": pid,
                           "message": f"{p.name} is listed {p.injury_status} and may not play."})
    for pid in unplaced:
        p = players.get(pid)
        issues.append({"kind": "illegal", "slot": None, "slot_index": None, "player_id": pid,
                       "message": f"{p.name if p else pid} doesn't fit an open starting slot."})
    return issues

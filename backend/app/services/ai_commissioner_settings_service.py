"""
AI Co-Commissioner v1 -- per-league enable/disable toggle.

The spec's own "Technical & UX Requirements" asked for "Easy toggle to
enable/disable AI Co-Commissioner features per league" -- this was
built after the fact, once the rest of the initiative was already
shipped, when the app moved toward a real public launch. Defaults to
ENABLED (see League.ai_commissioner_settings' own comment) so it never
silently yanks a feature commissioners already had.

Covers the whole AI Co-Commissioner surface as one on/off switch --
Weekly Digest, Trade Review, League Health, Scoring/Schedule Insights,
Communication Helpers, and AI Chat -- not per-sub-feature granularity.
The zero-LLM tools (Health/Insights/Schedule Insights) are included
under the same switch even though they never call an LLM, since
they're marketed and presented as part of one "AI Co-Commissioner"
surface; the toggle is about that surface as a whole, not literally
"does this call an LLM."
"""
from typing import Any

from app.models.league import League

DEFAULT_AI_COMMISSIONER_SETTINGS: dict[str, Any] = {
    "enabled": True,
}


def get_ai_commissioner_settings(league: League) -> dict[str, Any]:
    merged = dict(DEFAULT_AI_COMMISSIONER_SETTINGS)
    merged.update(league.ai_commissioner_settings or {})
    return merged

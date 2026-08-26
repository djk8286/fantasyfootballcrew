# app/api/v1/__init__.py
from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.leagues import router as leagues_router
from app.api.v1.teams import router as teams_router
from app.api.v1.players import router as players_router
from app.api.v1.scoring import router as scoring_router
from app.api.v1.ai import router as ai_router
from app.api.v1.drafts import router as drafts_router
from app.api.v1.standings import router as standings_router
from app.api.v1.commissioner import router as commissioner_router
from app.api.v1.trades import router as trades_router
from app.api.v1.waivers import router as waivers_router
from app.api.v1.coaches import router as coaches_router
from app.api.v1.lineups import router as lineups_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.playoffs import router as playoffs_router
from app.api.v1.invites import router as invites_router
from app.api.v1.dashboard import router as dashboard_router

__all__ = [
    "auth_router", "users_router", "leagues_router",
    "teams_router", "players_router", "scoring_router",
    "ai_router", "drafts_router", "standings_router",
    "commissioner_router", "trades_router", "waivers_router",
    "coaches_router", "lineups_router", "notifications_router",
    "playoffs_router", "invites_router", "dashboard_router",
]

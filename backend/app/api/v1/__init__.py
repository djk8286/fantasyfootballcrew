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

__all__ = [
    "auth_router", "users_router", "leagues_router",
    "teams_router", "players_router", "scoring_router",
    "ai_router", "drafts_router", "standings_router",
    "commissioner_router",
]

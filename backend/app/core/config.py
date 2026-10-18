from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, model_validator
from typing import List, Optional
import secrets


class Settings(BaseSettings):
    APP_NAME: str = "FantasyFootballCrew"
    DATABASE_URL: str = "sqlite+aiosqlite:///./ffc.db"
    SUPABASE_URL: Optional[str] = None
    SUPABASE_KEY: Optional[str] = None
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "https://fantasyfootballcrew.com",
        "https://www.fantasyfootballcrew.com",
    ]
    # Seconds a CPU (or ownerless) team waits on the clock before the
    # server-side draft watchdog picks for it. Small but non-zero so a
    # human watching can follow the board (QA round 2: was ~20s/pick).
    CPU_PICK_DELAY_S: float = 1.0
    JWT_SECRET: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    # Access-token lifetime. Was a hard-coded 30 days; shortened per the
    # 2026-10 security audit. Follow-up: refresh token + HttpOnly cookie.
    ACCESS_TOKEN_EXPIRE_DAYS: float = 7
    # Proxy hops we trust to append to X-Forwarded-For (see
    # app/core/limiter.py). Railway's internal edge uses RFC 6598 space.
    TRUSTED_PROXY_CIDRS: List[str] = ["100.64.0.0/10", "10.0.0.0/8", "127.0.0.0/8", "::1/128"]
    SLEEPER_API_BASE: str = "https://api.sleeper.app/v1"
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    # Password-reset emails -- see app/services/email_service.py. Without a
    # key, reset links are logged server-side instead of emailed (still
    # fully functional, just needs manual delivery until this is set).
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: str = "FantasyFootballCrew <onboarding@resend.dev>"
    FRONTEND_URL: str = "https://fantasyfootballcrew.com"
    # Error monitoring -- see app/core/sentry.py. Without a DSN, sentry_sdk
    # is simply never initialized (no-op, no errors, no dependency on this
    # being set) -- same deferred-but-ready shape as RESEND_API_KEY above.
    SENTRY_DSN: Optional[str] = None
    ENVIRONMENT: str = "development"  # set to "production" on Railway

    # AI cost tracking -- see app/services/ai_cost_service.py. USD per 1M
    # tokens, keyed by the exact model id sent to the provider. An unknown
    # model is still recorded (tokens + model), just with cost_usd=None,
    # so a model swap never silently under-reports -- it shows as
    # "unpriced" on the admin dashboard until this table is updated.
    # Override wholesale via env as JSON, e.g.
    # AI_MODEL_PRICING='{"gpt-5.6-luna": {"input": 0.2, "output": 1.2}}'
    AI_MODEL_PRICING: dict[str, dict[str, float]] = {
        "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
        "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    }
    # OpenAI bills hosted web_search tool calls per call on top of tokens
    # (bet analysis + per-team news use it). Estimate -- check current
    # OpenAI pricing for the model in use.
    AI_WEB_SEARCH_COST_PER_CALL: float = 0.01
    # Optional global ceiling on estimated AI spend over a rolling 24h.
    # Unset (default) = no cap. When reached, every AI call returns a
    # friendly "daily budget reached" message instead of calling the
    # provider, and the attempt is logged with error="daily_spend_cap".
    AI_DAILY_SPEND_CAP_USD: Optional[float] = None

    @field_validator("DATABASE_URL")
    @classmethod
    def _use_asyncpg_driver(cls, v: str) -> str:
        """Railway/Heroku-style DATABASE_URLs come as postgres:// or postgresql://,
        but SQLAlchemy's async engine needs the asyncpg driver spelled out."""
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+asyncpg://" + v[len("postgresql://"):]
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Parse CORS_ORIGINS from JSON string env var
        @classmethod
        def parse_env_var(cls, field_name: str, raw_val: str) -> object:
            if field_name == "CORS_ORIGINS" and raw_val:
                import json
                try:
                    return json.loads(raw_val)
                except (json.JSONDecodeError, TypeError):
                    return raw_val.split(",")
            return raw_val


    @model_validator(mode="after")
    def _require_strong_jwt_secret_in_production(self):
        """In production a random per-process JWT_SECRET silently logs every
        user out on each deploy/restart, and a short one is brute-forceable.
        Refuse to boot instead, with a message that says exactly what to fix."""
        if self.ENVIRONMENT.lower() == "production":
            explicit = "JWT_SECRET" in self.model_fields_set
            if not explicit or len(self.JWT_SECRET) < 32:
                msg = (
                    "FATAL CONFIG: JWT_SECRET must be set to a value of at least 32 "
                    "characters when ENVIRONMENT=production "
                    f"(currently {'unset' if not explicit else f'{len(self.JWT_SECRET)} chars'}). "
                    "Set it in Railway > backend service > Variables, e.g. the output of "
                    "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`. "
                    "Note: changing it signs out all users."
                )
                print(msg, flush=True)
                raise ValueError(msg)
        return self


settings = Settings()
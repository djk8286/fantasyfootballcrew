from pydantic_settings import BaseSettings
from pydantic import Field
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
    JWT_SECRET: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    SLEEPER_API_BASE: str = "https://api.sleeper.app/v1"

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


settings = Settings()
"""Application settings loaded from environment."""
from pydantic_settings import BaseSettings
from functools import lru_cache
import sys


class Settings(BaseSettings):
    database_url: str = "sqlite:///./renter_portal.db"
    secret_key: str = "dev-secret-change-me"
    access_token_minutes: int = 60 * 8   # 8 hours (was 24 — reduced for security)
    refresh_token_days: int = 30
    environment: str = "development"
    debug: bool = True
    base_url: str = "http://localhost:8000"
    stripe_secret_key: str = ""
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""
    ms_redirect_uri: str = "http://localhost:8000/auth/microsoft/callback"
    azure_storage_connection_string: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.environment == "production" and s.secret_key == "dev-secret-change-me":
        print("FATAL: SECRET_KEY is the default value in production. Set SECRET_KEY env var.", flush=True)
        sys.exit(1)
    return s

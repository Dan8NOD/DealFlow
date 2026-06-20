"""Application settings loaded from environment."""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str = "sqlite:///./renter_portal.db"
    secret_key: str = "dev-secret-change-me"
    access_token_minutes: int = 60 * 24
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
    return Settings()

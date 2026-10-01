"""B: typed configuration; secret contents never appear in repr or diagnostics."""
from pathlib import Path
from typing import Literal
from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FM_", extra="ignore")
    app_env: Literal["development", "production", "test"] = "development"
    public_origin: AnyHttpUrl = "https://localhost:8443"
    database_host: str = "postgres"
    database_port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = "file_manager"
    database_user: str = "fm_app"
    database_password_file: Path = Path("/run/secrets/pg_app_password")
    jwt_key_file: Path = Path("/run/secrets/jwt_key")
    csrf_key_file: Path = Path("/run/secrets/csrf_key")
    confirmation_key_file: Path = Path("/run/secrets/confirmation_key")
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "fm_api"
    minio_secret_key_file: Path = Path("/run/secrets/minio_api_password")
    minio_secure: bool = False
    cookie_secure: bool = True
    access_ttl_seconds: int = Field(default=900, ge=300, le=900)
    refresh_ttl_seconds: int = Field(default=604800, ge=86400, le=604800)

    @staticmethod
    def read_secret(secret_file: Path) -> str:
        value = secret_file.read_text(encoding="utf-8").strip()
        if not value:
            raise ValueError("Secret file is empty")
        return value

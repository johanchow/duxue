from __future__ import annotations

import os
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load server-root env file before reading os.environ. Existing process env wins
# (override=False), so tests and Docker-injected vars are not clobbered.
# Prefer ENV_FILE=.env.prod when you intentionally want another file.
_SERVER_ROOT = Path(__file__).resolve().parents[1]
_ENV_FILE = Path(os.getenv("ENV_FILE", ".env"))
if not _ENV_FILE.is_absolute():
    _ENV_FILE = _SERVER_ROOT / _ENV_FILE
if _ENV_FILE.is_file():
    load_dotenv(_ENV_FILE, override=False)


class ConfigurationError(RuntimeError):
    """Raised before startup when required runtime configuration is absent."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _integer(name: str, default: str) -> int:
    value = os.getenv(name, default)
    try:
        return int(value)
    except ValueError as error:
        raise ConfigurationError(f"Environment variable {name} must be an integer") from error


@dataclass(frozen=True)
class Settings:
    database_url: str = _required("DATABASE_URL").replace("postgresql+asyncpg://", "postgresql+psycopg://")
    secret_key: str = os.getenv("JWT_SECRET_KEY", "").strip() or os.getenv("SECRET_KEY", "").strip()
    access_token_minutes: int = _integer("ACCESS_TOKEN_MINUTES", "15")
    refresh_token_days: int = _integer("REFRESH_TOKEN_DAYS", "30")
    frame_retention_days: int = _integer("FRAME_RETENTION_DAYS", "90")
    capture_interval_seconds: int = _integer("CAPTURE_INTERVAL_SECONDS", "15")
    heartbeat_timeout_seconds: int = _integer("HEARTBEAT_TIMEOUT_SECONDS", "180")
    app_env: str = os.getenv("APP_ENV", "development").lower()
    cors_allow_origins: tuple[str, ...] = tuple(
        value.strip() for value in os.getenv("CORS_ALLOW_ORIGINS", "http://localhost:4173,http://127.0.0.1:4173").split(",") if value.strip()
    )
    auto_create_schema: bool = os.getenv("AUTO_CREATE_SCHEMA", "").lower() in {"1", "true", "yes"}
    upload_dir: Path = Path(os.getenv("LOCAL_UPLOAD_DIR", "./data/uploads"))
    storage_backend: str = os.getenv("STORAGE_BACKEND", "local")
    public_base_url: str = os.getenv("APP_BASE_URL") or os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    oss_endpoint: str = os.getenv("OSS_ENDPOINT_PUBLIC") or os.getenv("OSS_ENDPOINT", "")
    oss_endpoint_internal: str = os.getenv("OSS_ENDPOINT_INTERNAL") or os.getenv("OSS_ENDPOINT_PUBLIC") or os.getenv("OSS_ENDPOINT", "")
    oss_presign_expire_seconds: int = _integer("OSS_PRESIGN_EXPIRE_SECONDS", "300")
    oss_bucket: str = os.getenv("OSS_BUCKET_NAME") or os.getenv("OSS_BUCKET", "")
    oss_access_key_id: str = os.getenv("OSS_ACCESS_KEY_ID", "")
    oss_access_key_secret: str = os.getenv("OSS_ACCESS_KEY_SECRET", "")
    dashscope_api_key: str = os.getenv("VLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_base_url: str = os.getenv("VLM_BATCH_BASE_URL") or os.getenv("VLM_API_BASE_URL") or os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    vlm_model: str = os.getenv("VLM_MODEL_NAME") or os.getenv("VLM_MODEL", "qwen3-vl-flash")
    # Each text use case is independently routable.  A provider migration only
    # changes environment values; records retain the factual inputs, not a model
    # specific response schema.
    tutoring_model: str = os.getenv("TUTORING_MODEL_NAME") or os.getenv("VLM_MODEL_NAME") or "qwen3-vl-flash"
    insight_model: str = os.getenv("INSIGHT_MODEL_NAME") or os.getenv("VLM_MODEL_NAME") or "qwen3-vl-flash"
    guardian_story_model: str = os.getenv("GUARDIAN_STORY_MODEL_NAME") or os.getenv("VLM_MODEL_NAME") or "qwen3-vl-flash"
    batch_completion_window: str = os.getenv("VLM_BATCH_COMPLETION_WINDOW", "24h")
    batch_submit_hour: int = int(os.getenv("VLM_BATCH_SUBMIT_HOUR", "22"))
    batch_fallback_after_hours: int = int(os.getenv("VLM_BATCH_FALLBACK_AFTER_HOURS", "20"))
    redis_url: str = os.getenv("REDIS_URL") or ""
    redis_host: str = os.getenv("REDIS_HOST", "").strip()
    redis_port: int = _integer("REDIS_PORT", "6379")
    redis_username: str = os.getenv("REDIS_USERNAME", "")
    redis_password: str = os.getenv("REDIS_PASSWORD", "")
    redis_db: int = _integer("REDIS_DB", "0")
    redis_scheme: str = os.getenv("REDIS_SCHEME", "redis")

    def __post_init__(self) -> None:
        missing: list[str] = []
        if not self.secret_key:
            missing.append("JWT_SECRET_KEY (or SECRET_KEY)")
        if not self.redis_url and not self.redis_host:
            missing.append("REDIS_URL (or REDIS_HOST)")
        if not self.dashscope_api_key:
            missing.append("VLM_API_KEY (or DASHSCOPE_API_KEY)")
        if self.storage_backend not in {"local", "oss"}:
            raise ConfigurationError("STORAGE_BACKEND must be either 'local' or 'oss'")
        if self.storage_backend == "oss":
            if not self.oss_endpoint:
                missing.append("OSS_ENDPOINT_PUBLIC (or OSS_ENDPOINT)")
            if not self.oss_bucket:
                missing.append("OSS_BUCKET_NAME (or OSS_BUCKET)")
            if not self.oss_access_key_id:
                missing.append("OSS_ACCESS_KEY_ID")
            if not self.oss_access_key_secret:
                missing.append("OSS_ACCESS_KEY_SECRET")
        if missing:
            raise ConfigurationError(
                "Missing required runtime configuration: " + ", ".join(missing),
            )
        if (
            not self.auto_create_schema
            and self.app_env != "production"
            and self.database_url.startswith("sqlite")
        ):
            object.__setattr__(self, "auto_create_schema", True)
        if not self.redis_url:
            if self.redis_username:
                credentials = f"{quote(self.redis_username, safe='')}:{quote(self.redis_password, safe='')}@"
            elif self.redis_password:
                credentials = f":{quote(self.redis_password, safe='')}@"
            else:
                credentials = ""
            object.__setattr__(self, "redis_url", f"{self.redis_scheme}://{credentials}{self.redis_host}:{self.redis_port}/{self.redis_db}")


settings = Settings()

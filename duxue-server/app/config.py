from __future__ import annotations

import os
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./duxue.db").replace("postgresql+asyncpg://", "postgresql+psycopg://")
    secret_key: str = os.getenv("JWT_SECRET_KEY") or os.getenv("SECRET_KEY", "dev-only-change-me")
    access_token_minutes: int = int(os.getenv("ACCESS_TOKEN_MINUTES", "15"))
    refresh_token_days: int = int(os.getenv("REFRESH_TOKEN_DAYS", "30"))
    frame_retention_days: int = int(os.getenv("FRAME_RETENTION_DAYS", "90"))
    capture_interval_seconds: int = int(os.getenv("CAPTURE_INTERVAL_SECONDS", "15"))
    heartbeat_timeout_seconds: int = int(os.getenv("HEARTBEAT_TIMEOUT_SECONDS", "180"))
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
    oss_presign_expire_seconds: int = int(os.getenv("OSS_PRESIGN_EXPIRE_SECONDS", "300"))
    oss_bucket: str = os.getenv("OSS_BUCKET_NAME") or os.getenv("OSS_BUCKET", "")
    oss_access_key_id: str = os.getenv("OSS_ACCESS_KEY_ID", "")
    oss_access_key_secret: str = os.getenv("OSS_ACCESS_KEY_SECRET", "")
    dashscope_api_key: str = os.getenv("VLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_base_url: str = os.getenv("VLM_BATCH_BASE_URL") or os.getenv("VLM_API_BASE_URL") or os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    vlm_model: str = os.getenv("VLM_MODEL_NAME") or os.getenv("VLM_MODEL", "qwen3-vl-flash")
    batch_completion_window: str = os.getenv("VLM_BATCH_COMPLETION_WINDOW", "24h")
    batch_submit_hour: int = int(os.getenv("VLM_BATCH_SUBMIT_HOUR", "22"))
    batch_fallback_after_hours: int = int(os.getenv("VLM_BATCH_FALLBACK_AFTER_HOURS", "20"))
    redis_url: str = os.getenv("REDIS_URL") or ""
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    redis_username: str = os.getenv("REDIS_USERNAME", "")
    redis_password: str = os.getenv("REDIS_PASSWORD", "")
    redis_db: int = int(os.getenv("REDIS_DB", "0"))
    redis_scheme: str = os.getenv("REDIS_SCHEME", "redis")

    def __post_init__(self) -> None:
        if not self.auto_create_schema and self.app_env != "production" and self.database_url.startswith("sqlite"):
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

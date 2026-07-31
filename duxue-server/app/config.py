from __future__ import annotations

import os
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
    upload_dir: Path = Path(os.getenv("LOCAL_UPLOAD_DIR", "./data/uploads"))
    storage_backend: str = os.getenv("STORAGE_BACKEND", "local")
    public_base_url: str = os.getenv("APP_BASE_URL") or os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")
    oss_endpoint: str = os.getenv("OSS_ENDPOINT_PUBLIC") or os.getenv("OSS_ENDPOINT", "")
    oss_bucket: str = os.getenv("OSS_BUCKET_NAME") or os.getenv("OSS_BUCKET", "")
    oss_access_key_id: str = os.getenv("OSS_ACCESS_KEY_ID", "")
    oss_access_key_secret: str = os.getenv("OSS_ACCESS_KEY_SECRET", "")
    dashscope_api_key: str = os.getenv("VLM_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")
    dashscope_base_url: str = os.getenv("VLM_BATCH_BASE_URL") or os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    vlm_model: str = os.getenv("VLM_MODEL_NAME") or os.getenv("VLM_MODEL", "qwen3-vl-flash")
    redis_url: str = os.getenv("REDIS_URL") or f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}/0"


settings = Settings()

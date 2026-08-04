from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path

from fastapi import HTTPException

from .config import settings


class LocalStorage:
    """Development adapter with the same two-step contract as OSS presigned PUT."""

    def __init__(self) -> None:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)

    def sign(self, key: str, expires_in: int = 300) -> tuple[int, str]:
        expires = int(time.time()) + expires_in
        value = f"{key}:{expires}".encode()
        signature = hmac.new(settings.secret_key.encode(), value, hashlib.sha256).hexdigest()
        return expires, signature

    def verify(self, key: str, expires: int, signature: str) -> None:
        if expires < time.time():
            raise HTTPException(403, "upload URL expired")
        _, expected = self.sign_for_expiry(key, expires)
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(403, "invalid upload signature")

    def sign_for_expiry(self, key: str, expires: int) -> tuple[int, str]:
        value = f"{key}:{expires}".encode()
        signature = hmac.new(settings.secret_key.encode(), value, hashlib.sha256).hexdigest()
        return expires, signature

    def path(self, key: str) -> Path:
        target = (settings.upload_dir / key).resolve()
        root = settings.upload_dir.resolve()
        if root not in target.parents:
            raise HTTPException(400, "invalid object key")
        return target

    def delete(self, key: str | None) -> None:
        if not key:
            return
        path = self.path(key)
        if path.exists():
            path.unlink()

    def exists(self, key: str) -> bool:
        return self.path(key).exists()

    def read_bytes(self, key: str) -> bytes:
        return self.path(key).read_bytes()

    def upload_url(self, key: str, base_url: str, content_type: str) -> tuple[str, int, dict]:
        expires, signature = self.sign(key, settings.oss_presign_expire_seconds)
        return f"{base_url.rstrip('/')}/uploads/{key}?expires={expires}&signature={signature}", expires, {"Content-Type": content_type}


class OssStorage:
    def __init__(self) -> None:
        try:
            import oss2
        except ImportError as exc:
            raise RuntimeError("oss2 is required when STORAGE_BACKEND=oss") from exc
        auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
        self.public_bucket = oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)
        self.internal_bucket = oss2.Bucket(auth, settings.oss_endpoint_internal, settings.oss_bucket)

    def upload_url(self, key: str, base_url: str, content_type: str) -> tuple[str, int, dict]:
        expires = int(time.time()) + settings.oss_presign_expire_seconds
        url = self.public_bucket.sign_url("PUT", key, settings.oss_presign_expire_seconds, headers={"Content-Type": content_type})
        return url, expires, {"Content-Type": content_type}

    def exists(self, key: str) -> bool:
        return self.internal_bucket.object_exists(key)

    def read_bytes(self, key: str) -> bytes:
        return self.internal_bucket.get_object(key).read()

    def delete(self, key: str | None) -> None:
        if key:
            self.internal_bucket.delete_object(key)


storage = OssStorage() if settings.storage_backend == "oss" else LocalStorage()

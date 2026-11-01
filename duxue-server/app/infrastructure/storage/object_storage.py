from __future__ import annotations

import hashlib
import hmac
import os
import time
import tempfile
from pathlib import Path

from fastapi import HTTPException

from app.bootstrap.settings import settings


class LocalStorage:
    """Development adapter with the same two-step contract as OSS presigned PUT."""

    def __init__(self) -> None:
        settings.upload_dir.mkdir(parents=True, exist_ok=True)

    def sign(self, key: str, expires_in: int = 300) -> tuple[int, str]:
        expires = int(time.time()) + expires_in
        value = f"{key}:{expires}".encode()
        signature = hmac.new(settings.secret_key.encode(), value, hashlib.sha256).hexdigest()
        return expires, signature

    def verify(self, key: str, expires: int, signature: str, immutable: bool = False) -> None:
        if expires < time.time():
            raise HTTPException(403, "upload URL expired")
        _, expected = self.sign_for_expiry(key, expires, immutable)
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(403, "invalid upload signature")

    def sign_for_expiry(self, key: str, expires: int, immutable: bool = False) -> tuple[int, str]:
        value = (f"{key}:{expires}" + (":immutable" if immutable else "")).encode()
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

    def read_limited(self, key: str, maximum: int) -> bytes:
        with self.path(key).open("rb") as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise HTTPException(413, "image exceeds gateway limit")
        return data

    def write_uploaded(self, key: str, data: bytes, *, immutable: bool = False) -> None:
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if immutable:
            descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".upload-")
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    raise HTTPException(409, "immutable object already exists") from None
            finally:
                os.unlink(temporary)
        else:
            path.write_bytes(data)

    def upload_url(self, key: str, base_url: str, content_type: str, *, immutable: bool = False) -> tuple[str, int, dict]:
        lifetime = min(settings.oss_presign_expire_seconds, 300) if immutable else settings.oss_presign_expire_seconds
        expires = int(time.time()) + lifetime
        _, signature = self.sign_for_expiry(key, expires, immutable)
        suffix = "&immutable=true" if immutable else ""
        return f"{base_url.rstrip('/')}/uploads/{key}?expires={expires}&signature={signature}{suffix}", expires, {"Content-Type": content_type}


def server_side_oss_endpoint(*, app_env: str, public_endpoint: str, internal_endpoint: str) -> str:
    """Choose the endpoint the API itself uses to read and check objects.

    ``oss-*-internal`` hostnames only resolve inside an Aliyun VPC. Calling
    them from a laptop returns a proxy 502, and ``object_exists`` then fails
    the whole companion turn. Production keeps the internal endpoint.
    """
    if app_env == "production" and internal_endpoint:
        return internal_endpoint
    return public_endpoint or internal_endpoint


class OssStorage:
    def __init__(self, bucket: str) -> None:
        try:
            import oss2
        except ImportError as exc:
            raise RuntimeError("oss2 is required when STORAGE_BACKEND=oss") from exc
        auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
        self.public_bucket = oss2.Bucket(auth, settings.oss_endpoint, bucket)
        server_endpoint = server_side_oss_endpoint(
            app_env=settings.app_env,
            public_endpoint=settings.oss_endpoint,
            internal_endpoint=settings.oss_endpoint_internal,
        )
        self.internal_bucket = oss2.Bucket(auth, server_endpoint, bucket)

    def upload_url(self, key: str, base_url: str, content_type: str, *, immutable: bool = False) -> tuple[str, int, dict]:
        lifetime = min(settings.oss_presign_expire_seconds, 300) if immutable else settings.oss_presign_expire_seconds
        expires = int(time.time()) + lifetime
        headers = {"Content-Type": content_type}
        if immutable:
            headers["x-oss-forbid-overwrite"] = "true"
        url = self.public_bucket.sign_url("PUT", key, lifetime, headers=headers)
        return url, expires, headers

    def read_limited(self, key: str, maximum: int) -> bytes:
        try:
            result = self.internal_bucket.get_object(key)
        except Exception as error:
            if getattr(error, "status", None) == 404:
                raise FileNotFoundError(key) from None
            raise
        try:
            data = result.read(maximum + 1)
        finally:
            result.close()
        if len(data) > maximum:
            raise HTTPException(413, "image exceeds gateway limit")
        return data

    def exists(self, key: str) -> bool:
        return self.internal_bucket.object_exists(key)

    def read_bytes(self, key: str) -> bytes:
        return self.internal_bucket.get_object(key).read()

    def delete(self, key: str | None) -> None:
        if key:
            self.internal_bucket.delete_object(key)


storage = OssStorage(settings.oss_bucket) if settings.storage_backend == "oss" else LocalStorage()
# Camera frames use OSS_BUCKET_CAMERA. Local mode shares the upload directory.
camera_storage = OssStorage(settings.oss_camera_bucket) if settings.storage_backend == "oss" else storage

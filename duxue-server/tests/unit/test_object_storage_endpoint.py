from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from app.infrastructure.storage import object_storage
from app.infrastructure.storage.object_storage import server_side_oss_endpoint


def test_local_and_test_use_the_public_oss_endpoint():
    public = "oss-cn-shenzhen.aliyuncs.com"
    internal = "oss-cn-shenzhen-internal.aliyuncs.com"
    assert server_side_oss_endpoint(app_env="test", public_endpoint=public, internal_endpoint=internal) == public
    assert server_side_oss_endpoint(app_env="development", public_endpoint=public, internal_endpoint=internal) == public


def test_production_keeps_the_internal_oss_endpoint():
    public = "oss-cn-shenzhen.aliyuncs.com"
    internal = "oss-cn-shenzhen-internal.aliyuncs.com"
    assert server_side_oss_endpoint(app_env="production", public_endpoint=public, internal_endpoint=internal) == internal


@pytest.mark.parametrize("endpoint", [
    "oss-cn-shenzhen.aliyuncs.com",
    "http://oss-cn-shenzhen.aliyuncs.com",
    "https://oss-cn-shenzhen.aliyuncs.com",
])
def test_gateway_presigned_upload_uses_https_with_configured_endpoint(monkeypatch, endpoint):
    # The documented bare hostname makes oss2 default to HTTP. The gateway
    # rejects that URL before PUT; exercise the real offline OSS signer.
    monkeypatch.setattr(object_storage, "settings", SimpleNamespace(
        oss_access_key_id="test-access-key", oss_access_key_secret="test-secret",
        oss_endpoint=endpoint, oss_endpoint_internal="oss-cn-shenzhen-internal.aliyuncs.com",
        app_env="production", oss_presign_expire_seconds=300,
    ))
    storage = object_storage.OssStorage("test-camera")
    url, _, headers = storage.upload_url("ward/day/frame.jpg", "", "image/jpeg", immutable=True)
    assert urlsplit(url).scheme == "https"
    assert urlsplit(url).hostname == "test-camera.oss-cn-shenzhen.aliyuncs.com"
    assert headers["x-oss-forbid-overwrite"] == "true"
    assert "-internal" in storage.internal_bucket.endpoint


def test_camera_bucket_can_use_a_different_region(monkeypatch):
    monkeypatch.setattr(object_storage, "settings", SimpleNamespace(
        oss_access_key_id="test-access-key", oss_access_key_secret="test-secret",
        oss_endpoint="oss-cn-shenzhen.aliyuncs.com",
        oss_endpoint_internal="oss-cn-shenzhen-internal.aliyuncs.com",
        app_env="production", oss_presign_expire_seconds=300,
    ))
    storage = object_storage.OssStorage(
        "test-camera", public_endpoint="oss-cn-hangzhou.aliyuncs.com",
        internal_endpoint="oss-cn-hangzhou-internal.aliyuncs.com",
    )
    url, _, _ = storage.upload_url("ward/day/frame.jpg", "", "image/jpeg", immutable=True)
    assert urlsplit(url).hostname == "test-camera.oss-cn-hangzhou.aliyuncs.com"
    assert storage.internal_bucket.endpoint == "http://oss-cn-hangzhou-internal.aliyuncs.com"

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

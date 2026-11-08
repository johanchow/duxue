from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest


class ConfigTest(unittest.TestCase):
    def test_camera_oss_region_override_does_not_reuse_another_regions_internal_host(self):
        cases = [
            ({}, ["oss-cn-shenzhen.aliyuncs.com", "oss-cn-shenzhen-internal.aliyuncs.com"]),
            ({"OSS_CAMERA_ENDPOINT_PUBLIC": "oss-cn-hangzhou.aliyuncs.com"},
             ["oss-cn-hangzhou.aliyuncs.com", "oss-cn-hangzhou.aliyuncs.com"]),
            ({"OSS_CAMERA_ENDPOINT_PUBLIC": "oss-cn-hangzhou.aliyuncs.com",
              "OSS_CAMERA_ENDPOINT_INTERNAL": "oss-cn-hangzhou-internal.aliyuncs.com"},
             ["oss-cn-hangzhou.aliyuncs.com", "oss-cn-hangzhou-internal.aliyuncs.com"]),
        ]
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                environment = {
                    **os.environ, "ENV_FILE": "/dev/null", "DATABASE_URL": "sqlite://",
                    "SECRET_KEY": "test-secret", "REDIS_URL": "redis://localhost:6379/15",
                    "VLM_API_KEY": "test-vlm-key", "STORAGE_BACKEND": "local",
                    "OSS_ENDPOINT_PUBLIC": "oss-cn-shenzhen.aliyuncs.com",
                    "OSS_ENDPOINT_INTERNAL": "oss-cn-shenzhen-internal.aliyuncs.com",
                    "OSS_CAMERA_ENDPOINT_PUBLIC": "", "OSS_CAMERA_ENDPOINT_INTERNAL": "",
                    **overrides,
                }
                result = subprocess.run(
                    [sys.executable, "-c", "import json; from app.bootstrap.settings import settings; print(json.dumps([settings.oss_camera_endpoint, settings.oss_camera_endpoint_internal]))"],
                    cwd=os.path.dirname(os.path.dirname(__file__)), env=environment,
                    text=True, capture_output=True, check=True,
                )
                self.assertEqual(json.loads(result.stdout), expected)

    def test_redis_username_password_build_a_safe_url(self):
        environment = {
            **os.environ,
            "REDIS_URL": "",
            "REDIS_SCHEME": "rediss",
            "REDIS_HOST": "redis.example.com",
            "REDIS_PORT": "6380",
            "REDIS_DB": "1",
            "REDIS_USERNAME": "test-user",
            "REDIS_PASSWORD": "p@ss:/ word",
        }
        result = subprocess.run(
            [sys.executable, "-c", "from app.bootstrap.settings import settings; print(settings.redis_url)"],
            cwd=os.path.dirname(os.path.dirname(__file__)), env=environment,
            text=True, capture_output=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), "rediss://test-user:p%40ss%3A%2F%20word@redis.example.com:6380/1")

    def test_missing_database_url_fails_at_import(self):
        environment = {
            **os.environ,
            "ENV_FILE": ".env.not-present",
            "SECRET_KEY": "test-secret",
            "REDIS_URL": "redis://localhost:6379/15",
            "VLM_API_KEY": "test-vlm-key",
            "STORAGE_BACKEND": "local",
        }
        environment.pop("DATABASE_URL", None)
        result = subprocess.run(
            [sys.executable, "-c", "from app.bootstrap.settings import settings"],
            cwd=os.path.dirname(os.path.dirname(__file__)), env=environment,
            text=True, capture_output=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing required environment variable: DATABASE_URL", result.stderr)

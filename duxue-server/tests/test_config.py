from __future__ import annotations

import os
import subprocess
import sys
import unittest


class ConfigTest(unittest.TestCase):
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
            [sys.executable, "-c", "from app.config import settings; print(settings.redis_url)"],
            cwd=os.path.dirname(os.path.dirname(__file__)), env=environment,
            text=True, capture_output=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), "rediss://test-user:p%40ss%3A%2F%20word@redis.example.com:6380/1")

"""Release ordering, retry and failure behavior, without contacting OSS."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import oss2

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("publish_download", ROOT / "scripts/publish-download.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class FakeBucket:
    def __init__(self):
        self.objects = {}
        self.calls = []
        self.fail = None
        self.bad_meta = False

    def get_object(self, key):
        if key not in self.objects:
            raise oss2.exceptions.NoSuchKey(404, {}, b'', {})
        return io.BytesIO(self.objects[key][0])

    def put_object_from_file(self, key, filename, headers):
        if key in self.objects:
            raise oss2.exceptions.ObjectAlreadyExists(409, {}, b'', {})
        return self.put_object(key, Path(filename).read_bytes(), headers)

    def put_object(self, key, content, headers):
        self.calls.append(key)
        if self.fail == key or self.fail == "apk" and key.endswith(".apk"):
            raise RuntimeError("upload failed")
        self.objects[key] = (content, headers)

    def head_object(self, key):
        content, headers = self.objects[key]
        return SimpleNamespace(content_length=0 if self.bad_meta else len(content), headers=headers)


class DownloadPublishTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.apk = Path(self.folder.name) / "app.apk"
        self.apk.write_bytes(b"test APK bytes")
        self.bucket = FakeBucket()

    def publish(self, build=42, commit="abcdef1234567890"):
        return publisher.publish(self.bucket, self.apk, "0.2.0", build, commit)

    def test_orders_apk_then_page_then_latest_with_correct_headers(self):
        self.assertTrue(self.publish())
        apk_key, page, latest = self.bucket.calls
        self.assertTrue(apk_key.startswith("releases/android/"))
        self.assertNotIn("+", apk_key)
        self.assertEqual([page, latest], ["index.html", "latest.json"])
        data = json.loads(self.bucket.objects[latest][0])
        self.assertEqual(data["android"]["sha256"], hashlib.sha256(self.apk.read_bytes()).hexdigest())
        self.assertEqual(data["android"]["build"], 42)
        self.assertEqual(data["android"]["url"], "/" + apk_key)
        self.assertIn("immutable", self.bucket.objects[apk_key][1]["Cache-Control"])
        self.assertEqual(self.bucket.objects[latest][1]["Cache-Control"], publisher.NO_CACHE)
        self.assertIn(b"function releaseFrom", self.bucket.objects[page][0])
        self.assertNotIn(b'src="download.js"', self.bucket.objects[page][0])

    def test_failure_does_not_move_existing_latest(self):
        for fail in ["apk", "index.html", "latest.json"]:
            with self.subTest(fail=fail):
                self.bucket = FakeBucket()
                self.publish(41)
                original = self.bucket.objects["latest.json"]
                self.apk.write_bytes(self.apk.read_bytes() + b"next")
                self.bucket.fail = fail
                with self.assertRaises(RuntimeError):
                    self.publish(42)
                self.assertEqual(self.bucket.objects["latest.json"], original)

    def test_verification_failure_does_not_publish_page_or_latest(self):
        self.bucket.bad_meta = True
        with self.assertRaisesRegex(ValueError, "verification"):
            self.publish()
        self.assertEqual(len(self.bucket.calls), 1)

    def test_retry_recovers_uploaded_apk_after_page_failure(self):
        self.bucket.fail = "index.html"
        with self.assertRaises(RuntimeError):
            self.publish()
        self.bucket.fail = None
        self.assertTrue(self.publish())
        self.assertEqual(sum(key.endswith(".apk") for key in self.bucket.calls), 1)

    def test_repeated_or_older_build_cannot_roll_back_release(self):
        self.publish()
        self.bucket.calls.clear()
        self.assertFalse(self.publish())
        self.assertFalse(self.publish(41))
        self.assertEqual(self.bucket.calls, [])
        self.apk.write_bytes(b"different APK")
        with self.assertRaisesRegex(ValueError, "different APK"):
            self.publish()

    def test_read_permission_failure_is_not_treated_as_first_release(self):
        def denied(_):
            raise PermissionError("denied")
        self.bucket.get_object = denied
        with self.assertRaises(PermissionError):
            self.publish()
        self.assertEqual(self.bucket.calls, [])

    def test_same_apk_can_repair_legacy_url_without_changing_build_identity(self):
        self.publish()
        data = json.loads(self.bucket.objects["latest.json"][0])
        data["android"]["url"] = "/releases/android/legacy+42.apk"
        self.bucket.objects["latest.json"] = (json.dumps(data).encode(), {})
        self.assertTrue(self.publish())
        repaired = json.loads(self.bucket.objects["latest.json"][0])["android"]
        self.assertNotIn("+", repaired["url"])
        self.assertEqual(repaired["build"], 42)

    def test_invalid_identity_does_not_upload(self):
        for build, commit in [(0, "abcdef1"), (42, "main"), (True, "abcdef1")]:
            with self.subTest(build=build, commit=commit), self.assertRaises(ValueError):
                self.publish(build, commit)
        self.assertEqual(self.bucket.calls, [])


if __name__ == "__main__":
    unittest.main()

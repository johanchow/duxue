"""A media failure must never replace the live homepage or touch APK metadata."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.tests.test_publish_download import FakeBucket

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("publish_website", ROOT / "scripts/publish-website.py")
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class WebsitePublishTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.bucket = FakeBucket()
        self.bucket.objects["latest.json"] = (b'original APK pointer', {})
        self.assets = {}
        for name in ["video", "poster", "captions"]:
            content = name.encode()
            (self.path / name).write_bytes(content)
            self.assets[name] = {"file": name, "key": f"media/{name}", "size": len(content),
                                 "sha256": hashlib.sha256(content).hexdigest(), "content_type": "test/type"}
        patcher = patch.object(publisher.page, "demo_assets", return_value=self.assets)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_media_staging_never_updates_homepage_or_latest(self):
        self.bucket.objects["index.html"] = (b"existing homepage", {})
        publisher.publish_media(self.bucket, self.path)
        self.assertEqual(self.bucket.calls, ["media/video", "media/poster", "media/captions"])
        self.assertEqual(self.bucket.objects["latest.json"][0], b'original APK pointer')
        self.assertIn("immutable", self.bucket.objects["media/video"][1]["Cache-Control"])
        self.assertEqual(self.bucket.objects["index.html"][0], b"existing homepage")

    def test_ci_page_embeds_both_scripts_and_resolves_media(self):
        html = publisher.page.page_bytes()
        self.assertIn(b'function startDemo', html)
        self.assertNotIn(b'src="demo.js"', html)
        self.assertNotIn(b'__DEMO_', html)

    def test_bad_local_media_is_rejected_before_any_upload(self):
        (self.path / 'captions').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'manifest'):
            publisher.publish_media(self.bucket, self.path)
        self.assertEqual(self.bucket.calls, [])

    def test_failed_upload_or_verification_keeps_existing_homepage(self):
        for fail in ['media/video', 'media/poster', 'media/captions', 'verification']:
            with self.subTest(fail=fail):
                bucket = FakeBucket(); bucket.objects['index.html'] = (b'old page', {})
                bucket.fail = fail; bucket.bad_meta = fail == 'verification'
                with self.assertRaises((ValueError, RuntimeError)):
                    publisher.publish_media(bucket, self.path)
                self.assertEqual(bucket.objects['index.html'][0], b'old page')

    def test_retry_reuses_verified_immutable_objects(self):
        publisher.publish_media(self.bucket, self.path)
        self.bucket.calls.clear()
        publisher.publish_media(self.bucket, self.path)
        self.assertEqual(self.bucket.calls, [])

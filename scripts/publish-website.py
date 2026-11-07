"""Stage immutable demo media for the approved main-branch release.

Homepage, APK objects and latest.json are never changed here.
The homepage is published only by the main-branch release workflow.
Credentials use environment variables.
"""
import argparse
import hashlib
import importlib.util
import os
from pathlib import Path

import oss2

spec = importlib.util.spec_from_file_location("download_publisher", Path(__file__).with_name("publish-download.py"))
page = importlib.util.module_from_spec(spec)
spec.loader.exec_module(page)


def publish_media(bucket, directory):
    assets = page.demo_assets()
    # Validate every local input before the first external write.
    for asset in assets.values():
        path = directory / asset["file"]
        with path.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        if path.stat().st_size != asset["size"] or digest != asset["sha256"]:
            raise ValueError("Demo asset does not match the committed manifest")
    for asset in assets.values():
        headers = {
            "Content-Type": asset["content_type"],
            "Cache-Control": "public, max-age=31536000, immutable",
            "x-oss-meta-sha256": asset["sha256"],
            "x-oss-forbid-overwrite": "true",
        }
        try:
            bucket.put_object_from_file(asset["key"], str(directory / asset["file"]), headers=headers)
        except oss2.exceptions.ObjectAlreadyExists:
            pass
        meta = bucket.head_object(asset["key"])
        if meta.content_length != asset["size"] or meta.headers.get("x-oss-meta-sha256") != asset["sha256"]:
            raise ValueError("Uploaded demo asset verification failed")
    print("Staged verified demo media; homepage and APK metadata unchanged.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    bucket = oss2.Bucket(oss2.Auth(os.environ["OSS_ACCESS_KEY_ID"], os.environ["OSS_ACCESS_KEY_SECRET"]),
                         page.ENDPOINT, page.BUCKET, connect_timeout=60)
    publish_media(bucket, args.directory)


if __name__ == "__main__":
    main()

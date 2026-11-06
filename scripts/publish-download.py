"""Publish verified release objects, then atomically move the latest pointer.

Credentials come only from environment variables; no Bucket configuration changes.
All entry points share the guardian-release workflow concurrency group.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

import oss2

BUCKET = "duxue-download-page"
ENDPOINT = "https://oss-cn-beijing.aliyuncs.com"
ROOT = Path(__file__).resolve().parents[1]
NO_CACHE = "no-store, max-age=0"


def read_latest(bucket):
    try:
        return json.loads(bucket.get_object("latest.json").read())
    except oss2.exceptions.NoSuchKey:
        return None


def page_bytes():
    html = (ROOT / "download-page/index.html").read_text()
    script = (ROOT / "download-page/download.js").read_text()
    # One object makes an HTML/JS update atomic for visitors.
    marker = '<script src="download.js" defer></script>'
    if html.count(marker) != 1 or "</script" in script.lower():
        raise ValueError("Invalid download page script boundary")
    return html.replace(marker, f"<script>\n{script}\n</script>").encode()


def publish(bucket, apk, version, build, commit):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?", version):
        raise ValueError("Invalid version")
    if type(build) is not int or build < 1 or not re.fullmatch(r"[0-9a-f]{7,40}", commit):
        raise ValueError("Invalid build identity")
    with apk.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    size = apk.stat().st_size
    if size == 0:
        raise ValueError("Empty APK")
    # Avoid '+' in public paths: OSS static hosting may decode it as a space.
    key = f"releases/android/guardian-{version}-{build}-{commit[:7]}-{digest[:12]}.apk"
    current = read_latest(bucket)
    if current is not None:
        previous = current["android"]
        if previous["build"] > build:
            print("Newer release is already published; skipping stale run.")
            return False
        if previous["build"] == build:
            if previous["sha256"] != digest or previous["commit"] != commit:
                raise ValueError("Build number already belongs to a different APK")
            if previous["url"] == f"/{key}":
                print("This release is already published.")
                return False
            # The identical APK may be republished to repair a legacy URL.
    headers = {
        "Content-Type": "application/vnd.android.package-archive",
        "Content-Disposition": f'attachment; filename="duxue-{version}-{build}.apk"',
        "Cache-Control": "public, max-age=31536000, immutable",
        "x-oss-meta-sha256": digest,
        "x-oss-forbid-overwrite": "true",
    }
    try:
        bucket.put_object_from_file(key, str(apk), headers=headers)
    except oss2.exceptions.ObjectAlreadyExists:
        # A previous attempt may have uploaded the APK and failed on the page.
        pass
    meta = bucket.head_object(key)
    if meta.content_length != size or meta.headers.get("x-oss-meta-sha256") != digest:
        raise ValueError("Uploaded APK verification failed")
    bucket.put_object("index.html", page_bytes(), headers={
        "Content-Type": "text/html; charset=utf-8", "Cache-Control": NO_CACHE,
    })
    data = {"android": {
        "url": f"/{key}", "version": version, "build": build,
        "size": size, "sha256": digest, "commit": commit,
    }, "ios": None}
    # Do not change latest until every required upload has succeeded.
    bucket.put_object("latest.json", json.dumps(data).encode(), headers={
        "Content-Type": "application/json; charset=utf-8", "Cache-Control": NO_CACHE,
    })
    print(f"Published Android {version} (Build {build}) to https://download.duxuelai.xyz/")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", type=int, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    bucket = oss2.Bucket(oss2.Auth(os.environ["OSS_ACCESS_KEY_ID"], os.environ["OSS_ACCESS_KEY_SECRET"]),
                         ENDPOINT, BUCKET, connect_timeout=60)
    publish(bucket, args.apk, args.version, args.build, args.commit)


if __name__ == "__main__":
    main()

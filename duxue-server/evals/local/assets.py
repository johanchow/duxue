"""Private OSS references for selected evaluation images; no Langfuse media."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from evals.schema import ASSET_NAME

PREFIX = "evals/omni-edu-v1/images/"
TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_BYTES = 20 * 1024 * 1024


def validate_reference(name, ref):
    if not isinstance(name, str) or not ASSET_NAME.fullmatch(name):
        raise ValueError("invalid OSS asset name")
    if not isinstance(ref, dict) or set(ref) != {
        "provider",
        "bucket_alias",
        "key",
        "sha256",
        "content_type",
        "size_bytes",
    }:
        raise ValueError("invalid OSS asset reference fields")
    checksum = ref["sha256"]
    suffix = Path(name).suffix.lower()
    if (
        ref["provider"] != "oss"
        or ref["bucket_alias"] != "eval"
        or not isinstance(checksum, str)
        or len(checksum) != 64
        or any(c not in "0123456789abcdef" for c in checksum)
        or suffix not in TYPES
        or ref["content_type"] != TYPES[suffix]
        or ref["key"] != f"{PREFIX}{checksum}{suffix}"
        or type(ref["size_bytes"]) is not int
        or not 0 < ref["size_bytes"] <= MAX_BYTES
    ):
        raise ValueError(f"invalid OSS asset reference: {name}")


def connect_bucket():
    # Lazy imports keep static dataset validation independent of .env and the SDK.
    from app.bootstrap.settings import settings
    from app.infrastructure.storage.object_storage import OssStorage

    if not all(
        (
            settings.oss_access_key_id,
            settings.oss_access_key_secret,
            settings.oss_bucket,
            settings.oss_endpoint,
        )
    ):
        raise ValueError("OSS configuration incomplete in server .env")
    return OssStorage(settings.oss_bucket).public_bucket


def verified_read(bucket, name, ref):
    validate_reference(name, ref)
    try:
        stream = bucket.get_object(ref["key"])
        try:
            data = stream.read(ref["size_bytes"] + 1)
        finally:
            stream.close()
    except Exception as exc:  # noqa: BLE001 - redact storage SDK credentials/URLs
        # SDK exceptions can contain signed URLs/credentials; never print raw text.
        raise ValueError(f"OSS read failed: {name} ({type(exc).__name__})") from None
    if (
        len(data) != ref["size_bytes"]
        or hashlib.sha256(data).hexdigest() != ref["sha256"]
    ):
        raise ValueError(f"OSS image integrity mismatch: {name}")
    return data


def upload_images(directory, names, bucket):
    refs = {}
    for name in sorted(set(names)):
        if not ASSET_NAME.fullmatch(name) or Path(name).suffix.lower() not in TYPES:
            raise ValueError("invalid image upload name")
        path = Path(directory) / name
        if not path.resolve().is_relative_to(Path(directory).resolve()):
            raise ValueError("unsafe image upload path")
        data = path.read_bytes()
        checksum = hashlib.sha256(data).hexdigest()
        suffix = path.suffix.lower()
        ref = {
            "provider": "oss",
            "bucket_alias": "eval",
            "key": f"{PREFIX}{checksum}{suffix}",
            "sha256": checksum,
            "content_type": TYPES[suffix],
            "size_bytes": len(data),
        }
        validate_reference(name, ref)
        try:
            if not bucket.object_exists(ref["key"]):
                try:
                    bucket.put_object(
                        ref["key"],
                        data,
                        headers={
                            "Content-Type": ref["content_type"],
                            "x-oss-object-acl": "private",
                            "x-oss-forbid-overwrite": "true",
                            "x-oss-meta-sha256": checksum,
                        },
                    )
                except Exception as exc:
                    # A concurrent uploader may have installed the same content.
                    if getattr(exc, "status", None) != 409:
                        raise
        except Exception as exc:  # noqa: BLE001 - redact storage SDK credentials/URLs
            raise ValueError(
                f"OSS upload failed: {name} ({type(exc).__name__})"
            ) from None
        verified_read(bucket, name, ref)
        refs[name] = ref
    return refs


def materialize(refs, directory, *, bucket=None):
    for name, ref in refs.items():
        validate_reference(name, ref)
    if not refs:
        return directory
    bucket = bucket if bucket is not None else connect_bucket()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for name, ref in refs.items():
        target = directory / name
        if not target.resolve().is_relative_to(directory.resolve()):
            raise ValueError("unsafe OSS materialization path")
        data = verified_read(bucket, name, ref)
        target.write_bytes(data)
    return directory


def resolve_selected(manifest, tasks, root, output):
    if "assets" not in manifest:
        return Path(root) / "assets"
    names = sorted({n for _, r in tasks for m in r.messages for n in m.images})
    refs = {name: manifest["assets"][name] for name in names}
    return materialize(refs, Path(output) / "resolved-assets")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("upload", "check"))
    p.add_argument("--data", type=Path, default=Path("evals/data/omni-edu-v1"))
    args = p.parse_args(argv)
    from evals.local.dataset import load, validate
    from evals.local.prepare import build, write

    try:
        manifest, tasks = load(args.data)
        if args.command == "upload":
            names = {n for _, r in tasks for m in r.messages for n in m.images}
            refs = upload_images(args.data / "assets", names, connect_bucket())
            # Publish references only after every object has been read back and verified.
            write(args.data / "assets.oss.json", refs)
            build(args.data)
            write(args.data / "validation.json", validate(args.data))
        else:
            refs = manifest.get("assets")
            if refs is None:
                raise ValueError("dataset has no OSS asset references")
            bucket = connect_bucket()
            for name, ref in refs.items():
                verified_read(bucket, name, ref)
        print(
            f"OSS {args.command}: {len(refs)} images verified; no model or Langfuse calls"
        )
        return 0
    except (ValueError, OSError, KeyError) as exc:
        print(f"OSS asset error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

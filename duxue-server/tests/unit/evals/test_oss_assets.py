import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.local import assets

DATA = b"image-fixture"
DIGEST = hashlib.sha256(DATA).hexdigest()
NAME = "test.png"
REF = {
    "provider": "oss",
    "bucket_alias": "eval",
    "key": f"evals/omni-edu-v1/images/{DIGEST}.png",
    "sha256": DIGEST,
    "content_type": "image/png",
    "size_bytes": len(DATA),
}


class Bucket:
    def __init__(self):
        self.objects = {}
        self.puts = []

    def object_exists(self, key):
        return key in self.objects

    def put_object(self, key, data, headers):
        self.puts.append((key, headers))
        self.objects[key] = data

    def get_object(self, key):
        return io.BytesIO(self.objects[key])


def test_upload_private_idempotent_and_download_verifies_bytes(tmp_path):
    (tmp_path / NAME).write_bytes(DATA)
    bucket = Bucket()
    refs = assets.upload_images(tmp_path, [NAME], bucket)
    assert refs[NAME] == REF
    assets.upload_images(tmp_path, [NAME], bucket)
    assert len(bucket.puts) == 1
    assert bucket.puts[0][1]["x-oss-object-acl"] == "private"
    assert bucket.puts[0][1]["x-oss-forbid-overwrite"] == "true"
    assets.materialize(refs, tmp_path / "resolved", bucket=bucket)
    assert (tmp_path / "resolved" / NAME).read_bytes() == DATA
    bucket.objects[REF["key"]] = b"corrupted"
    with pytest.raises(ValueError, match="integrity"):
        assets.materialize(refs, tmp_path / "bad", bucket=bucket)
    assert not (tmp_path / "bad" / NAME).exists()


def test_existing_wrong_content_never_overwritten(tmp_path):
    (tmp_path / NAME).write_bytes(DATA)
    bucket = Bucket()
    bucket.objects[REF["key"]] = b"incorrect"
    with pytest.raises(ValueError, match="integrity"):
        assets.upload_images(tmp_path, [NAME], bucket)
    assert not bucket.puts


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "http"),
        ("bucket_alias", "camera"),
        ("key", "../secret"),
        ("key", REF["key"] + "?signature=secret"),
        ("sha256", "bad"),
        ("content_type", "text/html"),
        ("size_bytes", 0),
    ],
)
def test_invalid_reference_rejected_before_network(field, value, tmp_path):
    with pytest.raises(ValueError):
        assets.materialize({NAME: {**REF, field: value}}, tmp_path)


def test_names_cannot_escape_materialization_directory(tmp_path):
    with pytest.raises(ValueError):
        assets.materialize({"../escape.png": REF}, tmp_path)


def test_remote_failure_does_not_fall_back_or_expose_credentials(tmp_path):
    (tmp_path / NAME).write_bytes(DATA)

    class Broken(Bucket):
        def get_object(self, key):
            raise RuntimeError("secret-access-key signed-url")

    with pytest.raises(ValueError, match="OSS read failed") as error:
        assets.materialize({NAME: REF}, tmp_path, bucket=Broken())
    assert "secret" not in str(error.value)


def test_selected_assets_resolve_only_selected_images(tmp_path, monkeypatch):
    bucket = Bucket()
    bucket.objects[REF["key"]] = DATA
    monkeypatch.setattr(assets, "connect_bucket", lambda: bucket)
    record = SimpleNamespace(messages=[SimpleNamespace(images=[NAME])])
    manifest = {"assets": {NAME: REF, "unused.png": REF}}
    result = assets.resolve_selected(
        manifest, [(None, record)], tmp_path, tmp_path / "run"
    )
    assert (result / NAME).read_bytes() == DATA
    assert not (result / "unused.png").exists()


def test_full_batch_oss_references_match_each_image_case():
    from evals.local.dataset import load

    root = Path("evals/data/omni-edu-v1")
    manifest, tasks = load(root)
    assert len(manifest["assets"]) > 0
    for entry, record in tasks:
        names = {n for m in record.messages for n in m.images}
        assert entry["assets"] == {
            name: manifest["assets"][name] for name in sorted(names)
        }
    assert "assets.oss.json" in manifest["files"]
    assert json.loads((root / "assets.oss.json").read_text()) == manifest["assets"]


def test_local_run_supplies_remote_bytes_to_image_execution(tmp_path, monkeypatch):
    from evals import live
    from evals.local import execution
    from evals.local.__main__ import main
    from evals.runner import read_asset

    root = Path("evals/data/omni-edu-v1")
    manifest = json.loads((root / "manifest.json").read_text())
    bucket = Bucket()
    for name, ref in manifest["assets"].items():
        bucket.objects[ref["key"]] = (root / "assets" / name).read_bytes()
    monkeypatch.setattr(assets, "connect_bucket", lambda: bucket)
    monkeypatch.setattr(live, "preflight", lambda: None)

    class Judge:
        spec = SimpleNamespace(model="independent-vision-judge", accepts_images=True)

        def metadata(self):
            return {"judge_model": self.spec.model}

    monkeypatch.setattr(
        live, "build_backends", lambda *a: SimpleNamespace(semantic_grader=Judge())
    )
    seen = []

    def execute(entry, record, backend, directory, index):
        assert directory == tmp_path / "run/resolved-assets"
        for message in record.messages:
            for name in message.images:
                original = root / "assets" / name
                assert (directory / name).read_bytes() == original.read_bytes()
                assert read_asset(directory / name) == read_asset(original)
                seen.append(name)
        return {
            **entry,
            "case_id": record.id,
            "sample_index": index,
            "status": "pass",
            "checks": [],
        }

    monkeypatch.setattr(execution, "execute", execute)
    assert (
        main(
            [
                "run",
                "--data",
                str(root),
                "--case",
                "omni-math-007",
                "--config-snapshot",
                "tests/fixtures/admin-release.json",
                "--out",
                str(tmp_path / "run"),
            ]
        )
        == 0
    )
    assert len(seen) == 1


def test_static_validation_does_not_import_oss_or_settings():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from evals.local.dataset import validate; import sys; "
                "validate('evals/data/omni-edu-v1'); "
                "assert 'oss2' not in sys.modules; assert 'app.bootstrap.settings' not in sys.modules"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

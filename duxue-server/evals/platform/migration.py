"""One-time idempotent import and read-only versioned exports."""

import json
import hashlib
import mimetypes
from evals.platform.protocol import convert, asset_names, digest
from evals.platform.client import dataset_items, dump


def migrate(client, resources, source, assets):
    from langfuse.media import LangfuseMedia

    if not source.is_dir():
        raise ValueError(f"Missing bootstrap snapshot: {source}")
    counts = {}
    for ds in resources["datasets"]:
        old = {i.id: i for i in dataset_items(client, ds["name"])}
        created = skipped = 0
        for path in sorted((source / ds["name"]).glob("*.json")):
            row = convert(json.loads(path.read_text()), ds["name"])
            current = old.get(row["id"])
            if current:
                if (current.metadata or {}).get("migration_digest") != row["metadata"][
                    "migration_digest"
                ] or digest([current.input["record"], current.expected_output]) != row[
                    "metadata"
                ]["migration_digest"]:
                    raise ValueError(
                        f"Remote item changed; refusing overwrite: {path.stem}"
                    )
                skipped += 1
                continue
            media = {}
            for name in asset_names(row["input"]["record"]):
                data = (assets / name).read_bytes()
                media[name] = {
                    "media": LangfuseMedia(
                        content_bytes=data, content_type=mimetypes.guess_type(name)[0]
                    ),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            row["input"]["assets"] = media
            client.create_dataset_item(dataset_name=ds["name"], **row)
            created += 1
        counts[ds["name"]] = {"created": created, "skipped": skipped}
    return counts


def export(client, resources, destination, version):
    destination.mkdir(parents=True, exist_ok=False)
    manifest = {
        "version": version.isoformat(),
        "project_id": resources["projectId"],
        "datasets": {},
    }
    for ds in resources["datasets"]:
        items = dataset_items(client, ds["name"], version)
        (destination / (ds["name"] + ".json")).write_text(
            json.dumps([dump(i) for i in items], ensure_ascii=False, indent=2) + "\n"
        )
        manifest["datasets"][ds["name"]] = len(items)
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest

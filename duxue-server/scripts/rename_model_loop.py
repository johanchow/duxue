"""Rename the tutoring model-loop workflow in a verified Admin export."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.registrations import LEGACY_LOOP, MODEL_LOOP
from scripts.upgrade_workflow_nodes import upgrade as upgrade_snapshot


def rename_workflow(files, old_id, new_id, title):
    parent = files["workflows/tutoring.json"]
    old_path = f"workflows/{old_id}.json"
    new_path = f"workflows/{new_id}.json"
    if old_path in files:
        flow = files.pop(old_path)
        flow["id"] = flow["handler"] = new_id
        names = {node["id"]: new_id + node["id"][len(old_id):] for node in flow["nodes"]}
        flow["entry"] = names[flow["entry"]]
        for node in flow["nodes"]:
            node["id"] = names[node["id"]]
            if node.get("parent"):
                node["parent"] = names[node["parent"]]
        for edge in flow["edges"]:
            for field in ("from", "to", "via"):
                if edge.get(field) in names:
                    edge[field] = names[edge[field]]
        files[new_path] = flow
    for call in parent["nodes"]:
        if call["id"] == new_id and call["kind"] == "workflow":
            call.update(ref=new_id, display_name=title)


def rename_files(files):
    rename_workflow(files, LEGACY_LOOP, MODEL_LOOP, "答复生成与重试")


def upgrade(record):
    return upgrade_snapshot(record, transform=rename_files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(upgrade(json.loads(args.source.read_text())), ensure_ascii=False))

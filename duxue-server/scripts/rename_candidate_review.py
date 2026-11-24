"""Rename the tutoring candidate-review workflow in a verified Admin export."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.registrations import LEGACY_REVIEW, REVIEW
from scripts.rename_model_loop import rename_workflow
from scripts.upgrade_workflow_nodes import upgrade as upgrade_snapshot


def rename_files(files):
    rename_workflow(files, LEGACY_REVIEW, REVIEW, "候选回复审核")


def upgrade(record):
    return upgrade_snapshot(record, transform=rename_files)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(json.dumps(upgrade(json.loads(args.source.read_text())), ensure_ascii=False))

"""Inspect Agent definitions and regenerate the shared workflow document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.agent_specs.catalog import load_catalog, render_mermaid


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("export", "show", "validate"))
    parser.add_argument("agent", nargs="?")
    args = parser.parse_args()
    catalog = load_catalog()
    if args.command == "validate":
        print("Agent definitions valid")
    elif args.command == "show":
        if args.agent not in catalog.specs:
            parser.error("show requires companion, planning, tutoring or reflection")
        print(json.dumps(catalog.expanded(args.agent), ensure_ascii=False, indent=2))
    else:
        path = Path(__file__).resolve().parents[3] / "docs" / "technical" / "agent-flow-current.md"
        path.write_text(render_mermaid(catalog), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()

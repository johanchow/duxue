"""Local files + local scoring; model calls require network, validation does not."""

from __future__ import annotations

import argparse
import contextvars
import hashlib
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("validate", "run"):
        q = sub.add_parser(command)
        q.add_argument("--data", type=Path, default=Path("evals/data/omni-edu-v1"))
        if command == "run":
            q.add_argument("--config-snapshot", type=Path, required=True)
            q.add_argument("--out", type=Path, required=True)
            for key in ("dataset", "subject", "level", "case", "split"):
                q.add_argument("--" + key, action="append")
            q.add_argument(
                "--preflight-only",
                action="store_true",
                help="Validate pinned configuration and selected cases without model calls",
            )
            q.add_argument("--samples", type=int, default=1)
            q.add_argument("--workers", type=int, default=2)
            q.add_argument(
                "--math-engine-mode",
                choices=("auto", "socket", "subprocess"),
                default="auto",
                help="Math execution transport for local evaluation (default: auto)",
            )
            q.add_argument(
                "--allow-incomplete",
                action="store_true",
                help="Run reviewed subset despite explicit quota gaps",
            )
    return p


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    temporary.replace(path)


def run(args, validation):
    from app.agent_specs.configuration import read_snapshot, select_offline_snapshot
    from app.agent_specs.definitions import use_definitions
    from evals.configuration import _record
    from evals.local.assets import resolve_selected
    from evals.local.dataset import load, select
    from evals.local.execution import execute
    from evals.local.report import summarize
    from evals.local.solve import identity

    manifest, tasks = load(args.data)
    tasks = select(tasks, args)
    if args.out.resolve().is_relative_to(args.data.resolve()):
        raise ValueError("output directory must be outside the input dataset")
    args.out.mkdir(parents=True, exist_ok=False)
    assets = args.data / "assets"
    if not args.preflight_only:
        assets = resolve_selected(manifest, tasks, args.data, args.out)
    snapshot = read_snapshot()
    definitions = select_offline_snapshot(snapshot)
    token = _record.set(snapshot)
    try:
        with use_definitions(definitions.catalog):
            from app.infrastructure.ai.components import COMPONENTS
            from evals.live import build_backends, preflight

            if not args.preflight_only:
                preflight()
            spec = COMPONENTS.get("tutoring.turn")
            backend = build_backends(spec)
            if backend.semantic_grader.spec.model in {
                spec.model,
                COMPONENTS.get("tutoring.turn-backup").model,
            }:
                raise ValueError(
                    "local quality judge must differ from both tutor models"
                )
            if any(m.images for _, r in tasks for m in r.messages):
                required_specs = [
                    spec,
                    COMPONENTS.get("tutoring.turn-backup"),
                    backend.semantic_grader.spec,
                ]
                if any(not item.accepts_images for item in required_specs):
                    raise ValueError(
                        "selected images require image-capable tutor/backup/quality judge in snapshot"
                    )
            metadata = {
                "started_at": datetime.now(timezone.utc).isoformat(),
                "mode": "local_files_local_scores",
                "langfuse_used": False,
                "math_engine_mode": os.environ.get("MATH_ENGINE_MODE", "socket"),
                "config_digest": snapshot["digest"],
                "validation": validation,
                "selected_ids": [e["id"] for e, _ in tasks],
                "samples": args.samples,
                "solver": identity(spec),
                "grader": backend.semantic_grader.metadata(),
                "dataset_manifest": manifest,
            }
            code_files = {
                str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                for base in ("evals", "app")
                for p in sorted(Path(base).rglob("*.py"))
            }
            metadata["code_files"] = code_files
            write(args.out / "manifest.json", metadata)
            write(args.out / "config-snapshot.json", snapshot)
            shutil.copytree(args.data, args.out / "dataset")
            if args.preflight_only:
                write(
                    args.out / "preflight.json",
                    {
                        "status": "passed",
                        "selected_tasks": len(tasks),
                        "model_calls": 0,
                        "langfuse_used": False,
                        "selected_checkpoints": sum(len(r.checks) for _, r in tasks),
                    },
                )
                print(f"Preflight passed: {len(tasks)} tasks; no model calls")
                return 0
            jobs = [(e, r, index) for e, r in tasks for index in range(args.samples)]

            def work(entry, record, index):
                try:
                    return execute(
                        entry, record, backend, assets, spec, index
                    )
                except Exception as exc:  # noqa: BLE001 - isolate one failed evaluation sample
                    return {
                        **entry,
                        "case_id": record.id,
                        "sample_index": index,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                        "checks": [],
                    }

            rows = []
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures = [
                    pool.submit(contextvars.copy_context().run, work, *job)
                    for job in jobs
                ]
                for future in futures:
                    row = future.result()
                    write(
                        args.out / f"{row['case_id']}-{row['sample_index']}.json", row
                    )
                    rows.append(row)
                    print(
                        f"{len(rows)}/{len(jobs)} {row['case_id']} {row['status']}",
                        flush=True,
                    )
            result = {"summary": summarize(rows), "results": rows}
            write(args.out / "results.json", result)
            print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
            return int(any(row["status"] != "pass" for row in rows))
    finally:
        _record.reset(token)


def main(argv=None):
    args = parser().parse_args(argv)
    # Set before importing app/settings: .env must never activate remote exporters.
    os.environ["OTEL_SDK_DISABLED"] = "true"
    os.environ["LANGFUSE_ENABLED"] = "false"
    os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
    try:
        from evals.local.dataset import validate

        validation = validate(args.data)
        if args.command == "validate":
            print(json.dumps(validation, ensure_ascii=False, indent=2))
            return int(validation["acceptance_status"] != "passed")
        if args.samples < 1 or not 1 <= args.workers <= 8:
            raise ValueError("samples must be positive; workers must be 1..8")
        if validation["gaps"] and not args.allow_incomplete:
            raise ValueError(
                "dataset acceptance incomplete; review gaps or explicitly use --allow-incomplete"
            )
        os.environ["AGENT_CONFIG_SOURCE"] = "snapshot"
        os.environ["AGENT_CONFIG_SNAPSHOT"] = str(args.config_snapshot.resolve())
        if args.math_engine_mode in {"socket", "subprocess"}:
            os.environ["MATH_ENGINE_MODE"] = args.math_engine_mode
        elif not os.environ.get("MATH_ENGINE_MODE") and not os.environ.get(
            "MATH_ENGINE_SOCKET"
        ):
            socket_file = Path("/run/math/engine.sock")
            if not socket_file.exists():
                os.environ["MATH_ENGINE_MODE"] = "subprocess"
        return run(args, validation)
    except (ValueError, OSError, KeyError) as exc:
        print(f"Local evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

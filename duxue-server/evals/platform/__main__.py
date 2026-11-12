"""Langfuse is authoritative; this CLI only executes code and transports results."""

from __future__ import annotations
import argparse
import asyncio
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from evals.platform.client import connect, dataset_items, dump, RULE_ENVIRONMENTS
from evals.platform.protocol import hydrate


def write(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n"
    )
    temporary.replace(path)


def preflight(client, resources):
    versions = {}
    rules = []
    cursor = None
    while True:
        page = client.api.evaluation_rules.list(limit=100, cursor=cursor)
        rules.extend(dump(r) for r in page.data)
        cursor = page.meta.cursor
        if not cursor:
            break
    for entry in resources["evaluators"]:
        if not entry["name"].startswith("eval."):
            continue
        evaluator = client.api.evaluators.get(entry["id"])
        if evaluator.name != entry["name"]:
            raise ValueError(f"Evaluator score name changed: {entry['name']}")
        if evaluator.status != "active":
            raise ValueError(f"Evaluator inactive: {entry['name']}")
        versions[entry["name"]] = dump(evaluator)
        matching = [
            r
            for r in rules
            if r["name"] == "offline/" + entry["name"]
            and r["enabled"]
            and r["sampling"] == 1
        ]
        if len(matching) != 1:
            raise ValueError(f"Missing/ambiguous offline rule: {entry['name']}")
        rule = matching[0]
        if [a["evaluatorId"] for a in rule["evaluatorAssignments"]] != [entry["id"]]:
            raise ValueError(
                f"Offline rule references another evaluator: {entry['name']}"
            )
        required_filters = [
            {
                "column": "name",
                "type": "stringOptions",
                "operator": "any of",
                "value": ["eval.checkpoint"],
            },
            {
                "column": "environment",
                "type": "stringOptions",
                "operator": "any of",
                "value": RULE_ENVIRONMENTS,
            },
            {
                "column": "metadata",
                "type": "stringObject",
                "operator": "=",
                "key": entry["name"].replace(".", "_"),
                "value": "yes",
            },
        ]
        if sorted(
            map(lambda f: json.dumps(f, sort_keys=True), rule["filter"])
        ) != sorted(map(lambda f: json.dumps(f, sort_keys=True), required_filters)):
            raise ValueError(
                f"Offline rule filter differs from runner protocol: {entry['name']}"
            )
    return versions, rules


def score_comments(result):
    """Explain task aggregation without creating another copy of native grades."""
    lines = [
        f"自动汇总：{result['status']}。语义裁判未校准，失败不等于已确认的产品缺陷。"
    ]
    for check in result.get("checks", []):
        lines.append(
            f"{check.get('check_id')}: {check['status']}；详细评分所在 observation={check.get('observation_id', '未执行')}。"
        )
        if check.get("error"):
            lines.append(f"执行/收分错误：{check['error']}")
        for grade in check.get("grades", []):
            if grade["status"] != "pass":
                lines.append(
                    f"{grade['name']}={grade.get('value')} ({grade['status']})：{(grade.get('comment') or grade.get('reason') or '缺少有效评分')[:500]}"
                )
    if result.get("error"):
        lines.append(str(result["error"]))
    summary = "\n".join(lines)
    return {
        "eval.status": summary,
        "eval.task_success": "仅当所有必需检查点及原生评分均通过时为 True。\n"
        + summary,
        "eval.latency_ms": "实际业务组件执行耗时（毫秒）；不含云端评分排队与轮询等待。",
    }


def aggregate(client, configs, result, trace_id, observation_id):
    # Mechanical run status only; checkpoint judgments are never recomputed or copied.
    comments = score_comments(result)
    values = [("eval.status", result["status"], "CATEGORICAL")]
    if result["status"] in ("pass", "fail"):
        values.append(
            ("eval.task_success", float(result["status"] == "pass"), "BOOLEAN")
        )
    if result["status"] != "error":
        values.append(("eval.latency_ms", result["latency_ms"], "NUMERIC"))
    for name, value, kind in values:
        if name not in configs:
            raise ValueError(f"Missing Score Config: {name}")
        client.create_score(
            name=name,
            value=value,
            data_type=kind,
            config_id=configs[name],
            comment=comments[name],
            trace_id=trace_id,
            observation_id=observation_id,
            score_id=str(
                uuid.uuid5(uuid.NAMESPACE_URL, trace_id + observation_id + name)
            ),
            metadata={
                "scope": "task",
                "aggregation": "all_required",
                "calibration_status": "uncalibrated",
            },
        )


def run(args, client, resources):
    from evals.platform.native import NativeScorer
    from evals.platform.execution import execute_item
    from app.agent_specs.configuration import read_snapshot, select_offline_snapshot
    from app.agent_specs.definitions import use_definitions
    from evals.configuration import _record

    version = (
        datetime.fromisoformat(args.version.replace("Z", "+00:00"))
        if args.version
        else datetime.now(timezone.utc)
    )
    if version.tzinfo is None:
        raise ValueError("--version requires timezone")
    output = Path(
        args.out or ("var/evals/langfuse-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    )
    output.mkdir(parents=True, exist_ok=False)
    versions, rules = preflight(client, resources)
    configs = {
        c.name: c.id
        for c in client.api.score_configs.get(limit=100).data
        if not c.is_archived
    }
    selected = {}
    unknown_datasets = set(args.dataset or []) - {
        d["name"] for d in resources["datasets"]
    }
    if unknown_datasets:
        raise ValueError(f"Unknown datasets: {sorted(unknown_datasets)}")
    requested = set(args.case or [])
    for ds in resources["datasets"]:
        if args.dataset and ds["name"] not in args.dataset:
            continue
        items = [
            i
            for i in dataset_items(client, ds["name"], version)
            if i.status == "ACTIVE"
        ]
        if requested:
            items = [i for i in items if i.input["record"]["id"] in requested]
        for item in items:
            hydrate(item)
            for check in item.expected_output["checks"].values():
                if set(check["evaluators"]) - set(versions):
                    raise ValueError("Unknown evaluator in dataset")
        if items:
            selected[ds["name"]] = items
    found = {i.input["record"]["id"] for rows in selected.values() for i in rows}
    if len(found) != sum(map(len, selected.values())):
        raise ValueError("Duplicate case_id across datasets")
    if not found or requested - found:
        raise ValueError(f"No cases or missing cases: {sorted(requested - found)}")
    snapshot = read_snapshot()
    definition = select_offline_snapshot(snapshot)
    write(output / "config-snapshot.json", snapshot)
    write(output / "evaluators.json", versions)
    write(output / "evaluation-rules.json", rules)
    write(
        output / "datasets.json",
        {name: [dump(i) for i in rows] for name, rows in selected.items()},
    )
    manifest = {
        "run_id": output.name + "-" + uuid.uuid4().hex[:8],
        "dataset_version": version.isoformat(),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True)
        ),
        "config_digest": snapshot["digest"],
        "grader_version": ",".join(
            f"{name}:v{e['version']}" for name, e in versions.items()
        ),
        "case_count": len(found),
        "experiments": [],
    }
    source_files = {
        str(p): p.read_text()
        for base in ("app", "evals")
        for p in sorted(Path(base).rglob("*.py"))
    }
    from evals.platform.protocol import digest

    manifest["code_digest"] = digest(source_files)
    write(output / "code-snapshot.json", source_files)
    write(output / "manifest.json", manifest)
    results = []
    token = _record.set(snapshot)
    try:
        with use_definitions(definition.catalog):
            from evals.live import preflight as model_preflight, build_backends
            from app.infrastructure.ai.components import COMPONENTS

            model_preflight()
            backends = {
                key: build_backends(COMPONENTS.get(key), native_only=True)
                for key in ("tutoring.turn", "companion.intent")
            }
            scorer = NativeScorer(
                client,
                versions,
                timeout=args.score_timeout,
                journal=output / "checkpoints",
            )
            for name, items in selected.items():

                def sync_task(*, item):
                    trace_id = client.get_current_trace_id()
                    observation_id = client.get_current_observation_id()
                    try:
                        result = execute_item(client, item, scorer, backends)
                    except Exception as exc:
                        result = {
                            "case_id": item.input["record"]["id"],
                            "status": "error",
                            "error": f"{type(exc).__name__}: {exc}",
                            "checks": [],
                            "latency_ms": 0,
                        }
                    result.update(
                        trace_id=trace_id,
                        observation_id=observation_id,
                        dataset=name,
                        item_id=item.id,
                    )
                    from evals.platform.reporting import report_task_status

                    report_task_status(client, result)
                    write(output / (item.id + ".json"), result)
                    aggregate(client, configs, result, trace_id, observation_id)
                    results.append(result)
                    return result

                async def task(*, item, **kwargs):
                    from evals.platform.reporting import call_offline_task

                    return await asyncio.to_thread(
                        call_offline_task, sync_task, item=item
                    )

                experiment = client.run_experiment(
                    name=name,
                    run_name=manifest["run_id"] + "/" + name,
                    data=items,
                    task=task,
                    max_concurrency=args.workers,
                    _dataset_version=version,
                    metadata={
                        k: str(v) for k, v in manifest.items() if k != "experiments"
                    },
                )
                manifest["experiments"].append(
                    {
                        "dataset": name,
                        "id": experiment.experiment_id,
                        "url": experiment.experiment_url,
                    }
                )
                write(output / "manifest.json", manifest)
    finally:
        _record.reset(token)
        client.flush()
    # A changed evaluator definition makes the result non-reproducible; report explicitly.
    changed = [
        name
        for name, e in versions.items()
        if client.api.evaluators.get(e["id"]).version_id != e["versionId"]
    ]
    summary = {
        "counts": {
            s: sum(r["status"] == s for r in results)
            for s in ("pass", "fail", "error", "not_run")
        },
        "expected_cases": len(found),
        "completed_cases": len(results),
        "evaluator_changes": changed,
        "results": results,
        "calibration_status": "uncalibrated",
    }
    write(output / "results.json", summary)
    print(
        json.dumps(
            {
                "output": str(output.resolve()),
                "counts": summary["counts"],
                "evaluator_changes": changed,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return int(
        bool(changed)
        or len(results) != len(found)
        or any(r["status"] != "pass" for r in results)
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    migrate = sub.add_parser(
        "migrate",
        help="One-time import of the historical bootstrap snapshot; never overwrites edits",
    )
    migrate.add_argument("--source", default="evals/bootstrap/2026-11-11")
    migrate.add_argument("--assets", default="var/eval-assets")
    export = sub.add_parser("export", help="Read-only remote snapshot")
    export.add_argument("--out", required=True)
    export.add_argument("--version")
    resume = sub.add_parser(
        "resume", help="Collect late scores without repeating model calls"
    )
    resume.add_argument("--out", required=True)
    resume.add_argument("--score-timeout", type=int, default=300)
    p = sub.add_parser("run", help="Run current hosted datasets with native evaluators")
    p.add_argument("--dataset", action="append")
    p.add_argument("--case", action="append")
    p.add_argument("--version")
    p.add_argument("--config-snapshot", required=True)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--score-timeout", type=int, default=300)
    p.add_argument("--out")
    args = parser.parse_args(argv)
    if args.command == "run" and (args.workers < 1 or args.workers > 8):
        parser.error("--workers must be between 1 and 8")
    if hasattr(args, "score_timeout") and args.score_timeout <= 0:
        parser.error("--score-timeout must be positive")
    if args.command == "run":
        os.environ["AGENT_CONFIG_SOURCE"] = "snapshot"
        os.environ["AGENT_CONFIG_SNAPSHOT"] = str(Path(args.config_snapshot).resolve())
    client, resources = connect()
    try:
        if args.command == "run":
            return run(args, client, resources)
        if args.command == "resume":
            from evals.platform.resume import resume

            return resume(client, Path(args.out), args.score_timeout)
        from evals.platform import migration

        if args.command == "migrate":
            print(
                migration.migrate(
                    client, resources, Path(args.source), Path(args.assets)
                )
            )
        else:
            version = (
                datetime.fromisoformat(args.version.replace("Z", "+00:00"))
                if args.version
                else datetime.now(timezone.utc)
            )
            print(migration.export(client, resources, Path(args.out), version))
        return 0
    finally:
        client.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())

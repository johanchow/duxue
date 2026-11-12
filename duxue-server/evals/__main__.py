"""python -m evals {validate,run,export,compare}   (run from duxue-server/)"""

from __future__ import annotations

import os

# Historical offline commands disable telemetry; hosted run enables its explicit Langfuse client.
os.environ["OTEL_SDK_DISABLED"] = "true"

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# No app import at module level: `validate` must work without runtime secrets.
from evals import conversations, dataset, episodes

COMPONENTS = ("tutoring.turn", "companion.intent")
VARIANT_NAMES = (
    "baseline",
    "drop-no-guess-clause",
)  # kept in sync with evals.variants.VARIANTS (tested)


def _load_app(*modules: str):
    """Import modules that need the app's runtime configuration, with a readable failure."""
    import importlib

    try:
        return [importlib.import_module(name) for name in modules]
    except Exception as error:
        if type(error).__name__ == "ConfigurationError":
            raise SystemExit(f"缺少运行配置，无法调用应用代码：{error}") from error
        raise


def _git_sha() -> str:
    try:
        root = dataset.ROOT
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True
        ).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}" or "unknown"
    except OSError:
        return "unknown"


from evals.configuration import snapshot_identity as _snapshot_identity


def cmd_validate(args) -> int:
    from evals import judge_boundary

    path = (
        Path(args.path)
        if args.path
        else (dataset.DATA_DIR / args.category if args.category else dataset.DATA_DIR)
    )
    cases = dataset.load_cases(path)
    multi = episodes.load_episodes(path)
    judges = judge_boundary.load_cases(path)
    replays = conversations.load_conversations(path)
    problems = dataset.validate(cases)
    problems.extend(episodes.validate_episodes(multi))
    ids = (
        [c.id for c in cases]
        + [c.id for c in multi]
        + [c["id"] for c in judges]
        + [c.id for c in replays]
    )
    if len(ids) != len(set(ids)):
        problems.append("duplicate case id across record types")
    if path == dataset.DATA_DIR:
        problems.extend(dataset.validate_layout())
    if args.batch:
        cases = [case for case in cases if case.review_batch == args.batch]
        multi = [row for row in multi if row.review_batch == args.batch]
        judges = [row for row in judges if row.get("review_batch") == args.batch]
        replays = [row for row in replays if row.review_batch == args.batch]
    if not cases and not multi and not judges and not replays:
        problems.append("no matching cases or episodes")
    for problem in problems:
        print(f"! {problem}")
    by_status = {
        s: sum(c.label_status == s for c in cases)
        for s in ("confirmed", "proposed", "needs_decision")
    }
    print(
        f"{len(cases)} cases + {len(multi)} episodes + {len(judges)} judge cases + {len(replays)} conversations  {by_status}  hash={dataset.dataset_hash(cases)}"
    )
    return 1 if problems else 0


def cmd_run_conversations(args) -> int:
    if args.samples < 1:
        print("--samples 必须大于 0", file=sys.stderr)
        return 2
    rows = [
        row
        for row in conversations.load_conversations(
            Path(args.path) if args.path else conversations.DIRECTORY
        )
        if row.label_status in args.status.split(",")
        and (not args.case or row.id in args.case)
        and (not args.batch or row.review_batch == args.batch)
    ]
    if not rows:
        print("没有符合筛选条件的 conversation", file=sys.stderr)
        return 2
    live, runner, variants = _load_app(
        "evals.live", "evals.conversation_runner", "evals.variants"
    )
    live.preflight()
    from app.infrastructure.ai.components import COMPONENTS as registry

    scope = args.scope
    if scope == "image-context":
        if args.model or args.variant != "baseline":
            print(
                "image-context使用快照内选图Agent，不支持主模型variant", file=sys.stderr
            )
            return 2
        spec = registry.get("tutoring.image-target")
        results = runner.run_image_context(rows, samples=args.samples)
        gate_meta = {}
    else:
        spec = variants.resolve_spec(
            "tutoring.turn", model=args.model, variant=args.variant
        )
        gate = registry.get("tutoring.leak-judge")
        results = runner.run_conversations(
            rows, live.build_backends(spec), samples=args.samples
        )
        gate_meta = {
            "judge_version": gate.version,
            "judge_model": gate.model,
            "judge_prompt_digest": gate.prompt.digest,
            "judge_definition_digest": gate.definition_digest,
        }
    summary = runner.summarize(results)
    if scope == "image-context":
        summary["excluded_checks"] = sum(len(row["excluded_checks"]) for row in results)
        summary["note"] = (
            "仅验证选图与历史隔离；未执行主回复、数学批改及Judge准确率检查。"
        )
    payload = {
        "meta": {
            "type": "conversation_replay",
            "replay_mode": "fixed_history",
            "scope": scope,
            "component": spec.component_id,
            "component_version": spec.version,
            "model": spec.model,
            "prompt_digest": spec.prompt.digest,
            "definition_digest": spec.definition_digest,
            "variant": args.variant,
            "samples": args.samples,
            **gate_meta,
            "dataset_hash": conversations.conversations_hash(rows),
            "review_batch": args.batch,
            "config_snapshot": _snapshot_identity(),
            "report_version": "eval-report.v2",
            "git_sha": _git_sha(),
            "at": datetime.now(timezone.utc).isoformat(),
        },
        "summary": summary,
        "conversations": results,
    }
    out = (
        Path(args.out)
        if args.out
        else dataset.RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-conversations.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print(f"结果：{out}")
    return (
        1
        if summary["failed"]
        or summary["errors"]
        or (scope == "full" and summary["not_run"])
        else 0
    )


def cmd_run_judges(args) -> int:
    from evals import judge_boundary

    options = [
        "--samples",
        str(args.samples),
        "--workers",
        str(args.workers),
        "--status",
        args.status,
    ]
    for option in ("batch", "out"):
        value = getattr(args, option)
        if value:
            options.extend(["--" + option, value])
    for case_id in args.case or []:
        options.extend(["--case", case_id])
    if args.with_reference:
        options.append("--with-reference")
    return judge_boundary.main(options)


def cmd_run_episodes(args) -> int:
    if args.samples < 1:
        print("--samples 必须大于 0", file=sys.stderr)
        return 2
    live, episode_runner, variants = _load_app(
        "evals.live", "evals.episode_runner", "evals.variants"
    )
    rows = episodes.load_episodes()
    problems = episodes.validate_episodes(rows)
    problems.extend(dataset.validate_layout())
    if problems:
        print("\n".join(f"! {p}" for p in problems))
        return 1
    selected = [
        row
        for row in rows
        if row.label_status in args.status.split(",")
        and (not args.case or row.id in args.case)
        and (not args.batch or row.review_batch == args.batch)
    ]
    if not selected:
        print("没有符合筛选条件的 episode", file=sys.stderr)
        return 2
    live.preflight()
    spec = variants.resolve_spec(
        "tutoring.turn", model=args.model, variant=args.variant
    )
    from evals.runner import sample_json

    results = episode_runner.run_episodes(
        selected, live.build_backends(spec), samples=args.samples
    )
    summary = episode_runner.summarize_episodes(results)
    out = (
        Path(args.out)
        if args.out
        else dataset.RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-episodes.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "meta": {
                    "component": "tutoring.turn",
                    "component_version": spec.version,
                    "model": spec.model,
                    "variant": args.variant,
                    "config_snapshot": _snapshot_identity(),
                    "report_version": "eval-report.v2",
                    "git_sha": _git_sha(),
                    "at": datetime.now(timezone.utc).isoformat(),
                    "episodes_hash": episodes.episodes_hash(selected),
                    "review_batch": args.batch,
                    "samples": args.samples,
                    "prompt_digest": spec.prompt.digest,
                    "definition_digest": spec.definition_digest,
                },
                "summary": summary,
                "episodes": [
                    {
                        "id": row.episode.id,
                        "label_status": row.episode.label_status,
                        "reviewed_by": row.episode.reviewed_by,
                        "review_batch": row.episode.review_batch,
                        "grading": [
                            t.grading.model_dump(mode="json", by_alias=True)
                            for t in row.episode.turns
                        ],
                        "samples": [
                            {
                                "passed": sample.passed,
                                "status": sample.status,
                                "stopped_at": sample.stopped_at,
                                "turns": [
                                    {"student_said": said, **sample_json(step)}
                                    for said, step in zip(
                                        sample.student_said, sample.steps
                                    )
                                ],
                            }
                            for sample in row.samples
                        ],
                    }
                    for row in results
                ],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(
        f"{summary['episodes']} episodes  stable_pass={summary['stable_pass']}  any_pass={summary['any_pass']}  skipped={summary['skipped']}"
    )
    if not summary["by_status"]["confirmed"]["episodes"]:
        print("没有 confirmed episode；结果仅供观察，不构成发布门槛。")
    print(f"结果：{out}")
    return (
        1 if any(not sample.passed for row in results for sample in row.samples) else 0
    )


def cmd_run(args) -> int:
    live, report, runner, variants = _load_app(
        "evals.live", "evals.report", "evals.runner", "evals.variants"
    )
    run_cases, resolve_spec = runner.run_cases, variants.resolve_spec

    cases = dataset.load_cases(
        dataset.DATA_DIR / args.category if args.category else None
    )
    problems = dataset.validate(cases)
    problems.extend(dataset.validate_layout())
    if problems:
        print("\n".join(f"! {p}" for p in problems))
        return 1
    components = [args.component] if args.component else list(COMPONENTS)
    if (args.model or args.variant != "baseline") and not args.component:
        print(
            "--model / --variant 只作用于一个组件，请同时给 --component",
            file=sys.stderr,
        )
        return 2
    live.preflight()
    selected = [
        c
        for c in cases
        if c.component in components
        and c.label_status in args.status.split(",")
        and (not args.tag or args.tag in c.tags)
        and (not args.case or c.id in args.case)
        and (not args.batch or c.review_batch == args.batch)
    ]
    if not selected:
        print("没有符合筛选条件的 case", file=sys.stderr)
        return 2
    if args.min_pass is not None and any(
        case.grading.model_graded for case in selected
    ):
        print("语义裁判未校准，不能启用--min-pass质量门槛。", file=sys.stderr)
        return 2
    exit_code = 0
    for component in components:
        subset = [c for c in selected if c.component == component]
        if not subset:
            continue
        spec = resolve_spec(component, model=args.model, variant=args.variant)
        done = [0]

        def tick(_case, total=len(subset) * args.samples):
            done[0] += 1
            if sys.stderr.isatty():
                print(
                    f"\r{component} {done[0]}/{total}",
                    end="",
                    file=sys.stderr,
                    flush=True,
                )

        results = run_cases(
            subset,
            {component: live.build_backends(spec)},
            samples=args.samples,
            workers=args.workers,
            on_sample=tick,
        )
        if sys.stderr.isatty():
            print(file=sys.stderr)
        if any(
            result.status == "skipped" or any(not s.passed for s in result.samples)
            for result in results
        ):
            exit_code = 1
        summary = report.summarize(results)
        meta = {
            "component": component,
            "component_version": spec.version,
            "model": spec.model,
            "definition_digest": spec.definition_digest,
            "variant": args.variant,
            "prompt_digest": spec.prompt.digest[:12]
            if hasattr(spec.prompt, "digest")
            else None,
            "samples": args.samples,
            "dataset_hash": dataset.dataset_hash(selected),
            "cases_run": len(subset),
            "category": args.category,
            "review_batch": args.batch,
            "config_snapshot": _snapshot_identity(),
            "report_version": "eval-report.v2",
            "git_sha": _git_sha(),
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        print(report.render_text(meta, summary, results))
        if args.out:
            out = Path(args.out)
            if len(components) > 1:  # one file per component, never overwrite
                out = out.with_name(
                    f"{out.stem}-{component.replace('.', '_')}{out.suffix}"
                )
        else:
            out = (
                dataset.RESULTS_DIR
                / f"{datetime.now():%Y%m%d-%H%M%S}-{component.replace('.', '_')}-{args.variant}.json"
            )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {"meta": meta, "summary": summary, "cases": report.to_json(results)},
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"结果：{out}")
        if args.min_pass is not None:
            stable = summary["primary"]["confirmed"]["overall"]["cases_stable_pass"]
            if stable["n"] == 0 or stable["rate"] < args.min_pass:
                exit_code = 1
    return exit_code


def cmd_export(args) -> int:
    database, object_storage, export = _load_app(
        "app.infrastructure.persistence.database",
        "app.infrastructure.storage.object_storage",
        "evals.export",
    )
    SessionLocal, storage = database.SessionLocal, object_storage.storage

    db = SessionLocal()
    try:
        conversation_id, rows = export.load_thread_rows(db, args.thread)
    finally:
        db.close()
    cases = export.build_cases(
        rows,
        conversation_id=conversation_id,
        component=args.component,
        asset_for=export.asset_writer(storage.read_bytes),
        names=tuple(args.name or ()),
    )
    problems = dataset.validate([record.to_case() for record in cases])
    out = (
        Path(args.out)
        if args.out
        else dataset.RESULTS_DIR
        / "candidates"
        / f"{conversation_id}-{args.component.replace('.', '_')}.jsonl"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "\n".join(c.model_dump_json() for c in cases) + "\n", encoding="utf-8"
    )
    flagged = sum(bool(c.flags) for c in cases)
    print(f"{len(cases)} 个决策点（{flagged} 个被自动标记）→ {out}")
    print(
        "下一步：补 checks[].input_snapshot 和 grading，人工复核后放入对应目录；缺失快照不会被当作完整回放。"
    )
    for problem in problems:
        print(f"! {problem}")
    return 0


def cmd_compare(args) -> int:
    first, second = (
        json.loads(Path(p).read_text(encoding="utf-8")) for p in (args.a, args.b)
    )
    if any(
        row["meta"].get("report_version") != "eval-report.v2" for row in (first, second)
    ):
        print("报告协议不同或过旧，请重新运行评测。", file=sys.stderr)
        return 2
    if first["meta"].get("samples") != second["meta"].get("samples"):
        print("采样次数不同，不直接比较。", file=sys.stderr)
        return 2

    def scoring_identity(payload):
        return {
            c["id"]: [
                {
                    k: s.get("meta", {}).get(k)
                    for k in (
                        "grader_version",
                        "rubric_digest",
                        "judge_model",
                        "judge_prompt_digest",
                        "judge_parameters",
                    )
                }
                for s in c["samples"]
            ]
            for c in payload["cases"]
        }

    if scoring_identity(first) != scoring_identity(second):
        print("评分器、rubric或裁判配置不同，不直接比较。", file=sys.stderr)
        return 2
    if first["meta"]["dataset_hash"] != second["meta"]["dataset_hash"]:
        print("数据集哈希不同，两次结果不可比。", file=sys.stderr)
        return 2
    if first["meta"].get("review_batch") != second["meta"].get("review_batch"):
        print("复核批次不同，两次结果不可比。", file=sys.stderr)
        return 2
    print(
        f"A: {first['meta']['variant']} {first['meta']['model']}   B: {second['meta']['variant']} {second['meta']['model']}"
    )
    index = {c["id"]: c for c in second["cases"]}
    for case in first["cases"]:
        other = index.get(case["id"])
        if not other or case["status"] != "ran" or other["status"] != "ran":
            continue
        a, b = (sum(s["passed"] for s in c["samples"]) for c in (case, other))
        if a != b:
            print(
                f"{case['id']:<34}{a}/{len(case['samples'])} -> {b}/{len(other['samples'])}  [{case['label_status']}]"
            )
    print(
        "差异只有在两次采样次数和区间都支持时才算差异；小数据集上的 1~2 例变化是噪声。"
    )
    return 0


def historical_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="校验数据集（无网络）")
    p.add_argument("--path")
    p.add_argument(
        "--category",
        choices=dataset.CATEGORIES,
    )
    p.add_argument("--batch", help="仅统计指定人工复核批次，如 seed-v1")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("run", help="用真实模型重放数据集（联网，不进 CI）")
    p.add_argument("--component", choices=COMPONENTS)
    p.add_argument("--samples", type=int, default=5)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--model", help="仅评测进程内换模型")
    p.add_argument("--variant", default="baseline", choices=VARIANT_NAMES)
    p.add_argument("--status", default="confirmed,proposed,needs_decision")
    p.add_argument("--tag")
    p.add_argument("--case", action="append")
    p.add_argument("--category", choices=dataset.SINGLE_TURN_CATEGORIES)
    p.add_argument("--batch", help="仅运行指定人工复核批次，如 seed-v1")
    p.add_argument(
        "--min-pass",
        type=float,
        help="confirmed 全部采样都通过的 case 占比低于它则退出码 1",
    )
    p.add_argument("--out")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("run-judges", help="重放独立判官用例（联网）")
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--status", default="confirmed,proposed,needs_decision")
    p.add_argument("--case", action="append")
    p.add_argument("--batch")
    p.add_argument("--out")
    p.add_argument(
        "--with-reference", action="store_true", help="诊断对照：额外注入人工题面参考"
    )
    p.set_defaults(func=cmd_run_judges)

    p = sub.add_parser(
        "run-conversations", help="固定原始历史回放真实对话及门禁候选（联网）"
    )
    p.add_argument(
        "--scope",
        choices=("full", "image-context"),
        default="full",
        help="image-context仅执行真实选图和历史隔离，不执行主回复/数学审核",
    )
    p.add_argument("--path")
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--model")
    p.add_argument("--variant", default="baseline", choices=VARIANT_NAMES)
    p.add_argument("--status", default="confirmed,proposed,needs_decision")
    p.add_argument("--case", action="append")
    p.add_argument("--batch")
    p.add_argument("--out")
    p.set_defaults(func=cmd_run_conversations)

    p = sub.add_parser(
        "run-episodes", help="用真实模型连续运行多轮场景（联网，不进 CI）"
    )
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--model")
    p.add_argument("--variant", default="baseline", choices=VARIANT_NAMES)
    p.add_argument("--status", default="confirmed,proposed,needs_decision")
    p.add_argument("--case", action="append")
    p.add_argument("--batch", help="仅运行指定人工复核批次，如 seed-v1")
    p.add_argument("--out")
    p.set_defaults(func=cmd_run_episodes)

    p = sub.add_parser("export", help="从 companion_messages 导出待复核候选（只读库）")
    p.add_argument("--thread", required=True, help="thread id 前缀")
    p.add_argument("--component", choices=COMPONENTS, default="tutoring.turn")
    p.add_argument("--name", action="append", help="要从文本中抹去的姓名，可重复")
    p.add_argument("--out")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("compare", help="比较同一数据集的两次结果")
    p.add_argument("a")
    p.add_argument("b")
    p.set_defaults(func=cmd_compare)

    for name in ("run", "run-judges", "run-conversations", "run-episodes"):
        sub.choices[name].add_argument(
            "--config-snapshot", help="Admin导出的完整固定快照，不在线跟随发布"
        )
    args = parser.parse_args(argv)
    if args.command in {"run", "run-judges", "run-conversations", "run-episodes"}:
        # Explicit offline selection before any application/model imports.
        os.environ["AGENT_CONFIG_SOURCE"] = "snapshot"
        if args.config_snapshot:
            os.environ["AGENT_CONFIG_SNAPSHOT"] = str(
                Path(args.config_snapshot).resolve()
            )
        from app.agent_specs.configuration import read_snapshot, select_offline_snapshot
        from app.agent_specs.definitions import use_definitions
        from app.bootstrap import (
            settings as _settings_module,  # noqa: F401 - load deployment credentials
        )

        from evals.configuration import _record

        record = read_snapshot()
        snapshot = select_offline_snapshot(record)
        token = _record.set(record)
        try:
            with use_definitions(snapshot.catalog):
                return args.func(args)
        finally:
            _record.reset(token)
    return args.func(args)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in {"validate", "compare", "export"}:
        return historical_main(args)
    if args and args[0] == "snapshot":
        args[0] = "export"
    from evals.platform.__main__ import main as hosted_main
    return hosted_main(args)


if __name__ == "__main__":
    raise SystemExit(main())

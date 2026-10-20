"""python -m evals {validate,run,export,compare}   (run from duxue-server/)"""

from __future__ import annotations

import os

# The evaluation must never export traces or child content to the observability backend.
os.environ["OTEL_SDK_DISABLED"] = "true"

import argparse  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

# No app import at module level: `validate` must work without runtime secrets.
from evals import dataset, episodes  # noqa: E402

COMPONENTS = ("tutoring.turn", "companion.intent")
VARIANT_NAMES = ("baseline", "drop-no-guess-clause")  # kept in sync with evals.variants.VARIANTS (tested)


def _load_app(*modules: str):
    """Import modules that need the app's runtime configuration, with a readable failure."""
    import importlib

    try:
        return [importlib.import_module(name) for name in modules]
    except Exception as error:  # noqa: BLE001 - ConfigurationError lives inside the app package
        if type(error).__name__ == "ConfigurationError":
            raise SystemExit(f"缺少运行配置，无法调用应用代码：{error}") from error
        raise


def _git_sha() -> str:
    try:
        root = dataset.ROOT
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}" or "unknown"
    except OSError:
        return "unknown"


def cmd_validate(args) -> int:
    path = Path(args.path) if args.path else (dataset.DATA_DIR / args.category if args.category else dataset.DATA_DIR)
    cases = dataset.load_cases(path)
    problems = dataset.validate(cases)
    if not cases:
        problems.append(f"no single-turn cases found: {path}")
    if not args.path and not args.category:
        problems.extend(dataset.validate_layout())
        multi = episodes.load_episodes()
        problems.extend(episodes.validate_episodes(multi))
    else:
        multi = []
    for problem in problems:
        print(f"! {problem}")
    by_status = {s: sum(c.label_status == s for c in cases) for s in ("confirmed", "proposed", "needs_decision")}
    print(f"{len(cases)} cases + {len(multi)} episodes  {by_status}  hash={dataset.dataset_hash(cases)}")
    return 1 if problems else 0


def cmd_run_episodes(args) -> int:
    if args.samples < 1:
        print("--samples 必须大于 0", file=sys.stderr)
        return 2
    live, episode_runner, variants = _load_app("evals.live", "evals.episode_runner", "evals.variants")
    rows = episodes.load_episodes()
    problems = episodes.validate_episodes(rows)
    problems.extend(dataset.validate_layout())
    if problems:
        print("\n".join(f"! {p}" for p in problems))
        return 1
    selected = [row for row in rows if row.label_status in args.status.split(",")
                and (not args.case or row.id in args.case)]
    if not selected:
        print("没有符合筛选条件的 episode", file=sys.stderr)
        return 2
    live.preflight()
    spec = variants.resolve_spec("tutoring.turn", model=args.model, variant=args.variant)
    results = episode_runner.run_episodes(selected, live.build_backends(spec), samples=args.samples)
    summary = episode_runner.summarize_episodes(results)
    out = Path(args.out) if args.out else dataset.RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-episodes.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "meta": {"component": "tutoring.turn", "component_version": spec.version, "model": spec.model,
                 "variant": args.variant, "git_sha": _git_sha(), "at": datetime.now(timezone.utc).isoformat(),
                 "episodes_hash": episodes.episodes_hash(rows)},
        "summary": summary,
        "episodes": [{"id": row.episode.id, "label_status": row.episode.label_status,
                      "samples": [{"passed": sample.passed, "status": sample.status,
                                   "stopped_at": sample.stopped_at,
                                   "turns": [{"student_said": said, "outcome": step.observation.outcome,
                                              "content": step.observation.content, "failures": step.failures}
                                             for said, step in zip(sample.student_said, sample.steps)]}
                                  for sample in row.samples]} for row in results],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{summary['episodes']} episodes  stable_pass={summary['stable_pass']}  any_pass={summary['any_pass']}  skipped={summary['skipped']}")
    if not summary["by_status"]["confirmed"]["episodes"]:
        print("没有 confirmed episode；结果仅供观察，不构成发布门槛。")
    print(f"结果：{out}")
    return 0


def cmd_run(args) -> int:
    live, report, runner, variants = _load_app("evals.live", "evals.report", "evals.runner", "evals.variants")
    run_cases, resolve_spec = runner.run_cases, variants.resolve_spec

    cases = dataset.load_cases(dataset.DATA_DIR / args.category if args.category else None)
    problems = dataset.validate(cases)
    problems.extend(dataset.validate_layout())
    if problems:
        print("\n".join(f"! {p}" for p in problems))
        return 1
    components = [args.component] if args.component else list(COMPONENTS)
    if (args.model or args.variant != "baseline") and not args.component:
        print("--model / --variant 只作用于一个组件，请同时给 --component", file=sys.stderr)
        return 2
    live.preflight()
    selected = [
        c for c in cases
        if c.component in components and c.label_status in args.status.split(",")
        and (not args.tag or args.tag in c.tags) and (not args.case or c.id in args.case)
    ]
    if not selected:
        print("没有符合筛选条件的 case", file=sys.stderr)
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
                print(f"\r{component} {done[0]}/{total}", end="", file=sys.stderr, flush=True)

        results = run_cases(
            subset, {component: live.build_backends(spec)}, samples=args.samples, workers=args.workers, on_sample=tick,
        )
        if sys.stderr.isatty():
            print(file=sys.stderr)
        summary = report.summarize(results)
        meta = {
            "component": component, "component_version": spec.version, "model": spec.model,
            "variant": args.variant, "prompt_digest": spec.prompt.digest[:12] if hasattr(spec.prompt, "digest") else None,
            "samples": args.samples, "dataset_hash": dataset.dataset_hash(cases), "cases_run": len(subset),
            "category": args.category,
            "git_sha": _git_sha(), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        print(report.render_text(meta, summary, results))
        if args.out:
            out = Path(args.out)
            if len(components) > 1:  # one file per component, never overwrite
                out = out.with_name(f"{out.stem}-{component.replace('.', '_')}{out.suffix}")
        else:
            out = dataset.RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-{component.replace('.', '_')}-{args.variant}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"meta": meta, "summary": summary, "cases": report.to_json(results)},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"结果：{out}")
        if args.min_pass is not None:
            stable = summary["primary"]["confirmed"]["overall"]["cases_stable_pass"]
            if stable["n"] == 0 or stable["rate"] < args.min_pass:
                exit_code = 1
    return exit_code


def cmd_export(args) -> int:
    database, object_storage, export = _load_app(
        "app.infrastructure.persistence.database", "app.infrastructure.storage.object_storage", "evals.export",
    )
    SessionLocal, storage = database.SessionLocal, object_storage.storage

    db = SessionLocal()
    try:
        conversation_id, rows = export.load_thread_rows(db, args.thread)
    finally:
        db.close()
    cases = export.build_cases(
        rows, conversation_id=conversation_id, component=args.component,
        asset_for=export.asset_writer(storage.read_bytes), names=tuple(args.name or ()),
    )
    problems = dataset.validate(cases)
    out = Path(args.out) if args.out else dataset.RESULTS_DIR / "candidates" / f"{conversation_id}-{args.component.replace('.', '_')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(c.model_dump_json() for c in cases) + "\n", encoding="utf-8")
    flagged = sum(bool(c.flags) for c in cases)
    print(f"{len(cases)} 个决策点（{flagged} 个被自动标记）→ {out}")
    print("下一步：补 expect/tags/context，人工复核后把行并入 evals/data/*.jsonl，再设 confirmed + reviewed_by。")
    for problem in problems:
        print(f"! {problem}")
    return 0


def cmd_compare(args) -> int:
    first, second = (json.loads(Path(p).read_text(encoding="utf-8")) for p in (args.a, args.b))
    if first["meta"]["dataset_hash"] != second["meta"]["dataset_hash"]:
        print("数据集哈希不同，两次结果不可比。", file=sys.stderr)
        return 2
    print(f"A: {first['meta']['variant']} {first['meta']['model']}   B: {second['meta']['variant']} {second['meta']['model']}")
    index = {c["id"]: c for c in second["cases"]}
    for case in first["cases"]:
        other = index.get(case["id"])
        if not other or case["status"] != "ran" or other["status"] != "ran":
            continue
        a, b = (sum(s["passed"] for s in c["samples"]) for c in (case, other))
        if a != b:
            print(f"{case['id']:<34}{a}/{len(case['samples'])} -> {b}/{len(other['samples'])}  [{case['label_status']}]")
    print("差异只有在两次采样次数和区间都支持时才算差异；小数据集上的 1~2 例变化是噪声。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="校验数据集（无网络）")
    p.add_argument("--path")
    p.add_argument("--category", choices=dataset.SINGLE_TURN_CATEGORIES)
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
    p.add_argument("--min-pass", type=float, help="confirmed 全部采样都通过的 case 占比低于它则退出码 1")
    p.add_argument("--out")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("run-episodes", help="用真实模型连续运行多轮场景（联网，不进 CI）")
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--model")
    p.add_argument("--variant", default="baseline", choices=VARIANT_NAMES)
    p.add_argument("--status", default="confirmed,proposed,needs_decision")
    p.add_argument("--case", action="append")
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

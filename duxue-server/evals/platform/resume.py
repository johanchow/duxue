"""Collect late scores without rerunning application/model calls."""

import json
from evals.platform.native import NativeScorer
from evals.platform.__main__ import write, aggregate


def resume(client, directory, timeout):
    versions = json.loads((directory / "evaluators.json").read_text())
    changed = [
        name
        for name, e in versions.items()
        if client.api.evaluators.get(e["id"]).version_id != e["versionId"]
    ]
    if changed:
        raise ValueError(
            f"Evaluators changed since run; do not mix versions: {changed}"
        )
    configs = {
        c.name: c.id
        for c in client.api.score_configs.get(limit=100).data
        if not c.is_archived
    }
    scorer = NativeScorer(client, versions, timeout=timeout)
    results = []
    datasets = json.loads((directory / "datasets.json").read_text())
    for rows in datasets.values():
        for item in rows:
            path = directory / (item["id"] + ".json")
            if not path.exists():
                # Interrupted application calls are not reconstructed as successful tasks.
                results.append(
                    {
                        "case_id": item["input"]["record"]["id"],
                        "status": "error",
                        "error": "missing_task_result",
                    }
                )
                continue
            result = json.loads(path.read_text())
            for check in result["checks"]:
                if check["status"] != "error" or not check.get("observation_id"):
                    continue
                journal = (
                    directory / "checkpoints" / (check["observation_id"] + ".json")
                )
                evidence = json.loads(journal.read_text())
                if evidence["execution_error"]:
                    continue
                updated = scorer.collect(
                    evidence["required"], check["trace_id"], check["observation_id"]
                )
                check.pop("error", None)
                check.update(updated)
            states = {c["status"] for c in result["checks"]}
            if states:
                result["status"] = next(
                    (s for s in ("error", "fail", "not_run") if s in states), "pass"
                )
            write(path, result)
            aggregate(
                client, configs, result, result["trace_id"], result["observation_id"]
            )
            results.append(result)
    client.flush()
    summary = {
        "counts": {
            s: sum(r["status"] == s for r in results)
            for s in ("pass", "fail", "error", "not_run")
        },
        "expected_cases": sum(map(len, datasets.values())),
        "completed_cases": len(results),
        "results": results,
        "calibration_status": "uncalibrated",
        "evaluator_changes": changed,
    }
    write(directory / "results.json", summary)
    print(
        json.dumps({"output": str(directory.resolve()), "counts": summary["counts"]}),
        flush=True,
    )
    return int(any(r["status"] != "pass" for r in results))

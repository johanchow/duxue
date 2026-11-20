"""Score completed answer files and regenerate TSV evidence and per-paper totals."""

import argparse
import csv
import fcntl
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from .grading import JUDGE_MODEL, WEIGHTS, grade
from .papers import SOURCES, tasks
from .transport import digest, write


def score_one(source, dest, data, version, reuse=None):
    response = json.loads(source.read_text())
    if response["status"] == "submitted":
        return
    answer_hash = digest(source)
    if dest.exists():
        saved = json.loads(dest.read_text())
        if saved["answer_sha256"] == answer_hash and saved["version"] == version:
            return
    if reuse is not None and (reuse / source.name).exists():
        previous = json.loads((reuse / source.name).read_text())
        if previous["version"] == version and previous["answer_sha256"] == answer_hash:
            write(dest, previous)
            return
    if response["status"] in ("transport_error", "delivery_unknown"):
        a, b = response["questions"]
        rows = [
            {
                "number": n,
                "points": None,
                "reason": "无法确认交付，不能判分",
                "evidence": "",
                "parts": [],
            }
            for n in range(a, b + 1)
        ]
    elif response["status"] == "http_error":
        # A returned service error is an observed zero delivery on the first try.
        a, b = response["questions"]
        rows = [
            {
                "number": n,
                "points": 0,
                "reason": f"请求返回 HTTP {response['http']}，未交付答案",
                "evidence": "",
                "parts": [],
            }
            for n in range(a, b + 1)
        ]
    else:
        rows = grade(data, response)
    write(
        dest,
        {
            "version": version,
            "model": JUDGE_MODEL,
            "answer_sha256": answer_hash,
            "rows": rows,
        },
    )


def summarize(run, grades, version):
    totals = {}
    with (grades / "questions.tsv").open("w") as output:
        w = csv.writer(output, delimiter="\t")
        w.writerow(
            ["学科", "题号", "得分", "满分", "作答状态", "扣分依据", "答卷证据", "分项"]
        )
        for subject in SOURCES:
            points = pending = graded = failed = 0
            for a, b, _, _ in tasks(subject):
                name = f"{subject}-{a:02}.json"
                src = run / name
                raw = json.loads(src.read_text()) if src.exists() else {}
                ref = grades / name
                scores = {}
                if ref.exists() and src.exists():
                    saved = json.loads(ref.read_text())
                    if saved["version"] == version and saved["answer_sha256"] == digest(
                        src
                    ):
                        scores = {r["number"]: r for r in saved["rows"]}
                for n in range(a, b + 1):
                    cap = WEIGHTS[subject][n - 1]
                    r = scores.get(n, {})
                    value = r.get("points")
                    if value is None:
                        pending += cap
                    else:
                        points += value
                        graded += 1
                    if (
                        raw.get("status") == "http_error"
                        or raw.get("answer", {}).get("act") == "unavailable"
                    ):
                        failed += 1
                    w.writerow(
                        [
                            subject,
                            n,
                            value,
                            cap,
                            raw.get("answer", {}).get(
                                "act", raw.get("status", "not_run")
                            ),
                            r.get("reason"),
                            r.get("evidence"),
                            json.dumps(r.get("parts", []), ensure_ascii=False),
                        ]
                    )
            totals[subject] = {
                "earned": points,
                "max": sum(WEIGHTS[subject]),
                "pending": pending,
                "graded": graded,
                "delivery_failures": failed,
            }
    write(grades / "totals.json", totals)
    return totals


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("run", "data", "out"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--watch", action="store_true")
    p.add_argument("--reuse-grades", type=Path)
    args = p.parse_args()
    args.out.mkdir(exist_ok=True, parents=True)
    lock = (args.out / ".lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    version = hashlib.sha256(
        (digest(Path(__file__).with_name("grading.py")) + JUDGE_MODEL).encode()
    ).hexdigest()

    attempts = {}

    protocol = args.out / "protocol.json"
    meta = {
        "version": version,
        "model": JUDGE_MODEL,
        "run_manifest_sha256": digest(args.run / "manifest.json"),
    }
    if protocol.exists() and json.loads(protocol.read_text()) != meta:
        raise ValueError(
            "Scoring inputs changed; retain this evidence and use a new --out"
        )
    if not protocol.exists():
        for file in args.out.glob("*-*.json"):
            if json.loads(file.read_text()).get("version") != version:
                raise ValueError(
                    "Existing scores use another rubric; choose a new --out"
                )
        write(protocol, meta)

    def attempt(source):
        if attempts.get(source, 0) >= 3:
            return
        try:
            score_one(
                source, args.out / source.name, args.data, version, args.reuse_grades
            )
        except (ValueError, KeyError, TypeError, httpx.HTTPError) as exc:
            attempts[source] = attempts.get(source, 0) + 1
            print(source.name, type(exc).__name__, str(exc)[:100], flush=True)

    while True:
        with ThreadPoolExecutor(5) as pool:
            list(pool.map(attempt, sorted(args.run.glob("*-*.json"))))
        totals = summarize(args.run, args.out, version)
        if not args.watch or not any(s["pending"] for s in totals.values()):
            break
        # Once every input is terminal the summary explicitly retains any unresolved marks.
        expected = sum(len(tasks(s)) for s in SOURCES)
        terminal = [
            p
            for p in args.run.glob("*-*.json")
            if json.loads(p.read_text()).get("status") != "submitted"
        ]
        if len(terminal) == expected and all(
            (args.out / p.name).exists() or attempts.get(p, 0) >= 3 for p in terminal
        ):
            break
        time.sleep(15)


if __name__ == "__main__":
    main()

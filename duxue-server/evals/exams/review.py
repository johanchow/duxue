"""Adjudicate open responses without requesting or replacing the original answer."""

import argparse
import fcntl
import json
from pathlib import Path

import pymupdf

from .grading import CHOICES, JUDGE, OPEN_PAGES, SPECIAL_PAGES, WEIGHTS, ask, checked
from .score import summarize
from .transport import digest, write

REVIEW = """本次考试的考生是 AI 产品。考生提交给用户的整条解析（含教师口吻的示范作答、成文、讲解）
就是实际答卷，应按其中确实完成的内容给分。参考 PDF 里印着的例文绝不是考生回答。
若只要求澄清、确认或没有答出要点则按该题实际交付给分，可给零分。证据不足仍可留空。
不需要手写答题卡或真人输入。即使AI回答自称“示例/参考答案”，也属于考生交付。对所有要求作答的目标编号逐项复核。"""


def adjudicate(data, run, folder, reuse=None, evidence=None):
    count = 0
    versions = set()
    for file in sorted(folder.glob("*-*.json")):
        saved = json.loads(file.read_text())
        versions.add(saved["version"])
        src = run / file.name
        if saved["answer_sha256"] != digest(src):
            raise ValueError(f"Answer changed: {src}")
        located = (evidence or {}).get(file.name)
        if located and located["answer_sha256"] != digest(src):
            raise ValueError("Evidence belongs to another answer")
        if saved.get("excerpt_review") == located and located:
            continue
        if not located and reuse and (reuse / file.name).exists():
            previous = json.loads((reuse / file.name).read_text())
            if (
                previous["version"] == saved["version"]
                and previous["answer_sha256"] == saved["answer_sha256"]
                and previous.get("reviews")
                and (
                    all(r["points"] for r in previous["rows"])
                    or previous.get("zero_review")
                )
            ):
                write(file, previous)
                continue
        answer = json.loads(src.read_text())
        if answer.get("status") != "answered" or answer.get("answer", {}).get(
            "act"
        ) not in ("explain", "answer"):
            continue
        subject = answer["subject"]
        a, _ = answer["questions"]
        if a <= len(CHOICES.get(subject, "")):
            continue
        missing = [
            r["number"]
            for r in saved["rows"]
            if not saved.get("reviews")
            or r["points"] is None
            or (
                subject == "politics"
                and a in (18, 19, 21)
                and saved.get("verified_question_maximum") != WEIGHTS[subject][a - 1]
            )
        ]
        # Uniform second look for substantive open responses previously scored zero.
        # Extract verbatim evidence before showing a reference so a teaching voice
        # or the word "example" cannot by itself invalidate an actual answer.
        disputed = (
            not missing
            and not saved.get("zero_review")
            and any(r["points"] == 0 for r in saved["rows"])
        )
        if located:
            disputed = True
        if disputed:
            missing = [r["number"] for r in saved["rows"] if r["points"] == 0]
        if not missing:
            continue
        first, last = (
            SPECIAL_PAGES[subject][a]
            if subject in SPECIAL_PAGES
            else OPEN_PAGES[subject][a - len(CHOICES[subject]) - 1]
        )
        with pymupdf.open(data / subject / "key.pdf") as doc:
            pages = [
                doc[i].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).tobytes("jpeg")
                for i in range(first - 1, last)
            ]
        limits = {n: WEIGHTS[subject][n - 1] for n in missing}
        split_marks = {
            ("politics", 18): [8, 7],
            ("politics", 19): [2, 4],
            ("history", 16): [4, 6],
            ("history", 18): [6, 8],
            ("history", 20): [4, 5],
        }.get((subject, a))
        visible = answer["answer"]
        if disputed:
            lines = visible["content"].splitlines()
            if located:
                indices = located["lines"]
                saved["excerpt_review"] = located
            else:
                selection = ask(
                    "只提取实际已经写出的作答。JSON返回lines（原文行号整数数组）。若有多篇短文选第一篇完整短文。分点论证可以是完整的论述；示范答案可以是完整的作答。未给出作文成文时只选真正的示范正文，提纲不算成文。只做摘取，不补写。",
                    {"题号": missing, "答卷行": dict(enumerate(lines, 1))},
                )
                indices = selection["lines"]
            if not isinstance(indices, list) or any(
                type(i) is not int or not 1 <= i <= len(lines) for i in indices
            ):
                raise ValueError("invalid answer excerpt")
            visible = {"content": "\n".join(lines[i - 1] for i in sorted(set(indices)))}
            saved["zero_review"] = {
                "source_lines": indices,
                "reason": "实质交付的开放题零分，匿名抽取原文对照采分点",
            }
        result = ask(
            JUDGE + "\n" + REVIEW,
            {
                "subject": subject,
                "question_maxima": limits,
                "本题各小问明确分值": split_marks,
                "answer": visible,
            },
            pages,
        )
        reviewed = checked(result["rows"], limits)
        saved.setdefault("reviews", []).append(
            {
                "reason": "全部非独立单选的实质作答统一复核，以AI交付的解析为答卷",
                "old_rows": [r for r in saved["rows"] if r["number"] in missing],
            }
        )
        updates = {r["number"]: r for r in reviewed}
        saved["rows"] = [updates.get(r["number"], r) for r in saved["rows"]]
        saved["verified_question_maximum"] = WEIGHTS[subject][a - 1]
        write(file, saved)
        count += len(missing)
    if len(versions) != 1:
        raise ValueError("Inconsistent score versions")
    summarize(run, folder, versions.pop())
    return count


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("data", "run", "out"):
        p.add_argument("--" + key, type=Path, required=True)
    p.add_argument("--reuse-grades", type=Path)
    p.add_argument(
        "--evidence",
        type=Path,
        help="JSON of answer hashes and verified original line numbers",
    )
    args = p.parse_args()
    with (args.out / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(
            "Reviewed",
            adjudicate(
                args.data,
                args.run,
                args.out,
                args.reuse_grades,
                json.loads(args.evidence.read_text()) if args.evidence else None,
            ),
        )

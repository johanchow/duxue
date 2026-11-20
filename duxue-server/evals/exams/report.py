"""Create a shareable local index of per-question evidence for two scoring runs."""

import argparse
import json
from collections import Counter
from pathlib import Path

from .grading import WEIGHTS, checked
from .papers import tasks
from .transport import digest

LABELS = {
    "chinese": "语文",
    "math": "数学",
    "english": "英语笔试",
    "physics": "物理",
    "chemistry": "化学",
    "biology": "生物",
    "history": "历史",
    "geography": "地理",
    "politics": "思想政治",
}


def read_receipt(root, run, grades, subject, task):
    a, b, _, _ = task
    name = f"{subject}-{a:02}.json"
    src = root / run / name
    grade = root / grades / name
    record = json.loads(src.read_text())
    receipt = json.loads(grade.read_text())
    if (
        record.get("subject") != subject
        or record.get("questions") != [a, b]
        or digest(src) != receipt["answer_sha256"]
    ):
        raise ValueError(f"Invalid score evidence: {grade}")
    limits = {n: WEIGHTS[subject][n - 1] for n in range(a, b + 1)}
    rows = checked(receipt["rows"], limits)
    if any(r["points"] is None for r in rows):
        raise ValueError(f"Unresolved grade: {grade}")
    return record, rows


def build(root):
    intro = [
        "# 读学 · 2025 北京高考九科本地成绩",
        "",
        "每个总分均以整卷满分为分母。首答为本地 Guardian 导师解析首次可见交付；补答列仅对 HTTP 错误或明确返回暂不可用的请求替换为一次补答。未交付计零。语文选第 21、24 题，英语仅计笔试。",
        "",
        "| 学科 | 满分 | 首答得分 | 一次补答后 | 首答超时／暂不可用题数 | 补答后超时／暂不可用题数 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    detail = []
    counts = Counter()
    possible = Counter()
    earned = Counter()
    for s, label in LABELS.items():
        scores = [0, 0]
        missing = [0, 0]
        detail.extend(
            [
                "",
                f"## {label}",
                "",
                f"[试题 PDF]({s}/paper.pdf) · [参考解析 PDF]({s}/key.pdf)",
                "",
                "| 题号 | 首答 | 补答后 | 满分 | 首答交付 | 作答与评分 |",
                "|---|---:|---:|---:|---|---|",
            ]
        )
        for task in tasks(s):
            a, b, _, _ = task
            name = f"{s}-{a:02}.json"
            first, fr = read_receipt(root, "run", "final-first", s, task)
            second, sr = read_receipt(root, "recovered", "final-recovered", s, task)
            pairs = [(first, fr), (second, sr)]
            for idx, (answer, rows) in enumerate(pairs):
                scores[idx] += sum(r["points"] for r in rows)
                act = answer.get("answer", {}).get("act", answer["status"])
                counts[(idx, act)] += 1
                possible[(idx, act)] += sum(WEIGHTS[s][a - 1 : b])
                earned[(idx, act)] += sum(r["points"] for r in rows)
                if act in ("http_error", "unavailable"):
                    missing[idx] += len(rows)
            orig = {r["number"]: r["points"] for r in fr}
            updated = {r["number"]: r["points"] for r in sr}
            status = first.get("answer", {}).get(
                "act", str(first.get("http", first["status"]))
            )
            for n in range(a, b + 1):
                detail.append(
                    f"| {n} | {orig[n]:g} | {updated[n]:g} | {WEIGHTS[s][n - 1]:g} | {status} | "
                    f"[首答](run/{name}) · [判分](final-first/{name}) · "
                    f"[补答后](recovered/{name}) · [判分](final-recovered/{name}) |"
                )
        intro.append(
            f"| {label} | {sum(WEIGHTS[s]):g} | {scores[0]:g} | {scores[1]:g} | {missing[0]} | {missing[1]} |"
        )
    intro.extend(
        [
            "",
            "### 交付状态与卷面分",
            "",
            "| 场景 | 返回状态 | 请求数 | 覆盖的卷面满分 | 实得分 |",
            "|---|---|---:|---:|---:|",
        ]
    )
    states = {
        "explain": "已给解析",
        "answer": "已给答案",
        "http_error": "HTTP 服务错误",
        "unavailable": "暂不可用",
        "clarify": "要求澄清",
        "safety": "安全回复",
    }
    for (idx, act), calls in sorted(counts.items()):
        name = ["首次", "一次补答后"][idx]
        intro.append(
            f"| {name} | {states.get(act, act)} | {calls} | {possible[(idx, act)]:g} | {earned[(idx, act)]:g} |"
        )
    intro.extend(
        [
            "",
            "### 如何读分",
            "",
            "两种协议都保留用户实际收到的正文及图示。首答按整页图上的目标编号作答，部分页面带邻题；补答简化提示并在可定位时裁切独立题。两列都只计项目真实接口交付。失败题数按计分题号统计，一次阅读材料请求可能影响多个题号。",
            "",
            "参考解析来自第三方整理。独立阅卷模型抽取单选项后按标准选项比较；题组、开放题与作文按参考页和本地评分规则自动估分。部分语文题的逐题配分和未标明的分步细则采用本地量尺。政治第 18、19、21 题按同卷设问汇编核实配分，保留调整前评分。成绩未做教师复核。",
            "",
            "本批首题冒烟最多 3 路并发、其余首答最多 8 路、补答最多 5 路。首答、补答和判卷部分时段重叠，接口保留 105 秒总预算。分数描述本次批量负载。判分时答卷仅取产品的用户可见结果，未观测题库命中。实际运行使用本地 Guardian 草稿快照，其文件摘要见 [运行记录](run/manifest.json)。",
            "",
            "[首次逐题评分表](final-first/questions.tsv) · [一次补答后逐题评分表](final-recovered/questions.tsv)",
            "",
        ]
    )
    (root / "REPORT.md").write_text("\n".join(intro + detail) + "\n")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    print(build(parser.parse_args().data))

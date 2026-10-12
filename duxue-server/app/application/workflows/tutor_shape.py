"""`content` 的形状 lint：只读、只记录，绝不拒绝、不触发 fallback。

形状是软约束（见 docs/technical/domain-tutoring-presentation.md §四）。lint 的结果进 trace
和离线评测指标，用来看提示词是否把回答写得更有条理；它不改写 `content`，也不影响展示。
上限数值是**初始假设**，第 0 步对真实分布统计后再校准。
"""

from __future__ import annotations

import re

# 初始假设（字数）。act 不在表里不检查长度。
MAX_CHARS: dict[str, int] = {
    "answer": 400, "guide": 250, "chat": 120, "clarify": 200, "redirect": 120, "pronounce": 120,
}

_QUESTION = re.compile(r"[？?]")
_LIST_LINE = re.compile(r"^\s*(?:[-*•]|\d+[.、)）])\s+\S")
_HTML = re.compile(r"<\s*/?[a-zA-Z!][^>]*>")
_ESCAPED_DOLLAR = re.compile(r"\\\$")


def lint_shape(act: str, content: str, follow_up_question: str | None = None) -> list[str]:
    """返回触发的规则名；空列表表示形状没有问题。规则名是稳定的低基数标签。"""
    flags: list[str] = []
    shown = content if not follow_up_question or follow_up_question in content else f"{content}\n{follow_up_question}"
    limit = MAX_CHARS.get(act)
    if limit is not None and len(shown) > limit:
        flags.append("too_long")
    if act == "guide" and len(_QUESTION.findall(shown)) > 1:
        flags.append("multi_question")
    lines = [line for line in content.splitlines() if line.strip()]
    listed = sum(1 for line in lines if _LIST_LINE.match(line))
    if listed >= 3 and listed * 2 >= len(lines):
        flags.append("list_heavy")
    if len(_ESCAPED_DOLLAR.sub("", content).split("$")) % 2 == 0:
        flags.append("unpaired_dollar")
    if _HTML.search(content):
        flags.append("raw_html")
    return flags

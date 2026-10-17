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
_BULLET_LINE = re.compile(r"^\s*[-*•]\s+\S")
_BR_TAG = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_HTML = re.compile(r"<\s*/?[a-zA-Z!][^>]*>")
_CODE_BLOCK = re.compile(r"```[\s\S]*?```|`[^`\n]+`")
_ESCAPED_DOLLAR = re.compile(r"\\\$")


def _has_unpaired_delim(text: str, open_tok: str, close_tok: str) -> bool:
    depth = 0
    i = 0
    while i < len(text):
        if text.startswith(open_tok, i):
            depth += 1
            i += len(open_tok)
        elif text.startswith(close_tok, i):
            if depth == 0:
                return True
            depth -= 1
            i += len(close_tok)
        else:
            i += 1
    return depth != 0


def _has_unpaired_math(content: str) -> bool:
    cleaned = _ESCAPED_DOLLAR.sub("", _CODE_BLOCK.sub("", content))
    if _has_unpaired_delim(cleaned, r"\(", r"\)"):
        return True
    if _has_unpaired_delim(cleaned, r"\[", r"\]"):
        return True
    parts = cleaned.split("$$")
    if len(parts) % 2 == 0:
        return True
    outside_display = "".join(parts[0::2])
    return outside_display.count("$") % 2 == 1


def lint_shape(act: str, content: str) -> list[str]:
    """返回触发的规则名；空列表表示形状没有问题。规则名是稳定的低基数标签。"""
    flags: list[str] = []
    limit = MAX_CHARS.get(act)
    if limit is not None and len(content) > limit:
        flags.append("too_long")
    if act == "guide" and len(_QUESTION.findall(content)) > 1:
        flags.append("multi_question")
    lines = [line for line in content.splitlines() if line.strip()]
    list_pattern = _BULLET_LINE if act == "answer" else _LIST_LINE
    listed = sum(1 for line in lines if list_pattern.match(line))
    if listed >= 3 and listed * 2 >= len(lines):
        flags.append("list_heavy")
    if _has_unpaired_math(content):
        flags.append("unpaired_dollar")
    if _HTML.search(_BR_TAG.sub("", content)):
        flags.append("raw_html")
    return flags

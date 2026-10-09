"""答疑上下文里的授权历史候选。模型只能从这组里引用。"""

from __future__ import annotations


def history_candidates(utterances: list[dict]) -> list[dict]:
    candidates = []
    for index, item in enumerate(utterances):
        text = (item.get("text") or "").strip()
        if not text:
            continue
        candidates.append({"ref": f"u{index}", "author": item.get("author") or "", "text": text})
    return candidates

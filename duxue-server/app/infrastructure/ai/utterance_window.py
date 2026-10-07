"""Shared rule for the recent-utterance window sent with a Ward turn."""

from __future__ import annotations

import json

WINDOW_RULE = (
    "recent_utterances 是同一条对话到上一轮为止的最近原句，从旧到新。"
    "「他们」「刚才那句」「上面那个」只能根据这些原句确定对象。"
    "对不上，或有多句都可能时，追问是哪一句，不要自己补一个对象，也不要把孩子这句中文当成待解释的外语。"
)


def instruction_with_window(instruction: str, utterances: list[dict]) -> str:
    return (
        f"{instruction}\n{WINDOW_RULE}\n"
        f"recent_utterances={json.dumps(utterances, ensure_ascii=False)}"
    )

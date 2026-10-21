"""Prompt bodies are versioned.  Editing one must be a deliberate, reviewed act.

If this fails you changed a prompt.  Bump the prompt id version (and the
component version) in prompts.py / components.py, update the lock below, and run
the regression for the affected component.
"""

from __future__ import annotations

from app.infrastructure.ai.prompts import PROMPTS

LOCK = {
    "companion.intent.system.v3": "0ad3d18b7752bba0111c422156087ef81e1cc93a4af77e56664f5f8cd3ab06b6",
    "tutoring.turn.system.v19": "c86ad4e9bf8c495d89a75e7eafe3992a1cdd555830b8dc5626bd8373fb9b7140",
    "tutoring.leak-judge.system.v6": "7f4b7f8d6adeb1a87817bd51e770ad9e694bd6a1105e949b943b2de2de31237f",
    "tutoring.visual-leak-judge.system.v5": "781d3deb79c00b75ea1903c226b05ec9b3de9fd71f0e42fc5a056cab61403c8c",
    "companion.agent-text.system.v1": "cc88ff1f58e1f35e2d6e13167f9cb036c02a8d5a7ba1ece86154111511e6f56d",
    "task.intake.prompt.v1": "10f41ef644ea775084ba3569a6a210575fedc41c619296168dd1902d51090a38",
    "planning.intake.prompt.v1": "4ba2b6d91fd46240c2d98ab9501d2dfc154efd9621905cad04e3e964b38f8c59",
}


def test_prompt_digests_match_their_versioned_ids():
    assert set(PROMPTS) == set(LOCK), "register new prompts in LOCK"
    changed = [pid for pid, prompt in PROMPTS.items() if prompt.digest != LOCK[pid]]
    assert not changed, f"prompt body changed without a version bump: {changed}"

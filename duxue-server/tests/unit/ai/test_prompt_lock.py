"""Prompt bodies are versioned.  Editing one must be a deliberate, reviewed act.

If this fails you changed a prompt.  Bump the prompt id version (and the
component version) in prompts.py / components.py, update the lock below, and run
the regression for the affected component.
"""

from __future__ import annotations

from app.infrastructure.ai.prompts import PROMPTS

LOCK = {
    "companion.intent.system.v2": "eebd7da59196039f358049a5ef39127783a68deb687a1403aa7a3320bd42d73e",
    "tutoring.turn.system.v18": "e5a2bdb03a04a158c72e76dfb2db67fcdf891f67816d7d773002b28176b38371",
    "tutoring.leak-judge.system.v6": "7f4b7f8d6adeb1a87817bd51e770ad9e694bd6a1105e949b943b2de2de31237f",
    "tutoring.visual-leak-judge.system.v4": "2fbdb6d086a23852a8b9c6bfc3d6da9dd20333d0403c807bf5c77123f7b86f9d",
    "companion.agent-text.system.v1": "cc88ff1f58e1f35e2d6e13167f9cb036c02a8d5a7ba1ece86154111511e6f56d",
    "task.intake.prompt.v1": "10f41ef644ea775084ba3569a6a210575fedc41c619296168dd1902d51090a38",
    "planning.intake.prompt.v1": "4ba2b6d91fd46240c2d98ab9501d2dfc154efd9621905cad04e3e964b38f8c59",
}


def test_prompt_digests_match_their_versioned_ids():
    assert set(PROMPTS) == set(LOCK), "register new prompts in LOCK"
    changed = [pid for pid, prompt in PROMPTS.items() if prompt.digest != LOCK[pid]]
    assert not changed, f"prompt body changed without a version bump: {changed}"

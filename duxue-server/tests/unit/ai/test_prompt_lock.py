"""Prompt bodies are versioned.  Editing one must be a deliberate, reviewed act.

If this fails you changed a prompt.  Bump the prompt id version (and the
component version) in prompts.py / components.py, update the lock below, and run
the regression for the affected component.
"""

from __future__ import annotations

from app.infrastructure.ai.prompts import PROMPTS

LOCK = {
    "companion.intent.system.v1": "2c633f98032b7f540bd801c8a8b94c3af008cf252c9e35f26a7524caf7a84b31",
    "tutoring.turn.system.v10": "7174c00405dcb45a0296d573173481098986bcc7729e65a9cc13f11d49301d2b",
    "tutoring.leak-judge.system.v4": "8049e345e3538f4c3e3419656215cedc9997d233010e1c965dc98b71c707513c",
    "tutoring.visual-leak-judge.system.v2": "96ddf112b00eaf5b5e0043b655fc2ac8b29abffedc44cc801603ffd09534c26a",
    "companion.agent-text.system.v1": "cc88ff1f58e1f35e2d6e13167f9cb036c02a8d5a7ba1ece86154111511e6f56d",
    "task.intake.prompt.v1": "10f41ef644ea775084ba3569a6a210575fedc41c619296168dd1902d51090a38",
    "planning.intake.prompt.v1": "4ba2b6d91fd46240c2d98ab9501d2dfc154efd9621905cad04e3e964b38f8c59",
}


def test_prompt_digests_match_their_versioned_ids():
    assert set(PROMPTS) == set(LOCK), "register new prompts in LOCK"
    changed = [pid for pid, prompt in PROMPTS.items() if prompt.digest != LOCK[pid]]
    assert not changed, f"prompt body changed without a version bump: {changed}"

"""Prompt bodies are versioned.  Editing one must be a deliberate, reviewed act.

If this fails you changed a prompt.  Bump the prompt id version (and the
component version) in prompts.py / components.py, update the lock below, and run
the regression for the affected component.
"""

from __future__ import annotations

from app.infrastructure.ai.prompts import PROMPTS

LOCK = {
    "companion.intent.system.v1": "2c633f98032b7f540bd801c8a8b94c3af008cf252c9e35f26a7524caf7a84b31",
    "tutoring.turn.system.v7": "d1eca97b82c5fdd964581fdfc5174557ee6d896a3a7bb2c0a48e08893a990e0e",
    "tutoring.leak-judge.system.v2": "19a52a67a516ad25f1bd890143cd44aca95a37bfa9ed76d21d3cfe8e415975a3",
    "tutoring.visual-leak-judge.system.v1": "d50524a41fbb0a43ddbc361fa04969a2b2d1854ca853ab26f4e8c7f32d2ee388",
    "companion.agent-text.system.v1": "cc88ff1f58e1f35e2d6e13167f9cb036c02a8d5a7ba1ece86154111511e6f56d",
    "task.intake.prompt.v1": "10f41ef644ea775084ba3569a6a210575fedc41c619296168dd1902d51090a38",
    "planning.intake.prompt.v1": "4ba2b6d91fd46240c2d98ab9501d2dfc154efd9621905cad04e3e964b38f8c59",
}


def test_prompt_digests_match_their_versioned_ids():
    assert set(PROMPTS) == set(LOCK), "register new prompts in LOCK"
    changed = [pid for pid, prompt in PROMPTS.items() if prompt.digest != LOCK[pid]]
    assert not changed, f"prompt body changed without a version bump: {changed}"

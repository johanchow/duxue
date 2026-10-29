"""Prompt bodies are versioned.  Editing one must be a deliberate, reviewed act.

If this fails you changed a prompt.  Bump the prompt id version (and the
component version) in prompts.py / components.py, update the lock below, and run
the regression for the affected component.
"""

from __future__ import annotations

from app.infrastructure.ai.prompts import PROMPTS

LOCK = {
    "companion.intent.system.v7": "2e831170f127cf76c5f81280803ac63d676e20b2d556b230defa6e22130e1c1d",
    "tutoring.image-target.system.v1": "99439c3ad7d32dfc3cb4cea6c0646877044ebe586637faa28d15823391a89304",
    "tutoring.turn.system.v19": "c86ad4e9bf8c495d89a75e7eafe3992a1cdd555830b8dc5626bd8373fb9b7140",
    "tutoring.leak-judge.system.v7": "ff9d4b04084b8aa2b959e791eefe1f256ea983a08eda5415b5d38dfe4e4fdbd1",
    "tutoring.visual-leak-judge.system.v5": "781d3deb79c00b75ea1903c226b05ec9b3de9fd71f0e42fc5a056cab61403c8c",
    "companion.agent-text.system.v2": "3f2d9727250893bcd49643359c428e30f460e969066e44f303accc09e49e54d0",
    "task.intake.prompt.v1": "10f41ef644ea775084ba3569a6a210575fedc41c619296168dd1902d51090a38",
    "planning.intake.prompt.v2": "0d19094b1a599167f240ea9f8e1bbd334413ca85c10b59b9781e663fbbcd79d4",
    "evaluation.review-aspects.system.v1": "7558e943f00a2f642a226640487aa9a16cdea1ebcd6c22b8cb8a080684ffa00f",
}


def test_prompt_digests_match_their_versioned_ids():
    assert set(PROMPTS) == set(LOCK), "register new prompts in LOCK"
    changed = [pid for pid, prompt in PROMPTS.items() if prompt.digest != LOCK[pid]]
    assert not changed, f"prompt body changed without a version bump: {changed}"

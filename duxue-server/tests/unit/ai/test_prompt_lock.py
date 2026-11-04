"""Prompt bodies are versioned.  Editing one must be a deliberate, reviewed act.

If this fails you changed a prompt.  Bump the prompt id version (and the
component version) in prompts.py / components.py, update the lock below, and run
the regression for the affected component.
"""

from __future__ import annotations

from app.infrastructure.ai.prompts import PROMPTS

LOCK = {
    "study.sprint-intake.system.v1": "490b6927141cb7c49d4471b549484e68599cd8f6428fdf4f0a8b686a2b25dbbc",
    "companion.intent.system.v9": "b24b7bb01cc198ca8842ba83da7324986bec05229ff615e761a61b6399eab9c3",
    "companion.scene-switch.system.v2": "c6c7452c60ffbfe5a0b88478f37d5e6d1853f6666650157ac7fb0bd96ca12420",
    "tutoring.image-target.system.v1": "99439c3ad7d32dfc3cb4cea6c0646877044ebe586637faa28d15823391a89304",
    "tutoring.turn.system.v20": "72e440789c773203aa99843f4730f8a7966f69bc7e49f40cf6f31361643d65c0",
    "tutoring.leak-judge.system.v9": "dd8087d85f4ceaadd4b5a055108d4c2db4e77b05dc188a079d8dbafd096f9f1e",
    "tutoring.visual-leak-judge.system.v5": "781d3deb79c00b75ea1903c226b05ec9b3de9fd71f0e42fc5a056cab61403c8c",
    "companion.agent-text.system.v2": "3f2d9727250893bcd49643359c428e30f460e969066e44f303accc09e49e54d0",
    "task.intake.prompt.v2": "73995e7f1e1fe5641511300b06e0526d7220434e4a61ab35f8497ae9d5f3a3ad",
    "planning.intake.prompt.v6": "3b4debe34c4a6d7a6d9b025258742ee3d12d7b4d698cac6a9e8f218d5d4eaf98",
    "evaluation.review-aspects.system.v1": "7558e943f00a2f642a226640487aa9a16cdea1ebcd6c22b8cb8a080684ffa00f",
}


def test_prompt_digests_match_their_versioned_ids():
    assert set(PROMPTS) == set(LOCK), "register new prompts in LOCK"
    changed = [pid for pid, prompt in PROMPTS.items() if prompt.digest != LOCK[pid]]
    assert not changed, f"prompt body changed without a version bump: {changed}"

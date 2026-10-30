"""Prompt bodies are versioned.  Editing one must be a deliberate, reviewed act.

If this fails you changed a prompt.  Bump the prompt id version (and the
component version) in prompts.py / components.py, update the lock below, and run
the regression for the affected component.
"""

from __future__ import annotations

from app.infrastructure.ai.prompts import PROMPTS

LOCK = {
    "companion.intent.system.v7": "2e831170f127cf76c5f81280803ac63d676e20b2d556b230defa6e22130e1c1d",
    "companion.scene-switch.system.v1": "09958512bdcde9c42e0547f4520bfeb80c2476235df60ce12c00fe6bed937e92",
    "tutoring.image-target.system.v1": "99439c3ad7d32dfc3cb4cea6c0646877044ebe586637faa28d15823391a89304",
    "tutoring.turn.system.v20": "72e440789c773203aa99843f4730f8a7966f69bc7e49f40cf6f31361643d65c0",
    "tutoring.leak-judge.system.v9": "dd8087d85f4ceaadd4b5a055108d4c2db4e77b05dc188a079d8dbafd096f9f1e",
    "tutoring.visual-leak-judge.system.v5": "781d3deb79c00b75ea1903c226b05ec9b3de9fd71f0e42fc5a056cab61403c8c",
    "companion.agent-text.system.v2": "3f2d9727250893bcd49643359c428e30f460e969066e44f303accc09e49e54d0",
    "task.intake.prompt.v2": "73995e7f1e1fe5641511300b06e0526d7220434e4a61ab35f8497ae9d5f3a3ad",
    "planning.intake.prompt.v3": "9aaaf23becfa4cec5b45b20f7f1720d62083109ea678524b565fad794dcf424a",
    "evaluation.review-aspects.system.v1": "7558e943f00a2f642a226640487aa9a16cdea1ebcd6c22b8cb8a080684ffa00f",
}


def test_prompt_digests_match_their_versioned_ids():
    assert set(PROMPTS) == set(LOCK), "register new prompts in LOCK"
    changed = [pid for pid, prompt in PROMPTS.items() if prompt.digest != LOCK[pid]]
    assert not changed, f"prompt body changed without a version bump: {changed}"

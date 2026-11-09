"""Prompt bodies are versioned.  Editing one must be a deliberate, reviewed act.

If this fails you changed a prompt.  Bump the prompt id version (and the
component version) in agent_specs JSON, update the lock below, and run
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
    "tutoring.leak-judge.system.v10": "988011f3e4ab620b8249a1127c83d0a9d358d3504460e103c8e0b407406dc5c2",
    "tutoring.visual-leak-judge.system.v6": "7ca13eaf4f04e95e0a0c32c4814230368ffef5ab4cff80fbf0a14af407cbcaf5",
    "task.intake.prompt.v2": "73995e7f1e1fe5641511300b06e0526d7220434e4a61ab35f8497ae9d5f3a3ad",
    "planning.intake.prompt.v6": "3b4debe34c4a6d7a6d9b025258742ee3d12d7b4d698cac6a9e8f218d5d4eaf98",
    "evaluation.review-aspects.system.v1": "7558e943f00a2f642a226640487aa9a16cdea1ebcd6c22b8cb8a080684ffa00f",
    'planning.intake.window-rules.v1': '95738d22502e63b27a8f786bfe0d27f2a079b3e8287cc656f899d3ad3452c56e',
    'planning.intake.history-block.v1': 'a2b88bb4aece5e05ad9ffbecd299a67dbc22c525152ad13033da947517f22fad',
    'planning.intake.history-omitted.v1': 'ca365b0221334dac4e2e99922138749fd5ffefc06902803b96075e22389157c6',
    'planning.intake.history-complete.v1': 'd771810a166e441f132681e4449df95eaffc78ac8f4a5ded599f60586da31c84',
    'planning.intake.current-images.v1': '9fadc14fd581247fd4e878ddefe46148cae1f042bc004308263675ef64d37129',
    'tutoring.turn.invalid-json.v1': '072121473fc840aacb09d2ba05d75e2b91ea03bb266a22c4a7ff1d94387ccf7f',
    'tutoring.turn.visual-schema.v1': 'b03a6a307d6ec83c2da818d508a80d49d888429a6f103dffb08ba3f389908873',
    'tutoring.turn.widget-not-loaded.v1': '3785cf89853a8af17805981b49a23568c59d15cee55caac1b21c96f1caf7269d',
    'tutoring.turn.leak-prefix.v1': '338b373e1eb377aa2a8b2665f0e41b078f0c36328b0adeaeb4ed1fccdce21727',
    'tutoring.turn.leak-answer.v1': '3a47fe3e525bb03538300c547ddd5c8f2b1457780701832cc21aaefde95df75d',
    'tutoring.turn.leak-draft.v1': 'd3b1d5f9a115e1808c996245a005179c866f4fe73a89a7e9ab73e703026623f7',
    'tutoring.turn.visual-leak.v1': 'f4fdc4f18d0bc73b38c3a28f9b53aaf3243e2c6483db6fff1a33acfbc036d021',
    'tutoring.turn.missing-visual.v1': '04b80665935fc000cf2a5cdbab7a45d4706473f542caaf8631fe178abba2e53c',
    'tutoring.turn.image-review.v1': '670ee4c12fd5be6914438b91e4d688b11777522a02acbbfd33f455bf102398ca',
    'tutoring.turn.image-compare.v1': 'c20b6be3dc47a0e7c775de729be869b4c2b8abd3a28f6e08533bf2edf9841385',
    'tutoring.turn.self-review.v1': '8bf3fc0c4b028ce7e4650d403f02f325513986dff5d713e2510fd32d345b4a05',
}


def test_prompt_digests_match_their_versioned_ids():
    assert set(PROMPTS) == set(LOCK), "register new prompts in LOCK"
    changed = [pid for pid, prompt in PROMPTS.items() if prompt.digest != LOCK[pid]]
    assert not changed, f"prompt body changed without a version bump: {changed}"

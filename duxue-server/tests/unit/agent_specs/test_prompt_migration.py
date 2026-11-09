"""Golden hashes captured from the Python implementations before configuration migration."""

import hashlib
from types import SimpleNamespace

from app.agent_specs.static_tools import static_tool_result
from app.application.commands import plan_intake
from app.application.workflows import tutor_loop

EXPECTED = {
  "_visual_repair:schema": "f9d8c1872578ce49bc14e717cb5c490e18b7b9435e6878c650d382248638d799",
  "_leak_repair:choice_verdict": "0b87a45751dd8c0e36dac044add4627fa074c22227223f8ffeb4d8347951b8f8",
  "_leak_repair:final_answer": "cd0894e68b91f79e26b17efa3a97cd8c893373fc3192d87044de8f81ea263d83",
  "_visual_leak_repair:schema": "4e9984fd2c8842b567a30400b442c05387f52d56b84697330526a34347443833",
  "_missing_visual_repair:schema": "693c7bc135d7fc8948ffcfe4b9665a87549c231a760e6bbf7ebf4d0162ff317c",
  "planning:empty": "1922db23d1f3585b0f9e78052da2d43c8e7f21e15ae24751a7932f6a94fe4a3f",
  "planning:history": "6be390f7ca3a80f3e4903bf025ec59587463dfa9b63611a122a83537701e7c3b",
  "planning:omitted": "5333c0fdd02f8e85e7340d71d36ee4e6e6074cb32b1c61a8668f7c24bdce2d4c",
  "svg": "1b738388c5dc1eb34b9b4eeff920e6b39de543da5dd2feefa6d43777b75ab106"
}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_migrated_repair_window_and_svg_text_is_unchanged():
    raw = {"act": "guide", "content": "先想一想。",
           "turn": {"type": "work", "relation": "same", "student_move": "request_hint"}}
    candidate = SimpleNamespace(shown_text="先想一想。", visual_error="schema", model_dump=lambda **kw: raw)
    actual = {}
    for name in ("_visual_repair", "_leak_repair", "_visual_leak_repair", "_missing_visual_repair"):
        for reason in (("choice_verdict", "final_answer") if name == "_leak_repair" else ("schema",)):
            review = SimpleNamespace(candidate=candidate, leak_reason=reason, failure="leak_detected")
            args = (candidate, raw) if name == "_visual_repair" else (review,)
            actual[name + ":" + reason] = digest(getattr(tutor_loop, name)(*args))
    for kind, rows, omitted in [
        ("empty", [], 0),
        ("history", [{"author": "ward", "text": "数学", "image_urls": ["data:a"]}], 0),
        ("omitted", [{"author": "companion", "text": "确认这两项", "leading_omitted": True}], 2),
    ]:
        request = plan_intake.PlanIntakeInput(recent_utterances=rows,
            attachment_keys=["ward/w/companion/a.jpg"], omitted_utterance_count=omitted)
        actual["planning:" + kind] = digest(plan_intake._recent_utterance_block(request))
    actual["svg"] = digest(static_tool_result("tutoring.widget_guidelines")["guidelines"])
    assert actual == EXPECTED

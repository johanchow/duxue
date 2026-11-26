"""Partial image evidence must survive a pending whole-problem dossier."""

import pytest

from app.application.workflows.image_review import ImageReview, QuestionReview
from app.application.workflows.tutor_loop import (
    _response_image_review_observation,
    _verdict_assertion_allowed,
)


def report():
    return ImageReview(
        conclusion="uncertain",
        coverage="partial",
        scope="all_visible",
        questions=[
            QuestionReview(
                image_ref="img_0123456789abcdef01234567",
                kind="other",
                location="a",
                task="geometry",
                student_answer="submitted",
                verdict="correct",
                basis="independent visual reasoning",
            ),
            QuestionReview(
                image_ref="img_0123456789abcdef01234567",
                kind="unreadable",
                location="b",
                task="drawing",
                student_answer=None,
                verdict="uncertain",
                basis="unreadable",
            ),
        ],
    )


@pytest.mark.parametrize("reviewed", [False, True])
@pytest.mark.parametrize(
    "env",
    [
        {"_dossier_gate": {"allows_verdict_assertion": False}},
        {"_enforce_confidence_gate": True},
    ],
)
def test_partial_geometry_preserves_only_independently_reviewed_verdicts(reviewed, env):
    evidence = report()
    evidence._visual_review_passed = reviewed
    obs = _response_image_review_observation(env, evidence)
    assert obs["verdict_assertion_allowed"] is reviewed
    assert obs["image_review"]["questions"][0]["verdict"] == (
        "correct" if reviewed else "unverified"
    )
    assert obs["image_review"]["questions"][1]["verdict"] == "uncertain"
    assert evidence.questions[0].verdict == "correct"
    if reviewed:
        assert obs["verified_question_refs"] == [
            {"image_ref": evidence.questions[0].image_ref, "location": "a"}
        ]
        assert "response_constraint" in obs


def test_uncertain_only_report_never_grants_verdict_authority():
    evidence = report()
    evidence.questions = evidence.questions[1:]
    evidence._visual_review_passed = True
    assert not _verdict_assertion_allowed(
        {"_dossier_gate": {"allows_verdict_assertion": False}}, image_review=evidence
    )


def test_pending_dossier_delivers_reviewed_partial_geometry_without_repair():
    import json

    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.tutor_loop import run_tutor_turn
    from app.application.workflows.tutor_tools import TutorToolbox
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy
    from tests.support.fakes import StaticTutorModel, tutor_raw

    pixels = "data:image/jpeg;base64,YQ=="
    evidence = report()
    for question in evidence.questions:
        question.image_ref = image_ref(pixels)
    model = StaticTutorModel(
        tutor_raw(content="待核验", image_review=evidence.model_dump()),
        tutor_raw(content="a题已经核验正确；b题看不清，请补拍b题。"),
    )

    class IndependentJudge:
        def leaks(self, **kwargs):
            return {
                "leaks": False,
                "reason": None,
                "answer_protected": True,
                "student_answer_correct": "partial",
                "affirms_student_answer": bool(kwargs["text"]),
            }

    result = run_tutor_turn(
        model,
        {"_dossier_gate": {"allows_verdict_assertion": False}},
        "{}",
        [],
        [pixels],
        TutorToolbox(
            None,
            tutoring_session_id=None,
            problem=None,
            task_title=None,
            task_active=False,
            window=[],
        ),
        permit=TutorPermitPolicy.permit(None),
        leak_judge=IndependentJudge(),
        task_title=None,
        problem_summary=json.dumps({"current_request": "检查作业"}),
        judge_images=[pixels],
    )
    assert result.vetting.failure is None
    assert result.leak_retried is False
    assert result.call.used_calls == 2
    assert result.call.candidate.content == "a题已经核验正确；b题看不清，请补拍b题。"
    assert model.calls[1]["current_images"] == []
    assert result.call.candidate.image_review.questions[1].verdict == "uncertain"

from app.application.workflows.math_verification import MathVerification
from app.application.workflows.tutor_turn import TutorTurnCandidate
from app.infrastructure.math_engine.adapter import SubprocessMathEngineAdapter
from tests.support.fakes import tutor_raw

REF = "img_" + "a" * 24


def page(size):
    report = {"scope": "all_visible", "coverage": "complete", "conclusion": "uncertain",
              "questions": [], "arithmetic_rows": {REF: [[str(i), f"{i}+1", str(i+1)] for i in range(size)]}}
    return TutorTurnCandidate.model_validate(tutor_raw(image_review=report))


def test_hundred_rows_run_in_four_isolated_batches_and_reuse_unchanged_transcriptions():
    class CountingEngine(SubprocessMathEngineAdapter):
        def __init__(self):
            super().__init__()
            self.sizes = []

        def check_arithmetic(self, pairs, timeout):
            self.sizes.append(len(pairs))
            return super().check_arithmetic(pairs, timeout)

    engine = CountingEngine()
    ledger = MathVerification(engine, {}, {REF})
    candidate = page(100)
    result = ledger.reconcile_image(candidate)
    assert result.image_review.conclusion == "all_correct"
    assert engine.sizes == [25] * 4
    assert not result.math_claims and len(ledger.records) == 100 and ledger.calls == 0
    candidate.image_review.questions[-1].calculation.submitted = "0"
    other = ledger.reconcile_image(candidate)
    assert other.image_review.questions[-1].verdict == "incorrect"
    assert engine.sizes[-1] == 1 and len(engine.sizes) == 5
    assert len(ledger.records) == 100
    last_rec = next(r for r in ledger.records.values() if r["location"] == "99")
    assert last_rec["op"] == "check_arithmetic" and last_rec["verdict"] == "not_equal"


def test_partial_coverage_and_unknown_arithmetic_never_authorize_all_correct():
    candidate = page(30)
    candidate.image_review.coverage = "partial"
    candidate.image_review.questions[5].calculation.expression = "?"
    result = MathVerification(SubprocessMathEngineAdapter(), {}, {REF}).reconcile_image(candidate)
    assert result.image_review.questions[5].verdict == "uncertain"
    assert result.image_review.questions[6].verdict == "correct"
    assert result.image_review.conclusion == "uncertain"


def test_later_batch_timeout_preserves_completed_positions_and_tool_budget():
    class SlowSecondBatch(SubprocessMathEngineAdapter):
        def check_arithmetic(self, pairs, timeout):
            if pairs[0][0] == "25+1":
                return ["timeout"] * len(pairs)
            return super().check_arithmetic(pairs, timeout)

    ledger = MathVerification(SlowSecondBatch(), {}, {REF})
    result = ledger.reconcile_image(page(30))
    assert [q.verdict for q in result.image_review.questions] == ["correct"] * 25 + ["uncertain"] * 5
    assert result.image_review.coverage == "partial"
    assert ledger.calls == 0


def test_socket_and_subprocess_worksheet_protocol_match():
    import tempfile
    import threading
    from pathlib import Path

    from app.infrastructure.math_engine.adapter import MathEngineAdapter
    from math_executor.server import Server
    # Unix address length is limited on macOS.
    with tempfile.TemporaryDirectory(dir="/tmp") as directory:
        address = str(Path(directory) / "math.sock")
        with Server(address) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                pairs = [("1/3+1/6", "1/2"), ("1/0", "0"), ("2×3", "7")]
                assert MathEngineAdapter(address).check_arithmetic(pairs, 2) == ["equal", "invalid_input", "not_equal"]
            finally:
                server.shutdown()
                thread.join()
        assert MathEngineAdapter(address).check_arithmetic(pairs, 2) == ["unavailable"] * 3


def test_missing_positions_force_partial_and_judge_sees_only_item_evidence():
    import json

    from app.application.workflows.image_review import review_problem

    candidate = page(30)
    candidate.image_review.expected_count = 31
    ledger = MathVerification(SubprocessMathEngineAdapter(), {}, {REF})
    result = ledger.reconcile_image(candidate)
    assert result.image_review.coverage == "partial"
    assert result.image_review.conclusion == "uncertain"
    evidence = json.loads(review_problem(None, result, ["test-pixels"]))
    assert "image_review_check" not in evidence
    assert len(ledger.records) == 30
    assert all(r["op"] == "check_arithmetic" and r["verdict"] == "equal" for r in ledger.records.values())
    assert all(row["calculation_status"] == "equal" for row in evidence["image_review"]["questions"])


def test_crop_budget_counts_failed_attempts_across_retries():
    from app.application.workflows.tutor_tools import TutorToolbox

    tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[])
    req = {"image_ref": REF, "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1}}
    for _ in range(2):
        assert tools._inspect_image(req)["status"] in ("unauthorized", "no_match")
    assert tools._inspect_image(req)["detail"] == "crop_limit_exceeded"


def test_handwritten_equality_chains_check_every_line_and_isolate_malformed_items():
    engine = SubprocessMathEngineAdapter()
    assert engine.check_arithmetic([
        ("30-(7+3)", "=30-10\n=20"), ("30-(7+3)", "=30-9\n=20"),
        ("30-(7+3)", "=\n=20"), ("3÷4", "0.75"),
    ], 2) == ["equal", "not_equal", "invalid_input", "equal"]


def test_reviewed_worksheet_can_confirm_without_ready_dossier():
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.tutor_loop import run_tutor_turn
    from app.application.workflows.tutor_tools import TutorToolbox
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel

    class AffirmationJudge(StaticLeakJudge):
        def leaks(self, *, text, **kwargs):
            return {"leaks": False, "answer_protected": True, "affirms_student_answer": bool(text)}

    pixels = "data:image/png;base64,YQ=="
    first = tutor_raw(image_review={
        "scope": "all_visible", "coverage": "complete", "questions": [], "conclusion": "uncertain",
        "arithmetic_rows": {image_ref(pixels): [["1", "14-3", "11"]]},
    })
    model = StaticTutorModel(first, tutor_raw(content="你写的得数正确。"))
    tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False,
                         window=[], math_engine=SubprocessMathEngineAdapter())
    result = run_tutor_turn(
        model, {"_dossier_gate": {"allows_verdict_assertion": False}}, "检查作业", [], [pixels],
        tools, permit=TutorPermitPolicy.permit(None), leak_judge=AffirmationJudge(),
        task_title=None, problem_summary=None, judge_images=[pixels],
    )
    assert result.vetting.failure is None
    assert result.call.candidate.content == "你写的得数正确。"


def test_worksheet_batch_populates_unified_math_records_for_parallel_vet():
    import json
    from pathlib import Path

    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.definitions import use_definitions
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.tutor_loop import run_tutor_turn
    from app.application.workflows.tutor_tools import TutorToolbox
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy
    from scripts.upgrade_math_bundle import upgrade as upgrade_math
    from scripts.upgrade_workflow_nodes import upgrade as upgrade_parallel
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel

    class CapturingJudge(StaticLeakJudge):
        def __init__(self):
            super().__init__(False)
            self.math_contexts: list[dict] = []
            self.leak_summaries: list[str] = []

        def leaks(self, *, text, problem_summary=None, **kwargs):
            self.leak_summaries.append(problem_summary or "")
            return {"leaks": False, "answer_protected": True}

        def check_math(self, *, text, context, images):
            self.math_contexts.append(context)
            return True

    source = json.loads(Path("tests/fixtures/admin-release.json").read_text())
    compiled = compile_bundle(upgrade_parallel(upgrade_math(source, enable=True))["bundle"])
    pixels = "data:image/png;base64,YQ=="
    first = tutor_raw(image_review={
        "scope": "all_visible",
        "coverage": "partial",
        "questions": [],
        "conclusion": "uncertain",
        "arithmetic_rows": {image_ref(pixels): [["一中8", "600-20", "570"], ["一中9", "14-3", "11"]]},
    })
    model = StaticTutorModel(first, tutor_raw(content="一中8 的 600-20 算错了，请重算。"))
    judge = CapturingJudge()
    tools = TutorToolbox(
        None, tutoring_session_id=None, problem=None, task_title="检查作业",
        task_active=False, window=[], math_engine=SubprocessMathEngineAdapter(),
    )
    with use_definitions(compiled.catalog):
        result = run_tutor_turn(
            model, {}, "这里面题目是不是全部做对了？", [], [pixels],
            tools, permit=TutorPermitPolicy.permit(None), leak_judge=judge,
            task_title="检查作业", problem_summary='{"current_request":"这里面题目是不是全部做对了？"}',
            judge_images=[pixels],
        )

    assert result.vetting.failure is None
    assert len(judge.math_contexts) == 1
    records = judge.math_contexts[0]["math_records"]
    assert len(records) == 2
    by_loc = {r["location"]: r for r in records}
    assert by_loc["一中8"]["op"] == "check_arithmetic"
    assert by_loc["一中8"]["verdict"] == "not_equal"
    assert by_loc["一中9"]["verdict"] == "equal"
    # Runtime prompt patch string is gone from all judge payloads.
    assert all("image_review_check" not in s for s in judge.leak_summaries)
    assert "image_review_check" not in json.dumps(judge.math_contexts[0], ensure_ascii=False)

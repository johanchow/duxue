import json

import pytest
from app.application.workflows.tutor_loop import Vetting, _leak_repair
from app.application.workflows.tutor_turn import TutorTurnCandidate
from tests.support.fakes import tutor_raw


def test_confirmation_dispute_is_not_a_leak_accusation_or_a_copy_of_the_draft():
    candidate = TutorTurnCandidate.model_validate(tutor_raw(content='全部正确'))
    feedback = json.loads(_leak_repair(Vetting(candidate, None, 'leak_detected', 'incorrect_confirmation')))
    assert feedback['kind'] == 'verification_disagreement'
    assert feedback['student_answer_correct'] is None
    assert 'draft' not in feedback


def test_image_review_rejects_claiming_everything_correct_with_partial_coverage():
    from app.application.workflows.image_review import ImageReview
    with pytest.raises(ValueError):
        ImageReview.model_validate({'conclusion': 'all_correct', 'coverage': 'partial', 'questions': []}).supported_conclusion()


def test_deployment_refuses_an_admin_release_missing_the_required_review_protocol():
    from app.agent_specs.configuration import snapshot_bundle
    from app.application.workflows.image_review import require_configuration
    bundle = snapshot_bundle()
    with pytest.raises(ValueError, match='image-review.v1'):
        require_configuration(bundle)
    for name in ('agents/tutoring.turn.json', 'agents/tutoring.image-target.json', 'gates/tutoring.leak-judge.json'):
        bundle['files'][name]['prompt']['template'] += '\n[image-review.v1]'
    require_configuration(bundle)


def test_review_references_must_belong_to_current_pixels_and_reach_independent_judge():
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.image_review import (
        review_problem,
        validate_image_review,
    )
    pixels = 'data:image/jpeg;base64,YQ=='
    report = {'conclusion': 'some_incorrect', 'coverage': 'complete', 'questions': [
        {'image_ref': image_ref(pixels), 'kind': 'arithmetic', 'location': '二1', 'task': '34-(28-13)',
         'student_answer': '17', 'verdict': 'incorrect', 'basis': '最后一步核验不一致', 'calculation': {'expression': '34-(28-13)', 'submitted': '17'}}]}
    candidate = TutorTurnCandidate.model_validate(tutor_raw(image_review=report))
    validate_image_review(candidate, [pixels])
    body = json.loads(review_problem('{"current_request":"检查作业"}', candidate, [pixels]))
    assert body['selected_image_refs'] == [image_ref(pixels)]
    assert body['image_review']['questions'][0]['student_answer'] == '17'
    with pytest.raises(ValueError, match='unselected_image'):
        validate_image_review(candidate, ['data:image/jpeg;base64,Yg=='])


def test_pure_picture_question_cannot_make_a_work_claim_without_a_report():
    from app.application.workflows.image_review import validate_image_review
    candidate = TutorTurnCandidate.model_validate(tutor_raw(content='全对'))
    with pytest.raises(ValueError, match='image_review_required'):
        validate_image_review(candidate, ['data:image/jpeg;base64,YQ=='])


@pytest.mark.parametrize(('expression', 'submitted', 'correct'), [
    ('90-37', '53', True), ('34-(28-13)', '17', False), ('63/(21-12)', '7', True),
    ('40+6*6', '76', True), ('-3+5', '2', True),
])
def test_transcribed_arithmetic_is_checked_as_syntax_not_text_semantics(expression, submitted, correct):
    from app.application.workflows.image_review import Calculation
    assert Calculation(expression=expression, submitted=submitted).correct() is correct


@pytest.mark.parametrize('expression', ['__import__("os").system("echo bad")', '2**999999', '1/0', 'value+1', '1+'])
def test_calculation_never_executes_code_or_open_semantic_expressions(expression):
    from app.application.workflows.image_review import Calculation
    with pytest.raises(ValueError):
        Calculation(expression=expression, submitted='1').correct()


def test_correct_submitted_arithmetic_cannot_be_labelled_incorrect_in_a_review():
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.image_review import QuestionReview
    with pytest.raises(ValueError, match='calculation_verdict_mismatch'):
        QuestionReview(image_ref=image_ref('data:test'), kind='arithmetic', location='口算第22题', task='90-37',
                       student_answer='53', verdict='incorrect', basis='需要重算',
                       calculation={'expression': '90-37', 'submitted': '53'}).validate_calculation()


def test_verified_report_is_fixed_before_visible_reply_is_generated():
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.tutor_loop import run_tutor_turn
    from app.application.workflows.tutor_tools import TutorToolbox
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel
    pixels = 'data:image/jpeg;base64,YQ=='
    report = {'conclusion': 'all_correct', 'coverage': 'complete', 'questions': [
        {'image_ref': image_ref(pixels), 'kind': 'arithmetic', 'location': '一22', 'task': '90-37', 'student_answer': '53',
         'verdict': 'correct', 'basis': '核验一致', 'calculation': {'expression': '90-37', 'submitted': '53'}}]}
    model = StaticTutorModel(tutor_raw(content='不应直接展示的首版草稿', image_review=report),
                             tutor_raw(content='你提交的这道题算对了。'))
    judge = StaticLeakJudge(False)
    result = run_tutor_turn(model, {}, '{}', [], [pixels],
                            TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[]),
                            permit=TutorPermitPolicy.permit(None), leak_judge=judge,
                            task_title=None, problem_summary='{"current_request":"检查90-37=53"}', judge_images=[pixels])
    assert result.vetting.failure is None
    assert result.call.candidate.content == '你提交的这道题算对了。'
    assert result.call.used_calls == 2
    assert model.calls[1]['observations'][0]['kind'] == 'verified_image_review'
    assert model.calls[1]['envelope']['image_review_phase'] == 'response'
    assert model.calls[1]['current_images'] == []
    assert model.calls[1]['recent_utterances'] == []
    assert judge.texts[0] == ''
    assert judge.texts[-1] == '你提交的这道题算对了。'
    assert result.call.candidate.image_review.questions[0].verdict == 'correct'


def test_production_runtime_refuses_rollback_to_a_prompt_without_the_new_protocol(tmp_path):
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import snapshot_bundle
    from app.agent_specs.release_runtime import ReleaseRuntime
    bundle = snapshot_bundle()
    old = {'id': 'old', 'environment': 'prod', 'bundle': bundle, 'digest': compile_bundle(bundle).digest}
    runtime = ReleaseRuntime('http://unused', 'unused', tmp_path / 'last-good.json', expected_environment='prod')
    with pytest.raises(ValueError, match='image-review.v1'):
        runtime.accept(old)
    assert runtime.current is None and not runtime.cache.exists()


def test_arithmetic_report_is_reconciled_before_independent_review_and_response():
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.tutor_loop import run_tutor_turn
    from app.application.workflows.tutor_tools import TutorToolbox
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel

    pixels = 'data:image/jpeg;base64,YQ=='
    report = {'conclusion': 'all_correct', 'coverage': 'complete', 'questions': [
        {'image_ref': image_ref(pixels), 'kind': 'arithmetic', 'location': '二1', 'task': '34-(28-13)',
         'student_answer': '17', 'verdict': 'correct', 'basis': '模型误算为正确',
         'calculation': {'expression': '34-(28-13)', 'submitted': '17'}}]}
    model = StaticTutorModel(tutor_raw(content='模型误称全对', image_review=report),
                             tutor_raw(content='第二大题第1题最后一步需要再检查一下。'))
    judge = StaticLeakJudge(False)
    result = run_tutor_turn(model, {}, '{}', [], [pixels],
                           TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None,
                                        task_active=False, window=[]),
                           permit=TutorPermitPolicy.permit(None), leak_judge=judge,
                           task_title=None, problem_summary='{"current_request":"检查这张图"}', judge_images=[pixels])
    assert result.vetting.failure is None
    assert result.call.candidate.image_review.conclusion == 'some_incorrect'
    assert result.call.candidate.image_review.questions[0].verdict == 'incorrect'
    assert model.calls[1]['observations'][0]['image_review']['questions'][0]['student_answer'] == '17'
    assert model.calls[1]['current_images'] == []
    assert '模型误算' not in model.calls[1]['observations'][0]['image_review']['questions'][0]['basis']

@pytest.mark.parametrize(('expression', 'submitted'), [('1/3*3', '1'), ('0.1+0.2', '0.3')])
def test_transcribed_arithmetic_uses_exact_rational_comparison(expression, submitted):
    from app.application.workflows.image_review import Calculation
    assert Calculation(expression=expression, submitted=submitted).correct()


@pytest.mark.parametrize('submitted', ['NaN', 'Infinity', '1e-999999999', '1e999999999'])
def test_calculation_rejects_unbounded_decimal_encodings(submitted):
    from app.application.workflows.image_review import Calculation
    with pytest.raises(ValueError):
        Calculation(expression='1', submitted=submitted).correct()


def test_missing_image_report_repairs_stay_within_the_shared_model_call_budget():
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.tutor_loop import run_tutor_turn
    from app.application.workflows.tutor_tools import TutorToolbox
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel
    pixels = 'data:image/jpeg;base64,YQ=='
    report = {'conclusion': 'all_correct', 'coverage': 'complete', 'questions': [
        {'image_ref': image_ref(pixels), 'kind': 'arithmetic', 'location': '一1', 'task': '90-37',
         'student_answer': '53', 'verdict': 'correct', 'basis': '相符',
         'calculation': {'expression': '90-37', 'submitted': '53'}}]}
    class MissingReportModel(StaticTutorModel):
        def complete(self, **kwargs):
            raw = super().complete(**kwargs)
            if len(self.calls) < 3:
                raw.pop('image_review', None)
            return raw
    model = MissingReportModel(tutor_raw(), tutor_raw(), tutor_raw(image_review=report),
                               tutor_raw(content='这道题的作答正确。'))
    result = run_tutor_turn(model, {}, '{}', [], [pixels],
                           TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[]),
                           permit=TutorPermitPolicy.permit(None), leak_judge=StaticLeakJudge(False),
                           task_title=None, problem_summary='{}', judge_images=[pixels])
    assert result.vetting.failure is None
    assert result.call.used_calls == 4
    assert len(model.calls) == 4
    assert json.loads(model.calls[2]['repair_error'])['error_code'] == 'image_review_required_for_image_work'


def test_concurrent_turns_do_not_share_the_selected_image_refs():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace
    from app.application.workflows.tutoring_workflow import TutoringWorkflow
    barrier = Barrier(2)
    workflow = TutoringWorkflow(None)
    def turn(invocation):
        workflow._selected_image_refs[f'{invocation.run_id}:{invocation.turn_id}'] = [invocation.turn_id]
        barrier.wait(timeout=5)
        return SimpleNamespace(next_interaction={'kind': 'text'})
    workflow._turn = turn
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(workflow.invoke, [SimpleNamespace(run_id='r', turn_id='a'), SimpleNamespace(run_id='r', turn_id='b')]))
    assert [result.next_interaction['image_target_refs'] for result in results] == [['a'], ['b']]
    assert workflow._selected_image_refs == {}


def test_correct_final_verdict_does_not_promote_an_unverified_step_diagnosis():
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.image_review import ImageReview, reconcile_calculations
    report = ImageReview.model_validate({'conclusion': 'some_incorrect', 'coverage': 'complete', 'questions': [
        {'image_ref': image_ref('image'), 'kind': 'arithmetic', 'location': '二1', 'task': '34-(28-13)',
         'student_answer': '17', 'verdict': 'incorrect', 'basis': '括号内算错',
         'calculation': {'expression': '34-(28-13)', 'submitted': '17'}}]})
    reconciled = reconcile_calculations(report)
    assert reconciled.questions[0].verdict == 'incorrect'
    assert reconciled.questions[0].basis == '仅复算转写原式与最终作答，未核验中间步骤'
    assert report.questions[0].basis == '括号内算错'


def test_image_candidate_cannot_bypass_independent_review_by_claiming_non_work():
    from app.application.workflows.tutor_loop import vet_candidate
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy
    from tests.support.fakes import StaticLeakJudge
    candidate = TutorTurnCandidate.model_validate({'act': 'answer', 'content': '全都做对了',
                                                  'turn': {'type': 'non_work', 'topic': 'atomic_lookup'}})
    judge = StaticLeakJudge(True)
    checked = vet_candidate(candidate, permit=TutorPermitPolicy.permit(None), leak_judge=judge,
                            task_title=None, problem_summary='{}', judge_images=['data:image/jpeg;base64,YQ=='])
    assert checked.failure == 'leak_detected'
    assert judge.texts == ['全都做对了']


def test_arithmetic_reconciliation_precedes_conclusion_consistency_checks():
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.image_review import ImageReview, reconcile_calculations
    raw = {'conclusion': 'all_correct', 'coverage': 'partial', 'questions': [
        {'image_ref': image_ref('image'), 'kind': 'arithmetic', 'location': '二1', 'task': '34-(28-13)',
         'student_answer': '17', 'verdict': 'correct', 'basis': '模型误算',
         'calculation': {'expression': '34-(28-13)', 'submitted': '17'}}]}
    reconciled = reconcile_calculations(ImageReview.model_validate(raw))
    reconciled.supported_conclusion()
    assert reconciled.conclusion == 'some_incorrect'
    assert reconciled.coverage == 'partial'


def test_denied_image_evidence_cannot_reach_the_response_phase():
    from app.agent_specs.image_refs import image_ref
    from app.application.workflows.tutor_loop import run_tutor_turn
    from app.application.workflows.tutor_tools import TutorToolbox
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel
    pixels = 'data:image/jpeg;base64,YQ=='
    report = {'conclusion': 'all_correct', 'coverage': 'complete', 'questions': [
        {'image_ref': image_ref(pixels), 'kind': 'arithmetic', 'location': '一1', 'task': '90-37',
         'student_answer': '53', 'verdict': 'correct', 'basis': '相符',
         'calculation': {'expression': '90-37', 'submitted': '53'}}]}
    model = StaticTutorModel(tutor_raw(image_review=report))
    checked = run_tutor_turn(model, {}, '{}', [], [pixels],
                             TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[]),
                             permit=TutorPermitPolicy.permit(None), leak_judge=StaticLeakJudge(True),
                             task_title=None, problem_summary='{}', judge_images=[pixels])
    assert checked.vetting.failure == 'leak_detected'
    assert all(call['envelope'].get('image_review_phase') != 'response' for call in model.calls)


def test_text_only_turn_does_not_enter_the_image_evidence_phase():
    from app.application.workflows.tutor_loop import run_tutor_turn
    from app.application.workflows.tutor_tools import TutorToolbox
    from app.contexts.tutoring.domain.tutor_permit import TutorPermitPolicy
    from tests.support.fakes import StaticLeakJudge, StaticTutorModel
    report = {'conclusion': 'uncertain', 'coverage': 'partial', 'questions': [
        {'image_ref': 'img_' + 'a' * 24, 'kind': 'unreadable', 'location': '未提供',
         'task': '未提供图片', 'student_answer': None, 'verdict': 'uncertain', 'basis': '无图片'}]}
    model = StaticTutorModel(tutor_raw(content='请说明你已经做到哪一步。', image_review=report))
    result = run_tutor_turn(model, {}, '{}', [], [],
                           TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[]),
                           permit=TutorPermitPolicy.permit(None), leak_judge=StaticLeakJudge(False),
                           task_title=None, problem_summary='{}')
    assert result.vetting.failure is None
    assert result.call.used_calls == 1

"""Semantic visual requirements survive retries; output must still pass both judges."""
import pytest

from app.application.workflows.tutor_loop import run_tutor_turn
from app.application.workflows.tutor_tools import TutorToolbox
from tests.support.fakes import StaticTutorModel, StaticVisualLeakJudge, tutor_raw
from tests.unit.tutoring.test_visual_vetting import PROTECTED, SEGMENT


def run(model, judge):
    return run_tutor_turn(
        model, {}, '{}', [], [],
        TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None,
                     task_active=False, window=[]),
        permit=PROTECTED, leak_judge=judge, task_title='应用题',
        problem_summary='由独立模型判断当前请求需要的表达方式',
    )


def test_requested_visual_triggers_redraw_even_without_tex():
    judge = StaticVisualLeakJudge(result={'leaks': False, 'visual_need': 'requested'})
    model = StaticTutorModel(tutor_raw(), tutor_raw(visual=SEGMENT))
    result = run(model, judge)
    assert len(model.calls) == 2
    assert result.vetting.visual is not None
    assert len(judge.visual_texts) == 1


@pytest.mark.parametrize('need', ['not_needed', 'helpful'])
def test_no_visual_need_does_not_force_a_diagram(need):
    model = StaticTutorModel(tutor_raw())
    result = run(model, StaticVisualLeakJudge(result={'leaks': False, 'visual_need': need}))
    assert len(model.calls) == 1
    assert result.vetting.failure is None


def test_unsatisfied_requested_visual_is_not_silently_delivered_as_success():
    model = StaticTutorModel(tutor_raw(), tutor_raw())
    result = run(model, StaticVisualLeakJudge(result={'leaks': False, 'visual_need': 'requested'}))
    assert len(model.calls) == 2
    assert result.vetting.failure == 'visual_unavailable'
    assert result.vetting.verdict is None


def test_redraw_cannot_bypass_text_safety():
    class Judge(StaticVisualLeakJudge):
        def leaks(self, **kwargs):
            self.calls += 1
            return {'leaks': self.calls > 1, 'reason': 'final_answer', 'visual_need': 'requested'}
    result = run(StaticTutorModel(tutor_raw(), tutor_raw(visual=SEGMENT)), Judge())
    assert result.vetting.visual is None
    assert result.vetting.failure == 'visual_unavailable'
    assert result.vetting.verdict is None


def test_optional_visual_extension_keeps_old_release_compatibility():
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import read_snapshot
    from scripts.upgrade_visual_bundle import upgrade
    original = read_snapshot()
    original = {**original, 'kind': 'draft', 'revision': 15}
    updated = upgrade(original)
    assert updated['id'] == original['id']
    assert updated['migration_source'] == {key: original[key] for key in ('kind', 'id', 'digest', 'revision')}
    assert updated['bundle']['compatibility'] == original['bundle']['compatibility']
    assert updated['digest'] != original['digest']
    compile_bundle(original['bundle'])
    compile_bundle(updated['bundle'])
    updated['bundle']['files']['gates/tutoring.leak-judge.json']['provider_output_schema']['properties']['visual_need'] = {'type': 'boolean'}
    with pytest.raises(ValueError):
        compile_bundle(updated['bundle'])


def test_text_steps_do_not_satisfy_a_spatial_diagram_request():
    from tests.unit.tutoring.test_tutor_visual import STEPS
    class Judge(StaticVisualLeakJudge):
        def leaks(self, **kwargs):
            self.calls += 1
            return {'leaks': False, 'visual_need': 'requested', 'visual_adequate': self.calls > 1}
    result = run(StaticTutorModel(tutor_raw(visual=STEPS), tutor_raw(visual=SEGMENT)), Judge())
    assert result.vetting.visual.kind == 'segment'


@pytest.mark.parametrize('field', ['visual_need', 'visual_adequate', 'visual_evidence'])
def test_visual_extension_requires_all_three_facts(field):
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.configuration import read_snapshot
    from scripts.upgrade_visual_bundle import upgrade
    updated = upgrade(read_snapshot())
    schema = updated['bundle']['files']['gates/tutoring.leak-judge.json']['provider_output_schema']
    schema['required'].remove(field)
    with pytest.raises(ValueError, match='incomplete visual delivery'):
        compile_bundle(updated['bundle'])


def test_unrepairable_svg_cannot_deliver_text_pointing_to_a_missing_picture():
    draft = tutor_raw(content="看下图的箭头。", visual={"kind": "svg", "alt": "箭头", "svg": "<svg/>"})
    result = run(StaticTutorModel(draft, draft), StaticVisualLeakJudge(result={"leaks": False}))
    assert result.vetting.failure == "visual_unavailable"
    assert result.vetting.verdict is None

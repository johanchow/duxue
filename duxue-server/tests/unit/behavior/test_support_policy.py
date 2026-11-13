from datetime import timedelta

import pytest

from app.contexts.behavior_analysis.domain.support import (
    eligible_runs,
    validate_assessment,
)
from app.contexts.study.domain.help_offer import invitation_allowed
from tests.unit.behavior.test_observation import T


def test_four_minutes_stillness_is_only_an_assessment_trigger():
    run={'activity':'still_with_material','seconds':239,'observed_at':T}
    assert eligible_runs([run],T)==[]
    run['seconds']=240
    assert eligible_runs([run],T)==[run]
    assert eligible_runs([run],T+timedelta(seconds=61))==[]
    assert validate_assessment({'decision':'uncertain','evidence_refs':[],'observed_basis':'不确定'},['f'],has_learning_context=True) is None


def test_return_requires_observed_or_explicit_learning_context():
    result={'decision':'invite_return','evidence_refs':['f'],'observed_basis':'可见活动'}
    assert validate_assessment(result,['f'],has_learning_context=False) is None
    with pytest.raises(ValueError):
        validate_assessment(result,['another'],has_learning_context=True)


@pytest.mark.parametrize('override',[{'reserved_count':2},{'has_active':True},{'same_run':True},
    {'channel_active':False},{'opted_in':False},{'interaction_busy':True},
    {'last_reserved_at':T-timedelta(minutes=19)},{'observed_at':T-timedelta(seconds=61)}])
def test_hard_policy_gates(override):
    values=dict(current=T,observed_at=T,fresh_until=T+timedelta(seconds=120),reserved_count=0,
                last_reserved_at=None,has_active=False,same_run=False,channel_active=True,opted_in=True,interaction_busy=False)
    assert invitation_allowed(**values)
    assert not invitation_allowed(**{**values,**override})

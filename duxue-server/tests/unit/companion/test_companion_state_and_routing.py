from __future__ import annotations

from types import SimpleNamespace
import pytest

from app.application.ports.companion import IntentProposal
from app.contexts.companion.domain.intent_router import IntentRouter
from app.contexts.companion.domain.policy import PolicyRegistry
from app.infrastructure.ai.intent_classifier import ModelIntentClassifier, parse_intent_payload
from app.infrastructure.ai.model_gateway import ModelGatewayError


@pytest.fixture
def router():
    return IntentRouter()


@pytest.fixture
def policy():
    return PolicyRegistry()


def test_safety_keyword_triggers_immediate_safety_route(router):
    """自残/伤害等安全关键词具有绝对最高优先级。"""
    decision = router.decide(
        content="我不想活了，想自残",
        route_hint="planning",
        focus_run=SimpleNamespace(agent_type="planning", id="run-1"),
    )
    assert decision.target == "safety"
    assert decision.mode == "clarify"
    assert decision.route_reason == "safety_keyword"


def test_explicit_route_hint_takes_precedence(router):
    """已验证的 route_hint 覆盖模型提议。"""
    decision = router.decide(
        content="随便聊两句",
        route_hint="reflection",
        focus_run=None,
        proposal=IntentProposal(intent="tutoring"),
    )
    assert decision.target == "reflection"
    assert decision.mode == "start"
    assert decision.route_reason == "validated_route_hint"


def test_model_proposal_starts_one_business_intent(router):
    """模型提议的单一意图在没有 focus 时作为 start。关键词不能改写该提议。"""
    decision = router.decide(
        content="铁木真统一了蒙古的什么？",
        route_hint=None,
        focus_run=None,
        proposal=IntentProposal(intent="tutoring"),
    )
    assert decision.target == "tutoring"
    assert decision.mode == "start"
    assert decision.route_reason == "model_intent_proposal"


def test_unclear_proposal_clarifies_even_when_words_match_several_scenes(router):
    """多个场景或听不清时，模型提议 unclear，代码进入澄清，不再扫描关键词。"""
    decision = router.decide(
        content="帮我安排计划，顺便这道题目怎么做",
        route_hint=None,
        focus_run=None,
        proposal=IntentProposal(intent="unclear"),
    )
    assert decision.target == "clarify"
    assert decision.mode == "clarify"
    assert decision.route_reason == "insufficient_route_confidence"


def test_same_proposal_continues_focus(router):
    focus_run = SimpleNamespace(agent_type="tutoring", id="run-tutor-1")
    decision = router.decide(
        content="这道几何题第一步怎么做？",
        route_hint=None,
        focus_run=focus_run,
        proposal=IntentProposal(intent="tutoring"),
    )
    assert decision.target == "tutoring"
    assert decision.mode == "continue"
    assert decision.active_session_id == "run-tutor-1"


def test_different_proposal_hands_off(router):
    focus_run = SimpleNamespace(agent_type="planning", id="run-plan-1")
    decision = router.decide(
        content="这道题我看不懂",
        route_hint=None,
        focus_run=focus_run,
        proposal=IntentProposal(intent="tutoring"),
    )
    assert decision.target == "tutoring"
    assert decision.mode == "handoff"
    assert decision.active_session_id == "run-plan-1"


def test_invalid_model_payload_becomes_unclear():
    assert parse_intent_payload('{"intent":"tutoring"}').intent == "tutoring"
    assert parse_intent_payload('{"intent":"none"}').intent == "unclear"
    assert parse_intent_payload('{"intent":"delete_all"}').intent == "unclear"
    assert parse_intent_payload("not-json").intent == "unclear"


def test_classifier_failure_proposes_unclear():
    def fail(*, content: str, focus_agent_type: str | None) -> str:
        raise ModelGatewayError("model_transport_error")

    proposal = ModelIntentClassifier(complete=fail).propose(content="铁木真是谁", focus_agent_type=None)
    assert proposal.intent == "unclear"


def test_policy_blocks_direct_answer_request(policy):
    """直接索要答案或者代写作业必须被政策拦截并降级为启发。"""
    for phrase in ["直接告诉我答案", "这道题选 A 还是选 B", "帮我代写作业", "直接给答案"]:
        decision = policy.validate_tutoring_input(phrase)
        assert not decision.accepted
        assert decision.code == "direct_answer_request"
        assert decision.safe_response is not None


def test_policy_allows_concept_help(policy):
    """正常的提问和思路探索应当被政策接受。"""
    decision = policy.validate_tutoring_input("老师，我对这道题的垂径定理不太理解")
    assert decision.accepted
    assert decision.code is None


def test_policy_validates_candidate_tools_and_safety(policy):
    """模型输出候选验证：未注册工具或私有思维链必须被拒绝。"""
    # 未注册工具被拒
    decision = policy.validate_candidate({"tool": "unregistered_bash"}, allowed_tools={"search"})
    assert not decision.accepted
    assert decision.code == "unregistered_tool"

    # 包含不可持久化思维链被拒
    decision_cot = policy.validate_candidate({"raw_chain_of_thought": "secret reasoning"}, allowed_tools=set())
    assert not decision_cot.accepted
    assert decision_cot.code == "chain_of_thought_not_storable"

    # 合法文本候选被接受
    accepted = policy.validate_candidate({"content": "这是正常启发文本"}, allowed_tools=set())
    assert accepted.accepted

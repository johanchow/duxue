from __future__ import annotations

from types import SimpleNamespace
import pytest

from app.ai_runtime.intent_router import IntentRouter
from app.ai_runtime.policy import PolicyRegistry


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
    """客户端校验后的 route_hint 应直接生效。"""
    decision = router.decide(
        content="随便聊两句",
        route_hint="reflection",
        focus_run=None,
    )
    assert decision.target == "reflection"
    assert decision.mode == "start"
    assert decision.route_reason == "validated_route_hint"


def test_single_intent_starts_cleanly(router):
    """明确的单意图且无活跃会话时，作为 start 启动。"""
    decision = router.decide(
        content="帮我排一下明天的学习计划",
        route_hint=None,
        focus_run=None,
    )
    assert decision.target == "planning"
    assert decision.mode == "start"
    assert decision.confidence > 0.9


def test_multiple_conflicting_intents_require_clarification(router):
    """当单句话同时命中多个意图关键词时，要求澄清，不盲目分发。"""
    decision = router.decide(
        content="帮我安排计划，顺便这道题目怎么做",
        route_hint=None,
        focus_run=None,
    )
    assert decision.target == "clarify"
    assert decision.mode == "clarify"
    assert decision.route_reason == "multiple_explicit_intents"


def test_intent_continuation_with_active_focus(router):
    """在已有 focus_run 的情况下，属于同类型的意图应以 continue 模式继续。"""
    focus_run = SimpleNamespace(agent_type="tutoring", id="run-tutor-1")
    decision = router.decide(
        content="这道几何题第一步怎么做？",
        route_hint=None,
        focus_run=focus_run,
    )
    assert decision.target == "tutoring"
    assert decision.mode == "continue"
    assert decision.active_session_id == "run-tutor-1"


def test_handoff_from_planning_to_tutoring(router):
    """在计划进行中，用户突然提出答疑请求，应触发 handoff 交接。"""
    focus_run = SimpleNamespace(agent_type="planning", id="run-plan-1")
    decision = router.decide(
        content="这道题我看不懂",
        route_hint=None,
        focus_run=focus_run,
    )
    assert decision.target == "tutoring"
    assert decision.mode == "handoff"
    assert decision.active_session_id == "run-plan-1"


def test_vague_input_continues_existing_focus(router):
    """模糊日常回复在有活跃工作流时，默认延续当前 focus。"""
    focus_run = SimpleNamespace(agent_type="tutoring", id="run-tutor-2")
    decision = router.decide(
        content="好的，然后呢",
        route_hint=None,
        focus_run=focus_run,
    )
    assert decision.target == "tutoring"
    assert decision.mode == "continue"
    assert decision.route_reason == "focus_run_normal_continuation"


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

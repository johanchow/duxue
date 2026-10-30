from types import SimpleNamespace

from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.infrastructure.persistence.workflow_dispatcher import (
    SqlAlchemyWorkflowDispatcher,
)


def test_planning_dispatch_preserves_keyword_only_invocation_contract():
    invocation = RunInvocation(run_id="run", thread_id="thread", ward_id="ward", agent_type="planning", turn={})
    calls = []

    class Planning:
        def invoke(self, *, invocation):
            calls.append(invocation)
            return WorkflowOutcome(run_status="waiting_for_ward")

    db = SimpleNamespace(get=lambda *_: SimpleNamespace(thread_id="thread", ward_id="ward"))
    result = SqlAlchemyWorkflowDispatcher(db, planning_factory=lambda _: Planning()).invoke(invocation)
    assert calls == [invocation]
    assert result.run_status == "waiting_for_ward"

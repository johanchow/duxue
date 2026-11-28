from types import SimpleNamespace

from app.application.ports.companion import RunInvocation, WorkflowOutcome
from app.infrastructure.persistence.workflow_dispatcher import (
    SqlAlchemyWorkflowDispatcher,
)


def test_tutoring_dispatch_preserves_keyword_only_invocation_contract(monkeypatch):
    invocation = RunInvocation(run_id="run", thread_id="thread", ward_id="ward", agent_type="tutoring", turn={})
    calls = []

    class Planning:
        def invoke(self, *, invocation):
            calls.append(invocation)
            return WorkflowOutcome(run_status="waiting_for_ward")

    db = SimpleNamespace(get=lambda *_: SimpleNamespace(thread_id="thread", ward_id="ward"))
    monkeypatch.setattr("app.infrastructure.persistence.workflow_dispatcher.tutoring_workflow", lambda _: Planning())
    result = SqlAlchemyWorkflowDispatcher(db).invoke(invocation)
    assert calls == [invocation]
    assert result.run_status == "waiting_for_ward"

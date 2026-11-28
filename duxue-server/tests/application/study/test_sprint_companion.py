from types import SimpleNamespace
from uuid import uuid4
from app.application.ports.companion import StudyControl
from app.application.workflows.study_conversation import StudyConversation
from app.infrastructure.persistence.models import Task, Sprint
from tests.support.factories import create_ward


def test_quiet_and_duration_only_sprint_are_independent_of_tasks(db):
    ward = create_ward(db)
    service = StudyConversation(db)
    run = SimpleNamespace(id=str(uuid4()), attempt=1, ward_id=ward.id)
    for action in ("quiet_start", "sprint_prepare"):
        result = service.handle_action(run, SimpleNamespace(command_id=str(uuid4())),
            StudyControl(action=action, target_minutes=10))
        if action == "quiet_start":
            assert result.response["observation_quiet"]["active"]
    assert db.query(Sprint).one().status == "ready"
    assert db.query(Task).count() == 0

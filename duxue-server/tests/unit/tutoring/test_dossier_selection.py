from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.agent_specs.image_refs import image_ref
from app.application.queries.problem_dossier import GetProblemDossierQuery
from app.application.workflows.tutoring_workflow import TutoringWorkflow


@pytest.mark.parametrize(("selected_images", "reuse"), [
    (["data:image/png;base64,Yg=="], False),
    (["data:image/png;base64,YQ=="], True),
    ([], True),
])
def test_open_dossier_only_guides_its_own_image(monkeypatch, selected_images, reuse):
    original = image_ref("data:image/png;base64,YQ==")
    dossier = SimpleNamespace(evidence={"request_image_refs": [original]})
    stored_view = dossier, {"dossier_id": "old"}
    monkeypatch.setattr(GetProblemDossierQuery, "tutoring_view", Mock(return_value=stored_view))
    workflow = TutoringWorkflow(None, turn_model=Mock())
    view = workflow._resolve_active_dossier(
        ward_id="ward", problem_row=SimpleNamespace(dossier_id="old", milestone_progress={}),
        content="帮我看看", images=selected_images, attachment_keys=[], tutoring_intent=None,
    )
    assert view == (stored_view if reuse else (None, None))


def test_selected_history_attachment_is_resolved_from_the_same_read(monkeypatch):
    from app.application.queries import run_transcript
    from app.application.workflows.image_target import prepare_images

    key = "ward/w/companion/prior.jpg"
    pixel = "data:image/png;base64,YQ=="
    reader = Mock(return_value=pixel)
    monkeypatch.setattr(run_transcript, "_default_reader", reader)
    monkeypatch.setattr(run_transcript, "recent_thread_utterances", Mock(return_value=(
        [{"author": "ward", "text": "这张图", "attachment_refs": [key]}], 0,
    )))
    workflow = TutoringWorkflow(None, turn_model=Mock())
    invocation = SimpleNamespace(run_id="run", turn_id="turn", thread_id="thread", ward_id="w", turn={})
    window, current, keys = workflow._media(invocation)
    prepared = prepare_images(window, current, content="上一张图", select=lambda _rows, _content: {
        "target_image_ids": [1], "ambiguous": False,
    })
    assert [keys[ref] for ref in prepared.refs] == [key]
    reader.assert_called_once_with(key)

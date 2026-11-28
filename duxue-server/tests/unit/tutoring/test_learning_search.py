import asyncio
import base64
import json
import time
from types import SimpleNamespace

import pytest

from app.agent_specs.admin_bundle import compile_bundle
from app.agent_specs.configuration import read_snapshot
from app.agent_specs.definitions import use_definitions
from app.application.workflows.tutor_loop import run_tutor_turn
from app.application.workflows.tutor_tools import TutorToolbox
from app.application.workflows.tutor_turn import TutorTurnCandidate
from app.infrastructure.ai import learning_search
from scripts.upgrade_tutoring_search import upgrade
from tests.support.fakes import StaticTutorModel, StaticVisualLeakJudge, tutor_raw
from tests.unit.tutoring.test_visual_vetting import OPEN

ARGS = {"mode": "image", "query": "深圳 APEC 会议 官方照片", "learning_purpose": "解释区域合作"}
ROW = {"title": "代表会议照片", "hostPageUrl": "https://www.apec.org/example",
       "imageUrl": "https://photos.apec.org/example"}


@pytest.fixture
def provider(monkeypatch):
    calls = []
    async def fetch(mode, params, token):
        calls.append(params)
        return [ROW, {**ROW, "imageUrl": ""}]

    async def image(url):
        return b"test-thumbnail"

    monkeypatch.setattr(learning_search, "settings", SimpleNamespace(iqs_api_key="test", search_budget_ms=4000))
    monkeypatch.setattr(learning_search, "_fetch", fetch)
    monkeypatch.setattr(learning_search, "_thumbnail", image)
    return calls


@pytest.fixture
def bundle():
    old = read_snapshot()
    draft = upgrade(old)
    assert compile_bundle(old["bundle"]).digest == old["digest"]
    assert upgrade(draft)["digest"] == draft["digest"]
    with use_definitions(compile_bundle(draft["bundle"]).catalog):
        yield


@pytest.mark.parametrize("decision", [False, True, None])
def test_followup_photo_passes_same_pixels_to_existing_judge(bundle, provider, decision):
    class Tutor(StaticTutorModel):
        def complete(self, **context):
            results = [row for row in context["observations"] if row["tool"] == "web_search"]
            if not results:
                return {"tool": "web_search", "args": ARGS}
            photo, = results[0]["results"]
            return tutor_raw(act="answer", relation="none", topic="atomic_lookup",
                             content="图中是各方代表。", photo_ref=photo["photo_ref"], photo_caption="代表会议")

    class Judge(StaticVisualLeakJudge):
        def visual_leaks(self, *, image, **kwargs):
            assert base64.b64decode(image.split(",")[1]) == b"test-thumbnail"
            self.visual_texts.append(kwargs["text"])
            return decision

    judge = Judge({"leaks": False, "visual_need": "requested", "visual_adequate": True})
    tools = TutorToolbox(None, tutoring_session_id=None, problem=None, task_title=None, task_active=False, window=[])
    result = run_tutor_turn(Tutor(), {}, "我是说把图显示出来", [], [], tools, permit=OPEN,
                            leak_judge=judge, task_title=None, problem_summary="深圳APEC")
    assert len(judge.visual_texts) == len(provider) == 1
    assert provider[0]["engineType"] == "MultimodalSpeed"
    if decision is False:
        assert result.vetting.visual.source == ROW["hostPageUrl"]
        assert result.vetting.visual.jpeg == b"test-thumbnail"
    else:
        assert result.vetting.failure == "photo_unavailable"
        assert result.vetting.visual is None


def test_retry_count_and_bounded_wait(provider, monkeypatch):
    tool = learning_search.LearningSearch()
    assert tool.search({**ARGS, "count": 8})["status"] == "found"
    assert provider[0]["advancedParams"]["numResults"] == "8"
    async def slow(*args):
        await asyncio.sleep(3)
    monkeypatch.setattr(learning_search, "_fetch", slow)
    tool.deadline = time.monotonic() + 0.12
    assert tool.search(ARGS)["status"] == "timeout"
    assert tool.search(ARGS)["status"] == "budget_exhausted"


def test_model_cannot_self_issue_photo(provider):
    candidate = TutorTurnCandidate.model_validate(tutor_raw(visual={"kind": "web_photo", "alt": "图", "source": ROW["hostPageUrl"]}))
    assert candidate.visual is None
    with pytest.raises(ValueError, match="unknown photo_ref"):
        learning_search.LearningSearch().photo("fabricated")


def test_reviewed_attachment_is_readable_only_on_owners_message(db, bundle, provider, monkeypatch, tmp_path):
    from fastapi import HTTPException

    from app.api.v1.common import Principal
    from app.api.v1.companion import companion_message_image
    from app.application.process_managers.companion_coordinator import (
        CompanionCoordinator,
    )
    from app.application.workflows.tutoring_workflow import TutoringWorkflow
    from app.infrastructure.persistence.models import CompanionMessage
    from app.infrastructure.storage import object_storage
    from tests.support.factories import create_ward
    from tests.support.fakes import StaticIntentClassifier, StaticSafetyScreening

    storage = object_storage.LocalStorage()
    monkeypatch.setattr(storage, "path", lambda key: tmp_path / key)
    monkeypatch.setattr(object_storage, "storage", storage)
    monkeypatch.setattr("app.api.v1.companion.storage", storage)
    ward = create_ward(db)
    other = create_ward(db)
    db.commit()

    class Tutor(StaticTutorModel):
        def complete(self, **context):
            items = [r for r in context["observations"] if r["tool"] == "web_search"]
            if not items:
                return {"tool": "web_search", "args": ARGS}
            return tutor_raw(act="answer", relation="none", topic="atomic_lookup",
                             content="这张照片展示代表会议。", photo_caption="代表会议",
                             photo_ref=items[0]["results"][0]["photo_ref"])

    class Judge(StaticVisualLeakJudge):
        def visual_leaks(self, *, image, **kwargs):
            return False

    workflow = TutoringWorkflow(db, turn_model=Tutor(), leak_judge=Judge(),
                                safety_screening=StaticSafetyScreening())
    from app.infrastructure.persistence import workflow_dispatcher

    monkeypatch.setattr(workflow_dispatcher, "tutoring_workflow", lambda db: workflow)
    dispatcher = workflow_dispatcher.SqlAlchemyWorkflowDispatcher(db)
    coordinator = CompanionCoordinator(db, dispatcher=dispatcher, classifier=StaticIntentClassifier("tutoring"))
    result = coordinator.handle(ward_id=ward.id, content="找一张深圳APEC会议照片", thread_id=None,
                                expected_thread_version=0, route_hint="tutoring")
    message = db.query(CompanionMessage).filter_by(thread_id=result.thread_id, author_type="companion").one()
    assert message.interaction_ref["parts"][0]["visual"]["source"] == ROW["hostPageUrl"]
    assert len(message.attachment_refs) == 1
    assert companion_message_image(message.id, 0, Principal(role="ward", user_id=ward.id), db).body == b"test-thumbnail"
    with pytest.raises(HTTPException) as exc:
        companion_message_image(message.id, 0, Principal(role="ward", user_id=other.id), db)
    assert exc.value.status_code == 404


@pytest.mark.parametrize(("review", "blocked"), [
    (None, None),
    ({"learning_related": True, "age_appropriate": True, "caption_supported": False}, True),
    ({"learning_related": True, "age_appropriate": False, "caption_supported": True}, True),
    ({"learning_related": False, "age_appropriate": True, "caption_supported": True}, True),
    ({"learning_related": True, "age_appropriate": True, "caption_supported": True}, False),
])
def test_photo_gate_requires_positive_facts_in_addition_to_answer_protection(bundle, monkeypatch, review, blocked):
    from app.infrastructure.ai import components
    from app.infrastructure.ai.tutor_turn_model import QwenLeakJudge
    def invoke(**kwargs):
        assert kwargs["spec"].accepts_images
        assert kwargs["user"][-1]["image_url"]["url"] == "data:image/jpeg;base64,dGVzdA=="
        return {"leaks": False, **({"photo_review": {**review, "observation": "观察画面"}} if review else {})}
    monkeypatch.setattr(components, "invoke_json_component", invoke)
    assert QwenLeakJudge().visual_leaks(text="图注", task_title=None, problem_summary="问题",
        image="data:image/jpeg;base64,dGVzdA==") is blocked


def test_web_mode_returns_source_evidence_without_downloading_pages(monkeypatch):
    import httpx

    client = httpx.AsyncClient
    seen = []
    def dispatch(request):
        seen.append(request.url.path)
        assert request.url.host == "cloud-iqs.aliyuncs.com"
        assert request.method == "POST"
        assert json.loads(request.content)["engineType"] == "LiteAdvanced"
        assert request.headers["Authorization"] == "Bearer test"
        return httpx.Response(200, json={"pageItems": [
            {"link": ROW["hostPageUrl"], "title": "会议公报", "snippet": "合作议题摘要"},
        ]})
    monkeypatch.setattr(learning_search, "settings", SimpleNamespace(iqs_api_key="test", search_budget_ms=4000))
    monkeypatch.setattr(learning_search.httpx, "AsyncClient", lambda: client(transport=httpx.MockTransport(dispatch)))
    tool = learning_search.LearningSearch()
    result = tool.search({**ARGS, "mode": "web"})
    assert result == {"status": "found", "results": [
        {"source": ROW["hostPageUrl"], "title": "会议公报", "excerpt": "合作议题摘要"}]}
    tool.deadline = time.monotonic() - 1
    assert tool.search({**ARGS, "mode": "web"})["status"] == "budget_exhausted"
    assert seen == ["/search/unified"]


def test_failed_thumbnail_is_not_downloaded_again(provider, monkeypatch):
    import httpx
    seen = []
    async def failed(url):
        seen.append(url)
        raise httpx.ConnectTimeout("test timeout")
    monkeypatch.setattr(learning_search, "_thumbnail", failed)
    tool = learning_search.LearningSearch()
    ref = tool.search(ARGS)["results"][0]["photo_ref"]
    for _ in range(2):
        with pytest.raises(ValueError, match="thumbnail unavailable"):
            tool.photo(ref)
    assert seen == [ROW["imageUrl"]]


def test_iqs_image_downloads_only_selected_photo_and_preserves_attribution(monkeypatch):
    import io
    import socket

    import httpx
    from PIL import Image

    picture = io.BytesIO()
    Image.new("RGB", (1200, 800)).save(picture, "PNG")
    seen = []
    def dispatch(request):
        seen.append(request.url.host)
        if request.url.host == "cloud-iqs.aliyuncs.com":
            assert request.url.path == "/search/multimodal"
            assert json.loads(request.content) == {
                "query": ARGS["query"], "engineType": "MultimodalSpeed", "advancedParams": {"numResults": "3"}}
            return httpx.Response(200, json={"imageItems": [{**ROW, "publishedTime": "2026-11-01"}]})
        assert request.url.host == "93.184.216.34"
        assert request.headers["Host"] == "photos.apec.org"
        assert request.extensions["sni_hostname"] == "photos.apec.org"
        assert "Authorization" not in request.headers
        return httpx.Response(200, content=picture.getvalue())

    async def lookup(loop, host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    client = httpx.AsyncClient
    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", lookup)
    monkeypatch.setattr(learning_search.httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(dispatch), **kw))
    monkeypatch.setattr(learning_search, "settings", SimpleNamespace(iqs_api_key="test", search_budget_ms=4000))
    tool = learning_search.LearningSearch()
    item, = tool.search(ARGS)["results"]
    assert seen == ["cloud-iqs.aliyuncs.com"]
    assert item["published_time"] == "2026-11-01"
    source, title, jpeg = tool.photo(item["photo_ref"])
    assert (source, title) == (ROW["hostPageUrl"], ROW["title"])
    with Image.open(io.BytesIO(jpeg)) as image:
        assert image.format == "JPEG" and image.width == 640
    assert len(seen) == 2


def test_image_download_rejects_local_destination():
    with pytest.raises(ValueError, match="non-public"):
        asyncio.run(learning_search._download_image("https://127.0.0.1/photo"))

"""Non-persistent interpretation of one Ward's spoken sprint setup."""

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent_specs.catalog import load_catalog
from app.agent_specs.contexts import build_context
from app.agent_specs.runtime import execute_workflow
from app.application.commands.task_intake import TaskIntakeError
from app.infrastructure.ai import components
from app.infrastructure.ai.errors import ModelGatewayError


class SprintSpokenDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    topic: str | None = Field(default=None, max_length=300)
    target_minutes: int | None = Field(default=None, ge=1, le=180, strict=True)


class SprintPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=4000)
    previous: SprintSpokenDraft | None = None


class SprintVoiceCandidate(SprintSpokenDraft):
    cancelled: bool = False
    needs_clarification: bool = False


def preview_spoken_sprint(request: SprintPreviewRequest) -> dict:
    catalog = load_catalog()
    try:
        state = execute_workflow(
            catalog.spec("sprint-intake"),
            handlers={
                "study.sprint-intake": lambda _state: components.invoke_agent_component(
                    spec=catalog.component("sprint-intake", "run"),
                    user=build_context("study.sprint-intake", request=request),
                ),
            },
        )
        proposal = SprintVoiceCandidate.model_validate(
            state["results"]["sprint-intake.run"].unwrap()
        )
    except (ModelGatewayError, ValidationError) as error:
        raise TaskIntakeError("挑战整理暂不可用，请再说一次") from error
    if proposal.cancelled:
        return {
            "status": "cancelled",
            "topic": None,
            "target_minutes": None,
            "message": "先直接做作业。",
        }
    if proposal.needs_clarification:
        return {
            "status": "clarify",
            "topic": None,
            "target_minutes": None,
            "message": "这轮想试多久？可以按住说话再说一次。",
        }
    topic = (proposal.topic or "").strip() or None
    if proposal.target_minutes is None:
        return {
            "status": "needs_duration",
            "topic": topic,
            "target_minutes": None,
            "message": "想试多久？",
        }
    topic = topic or "专注挑战"
    return {
        "status": "ready",
        "topic": topic,
        "target_minutes": proposal.target_minutes,
        "message": f"{topic} · {proposal.target_minutes}分钟",
    }

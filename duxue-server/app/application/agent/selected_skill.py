"""Execute model-selected single or composite skills with domain-owned delivery results."""

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from app.application.agent.gates import GateRunner
from app.application.agent.orchestrator import EduAgentOrchestrator, OrchestratorStep
from app.application.agent.registry import ToolContext
from app.application.tools.core_tools import build_default_registries

MAX_SKILLS_PER_TURN = 3
_COURSEWARE_ACTION_TEXT = "打开课件编辑器，生成并核验这份交互课件。"


@dataclass(frozen=True)
class CompositeTurnOutcome:
    documents: tuple[Any, ...] = ()
    reply: dict[str, Any] | None = None
    recommend_courseware: bool = False
    courseware_prompt: str | None = None
    summary_content: str | None = None
    completed_skills: tuple[str, ...] = ()
    partial_failure_note: str | None = None


def execute_selected_skill(
    *,
    role,
    owner,
    thread_id,
    message,
    attachments,
    skill,
    tool,
    arguments,
    invoke,
    gates,
    summarize,
):
    result = None
    failure = None

    def command(_args, _context):
        nonlocal result, failure
        try:
            result = invoke()
        except Exception as error:
            failure = error
            raise
        return {"completed": True}

    def planner(state):
        if not state["active_skill"]:
            return OrchestratorStep(action="load_skill", skill_id=skill)
        if result is None:
            return OrchestratorStep(
                action="call_tool", tool_id=tool, tool_args=arguments
            )
        return OrchestratorStep(action="respond", content=summarize(result))

    def handler(check):
        def evaluate(phase, step):
            if phase == "write":
                return (
                    step.tool_id == tool
                    and step.tool_args == arguments
                    and check(phase, None)
                )
            return (
                result is not None
                and step.content == summarize(result)
                and check(phase, result)
            )

        return evaluate

    tools, skills = build_default_registries()
    orchestrator = EduAgentOrchestrator(
        tool_registry=tools,
        skill_registry=skills,
        gates=GateRunner({name: handler(check) for name, check in gates.items()}),
    )
    run = orchestrator.run(
        ctx=ToolContext(
            actor_role=role, actor_id=owner, thread_id=thread_id, extras={tool: command}
        ),
        message=message,
        attachments=attachments,
        planner=planner,
    )
    if failure is not None:
        raise failure
    if run.status != "completed":
        raise RuntimeError("selected skill did not pass its execution gates")
    return result


def adult_reply(
    *,
    role,
    owner,
    thread_id,
    message,
    attachments,
    skill,
    invoke,
    choice=None,
    previous=None,
):
    """Courseware generation starts when the adult opens its editor from the turn."""
    from app.application.agent.role_policy import ADULT_ROLES

    if role not in ADULT_ROLES:
        raise ValueError("adult identity required")
    if skill == "edu.homework_tutoring":
        return execute_selected_skill(
            role=role,
            owner=owner,
            thread_id=thread_id,
            message=message,
            attachments=attachments,
            skill=skill,
            tool="tutoring.run_homework_turn",
            arguments={"content": message},
            invoke=invoke,
            gates={
                "tutoring.answer_protection": lambda phase, reply: (
                    phase == "write" or bool(reply.get("content"))
                )
            },
            summarize=lambda reply: reply["content"],
        )
    action_text = "打开课件编辑器，生成并核验这份交互课件。"
    is_courseware = skill == "edu.interactive_courseware"
    if not is_courseware and skill != "general":
        raise ValueError("unsupported adult reply skill")
    reply = None

    def planner(state):
        nonlocal reply
        if is_courseware and not state["active_skill"]:
            return OrchestratorStep(action="load_skill", skill_id=skill)
        if skill == "general" and choice is not None:
            from app.application.workflows.education_workspace import choose_skill

            results = state["tool_results"]
            step = (
                choose_skill(
                    content=message,
                    keys=attachments,
                    previous=previous,
                    role=role,
                    tool_results=results,
                )
                if results
                else choice
            )
            if step.skill == "general" and step.search and len(results) < 2:
                return OrchestratorStep(
                    action="call_tool",
                    tool_id="web.search",
                    tool_args={**step.search.model_dump(), "mode": "web"},
                )
            if (
                step.skill == "general"
                and step.answer
                and not step.search
                and not attachments
            ):
                reply = {"content": step.answer, "act": "answer"}
                return OrchestratorStep(action="respond", content=step.answer)
        reply = (
            {"content": action_text, "recommend_courseware": True}
            if is_courseware
            else invoke()
        )
        return OrchestratorStep(action="respond", content=reply["content"])

    def editor_link_only(phase, candidate):
        return (
            phase == "respond"
            and candidate.content == action_text
            and candidate.artifact_id is None
        )

    tools, skills = build_default_registries()
    agent = EduAgentOrchestrator(
        tool_registry=tools,
        skill_registry=skills,
        gates=GateRunner(
            {
                "artifact.verification_honesty": editor_link_only,
                "media.script_sandbox_prerun": editor_link_only,
            }
        ),
    )
    run = agent.run(
        ctx=ToolContext(actor_role=role, actor_id=owner, thread_id=thread_id),
        message=message,
        attachments=attachments,
        planner=planner,
    )
    if run.status != "completed" or reply is None:
        raise RuntimeError("adult reply did not pass its execution gates")
    return reply


def run_adult_composite_turn(
    *,
    role,
    owner,
    thread_id,
    message,
    attachments,
    previous,
    invoke_domain,
    skill_hint=None,
    initial_choice=None,
    max_skills: int = MAX_SKILLS_PER_TURN,
) -> CompositeTurnOutcome:
    """Two-tier bounded composite loop: LLM chooses next skill or finish; code enforces ceilings."""
    from app.application.agent.role_policy import ADULT_ROLES
    from app.application.commands.workspace_documents import honest
    from app.application.workflows import education_workspace as ws

    if role not in ADULT_ROLES:
        raise ValueError("adult identity required")

    documents: list[Any] = []
    completed_steps: list[dict[str, Any]] = []
    executed_skills: list[str] = []
    recommend_courseware = False
    courseware_prompt: str | None = None
    domain_reply: dict[str, Any] | None = None
    summary_content: str | None = None
    partial_failure_note: str | None = None
    first_failure: Exception | None = None
    pending_choice = initial_choice
    search_count = 0

    def _effective_action(choice):
        if choice.action is not None:
            return choice.action
        if completed_steps:
            # Legacy planner schema without `action` cannot signal finish; stop after 1 skill.
            return "finish"
        if choice.skill == "general":
            if choice.search and search_count < 2:
                return "call_read_tool"
            if choice.answer and not attachments:
                return "finish"
            return "general_reply"
        return "run_skill"

    def _default_summary() -> str:
        parts: list[str] = []
        if documents:
            titles = "、".join(doc.title for doc in documents)
            parts.append(f"已为你生成：{titles}。")
        if recommend_courseware:
            parts.append(_COURSEWARE_ACTION_TEXT)
        if partial_failure_note:
            parts.append(partial_failure_note)
        return "\n".join(parts) if parts else _COURSEWARE_ACTION_TEXT

    def _respond():
        nonlocal summary_content
        if recommend_courseware:
            # This path prepares an editor handoff, not a generated asset.
            # Keep the delivery description code-owned before the final gate.
            summary_content = _default_summary()
        return OrchestratorStep(action="respond", content=summary_content)

    def _merged_previous() -> dict[str, Any]:
        merged = dict(previous or {})
        if completed_steps:
            merged["completed_steps"] = list(completed_steps)
        return merged

    def _artifact_command(args, _context):
        nonlocal first_failure, partial_failure_note
        target_skill = args["skill_id"]
        sub_goal = args.get("sub_goal") or message
        try:
            doc = ws.build_document(
                owner=owner,
                content=sub_goal,
                keys=attachments,
                skill=target_skill,
                previous=_merged_previous(),
            )
            if not honest("write", doc):
                raise HTTPException(422, "无法交付尚未核验的产物")
        except Exception as exc:
            if completed_steps:
                partial_failure_note = "已完成前置产物，后续步骤暂不可用，可稍后重试。"
                return {"completed": False, "partial_failure": True}
            first_failure = exc
            raise
        documents.append(doc)
        executed_skills.append(target_skill)
        summary = ws.summarize_document(doc)
        completed_steps.append(
            {
                "step": len(completed_steps) + 1,
                "skill_id": target_skill,
                "status": "completed",
                "summary": summary,
            }
        )
        return {"completed": True, "summary": summary}

    def _tutoring_command(_args, _context):
        nonlocal domain_reply, first_failure
        try:
            domain_reply = invoke_domain()
        except Exception as exc:
            first_failure = exc
            raise
        executed_skills.append("edu.homework_tutoring")
        completed_steps.append(
            {
                "step": len(completed_steps) + 1,
                "skill_id": "edu.homework_tutoring",
                "status": "completed",
            }
        )
        return {"completed": True}

    def planner(state):
        nonlocal pending_choice, search_count, recommend_courseware, courseware_prompt
        nonlocal domain_reply, summary_content, partial_failure_note, first_failure

        if partial_failure_note is not None:
            summary_content = _default_summary()
            return _respond()

        if "edu.homework_tutoring" in executed_skills and domain_reply is not None:
            summary_content = domain_reply["content"]
            return _respond()

        if skill_hint:
            if completed_steps:
                summary_content = (
                    domain_reply["content"]
                    if domain_reply is not None
                    else (documents[0].title if len(documents) == 1 and not recommend_courseware else _default_summary())
                )
                return _respond()
            target = skill_hint
            sub_goal = message
            action = "run_skill"
        else:
            if pending_choice is None:
                if len(executed_skills) >= max_skills:
                    summary_content = _default_summary()
                    return _respond()
                planner_kwargs: dict[str, Any] = {
                    "content": message,
                    "keys": attachments,
                    "previous": previous,
                    "role": role,
                    "tool_results": state["tool_results"] if not completed_steps else None,
                }
                if completed_steps:
                    planner_kwargs["completed_steps"] = list(completed_steps)
                    planner_kwargs["remaining_skill_budget"] = max_skills - len(executed_skills)
                pending_choice = ws.choose_skill(**planner_kwargs)

            action = _effective_action(pending_choice)
            target = pending_choice.skill
            sub_goal = pending_choice.sub_goal or message

            if action == "finish":
                if pending_choice.answer:
                    summary_content = pending_choice.answer
                    if not documents and not recommend_courseware and domain_reply is None:
                        domain_reply = {"content": pending_choice.answer, "act": "answer"}
                else:
                    summary_content = (
                        documents[0].title
                        if len(documents) == 1 and not recommend_courseware
                        else _default_summary()
                    )
                return _respond()

            if action == "call_read_tool" and pending_choice.search and search_count < 2:
                search_args = {**pending_choice.search.model_dump(), "mode": "web"}
                search_count += 1
                pending_choice = None
                return OrchestratorStep(
                    action="call_tool",
                    tool_id="web.search",
                    tool_args=search_args,
                )

            if action == "general_reply" or target == "general":
                if not completed_steps:
                    domain_reply = invoke_domain()
                    summary_content = domain_reply["content"]
                else:
                    summary_content = _default_summary()
                return _respond()

        # action == "run_skill": code-enforced deduplication & preconditions.
        if target in executed_skills or len(executed_skills) >= max_skills:
            summary_content = _default_summary()
            return _respond()

        if target == "edu.worksheet_grading" and not attachments:
            if completed_steps:
                partial_failure_note = "批改作业需要上传作业照片，已先交付其他已完成内容。"
                summary_content = _default_summary()
                return _respond()
            first_failure = HTTPException(422, "请按顺序上传需要批改的作业页")
            raise first_failure

        active_id = state["active_skill"]["id"] if state["active_skill"] else None
        if active_id != target:
            return OrchestratorStep(action="load_skill", skill_id=target)

        # Target skill is now loaded: consume pending_choice and execute.
        pending_choice = None

        if target in {"edu.worksheet_grading", "edu.lesson_pack"}:
            kind = "lesson_pack" if target == "edu.lesson_pack" else "grading_report"
            return OrchestratorStep(
                action="call_tool",
                tool_id="artifact.create_or_revise",
                tool_args={
                    "artifact_type": kind,
                    "skill_id": target,
                    "sub_goal": sub_goal,
                },
            )

        if target == "edu.interactive_courseware":
            recommend_courseware = True
            courseware_prompt = sub_goal
            executed_skills.append(target)
            completed_steps.append(
                {
                    "step": len(completed_steps) + 1,
                    "skill_id": target,
                    "status": "ready_to_generate",
                    "summary": {
                        "kind": "interactive_courseware",
                        "recommended": True,
                        "generation_status": "not_started",
                        "prompt": sub_goal[:240],
                    },
                }
            )
            if skill_hint or len(executed_skills) >= max_skills:
                summary_content = _default_summary()
                return _respond()
            # Ask planner in the next step whether additional skills remain or to finish.
            pending_choice = ws.choose_skill(
                content=message,
                keys=attachments,
                previous=previous,
                role=role,
                completed_steps=list(completed_steps),
                remaining_skill_budget=max_skills - len(executed_skills),
            )
            if _effective_action(pending_choice) == "finish":
                summary_content = pending_choice.answer or _default_summary()
                return _respond()
            next_target = pending_choice.skill
            if next_target in executed_skills or next_target == "general":
                summary_content = _default_summary()
                return _respond()
            return OrchestratorStep(action="load_skill", skill_id=next_target)

        if target == "edu.homework_tutoring":
            return OrchestratorStep(
                action="call_tool",
                tool_id="tutoring.run_homework_turn",
                tool_args={"content": sub_goal},
            )

        summary_content = _default_summary()
        return _respond()

    def _honesty_gate(phase, candidate):
        if phase == "write":
            return True
        if documents:
            return all(honest("respond", doc) for doc in documents)
        if recommend_courseware:
            return candidate.artifact_id is None
        return False

    def _courseware_gate(phase, candidate):
        if phase == "write":
            return True
        return candidate.artifact_id is None

    def _tutoring_gate(phase, _candidate):
        if phase == "write":
            return True
        return domain_reply is not None and bool(domain_reply.get("content"))

    tools, skills = build_default_registries()
    orchestrator = EduAgentOrchestrator(
        tool_registry=tools,
        skill_registry=skills,
        max_steps=12,
        gates=GateRunner(
            {
                "artifact.verification_honesty": _honesty_gate,
                "media.script_sandbox_prerun": _courseware_gate,
                "tutoring.answer_protection": _tutoring_gate,
            }
        ),
    )
    run = orchestrator.run(
        ctx=ToolContext(
            actor_role=role,
            actor_id=owner,
            thread_id=thread_id,
            extras={
                "artifact.create_or_revise": _artifact_command,
                "tutoring.run_homework_turn": _tutoring_command,
            },
        ),
        message=message,
        attachments=attachments,
        planner=planner,
    )
    if first_failure is not None:
        raise first_failure
    if run.status != "completed":
        raise RuntimeError("adult composite turn did not pass its execution gates")
    return CompositeTurnOutcome(
        documents=tuple(documents),
        reply=domain_reply,
        recommend_courseware=recommend_courseware,
        courseware_prompt=courseware_prompt,
        summary_content=summary_content or run.content,
        completed_skills=tuple(executed_skills),
        partial_failure_note=partial_failure_note,
    )

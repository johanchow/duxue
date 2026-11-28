"""Execute a model-selected, single-command skill with a domain-owned delivery result."""

from app.application.agent.gates import GateRunner
from app.application.agent.orchestrator import EduAgentOrchestrator, OrchestratorStep
from app.application.agent.registry import ToolContext
from app.application.tools.core_tools import build_default_registries


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

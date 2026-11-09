"""Read-only management inventory derived from the runtime configuration catalog."""

from app.agent_specs.admin_bundle import _artifact_document, seed_bundle
from app.agent_specs.catalog import load_catalog

# Display metadata has no effect on execution or the release compatibility hash.
AGENT_PURPOSES = {
    "companion.intent": (
        "对话意图路由",
        "理解当前请求，提出进入计划、答疑或复盘等场景的路由候选。",
    ),
    "evaluation.review-aspects": (
        "自述维度归纳",
        "从孩子的原话中提取复盘维度和逐字依据，不把主观自述写成客观记忆。",
    ),
    "planning.intake": (
        "计划信息整理",
        "把孩子的安排表达整理成计划候选，交由领域规则和确认门禁处理。",
    ),
    "planning.session-turn": (
        "计划会话执行",
        "执行授权的单轮计划用例，负责确认恢复与受控业务写入。",
    ),
    "reflection.session-turn": (
        "复盘会话执行",
        "执行授权的复盘会话，组织自述反馈和相关领域操作。",
    ),
    "study.sprint-intake": (
        "专注挑战信息提取",
        "从自然语言提取主动限时专注挑战的候选参数。",
    ),
    "task.intake": (
        "任务信息提取",
        "从自然语言提取任务候选信息，保留领域校验与确认边界。",
    ),
    "tutoring.image-target": (
        "答疑图片定位",
        "判断本轮提问指向哪张已授权图片，帮助答疑模型获取正确题面。",
    ),
    "tutoring.session-turn": (
        "答疑会话执行",
        "组织单轮答疑、审核、重试及受控教学事实写入，固定本轮配置快照。",
    ),
    "tutoring.turn": (
        "启发式答疑",
        "结合题面与授权上下文生成分步提示、配图或发音候选，经独立门禁审核后交付。",
    ),
}


COMPONENT_PURPOSES = {
    **AGENT_PURPOSES,
    "companion.scene-switch": (
        "场景切换裁判",
        "审核跨场景切换候选，判断是否需要向孩子确认。",
    ),
    "planning.confirmation-gate": (
        "计划确认门禁",
        "在修改计划事实前检查确认条件，拒绝未经确认的写入。",
    ),
    "tutoring.authority": (
        "教学权限门禁",
        "按当前题目与教学状态裁决候选动作是否允许。",
    ),
    "tutoring.candidate_exit": (
        "答疑出口门禁",
        "校验候选是否满足本轮允许交付的出口约束。",
    ),
    "tutoring.candidate_schema": (
        "答疑结构校验",
        "校验模型答疑候选的结构化字段与协议。",
    ),
    "tutoring.leak-judge": (
        "文字答案保护裁判",
        "独立审核文字候选是否泄露受保护题目的最终答案。",
    ),
    "tutoring.output_safety": (
        "答疑输出安全门禁",
        "交付前执行既有输出安全检查，失败时使用安全兜底。",
    ),
    "tutoring.tool_budget": ("工具预算门禁", "约束本轮模型使用工具的次数与权限。"),
    "tutoring.visual-leak-judge": (
        "配图答案保护裁判",
        "独立审核配图是否泄露受保护题目的答案。",
    ),
    "tutoring.visual": ("配图交付门禁", "检查配图满足当前教学动作与交付规则。"),
    "tutoring.visual_schema": ("配图结构校验", "检查模型生成配图的结构化协议。"),
    "tutoring.get_task_context": (
        "任务上下文工具",
        "读取当前已授权任务的上下文，不扩大数据访问范围。",
    ),
    "tutoring.get_attempt_summary": (
        "作答摘要工具",
        "读取已授权作答尝试的摘要，为启发式答疑提供依据。",
    ),
    "tutoring.lookup_history": ("答疑历史工具", "查询授权范围内的历史答疑上下文。"),
    "tutoring.widget_guidelines": (
        "配图规范工具",
        "返回只读的SVG配图规范，生成与修复使用同一正文。",
    ),
}
WORKFLOW_DESCRIPTIONS = {
    "companion": "识别对话意图，审核场景切换，并将请求路由到相应业务流程。",
    "planning": "组织计划信息整理、安排确认与受控写入，支持会话恢复。",
    "reflection": "组织孩子的原话复盘和单轮反馈，不将主观自述写入客观记忆。",
    "review-aspects": "从自述原文提取复盘维度与逐字依据。",
    "sprint-intake": "从自然语言提取主动限时专注挑战的候选参数。",
    "task-intake": "将自然语言整理为结构化任务候选。",
    "tutoring-retry": "组织主模型尝试、泄露修复、备用模型及配图的有界重试。",
    "tutoring-vet": "依次进行教学权限、文字答案保护与必要的配图答案保护审核。",
    "tutoring": "执行单轮启发答疑，串联题面定位、模型生成、审核、安全交付与教学事实写入。",
}


def management_inventory():
    catalog = load_catalog()
    workflows = {
        key: _artifact_document(spec.model_dump(mode="json", by_alias=True))
        for key, spec in catalog.specs.items()
    }
    files = {
        name: doc
        for name, doc in seed_bundle()["files"].items()
        if doc.get("kind") in {"agent", "gate", "tool"}
    }
    definitions = {definition["id"]: definition for definition in files.values()}

    components = []
    for path, definition in files.items():
        identifier = definition["id"]
        name, description = COMPONENT_PURPOSES.get(
            identifier, (identifier, "尚未补充作用简介；可查看完整配置。")
        )
        implementation = definition.get("implementation", "tool")
        component_type = (
            ("model-agent" if implementation == "llm" else "code-agent")
            if definition["kind"] == "agent"
            else ("model-judge" if implementation == "judge" else "code-gate")
            if definition["kind"] == "gate"
            else "tool"
        )
        components.append(
            {
                "id": identifier,
                "name": definition.get("display_name") or name,
                "description": definition.get("description") or description,
                "kind": definition["kind"],
                "type": component_type,
                "implementation": implementation,
                "file": path,
                "editable": True,
                "editable_fields": (
                    ["models", "prompt", "tools", "display_name", "description"]
                    if implementation in {"llm", "judge"}
                    else ["static_result", "display_name", "description"]
                    if definition.get("handler_id") == "tool.static_result"
                    else ["display_name", "description"]
                ),
                "workflows": [
                    key
                    for key, flow in workflows.items()
                    if flow["invocation_agent"] == identifier
                    or any(
                        node["ref"] == identifier
                        or identifier
                        in definitions.get(node["ref"], {}).get("tools", [])
                        for node in flow["nodes"]
                    )
                ],
            }
        )
    agents = [item for item in components if item["kind"] == "agent"]
    return {
        "components": components,
        "workflow_descriptions": {
            key: WORKFLOW_DESCRIPTIONS.get(key, "尚未补充简介。") for key in workflows
        },
        "source": "code-baseline",
        "agents": agents,
        "definitions": definitions,
        "workflows": workflows,
        "counts": {
            "agents": len(agents),
            "components": len(components),
            "model_agents": sum(a["implementation"] == "llm" for a in agents),
            "code_agents": sum(a["implementation"] == "code" for a in agents),
            "gates": sum(d["kind"] == "gate" for d in definitions.values()),
            "tools": sum(d["kind"] == "tool" for d in definitions.values()),
            "workflows": len(workflows),
        },
    }

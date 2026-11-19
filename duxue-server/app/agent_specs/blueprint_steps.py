"""Reviewed topology and configuration migration for staged problem solving."""

from __future__ import annotations

from copy import deepcopy

from app.agent_specs.gaokao_contracts import (
    INSPECT_IMAGE_TOOL_ID,
    PLANNER_ID,
    SCIENCE_TOOL_ID,
    WORKFLOW_ID,
    frozen_contracts,
)

EXTRACT = "tutoring.stem-extract"
REREAD = "tutoring.stem-review"
BACKUP = "tutoring.blueprint-backup"
ROUTE = "tutoring.select-route"
REREAD_CHECK = "tutoring.reread-check"
VERIFY = "tutoring.verify-route"
VERIFY_BACKUP = "tutoring.verify-backup"
VERIFY_T2 = "tutoring.verify-t2"
FINISH = "tutoring.finish-solution"
FLOW_FILE = f"workflows/{WORKFLOW_ID}.json"

SOLVER_TOOLS = (SCIENCE_TOOL_ID, INSPECT_IMAGE_TOOL_ID)
VISION_TOOLS = (INSPECT_IMAGE_TOOL_ID,)

NODES = [
    ("extract", "agent", EXTRACT),
    ("select", "gate", ROUTE),
    ("reread", "agent", REREAD),
    ("reread_check", "gate", REREAD_CHECK),
    ("ordinary", "agent", PLANNER_ID),
    ("verify", "gate", VERIFY),
    ("backup", "agent", BACKUP),
    ("verify_backup", "gate", VERIFY_BACKUP),
    ("primary", "agent", PLANNER_ID),
    ("alternative", "agent", BACKUP),
    ("verify_t2", "gate", VERIFY_T2),
    ("finish", "action", FINISH),
]
TITLES = dict(
    extract="首次读题与分级",
    select="题库缓存与路径路由",
    reread="按需独立复读题面",
    reread_check="关键条件一致性核对",
    ordinary="普通题主求解",
    verify="确定性引擎核验(T1)",
    backup="异构备用求解",
    verify_backup="确定性引擎核验(备用)",
    primary="复杂题主路线(并发)",
    alternative="复杂题异构路线(并发)",
    verify_t2="确定性引擎核验与双路比对",
    finish="汇总核验与置信度定级",
)
EDGES = [
    ("START", "extract", None),
    ("extract", "select", None),
    ("select", "finish", "complete"),
    ("select", "reread", "reread"),
    ("select", "ordinary", "ordinary"),
    ("select", "primary", "complex"),
    ("select", "alternative", "complex"),
    ("reread", "reread_check", None),
    ("reread_check", "finish", "disputed"),
    ("reread_check", "select", "resume_select"),
    ("reread_check", "backup", "backup"),
    ("ordinary", "verify", None),
    ("verify", "finish", "verified"),
    ("verify", "finish", "not_applicable"),
    ("verify", "finish", "unknown"),
    ("verify", "reread", "reread"),
    ("verify", "backup", "backup"),
    ("backup", "verify_backup", None),
    ("verify_backup", "finish", None),
    ("primary", "verify_t2", None),
    ("alternative", "verify_t2", None),
    ("verify_t2", "finish", None),
    ("finish", "END", None),
]
CONDITIONS = frozenset(
    {
        "complete",
        "reread",
        "ordinary",
        "complex",
        "disputed",
        "resume_select",
        "backup",
        "verified",
        "not_applicable",
        "unknown",
    }
)


def node_id(key):
    return key if key in {"START", "END"} else f"{WORKFLOW_ID}.{key}"


def workflow():
    return dict(
        kind="workflow",
        id=WORKFLOW_ID,
        handler=WORKFLOW_ID,
        entry=node_id("extract"),
        nodes=[
            {
                "id": node_id(key),
                "kind": kind,
                "display_name": TITLES[key],
                ("handler_id" if kind == "action" else "ref"): ref,
            }
            for key, kind, ref in NODES
        ],
        edges=[
            {
                "from": node_id(src),
                "to": node_id(dst),
                **({"condition_id": condition} if condition else {}),
            }
            for src, dst, condition in EDGES
        ],
    )


def contracts():
    result = {}
    base_planner = frozen_contracts()[f"agents/{PLANNER_ID}.json"]

    extract_doc = deepcopy(base_planner)
    extract_doc.update(
        id=EXTRACT,
        operation=EXTRACT,
        input_contract=EXTRACT + ".input.v1",
        output_contract=EXTRACT + ".output.v1",
        context_builder_id=EXTRACT.replace("-", "_") + ".context",
        prompt={"id": EXTRACT + ".prompt"},
        models=[{"component_id": EXTRACT}],
        output_schema={
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "shared_stem_summary": {"type": "string"},
                "tier": {"enum": ["T0", "T1", "T2"]},
                "needs_student_confirmation": {"type": "boolean"},
            },
            "required": [
                "subject",
                "shared_stem_summary",
                "tier",
                "needs_student_confirmation",
            ],
        },
    )
    result[f"agents/{EXTRACT}.json"] = extract_doc

    reread_doc = deepcopy(base_planner)
    reread_doc.update(
        id=REREAD,
        operation=REREAD,
        input_contract=REREAD + ".input.v1",
        output_contract=REREAD + ".output.v1",
        context_builder_id=REREAD.replace("-", "_") + ".context",
        prompt={"id": REREAD + ".prompt"},
        models=[{"component_id": REREAD}],
        output_schema={
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "shared_stem_summary": {"type": "string"},
                "needs_student_confirmation": {"type": "boolean"},
            },
            "required": [
                "subject",
                "shared_stem_summary",
                "needs_student_confirmation",
            ],
        },
    )
    result[f"agents/{REREAD}.json"] = reread_doc

    backup_doc = deepcopy(base_planner)
    backup_doc.update(
        id=BACKUP,
        operation=BACKUP,
        input_contract=BACKUP + ".input.v1",
        output_contract=BACKUP + ".output.v1",
        context_builder_id=BACKUP.replace("-", "_") + ".context",
        prompt={"id": BACKUP + ".prompt"},
        models=[{"component_id": BACKUP}],
    )
    result[f"agents/{BACKUP}.json"] = backup_doc

    for uid in (ROUTE, REREAD_CHECK, VERIFY, VERIFY_BACKUP, VERIFY_T2):
        result[f"gates/{uid}.json"] = dict(
            id=uid,
            kind="gate",
            implementation="code",
            handler_id=uid,
            input_schema={"type": "object"},
            verdict_schema={"type": "object"},
            on_error="abort",
            safety_class="standard",
        )
    return result


def upgrade_files(files):
    docs = contracts()
    planner = files[f"agents/{PLANNER_ID}.json"]
    primary_model = deepcopy(planner["models"][0])
    alt_model = deepcopy(planner["models"][1] if len(planner["models"]) > 1 else planner["models"][0])

    # Enable science + inspect_image tools on primary planner
    planner["tools"] = list(SOLVER_TOOLS)

    extract_doc = docs[f"agents/{EXTRACT}.json"]
    extract_doc["display_name"] = TITLES["extract"]
    extract_doc["tools"] = list(VISION_TOOLS)
    extract_doc["models"] = [
        {**primary_model, "component_id": EXTRACT, "enable_thinking": False}
    ]
    extract_doc["models"][0].pop("thinking_budget", None)
    extract_doc["prompt"]["template"] = (
        "首次读题与分级。从原题与图片逐项转写，不解题；若局部角标或数字看不清可先调用 inspect_image 局部放大。"
        "仅输出 JSON 对象，包含 subject、shared_stem_summary（题面、条件、数值与全部设问）、subproblems、"
        "diagram_summary、needs_student_confirmation（仅在模糊/涂改/缺条件时为 true，清晰题面为 false）、"
        "tier（T0 概念事实、T1 普通题、T2 复杂解答/高考压轴需双路异构核验）。"
    )

    reread_doc = docs[f"agents/{REREAD}.json"]
    reread_doc["display_name"] = TITLES["reread"]
    reread_doc["tools"] = list(VISION_TOOLS)
    reread_doc["models"] = [
        {**alt_model, "component_id": REREAD, "enable_thinking": False}
    ]
    reread_doc["models"][0].pop("thinking_budget", None)
    reread_doc["prompt"]["template"] = (
        "按需独立复读题面。独立核对原图中的关键数值、符号、角标与全部设问，不解题、不猜测模糊字符。"
        "仅输出 JSON 对象，包含 subject、shared_stem_summary（关键数值、符号与全部设问）、subproblems、"
        "needs_student_confirmation（若存在看不清或涂改则为 true）。"
    )

    backup_doc = docs[f"agents/{BACKUP}.json"]
    backup_doc["display_name"] = TITLES["backup"]
    backup_doc["tools"] = list(SOLVER_TOOLS)
    backup_model = {
        **alt_model,
        "component_id": BACKUP,
        "max_output_tokens": max(int(alt_model.get("max_output_tokens") or 4096), 4096),
        "timeout_ms": max(int(alt_model.get("timeout_ms") or 45000), 45000),
        "enable_thinking": bool(primary_model.get("enable_thinking", True)),
    }
    if backup_model["enable_thinking"]:
        backup_model["thinking_budget"] = int(primary_model.get("thinking_budget") or 4096)
    else:
        backup_model.pop("thinking_budget", None)
    backup_doc["models"] = [backup_model]
    backup_doc["prompt"]["template"] = (
        planner["prompt"]["template"]
        + "\n若输入包含 contradiction_feedback（确定性引擎打回原因/反例），必须针对该反例重新推导并修正；"
        "若 route_hint=\"T2_alternative\"，请采用与常规代数法不同的独立替代解法路线并给出可核验锚点。"
    )

    for uid, key in (
        (ROUTE, "select"),
        (REREAD_CHECK, "reread_check"),
        (VERIFY, "verify"),
        (VERIFY_BACKUP, "verify_backup"),
        (VERIFY_T2, "verify_t2"),
    ):
        docs[f"gates/{uid}.json"]["display_name"] = TITLES[key]

    files.update(docs)
    files[FLOW_FILE] = workflow()

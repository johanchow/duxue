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

SOLVER_MAX_OUTPUT_TOKENS = 16384
SOLVER_THINKING_BUDGET = 2560

_LEGACY_SOLVER_DISCIPLINE_MARKER = "[solver-discipline.v1]"
SOLVER_DISCIPLINE_RULES = (
    "\n[solver-discipline.v2] 审题与作答铁律：\n"
    "1. 单选题唯选与方向反推：单选题必须且只能给出唯一最优选项，严禁同时选出两个或多个选项（如 AB、BC）；若初步推导出 ≥2 个选项成立，必须立刻判定至少有一个前置方向性规律用反了（如波的折射弯曲方向、光路可逆性、左手/右手定则、楞次定律方向），强制重核方向性规律并排除干扰项，只选唯一 1 项。\n"
    "2. 禁止轻率判无解：严禁轻易输出「无正确选项」「题目有误」；若初步推导四项均不符，必须将其视为读图、方向、正负号或隐含条件出错的强信号，强制重审原图坐标轴、箭头方向、回路连接与题干条件后再下结论。\n"
    "3. 整页题界隔离：若图片包含多道题，仅转写与解答用户明确指定的目标题号，严禁混入或顺带解答同页其他邻题。\n"
    "4. 实验精密读图与截断重裁：遇到螺旋测微器、游标卡尺、电表表盘、纸带点迹、电路图、光路图、坐标曲线等精细读图时，必须先调用 inspect_image（返回 {\"tool_request\": {\"name\": \"inspect_image\", \"args\": {\"image_ref\": \"img_...\", \"bbox\": {\"x0\": 0.1, \"y0\": 0.2, \"x1\": 0.6, \"y1\": 0.7}, \"label\": \"...\"}}}，bbox 为 [0.0, 1.0] 归一化坐标）局部放大后再读数；若收到切片后发现主尺零刻度、下方距离标注、端点或接线柱被裁掉，严禁盲猜，必须立刻扩大 bbox 再次调用 inspect_image 重新放大；纸带题必须先显式写出从左到右相邻计数点间距的变化趋势（增大或减小），再结合加速/减速运动判断纸带哪一端连接小车。\n"
    "5. 理科算中核验：涉及积分、求导、对数符号、方程求解、数值化简、量纲或配平核验时，先调用 science 工具（返回 {\"tool_request\": {\"name\": \"science\", \"args\": {\"op\": \"...\", ...}}}）核验后再输出最终 JSON。"
)

TOOL_TURN_GUIDANCE = (
    "\n[blueprint-tool-turn.v1] 按当前回合选择 JSON 格式。需要从图上读刻度、端点标注或接线时，"
    "若尚无该区域的切片，本回合只返回一个 tool_request，立即结束并等待下一回合。"
    "从 image_manifest 复制目标题页的 image_ref，按原图位置框选具体区域（框选宁大勿小，完整包住主尺与标注）。"
    "收到 tool_observations 和局部图后，若发现主尺零刻度、距离标注端点或接线柱被裁掉，严禁盲猜，立刻扩大 bbox 再调用一次 inspect_image；"
    "看清后按图分别记录主尺与副尺、距离标注的两个端点或实际接线，再给最终 JSON。"
    "最终字段（如 subject）仅在作答回合填写。若 tool_budget_exhausted 为 true，使用已有证据完成作答。"
)

VISION_INSPECT_GUIDANCE = (
    "若图片包含多道题，只转写用户明确指定的目标题号，严禁混入邻题。"
    "若图片中包含螺旋测微器、游标卡尺、电表刻度、纸带点迹、电路元件连接、坐标曲线或模糊小字/角标，"
    "请先调用 inspect_image 局部放大（返回 {\"tool_request\": {\"name\": \"inspect_image\", \"args\": {\"image_ref\": \"img_...\", \"bbox\": {\"x0\": 0.1, \"y0\": 0.2, \"x1\": 0.6, \"y1\": 0.7}, \"label\": \"...\"}}}）看清后再转写；若切片裁掉了主尺零刻度或距离标注，必须扩大 bbox 再裁一次。"
)

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

    # Enable science + inspect_image tools and ensure output budget exceeds thinking budget
    planner["tools"] = list(SOLVER_TOOLS)
    for m in planner["models"]:
        m["max_output_tokens"] = max(int(m.get("max_output_tokens") or 0), SOLVER_MAX_OUTPUT_TOKENS)
        if m.get("enable_thinking"):
            m["thinking_budget"] = min(int(m.get("thinking_budget") or SOLVER_THINKING_BUDGET), SOLVER_THINKING_BUDGET)
    tpl = planner["prompt"]["template"]
    for marker in (_LEGACY_SOLVER_DISCIPLINE_MARKER, "[solver-discipline.v2]", "[blueprint-tool-turn.v1]"):
        if marker in tpl:
            tpl = tpl.split(marker, 1)[0]
    planner["prompt"]["template"] = tpl.rstrip() + SOLVER_DISCIPLINE_RULES + TOOL_TURN_GUIDANCE

    primary_model = deepcopy(planner["models"][0])
    alt_model = deepcopy(planner["models"][1] if len(planner["models"]) > 1 else planner["models"][0])

    extract_doc = docs[f"agents/{EXTRACT}.json"]
    extract_doc["display_name"] = TITLES["extract"]
    extract_doc["tools"] = list(VISION_TOOLS)
    extract_doc["models"] = [
        {**primary_model, "component_id": EXTRACT, "enable_thinking": False}
    ]
    extract_doc["models"][0].pop("thinking_budget", None)
    extract_doc["prompt"]["template"] = (
        "首次读题与分级。从原题与图片逐项转写，不解题；"
        + VISION_INSPECT_GUIDANCE
        + "仅输出 JSON 对象，包含 subject、shared_stem_summary（题面、条件、数值与全部设问）、subproblems、"
        "diagram_summary、needs_student_confirmation（仅在模糊/涂改/缺条件时为 true，清晰题面为 false）、"
        "tier（T0 概念事实、T1 普通题、T2 复杂解答/高考压轴需双路异构核验）。"
        + TOOL_TURN_GUIDANCE
    )

    reread_doc = docs[f"agents/{REREAD}.json"]
    reread_doc["display_name"] = TITLES["reread"]
    reread_doc["tools"] = list(VISION_TOOLS)
    reread_doc["models"] = [
        {**alt_model, "component_id": REREAD, "enable_thinking": False}
    ]
    reread_doc["models"][0].pop("thinking_budget", None)
    reread_doc["prompt"]["template"] = (
        "按需独立复读题面。独立核对原图中的关键数值、符号、角标与全部设问，不解题、不猜测模糊字符；"
        + VISION_INSPECT_GUIDANCE
        + "仅输出 JSON 对象，包含 subject、shared_stem_summary（关键数值、符号与全部设问）、subproblems、"
        "needs_student_confirmation（若存在看不清或涂改则为 true）。"
        + TOOL_TURN_GUIDANCE
    )

    backup_doc = docs[f"agents/{BACKUP}.json"]
    backup_doc["display_name"] = TITLES["backup"]
    backup_doc["tools"] = list(SOLVER_TOOLS)
    backup_model = {
        **alt_model,
        "component_id": BACKUP,
        "max_output_tokens": max(int(alt_model.get("max_output_tokens") or 0), SOLVER_MAX_OUTPUT_TOKENS),
        "timeout_ms": max(int(alt_model.get("timeout_ms") or 45000), 45000),
        "enable_thinking": bool(primary_model.get("enable_thinking", True)),
    }
    if backup_model["enable_thinking"]:
        backup_model["thinking_budget"] = min(
            int(primary_model.get("thinking_budget") or SOLVER_THINKING_BUDGET),
            SOLVER_THINKING_BUDGET,
        )
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

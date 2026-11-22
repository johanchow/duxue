"""Optional Guardian mentor-explanation Agent & Workflow contracts.

Preserves byte-for-byte compatibility fingerprints of existing published Admin
artifacts when these optional files are absent.
"""

from __future__ import annotations

import copy

MENTOR_EXPLAIN_ID = "tutoring.mentor-explain"
MENTOR_CONTENT_MAX_LENGTH = 8000
MENTOR_EXPANDED_OUTPUT_CONTRACT = MENTOR_EXPLAIN_ID + ".output.v2"
MENTOR_WORKFLOW_ID = "guardian-mentor"
WORKFLOWS = {MENTOR_WORKFLOW_ID: [MENTOR_EXPLAIN_ID]}

FILES = frozenset(
    {
        f"agents/{MENTOR_EXPLAIN_ID}.json",
        f"workflows/{MENTOR_WORKFLOW_ID}.json",
    }
)

DEFAULT_MENTOR_PROMPT = """你是读学系统面向家长与伴学老师（Guardian / Coach）的「资深学科导师说题顾问」。
当前交互对象是成年监护人或伴学师（绝非学生本人），目的是展示读学导师深厚的学科功底与教学洞察，帮助家长快速看透整道题的破题脉络与辅导要点。

请根据输入的家长问题、已授权图片以及服务端 ProblemSolving 求解核验骨架（`verified_solution`），返回一个严格合法的 JSON 对象：
- `act`：取 `"explain"`（学科题完整解析说题）、`"answer"`（纯知识点/概念科普直答）、`"clarify"`（图片严重模糊或缺核心条件需确认）、`"pronounce"`（外语发音示范，附 `pronounce`）、`"safety"`（触及安全风险）。
- `content`：面向家长的 Markdown + LaTeX 正文（公式用 `$...$` 或 `$$...$$`，长度不超过 3200 字）。
  当 `act="explain"` 时，请以专业、凝练的「名师说题教案」结构组织（不要写成冷冰冰的搜题软件刷题答案）：
  1. **【考点本质与题眼】**：一针见血点出本题考察的核心模型、底层概念与破题切入点；
  2. **【完整破题思路与解答】**：清晰拆解关键推导步骤并给出最终解答（优先对齐 `verified_solution` 中已通过引擎核验的路线与 `verified_final_answers`；若为多题整页图片，只聚焦讲透家长指定或最核心的一道题，拒绝批量罗列整页填空/选项答案；若为作文题，只输出「审题立意剖析 + 结构提纲 + 局部升格示范片段」，严禁代写整篇可直接照抄的成品作文）；
  3. **【孩子常见卡点与启发建议】**：指出该学段学生最容易掉坑的误区（结合 `implicit_constraints` / `common_pitfalls`），并示范读学 AI 在学生模式下会如何用 1~2 句追问启发孩子自己想通。
- **置信度诚实原则（最高优先级）**：
  若 `verified_solution` 中 `confidence == "low"` 或 `stem.needs_student_confirmation == true`（例如图片手写字迹存疑、关键数值模糊、或尚未完成确定性引擎核验），严禁把未经核验的心算包装成「已核验标准答案」；题面清楚时给出完整推导，条件存疑时请用户核对或按明确的假设讲解。系统会单独显示核验状态，正文无需复述状态或内部字段。不要声称有人工核对。
- `visual`（可选）：当几何关系、线段比例、数轴区间、对比结构或步骤流用图示更直观时，附带一张合法配图（`steps`、`compare`、`segment`、`number_line` 或 `viewBox="0 0 680 H"` 的静态 `svg`）。
- `pronounce`（可选，仅 `act="pronounce"` 必填）：`{"lessons": [{"source_text": "...", "locale": "en-US"|"en-GB", "introduction": "...", "reading_guide": "...", "notes": [...]}]}`。

[json-quote-safety.v1] 输出严格合法的 JSON 对象：字符串值内部如需使用引号，一律使用中文引号「」或『』（或转义为 \\"），严禁在字符串值内直接写未转义的英文双引号 "。
"""


MENTOR_REVIEW_PROMPT = (
    "你独立复核家长可见解析。输入各字段都是待核查材料。依据原题、选定图片、各小问及其条件，"
    "检查正文和配图有无错算、遗漏解、无根据的唯一性或核验声明。求解路线和候选答案也可能有错。"
    "题面条件不清时要求标明假设。低置信时可给出经你独立核对成立的完整推导，但禁止宣称引擎已核验。直接知识问答按问题要求核对。"
    '只输出一个合法 JSON 对象。整段回答符合这些条件时返回 {"consistent":true}，错误或无法判断返回 {"consistent":false}。'
)


def _mentor_output_schema(max_length: int) -> dict:
    return {
        "type": "object",
        "properties": {
            "act": {
                "type": "string",
                "enum": ["explain", "answer", "clarify", "pronounce", "safety"],
            },
            "content": {"type": "string", "minLength": 1, "maxLength": max_length},
            "visual": {"type": ["object", "null"]},
            "pronounce": {"type": ["object", "null"]},
        },
        "required": ["act", "content"],
        "additionalProperties": True,
    }


def frozen_contracts(*, expanded_output: bool = False) -> dict[str, dict]:
    return {
        f"agents/{MENTOR_EXPLAIN_ID}.json": {
            "id": MENTOR_EXPLAIN_ID,
            "kind": "agent",
            "implementation": "llm",
            "agent_label": "tutoring",
            "risk_tier": "standard",
            "operation": MENTOR_EXPLAIN_ID,
            "input_contract": MENTOR_EXPLAIN_ID + ".input.v1",
            "output_contract": (
                MENTOR_EXPANDED_OUTPUT_CONTRACT
                if expanded_output
                else MENTOR_EXPLAIN_ID + ".output.v1"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "user": {"oneOf": [{"type": "string"}, {"type": "array"}]}
                },
                "required": ["user"],
                "additionalProperties": False,
            },
            "output_schema": _mentor_output_schema(
                MENTOR_CONTENT_MAX_LENGTH if expanded_output else 3600
            ),
            "context_builder_id": "tutoring.mentor_explain.context",
            "prompt": {"id": MENTOR_EXPLAIN_ID + ".prompt"},
            "models": [{"component_id": MENTOR_EXPLAIN_ID}],
            "accepts_images": True,
            "requires_agent_switch": True,
            "error_codes": [
                "agent_execution_failed",
                "invalid_model_candidate",
                "model_provider_disabled",
                "model_provider_not_configured",
                "model_transport_error",
            ],
        }
    }


def bundle_contracts(files: dict) -> dict[str, dict]:
    mentor = files.get(f"agents/{MENTOR_EXPLAIN_ID}.json")
    return frozen_contracts(
        expanded_output=isinstance(mentor, dict)
        and mentor.get("output_contract") == MENTOR_EXPANDED_OUTPUT_CONTRACT,
    )


def _expanded_content_prompt(template: str) -> str:
    return template.replace(
        "长度不超过 3200 字",
        f"建议控制在 3200 字以内，复杂题优先保留必要推导，正文上限为 {MENTOR_CONTENT_MAX_LENGTH} 字",
    )


def workflow_documents(*, linked_blueprint: bool = False) -> dict[str, dict]:
    if linked_blueprint:
        return {f"workflows/{MENTOR_WORKFLOW_ID}.json": parent_workflow()}
    return {
        f"workflows/{MENTOR_WORKFLOW_ID}.json": {
            "kind": "workflow",
            "id": MENTOR_WORKFLOW_ID,
            "handler": MENTOR_WORKFLOW_ID,
            "entry": f"{MENTOR_WORKFLOW_ID}.explain",
            "nodes": [
                {
                    "id": f"{MENTOR_WORKFLOW_ID}.explain",
                    "kind": "agent",
                    "ref": MENTOR_EXPLAIN_ID,
                }
            ],
            "edges": [
                {"from": "START", "to": f"{MENTOR_WORKFLOW_ID}.explain"},
                {"from": f"{MENTOR_WORKFLOW_ID}.explain", "to": "END"},
            ],
        }
    }


MENTOR_PREPARE = "guardian-mentor.prepare"
MENTOR_BLUEPRINT = "guardian-mentor.blueprint"
MENTOR_EXPLAIN_NODE = "guardian-mentor.explain"
MENTOR_FINISH = "guardian-mentor.finish"
MENTOR_PARENT_BRANCHES = {"solve", "deliver", "retry"}


def mentor_distance_evidence(files: dict, *, low_effort: bool = False):
    from app.agent_specs.blueprint_steps import BACKUP, EXTRACT, PLANNER_ID, REREAD

    reader_rules = (
        "\n[guardian-distance.v2] distance_stage 存在时优先执行以下专门任务，返回 JSON，不输出 tool_request，也不重写题面。"
        '专门任务仍保留外层 {"subject":"physics","shared_stem_summary":"",'
        '"needs_student_confirmation":false}；locate 还须给 tier，使用 stem_tier。'
        "在 include_distance_targets=true 的终稿以及 locate 阶段，先把 subproblems 中的设问与 "
        "diagram_summary 中相同图号的图描述逐项对应，再在原图中确认位置并填写 distance_targets。"
        "include_distance_targets=true 时，在终稿中给计划，服务端会裁图，无需为距离符号先请求裁图。"
        "distance_targets 是数组，每个元素含 figure（图的原标签）、image_id（image_manifest 中的整数）、"
        "bbox（x0、y0、x1、y1 归一化坐标，留出标注线和点名所需余量）、parts（含 part 和 kind 的数组）及 "
        "symbols（该图实际印出的代数距离符号数组，不用点名拼造符号）。"
        'parts 的严格结构为 [{"part":"原小问号","kind":"adjacent_spacing 或 midpoint_velocity 之一"}]，每项都是对象。'
        "只有能写出实际印出的代数距离符号时，才为该图创建目标。逐个检查使用这同一张图的所有设问。"
        "只要用相邻点距或疏密推断定性结论，就要列为 adjacent_spacing，包括答案本身不需要写公式的判断。"
        "一张图可以同时支持这样的判断和符号速度计算，分别列出各自的小问号。"
        "图上的数值和区间端点名称各按原文转写，不把它们改写成代数距离符号。没有符合条件的目标时返回空数组。"
        "part 用原小问号。相邻点距比较或基于点距变化的判断为 adjacent_spacing。"
        "符号中点速度为 midpoint_velocity。同图的小问归在一起，不漏掉使用同一图的其他目标小问。"
        "有 distance_relocate 时只重新定位其中指定的小问，保留 part 和 kind。"
        "read 阶段只看所给裁图。输出 distance_reading={status: read, labels:[{symbol,start,end}], "
        "questions:[{part,kind,start,middle,end,interval_symbol}]}。不要返回 crop_ref、value 或其他字段。"
        "只列图上印出的距离符号，按原意用 ASCII 表达；记录每根相关标注线的两端，区分累计距离与相邻间距。"
        "questions 覆盖 distance_target 中每个指定小问。start、middle、end 是按时间顺序的三个计数点。"
        "related_subproblems 是还引用了同一张图的其他设问，按键逐项检查。若需比较点距或计算符号中点速度，补入 questions。"
        "其余设问的键填入 distance_reading.not_applicable_parts 数组。"
        "只有 midpoint_velocity 填题面给出的时间间隔符号。adjacent_spacing 省略 interval_symbol。"
        "如果裁图未包含目标标注线和完整端点，输出 distance_reading={status: wrong_region}。"
        "若裁图确实包含相关区域但印刷模糊或残缺，输出 distance_reading={status: image_unclear}。"
        "有 distance_format_errors 时，仅用同一裁图修复对应字段。"
        "没有 distance_stage 时，按原约定转写，subproblems 用设问原文字符串数组。"
    )
    solver_rules = (
        "\n[guardian-distance.v2] 当 stem.distance_evidence.status=read 时，以 figures 中逐条记录的标注端点作答。"
        "formulas 中 expected 是由这些端点约束推导的检查目标。"
        "在 distance_claims 按 slot 返回你实际使用的表达式，键和值的格式与 expected 一致，使用 ASCII 表达式，"
        "不能只核对量纲或抄对元数据却在正文用另一套关系。相邻点距应分别求出；中点速度的分子应是完整跨两段的位移。"
        "若 contradiction_feedback 指出某小问距离关系不一致，按已确认的端点仅修正相关小问。"
        "若有 unresolved_parts，仅回答其他小问；final_answers 的键用相应的原小问号。"
    )
    mentor_rules = (
        "\n[guardian-distance.v2] 如果 verified_solution.stem.distance_evidence.status=read，"
        "对 formulas 中每个 part，在对应小问的正文中原样输出其 slot（例如 [[distance_1]]）一次。"
        "不要加代码围栏或美元符号，不要自行改写、另写或重复这些关键公式，服务端会把原标记替换为已核对的公式。"
        "用这些实际相邻间距说明点迹变化，每个小问只讲解一次。"
        "收到公式占位修复指令时，只修复相应小问，保留其他已完成部分。"
        "如果距离证据取证不可用，按常规讲解可从原题确认的内容，并明确对应结论的核验限度。"
    )
    for component, extra in (
        (EXTRACT, reader_rules), (REREAD, reader_rules), (PLANNER_ID, solver_rules),
        (BACKUP, solver_rules), (MENTOR_EXPLAIN_ID, mentor_rules),
    ):
        doc = files[f"agents/{component}.json"]
        template = doc["prompt"]["template"]
        if "\n[guardian-distance.v1]" in template:
            template = template.split("\n[guardian-distance.v1]", 1)[0]
        doc["prompt"]["template"] = template if "[guardian-distance.v2]" in template else template + extra
    for component in (EXTRACT, REREAD):
        if "tutoring.inspect_image" not in files[f"agents/{component}.json"]["tools"]:
            raise ValueError("Guardian distance evidence requires inspect_image on both readers")
    files[f"agents/{EXTRACT}.json"]["models"][0]["guardian_distance_evidence"] = True
    planner = files[f"agents/{PLANNER_ID}.json"]["models"][0]
    if low_effort:
        planner["guardian_t1_reasoning_effort"] = "low"
    else:
        planner.pop("guardian_t1_reasoning_effort", None)


def parent_workflow():
    from app.agent_specs.blueprint_steps import WORKFLOW_ID

    return {
        "kind": "workflow", "id": MENTOR_WORKFLOW_ID, "handler": MENTOR_WORKFLOW_ID,
        "entry": MENTOR_PREPARE,
        "limits": {"model_calls": 2},
        "nodes": [
            {"id": MENTOR_PREPARE, "kind": "action", "handler_id": MENTOR_PREPARE, "display_name": "安全检查与选图"},
            {"id": MENTOR_BLUEPRINT, "kind": "workflow", "ref": WORKFLOW_ID, "display_name": "读题、求解与核验"},
            {"id": MENTOR_EXPLAIN_NODE, "kind": "agent", "ref": MENTOR_EXPLAIN_ID, "display_name": "导师讲解"},
            {"id": MENTOR_FINISH, "kind": "action", "handler_id": MENTOR_FINISH, "display_name": "校验并交付"},
        ],
        "edges": [
            {"from": "START", "to": MENTOR_PREPARE},
            {"from": MENTOR_PREPARE, "to": MENTOR_BLUEPRINT, "condition_id": "solve"},
            {"from": MENTOR_PREPARE, "to": MENTOR_FINISH, "condition_id": "deliver"},
            {"from": MENTOR_BLUEPRINT, "to": MENTOR_EXPLAIN_NODE},
            {"from": MENTOR_EXPLAIN_NODE, "to": MENTOR_EXPLAIN_NODE, "condition_id": "retry"},
            {"from": MENTOR_EXPLAIN_NODE, "to": MENTOR_FINISH, "condition_id": "deliver"},
            {"from": MENTOR_FINISH, "to": "END"},
        ],
    }


MENTOR_DISCIPLINE_RULES = (
    "\n[mentor-discipline.v2] 客观题、实验题与题界核对红线：\n"
    "- 整页题界隔离：当用户已明确指定目标题号（如「第14题」）时，正文只能讲解该目标题，严禁在末尾顺带解答同页其他邻题。\n"
    "- 单选题唯选与方向反推：单选题必须且只能给出唯一最优选项，严禁合并输出两个选项（如 AB、BC）；若初步推导出 ≥2 项成立，必须立刻判定至少有一个前置方向性规律用反了（如波的折射弯曲方向、光路可逆性、左手/右手定则等），重核规律后只选唯一 1 项。\n"
    "- 禁止轻率判定「无正确选项」或「题目有误」；若初步推导出四项均不符，必须反推重审图像坐标、方向、正负号与隐含条件后再作答。\n"
    "- 实验题涉及螺旋测微器/游标卡尺/电表读数或纸带点迹时，须显式写明主尺与估读位，纸带题须先写出从左到右相邻点间距的变化趋势，再判断小车连接端。\n"
    "- 凝练交付原则：正文只写清晰的最终推导与结论，禁止把反复试探、走不通的草稿枚举写进正文；若多小问压轴题的最后一问尚未构成完备证明，先完整交付已确定成立的前几小问，再简明给出最后一问的核心思路，严禁冗长铺陈导致输出截断。"
)


def provision_mentor_explain(
    *,
    model: str,
    prompt: str = DEFAULT_MENTOR_PROMPT,
    enable_thinking: bool = True,
    thinking_budget: int = 2560,
) -> dict:
    doc = frozen_contracts(expanded_output=True)[f"agents/{MENTOR_EXPLAIN_ID}.json"]
    prompt = _expanded_content_prompt(prompt)
    doc["display_name"] = "家长视角导师说题解析"
    doc["description"] = "仅限成人体验沙盒使用：基于已核验解题骨架生成考点本质、完整破题链路与常见卡点解析，零学生域写入。"
    doc["prompt"]["template"] = (
        prompt
        if "[mentor-discipline.v2]" in prompt
        else prompt.split("[mentor-discipline.v1]", 1)[0].rstrip() + MENTOR_DISCIPLINE_RULES
    )
    doc["tools"] = []
    model_cfg: dict = {
        "component_id": MENTOR_EXPLAIN_ID,
        "name": model,
        "temperature": 0.2,
        "max_output_tokens": 16384,
        "timeout_ms": 60000,
        "enable_thinking": enable_thinking,
    }
    if enable_thinking:
        model_cfg["thinking_budget"] = thinking_budget
    doc["models"] = [model_cfg]
    return doc


MENTOR_REVIEW_ID = "tutoring.mentor-review"
MENTOR_REPAIR_ID = "tutoring.mentor-repair"
MENTOR_DELIVER_ID = "guardian-mentor.deliver"
MENTOR_BRANCHES = {"review", "skip_review", "repair", "finish"}


def _sections_schema():
    return {
        "type": "object",
        "required": ["sections"],
        "additionalProperties": False,
        "properties": {
            "sections": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "required": ["id", "content"],
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "minLength": 1, "maxLength": 32},
                        "content": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 3600,
                        },
                    },
                },
            }
        },
    }


def staged_contracts(*, include_repair=True):
    result = {}
    for uid, kind in ((MENTOR_REVIEW_ID, "gate"), (MENTOR_REPAIR_ID, "agent")):
        doc = copy.deepcopy(frozen_contracts()[f"agents/{MENTOR_EXPLAIN_ID}.json"])
        doc.update(
            id=uid,
            kind=kind,
            operation=uid,
            input_contract=uid + ".input.v1",
            output_contract=uid + ".output.v1",
            context_builder_id=uid.replace("-", "_") + ".context",
            prompt={"id": uid + ".prompt"},
            models=[{"component_id": uid}],
        )
        if kind == "agent":
            doc["output_schema"] = _sections_schema()
        else:
            from app.agent_specs.verdicts import GateVerdict

            row = {
                "type": "object",
                "required": ["id", "status", "reason"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string", "minLength": 1, "maxLength": 32},
                    "status": {"enum": ["pass", "wrong", "unknown"]},
                    "reason": {"type": "string", "maxLength": 100},
                },
            }
            doc.pop("output_schema")
            doc.pop("error_codes")
            doc.update(
                implementation="judge",
                on_error="deny",
                safety_class="standard",
                verdict_schema=GateVerdict.model_json_schema(),
                provider_output_schema={
                    "type": "object",
                    "required": ["rows", "coverage_complete"],
                    "additionalProperties": False,
                    "properties": {
                        "coverage_complete": {"type": "boolean"},
                        "rows": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 10,
                            "items": row,
                        },
                    },
                },
            )
        result[f"{'agents' if kind == 'agent' else 'gates'}/{uid}.json"] = doc
    if not include_repair:
        result.pop(f"agents/{MENTOR_REPAIR_ID}.json")
    return result


def staged_workflow():
    def node(key):
        return f"guardian-mentor.{key}" if key not in {"START", "END"} else key

    return {
        "kind": "workflow",
        "id": MENTOR_WORKFLOW_ID,
        "handler": MENTOR_WORKFLOW_ID,
        "entry": node("explain"),
        "nodes": [
            {"id": node("explain"), "kind": "agent", "ref": MENTOR_EXPLAIN_ID},
            {
                "id": node("review"),
                "kind": "gate",
                "ref": MENTOR_REVIEW_ID,
                "display_name": "逐问审核",
            },
            {
                "id": node("repair"),
                "kind": "agent",
                "ref": MENTOR_REPAIR_ID,
                "display_name": "定向修复",
            },
            {
                "id": node("recheck"),
                "kind": "gate",
                "ref": MENTOR_REVIEW_ID,
                "display_name": "修复复核",
            },
            {
                "id": node("deliver"),
                "kind": "action",
                "handler_id": MENTOR_DELIVER_ID,
                "display_name": "汇总并交付",
            },
        ],
        "edges": [
            {"from": node(a), "to": node(b), **({"condition_id": c} if c else {})}
            for a, b, c in [
                ("START", "explain", None),
                ("explain", "review", "review"),
                ("explain", "deliver", "skip_review"),
                ("review", "repair", "repair"),
                ("review", "deliver", "finish"),
                ("repair", "recheck", "review"),
                ("repair", "deliver", "finish"),
                ("recheck", "deliver", None),
                ("deliver", "END", None),
            ]
        ],
    }


def stage_mentor_review(files):
    path = f"agents/{MENTOR_EXPLAIN_ID}.json"
    if path not in files:
        source = files["agents/tutoring.turn.json"]["models"][0]
        files[path] = provision_mentor_explain(
            model=source["name"], enable_thinking=False
        )
    files[path]["prompt"]["template"] += (
        "\n当 act 为 explain 或 answer 时额外返回 sections。每一小问用独立条目，"
        "id 为题号或小问编号（单问用 main），content 为该问可独立阅读的解答。"
        "所有条目正文总计不超过 3200 字。全题背景和共享推导请放在相应小问内。"
    )
    docs = staged_contracts()
    repair_model = files[path]["models"][0]["name"]
    judge_model = files["gates/tutoring.leak-judge.json"]["models"][0]["name"]
    if repair_model == judge_model:
        raise ValueError(
            "Guardian Judge must be independent from the explanation model"
        )
    for key, uid, model, title, limit, prompt in (
        (
            "gates",
            MENTOR_REVIEW_ID,
            judge_model,
            "家长解析逐问审核",
            1000,
            "依据原题、图片独立核对以下 sections。逐条用原 id 返回 rows，每条包含 id、status（pass/wrong/unknown）、"
            "reason（不超过100字，正确时留空，错误指出首个错误步骤）。请直接输出简短 JSON，禁止长篇解释。"
            "coverage_complete 表示本次待审范围完整。首次全题审核时根据原题检查小问是否齐全。"
            "复核仅核对给定小问，其他小问是已通过的上下文。若一段混合正确和错误推导，把该段判为 wrong。",
        ),
        (
            "agents",
            MENTOR_REPAIR_ID,
            repair_model,
            "家长解析定向修复",
            4096,
            "依据原题、图片、已通过小问和审核反馈，仅重写 targets 中的错误小问。"
            "输出 JSON 对象 sections，每条只含原 id 和 content。每问写必要推导和答案，合计不超过3200字。"
            "已通过内容仅供参照，不要改写或重复输出。",
        ),
    ):
        doc = docs[f"{key}/{uid}.json"]
        doc.update(display_name=title, tools=[])
        doc["prompt"]["template"] = prompt
        doc["models"] = [
            {
                "component_id": uid,
                "name": model,
                "temperature": 0,
                "max_output_tokens": limit,
                "timeout_ms": 25000,
                "enable_thinking": False,
            }
        ]
    files.update(docs)
    files["workflows/guardian-mentor.json"] = staged_workflow()


def simple_workflow():
    workflow = staged_workflow()
    removed = {"guardian-mentor.repair", "guardian-mentor.recheck"}
    workflow["nodes"] = [
        node for node in workflow["nodes"] if node["id"] not in removed
    ]
    workflow["edges"] = [
        edge for edge in workflow["edges"] if not ({edge["from"], edge["to"]} & removed)
    ]
    for edge in workflow["edges"]:
        if edge["from"] == "guardian-mentor.review":
            edge.pop("condition_id")
    return workflow


def simplify_mentor_review(files):
    gate_path = f"gates/{MENTOR_REVIEW_ID}.json"
    if gate_path not in files:
        stage_mentor_review(files)
    files.pop(f"agents/{MENTOR_REPAIR_ID}.json", None)
    files[f"workflows/{MENTOR_WORKFLOW_ID}.json"] = simple_workflow()
    files[gate_path]["prompt"]["template"] = (
        "你是独立审核员。依据原题和图片审核 sections 中给定的每一项。"
        "只输出一个 JSON 对象，示例："
        '{"rows":[{"id":"24","status":"pass","reason":""},{"id":"25","status":"wrong","reason":"选项与原文矛盾"}],'
        '"coverage_complete":true}。'
        "严格使用输入 sections 中的原 ID，每个 ID 只出现一次。不要添加图片中的相邻题；"
        "目标范围内无法判断的条目返回 unknown。每条 reason 最多100字，通过时用空字符串。"
        "仅在目标题目及全部小问确实齐全时返回 coverage_complete=true；不明确时返回 false。"
    )


def normalize_review_shape(payload):
    """Adapt observed wire shapes. Missing whole-question coverage stays unknown."""
    if isinstance(payload, list):
        payload = {"rows": payload}
    if not isinstance(payload, dict):
        return payload
    if (
        "rows" not in payload
        and payload
        and all(
            isinstance(row, dict) and row.get("id") == key
            for key, row in payload.items()
        )
    ):
        payload = {"rows": list(payload.values())}

    if isinstance(payload.get("rows"), list):
        payload = {**payload}
        payload.setdefault("coverage_complete", False)
        # Reason is display metadata in the simplified graph. Keep the judgment
        # and the ID unchanged, and bound the logged explanation.
        payload["rows"] = [
            {**row, "reason": row["reason"][:100]}
            if isinstance(row, dict) and isinstance(row.get("reason"), str)
            else row
            for row in payload["rows"]
        ]
    return payload


def direct_mentor_workflow(files):
    """Select direct delivery and link the staged blueprint when the snapshot provides it."""
    from app.agent_specs.blueprint_steps import EXTRACT

    files.pop(f"gates/{MENTOR_REVIEW_ID}.json", None)
    files.pop(f"agents/{MENTOR_REPAIR_ID}.json", None)
    files.update(workflow_documents(linked_blueprint=f"agents/{EXTRACT}.json" in files))
    explain_path = f"agents/{MENTOR_EXPLAIN_ID}.json"
    if explain_path in files:
        explain = files[explain_path]
        explain["output_contract"] = MENTOR_EXPANDED_OUTPUT_CONTRACT
        explain["output_schema"] = _mentor_output_schema(MENTOR_CONTENT_MAX_LENGTH)
        sections_suffix = (
            "\n当 act 为 explain 或 answer 时额外返回 sections。每一小问用独立条目，"
            "id 为题号或小问编号（单问用 main），content 为该问可独立阅读的解答。"
            "所有条目正文总计不超过 3200 字。全题背景和共享推导请放在相应小问内。"
        )
        template = _expanded_content_prompt(explain["prompt"]["template"])
        if sections_suffix in template:
            template = template.replace(sections_suffix, "")
        for marker in ("[mentor-discipline.v1]", "[mentor-discipline.v2]"):
            if marker in template:
                template = template.split(marker, 1)[0].rstrip()
        template = template.rstrip() + MENTOR_DISCIPLINE_RULES
        explain["prompt"]["template"] = template
        for m in explain.get("models") or []:
            m["max_output_tokens"] = max(int(m.get("max_output_tokens") or 0), 16384)
            if m.get("enable_thinking"):
                m["thinking_budget"] = min(int(m.get("thinking_budget") or 2560), 2560)


def review_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate review JSON key")
        result[key] = value
    return result

def mentor_latency_trial(files):
    """Prepare an isolated Guardian candidate against the staged direct workflow."""
    from app.agent_specs import blueprint_steps as steps

    if files["workflows/guardian-mentor.json"]["entry"] != MENTOR_PREPARE:
        raise ValueError("mentor latency trial requires the direct parent workflow")
    files[steps.FLOW_FILE] = steps.workflow(mentor_language=True)
    path = f"agents/{steps.EXTRACT}.json"
    extract = files[path]
    extract["output_contract"] = steps.EXTRACT + ".output.guardian.v2"
    extract["output_schema"] = steps.contracts(files)[path]["output_schema"]
    prompts = {
        steps.EXTRACT: (
            "输入含 guardian_request 时，以其中明确指定的题号和小问限定作答范围。先确定该范围，再看原图。"
            "仅当指定目标全是英语写作且图片清晰、无需计算、实验、跨学科或独立核验时，"
            "返回 guardian_task=english_writing，subject=english；题面摘要仅写目标题号、共享材料位置及必要限制，"
            "subproblems仅列请求的小问，不逐字抄录原文。阅读、完形、语法、混合任务及不确定时均填 solve；完整保留必要材料，只列目标题号内的设问。"
            "精细图像仍须核对标注端点和读数。按实际难度分级。"
        ),
        steps.PLANNER_ID: (
            "输入含 guardian_request 时该请求限定作答范围，邻题仅供理解上下文。"
            "仅输出目标题号的结论、必要推导与核验依据，每条采分点、易错点用简短短语；保留全部影响结论的条件及核验请求。"
        ),
        MENTOR_EXPLAIN_ID: (
            "按 guardian_question 的交付目的与题号作答。核对试卷时，严格只答指定的题和小问："
            "先给题号与最终答案，随后写必要依据、计算或完整证明。简易选择填空每题一句依据即可。"
            "家长明确要求完整作文时直接给出符合题意、字数和格式的成文。"
            "核对答案不另写教学对话、考点综述及通用易错点；家长明确问如何教时，再给最相关的启发建议。"
            "若 verified_solution.evidence.target_scope 存在，正文仅回答这段用户原文明确要求的范围。共享文章仅作依据。关键条件模糊仍须澄清，未核验不得声称已核验。"
        ),
    }
    for unit, guidance in prompts.items():
        prompt = files[f"agents/{unit}.json"]["prompt"]
        marker = "[guardian-latency-trial.v1]"
        if marker not in prompt["template"]:
            prompt["template"] += "\n" + marker + guidance

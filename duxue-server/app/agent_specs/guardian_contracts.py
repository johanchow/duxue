"""Optional Guardian mentor-explanation Agent & Workflow contracts.

Preserves byte-for-byte compatibility fingerprints of existing published Admin
artifacts when these optional files are absent.
"""

from __future__ import annotations

import copy

MENTOR_EXPLAIN_ID = "tutoring.mentor-explain"
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


def _mentor_output_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "act": {
                "type": "string",
                "enum": ["explain", "answer", "clarify", "pronounce", "safety"],
            },
            "content": {"type": "string", "minLength": 1, "maxLength": 3600},
            "visual": {"type": ["object", "null"]},
            "pronounce": {"type": ["object", "null"]},
        },
        "required": ["act", "content"],
        "additionalProperties": True,
    }


def frozen_contracts() -> dict[str, dict]:
    return {
        f"agents/{MENTOR_EXPLAIN_ID}.json": {
            "id": MENTOR_EXPLAIN_ID,
            "kind": "agent",
            "implementation": "llm",
            "agent_label": "tutoring",
            "risk_tier": "standard",
            "operation": MENTOR_EXPLAIN_ID,
            "input_contract": MENTOR_EXPLAIN_ID + ".input.v1",
            "output_contract": MENTOR_EXPLAIN_ID + ".output.v1",
            "input_schema": {
                "type": "object",
                "properties": {
                    "user": {"oneOf": [{"type": "string"}, {"type": "array"}]}
                },
                "required": ["user"],
                "additionalProperties": False,
            },
            "output_schema": _mentor_output_schema(),
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


def workflow_documents() -> dict[str, dict]:
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


def provision_mentor_explain(
    *,
    model: str,
    prompt: str = DEFAULT_MENTOR_PROMPT,
    enable_thinking: bool = True,
    thinking_budget: int = 4096,
) -> dict:
    doc = copy.deepcopy(frozen_contracts()[f"agents/{MENTOR_EXPLAIN_ID}.json"])
    doc["display_name"] = "家长视角导师说题解析"
    doc["description"] = "仅限成人体验沙盒使用：基于已核验解题骨架生成考点本质、完整破题链路与常见卡点解析，零学生域写入。"
    doc["prompt"]["template"] = prompt
    doc["tools"] = []
    model_cfg: dict = {
        "component_id": MENTOR_EXPLAIN_ID,
        "name": model,
        "temperature": 0.2,
        "max_output_tokens": 4096,
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


def review_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate review JSON key")
        result[key] = value
    return result

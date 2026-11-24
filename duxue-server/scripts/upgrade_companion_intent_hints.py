"""Create an Admin import-upgrade artifact adding optional history_image_ref & thinking hints to companion.intent.

Upgrades an exported Admin release/draft snapshot idempotently:
1. Adds optional `history_image_ref` ("none" | "needed") and `thinking` ("default" | "off")
   to `agents/companion.intent.json`'s `output_schema` (keeping `required: ["intent"]`).
2. Appends concise semantic guidance for both optional fields to `prompt.template`.
3. Ensures `models[*].max_output_tokens >= 90` for `companion.intent`.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility

_CONCISE_INTENT_PROMPT = (
    "你是读学对话的轻量前置路由，只返回一个 JSON 对象，不要回答问题本身，不要输出多余字段。\n"
    "字段：\n"
    "1. intent（必填）：正常学习提问、作业讨论、知识科普、词义发音、闲聊一律填 \"tutoring\"；只有完全无法理解的乱码才填 \"unclear\"。\n"
    "2. history_image_ref（仅本轮无 current_image_ids 且 recent_utterances 含历史图片时判断）：\n"
    "   - \"none\"：本轮是独立于历史图片的纯文字提问（知识科普、概念解释、词义/发音、新文字题、闲聊），与历史照片无关。\n"
    "   - \"needed\"：本轮指代、追问或纠正历史照片（如“再看那张图”“不是同一张”“上一张第2题”“这个对不对”等依赖旧图才能看懂的省略指代）。\n"
    "3. thinking（仅 intent=\"tutoring\" 且本轮无新图时判断）：\n"
    "   - \"off\"：常识科普、概念/原理解释、历史地理人物、词义翻译、发音、闲聊等无需复杂多步推导的问题。\n"
    "   - \"default\"：需要看图、做作业题、数学计算、理科推导、证明、逻辑推理、批改核验，或拿不准的情况。\n"
    "示例：\n"
    "- 历史有数学作业图，本轮问「英伟达公司为什么这么厉害？」→ {\"intent\":\"tutoring\",\"history_image_ref\":\"none\",\"thinking\":\"off\"}\n"
    "- 历史有数学作业图，本轮问「你刚才看的是上一张，看新发的那张第2题」→ {\"intent\":\"tutoring\",\"history_image_ref\":\"needed\",\"thinking\":\"default\"}\n"
    "- 历史有数学作业图，本轮问「鸡兔同笼共35个头94只脚，鸡兔各几只？」→ {\"intent\":\"tutoring\",\"history_image_ref\":\"none\",\"thinking\":\"default\"}"
)


def upgrade(record: dict) -> dict:
    bundle = deepcopy(record["bundle"])
    if compile_bundle(bundle).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    files = bundle["files"]

    intent_key = "agents/companion.intent.json"
    if intent_key not in files:
        raise ValueError(f"missing {intent_key} in bundle")

    doc = files[intent_key]
    schema = doc.get("output_schema")
    if isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
        schema["properties"]["history_image_ref"] = {"enum": ["none", "needed"]}
        schema["properties"]["thinking"] = {"enum": ["default", "off"]}

    prompt = doc.get("prompt")
    if isinstance(prompt, dict) and isinstance(prompt.get("template"), str):
        prompt["template"] = _CONCISE_INTENT_PROMPT

    for model in doc.get("models") or []:
        if isinstance(model, dict) and isinstance(model.get("max_output_tokens"), int):
            model["max_output_tokens"] = max(model["max_output_tokens"], 90)

    bundle["compatibility"] = contract_compatibility(files)
    compiled = compile_bundle(bundle)
    return {
        **record,
        "bundle": bundle,
        "kind": "draft",
        "digest": compiled.digest,
        "migration_source": {
            k: record[k] for k in ("kind", "id", "digest", "revision") if k in record
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = upgrade(json.loads(args.source.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

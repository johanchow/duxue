"""Create an editable draft export with natural language camera rules."""

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs import reminder_policy as rules
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility


def upgrade(record):
    bundle = copy.deepcopy(record["bundle"])
    if compile_bundle(bundle).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    files = bundle["files"]
    if rules.FILE in files:
        raise ValueError("observation rules already enabled")
    for name, doc in rules.upgraded_contracts(files).items():
        files[name] = doc
    files[rules.FILE] = {
        "schema_version": 1,
        "groups": {
            "offer_help": [
                {
                    "id": "still-material",
                    "assessment_rule": "面对学习材料保持静止，没有可见操作；不能确认为静止时标为不确定。",
                    "min_continuous_seconds": 240,
                }
            ],
            "invite_return": [
                {
                    "id": "other-activity",
                    "assessment_rule": "持续进行与当前学习材料无关的可见活动，包括反复把玩物品；正常书写、翻页和使用学具不符合。",
                    "min_continuous_seconds": 120,
                }
            ],
        },
    }
    for name, instruction in {
        rules.VISION: "对每个采样槽按 rule_groups 逐条判断描述的可见行为。rule_matches 必须覆盖所有规则，分别给出 rule_id、matched/not_matched/uncertain 和本槽 evidence_frame_ids。quiet_slots 内只判定基础 activity，rule_matches 返回空数组。基础 activity 独立判定。",
        rules.INTAKE: "孩子明确声明现在要休息、去厕所或暂时不要摄像头提醒时，study_action.action=quiet_start，时长用 target_minutes；已在休息时延长为 quiet_extend，明确回来为 quiet_end。暂停信息 camera_hints_paused_until 出现在 current_sprint 时，学生说“我回来了”须返回 quiet_end，不填 target_minutes；不要当成闲聊或恢复任务。仅开始或延长时缺少时间才澄清。区分叙述、题目和暂停任务。",
        "agents/companion.intent.json": "当前声明暂时休息、不想被摄像头打扰、延长休息或结束休息走 planning，即使没有任务。",
        "gates/companion.scene-switch.json": "允许明确的暂时休息、延长、回来等操作插入当前答疑，路由到 planning。",
        "agents/behavior.support-opportunity.json": "有 assessment_rule 时，结合原图判断该描述所触发的邀请是否适当。只能建议 requested_kind 或返回 none/uncertain。",
    }.items():
        files[name]["prompt"]["template"] += "\n" + instruction
    bundle["compatibility"] = contract_compatibility(files)
    result = compile_bundle(bundle)
    return {
        **record,
        "kind": "draft",
        "bundle": bundle,
        "digest": result.digest,
        "migration_source": {
            k: record[k] for k in ("id", "kind", "revision", "digest") if k in record
        },
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            upgrade(json.loads(args.source.read_text())), ensure_ascii=False, indent=2
        )
    )

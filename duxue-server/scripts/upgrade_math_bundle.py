"""Explicit offline migration of an Admin export. Never publishes or overwrites input.

Usage: python -m scripts.upgrade_math_bundle INPUT.json OUTPUT.json [--enable]
Import OUTPUT into an Admin draft and validate/debug before publishing.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility, digest
from app.agent_specs.configuration import code_contract

TUTOR = """
[math.v1]
数学工具协议补充（优先于旧顶层字段清单）：可返回 math_claims 数组。
计算、等价、解方程、求导、积分、极限必须通过 math 工具获得依据；不要心算后自称已核验。
先只返回 {"tool":"math","args":{"op":"equivalent","args":{"left":"90-37","right":"53"},"symbols":[],"assumptions":[],"step_ref":"当前题步骤1"}}。
操作参数：evaluate(expression,precision可选)；equivalent(left,right)；solve(equations,variables)，首期仅单变量单方程，equations写左式减右式；differentiate(expression,variable,order)；integrate(expression,variable,bounds可选)；limit(expression,variable,point,direction)。symbols元素为{name,domain:real|complex|integer}。假设仅接受“变量名:positive|negative|nonzero|nonnegative”，不得编造题面未给定的条件。语法仅数字、声明变量、pi/E/oo、四则、整数幂及sin/cos/tan/exp/log/sqrt/abs单参数调用。
图片请求携带当前授权image_ref和step_ref；读不清先澄清。输出候选时math_claims=[{request_id:工具返回ID,step_ref:原步骤引用,assertion:equal|not_equal|unknown|result,value:引用result时须原样填写}]。不得自造ID或改变工具结论。unknown/error仅说明未核验，不判错。导师新写的示例计算也必须核验；不要把数值正确说成列式、过程或整题正确。工具结果仅作内部依据，现有答案保护不变。
"""
JUDGE = """
[math.v1]
当problem中math_review_required=true时，额外返回math_consistent:boolean（无法判断为null）。对没有数学断言的合规回复可返回true。独立检查当前题意、授权原图转写与工具参数是否相符；检查正文及配图中的每个计算性断言是否由math_records支持且被math_claims引用。不要信任模型遗漏的claims，不要把旧助手结论当依据。candidate_turn中的progress/evidence也不得在无依据时声称学生已完成数学验证。缺证据、假设无来源、转写不符、将unknown说成错误、把数值核验扩张为过程/整题正确，均返回false。只讨论方法而未断言数学结果不强求工具。工具精确运算结果不可凭心算推翻；争议定位到转写/条件/表达。result是内部参考，不因此允许对孩子披露最终答案。其他答案保护字段仍按原规则返回。
"""


def upgrade(record: dict, *, enable=False):
    result = copy.deepcopy(record)
    if digest(record["bundle"]) != record["digest"]:
        raise ValueError("input_digest_mismatch")
    bundle = result["bundle"]
    files = bundle["files"]
    tool = copy.deepcopy(code_contract()["files"]["tools/tutoring.math.json"])
    tool["description"] = "受限数学核验；结果不改变答案保护"
    files["tools/tutoring.math.json"] = tool
    judge = files["gates/tutoring.leak-judge.json"]
    judge["provider_output_schema"]["properties"]["math_consistent"] = {
        "type": ["boolean", "null"]
    }
    if enable:
        tutor = files["agents/tutoring.turn.json"]
        if "tutoring.math" not in tutor["tools"]:
            tutor["tools"].append("tutoring.math")
        for doc, addition in ((tutor, TUTOR), (judge, JUDGE)):
            if "[math.v1]" not in doc["prompt"]["template"]:
                doc["prompt"]["template"] += addition
    bundle["compatibility"] = contract_compatibility(files)
    result["digest"] = compile_bundle(bundle).digest
    # A transformed export is an unpublished proposal, never a released identity.
    result["migration_source"] = {"id": record["id"], "digest": record["digest"],
                                  "kind": record.get("kind", "release"),
                                  "revision": record.get("revision")}
    result["id"] = "math-migration-draft"
    result["kind"] = "draft"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--enable", action="store_true")
    args = parser.parse_args()
    record = upgrade(json.loads(args.input.read_text()), enable=args.enable)
    with args.output.open("x") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")

"""Explicit offline migration of an Admin export. Never publishes or overwrites input.

Usage:
  python -m scripts.upgrade_math_bundle INPUT.json OUTPUT.json [--enable] \
    [--enable-thinking] [--thinking-budget 4096] [--judge-thinking-budget 1024]
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
计算、等价、解方程（组）/不等式、求导、积分、极限、复数、排列组合、向量运算必须通过 math 工具获得依据；不要心算后自称已核验。
先只返回 {"tool":"math","args":{"op":"equivalent","args":{"left":"90-37","right":"53"},"symbols":[],"assumptions":[],"step_ref":"当前题步骤1"}}。
操作参数：evaluate(expression,precision可选)；equivalent(left,right)；solve(equations,variables)，支持单变量/多变量方程组（1~4变量，可写左式减右式或 lhs==rhs）、含已声明参数符号的方程，以及实数单变量不等式（组）（<, <=, >, >=, !=）；differentiate(expression,variable,order)；integrate(expression,variable,bounds可选)；limit(expression,variable,point,direction)。symbols元素为{name,domain:real|complex|integer}。假设仅接受“变量名:positive|negative|nonzero|nonnegative”，不得编造题面未给定的条件。语法支持数字、声明变量、常数 pi/E/oo/I（虚数单位）、四则、有理分数幂与受限符号指数、sin/cos/tan/cot/asin/acos/atan/exp/ln/log(x[,base])/sqrt/cbrt/root(x,n)/abs/re/im/conjugate/factorial/binomial(n,k)/gcd/lcm 以及二维/三维向量 dot([..],[..])/norm([..])/cross([..],[..])。
图片请求携带当前授权image_ref和step_ref；读不清先澄清。输出候选时math_claims=[{request_id:工具返回ID,step_ref:原步骤引用,assertion:equal|not_equal|unknown|result,value:仅assertion=result时原样填写，其他assertion禁止填写value}]。不得自造ID或改变工具结论。unknown/error仅说明未核验，不判错。导师新写的示例计算也必须核验；不要把数值正确说成列式、过程或整题正确。工具结果仅作内部依据，现有答案保护不变。
"""
JUDGE = """
[math.v1]
当problem中math_review_required=true时，额外返回math_consistent:boolean（无法判断为null）。对没有具体计算式或数值断言的合规回复（如概念辨析、审题引导、图形识别、只讨论方法）必须返回true，不得因未调用工具或math_records为空而返回null或false。独立检查当前题意、授权原图转写与工具参数是否相符；检查正文及配图中的每个计算性断言是否由math_records支持且被math_claims引用。不要信任模型遗漏的claims，不要把旧助手结论当依据。candidate_turn中的progress/evidence也不得在无依据时声称学生已完成数学验证。缺计算证据、假设无来源、转写不符、将unknown说成错误、把数值核验扩张为过程/整题正确，均返回false。工具精确运算结果不可凭心算推翻；争议定位到转写/条件/表达。result是内部参考，不因此允许对孩子披露最终答案。其他答案保护字段仍按原规则返回。
"""


def _apply_thinking(
    doc: dict, *, enable_thinking: bool, thinking_budget: int | None, primary_only: bool = False
) -> None:
    models = doc.get("models", [])
    targets = models[:1] if primary_only else models
    for model in targets:
        model["enable_thinking"] = enable_thinking
        if enable_thinking:
            model["max_output_tokens"] = max(int(model.get("max_output_tokens") or 0), 4096)
        if enable_thinking and thinking_budget is not None:
            model["thinking_budget"] = thinking_budget
        else:
            model.pop("thinking_budget", None)


def upgrade(
    record: dict,
    *,
    enable: bool = False,
    enable_thinking: bool | None = None,
    thinking_budget: int | None = None,
    judge_thinking_budget: int | None = None,
):
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
    for model in judge.get("models", []):
        model["max_output_tokens"] = max(int(model.get("max_output_tokens") or 0), 512)
    tutor = files["agents/tutoring.turn.json"]
    if enable:
        if "tutoring.math" not in tutor["tools"]:
            tutor["tools"].append("tutoring.math")
        for doc, addition in ((tutor, TUTOR), (judge, JUDGE)):
            if "[math.v1]" not in doc["prompt"]["template"]:
                doc["prompt"]["template"] += addition
        judge_tpl = judge["prompt"]["template"]
        old_json = (
            '{"answer_protected":true或false,"student_answer_correct":true或false或null,'
            '"affirms_student_answer":false,"new_final_answer":false,'
            '"complete_solution":false,"choice_verdict":false,"premature_conclusion":false}'
        )
        new_json = (
            '{"answer_protected":true或false,"student_answer_correct":true或false或null,'
            '"affirms_student_answer":false,"new_final_answer":false,'
            '"complete_solution":false,"choice_verdict":false,"premature_conclusion":false,'
            '"math_consistent":true或false或null}'
        )
        if old_json in judge_tpl:
            judge_tpl = judge_tpl.replace(old_json, new_json, 1)
        judge_tpl = judge_tpl.replace("字段沿用既有契约，不加字段。", "不额外发明契约外字段。")
        judge["prompt"]["template"] = judge_tpl
    if enable_thinking is not None:
        _apply_thinking(
            tutor,
            enable_thinking=enable_thinking,
            thinking_budget=thinking_budget,
            primary_only=True,
        )
    if judge_thinking_budget is not None:
        _apply_thinking(
            judge,
            enable_thinking=True,
            thinking_budget=judge_thinking_budget,
        )
    bundle["compatibility"] = contract_compatibility(files)
    result["digest"] = compile_bundle(bundle).digest
    # A transformed export is an unpublished proposal, never a released identity.
    result["migration_source"] = {
        "id": record["id"],
        "digest": record["digest"],
        "kind": record.get("kind", "release"),
        "revision": record.get("revision"),
    }
    result["id"] = "math-migration-draft"
    result["kind"] = "draft"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--enable", action="store_true")
    parser.add_argument("--enable-thinking", action="store_true", default=None)
    parser.add_argument("--disable-thinking", action="store_true", default=False)
    parser.add_argument("--thinking-budget", type=int, default=None)
    parser.add_argument("--judge-thinking-budget", type=int, default=None)
    args = parser.parse_args()
    thinking_flag: bool | None = (
        False if args.disable_thinking else True if args.enable_thinking else None
    )
    record = upgrade(
        json.loads(args.input.read_text()),
        enable=args.enable,
        enable_thinking=thinking_flag,
        thinking_budget=args.thinking_budget,
        judge_thinking_budget=args.judge_thinking_budget,
    )
    with args.output.open("x") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")

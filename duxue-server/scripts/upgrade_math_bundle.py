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
[choice-guidance.v1]
非判题请求若在image_review中声明conclusion="not_checking"，必须直接在content填写完整面向学生的回复，禁止把content写成「待核验」占位符。
选择题或判断题在引导阶段（学生未提交完整推导，或请求提示/下一步），严禁按选项编号（例如「先看A和C」「拿四个选项逐个对照」「先判断①和②」「说说你觉得该选哪个」）组织引导，也不得逐个拆解具体选项或暗示排除方向；一律脱离选项字母，只围绕题干中的核心概念、已知条件、原理或材料事实提出一个具体可执行的最小问题。学生要求「换一种说法或拆细」时，必须换成更具体的底层概念或小例子，不得只复述题干或说「再想想」。
"""
JUDGE = """
[math.v1]
当problem中math_review_required=true时，额外返回math_consistent:boolean（仅在完全无法辨认图片算式时才可为null）。只要回复中没有具体的数值计算或代数等式断言（例如概念辨析、抽样方法判断、审题提示、纯文字原理引导），math_consistent必须返回true，严禁因math_records为空而填null或false。独立检查当前题意、授权原图转写与工具参数是否相符；检查正文及配图中的每个计算性断言是否由math_records支持且被math_claims引用。不要信任模型遗漏的claims，不要把旧助手结论当依据。candidate_turn中的progress/evidence也不得在无依据时声称学生已完成数学验证。缺计算证据、假设无来源、转写不符、将unknown说成错误、把数值核验扩张为过程/整题正确，均返回false。工具精确运算结果不可凭心算推翻；争议定位到转写/条件/表达。若学生在计算/填空题中已独立写出等价的正确表达式（如 3+(n-1)*2），导师核验确认其正确不算new_final_answer。result是内部参考，不因此允许对孩子披露最终答案。其他答案保护字段仍按原规则返回。
"""


PHASE3_TUTOR = """
[reasoned-choice.v1]
选择题/判断题核验边界（优先于旧“始终不确认候选项对错”规则）：
1. 裸猜试探（学生只报了选项字母/对错，或仅复述题面，没有写出针对本题的推理过程或排除依据）：严禁确认或否认其所猜选项，只追问其判断依据或引导回到核心概念。
2. 有据作答（学生在当前或最近原话中明确写出了针对本题的推理过程、计算推导或排除依据，并选出选项）：在题面信息完整时，先依据原题独立核验其推理与结论——推理与所选选项都正确，简短明确肯定（多选题不直接替学生补出漏选的其余选项）；推理有误或选错，指出具体逻辑漏洞或错步并给一个自检提示，不直接报出正确选项。
3. 多采分点主观题/实验题：若学生只答对部分要点，先明确肯定已成立的部分，再提示缺失的维度。
"""
PHASE3_JUDGE = """
[reasoned-choice.v1]
student_answer_correct 现支持 true | "partial" | false | null（仅在完全答对时填 true，多采分点答对部分要点且无原则性错误时填 "partial"，答错填 false，未作答或题面不足无法独立核验填 null）。
choice_verdict 判定更新（区分裸猜与有据作答）：
- 当学生未提供实质推理依据（裸猜或仅报选项字母）时，reply 若确认或否认任何候选项对错，choice_verdict 必须为 true；
- 当学生在 current_request 或 student_evidence 中已明确写出针对本题的推理/排除/计算依据并选出选项，且题面完整可核验时：reply 核验其推理并确认其所选选项对错，属于合法教学反馈，choice_verdict 为 false（但多选题中若 reply 直接补出学生未提及的漏选正确选项，仍为 true）。
- 学生已给出完整正确推理和结论时，reply 准确肯定其推理成立不算 premature_conclusion；仅在题面缺失无法核验却下结论、或未算完就宣布答案时才标 premature_conclusion=true。
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
    if enable_thinking and "prompt" in doc:
        quote_rule = (
            '\n[json-quote-safety.v1] 输出严格合法的 JSON 对象：字符串值内部如需使用引号，'
            '一律使用中文引号「」或『』（或转义为 \\"），严禁在字符串值内直接写未转义的英文双引号 "。'
        )
        if "[json-quote-safety.v1]" not in doc["prompt"]["template"]:
            doc["prompt"]["template"] += quote_rule
        invalid_frag = doc["prompt"].get("fragments", {}).get("invalid_json")
        if isinstance(invalid_frag, dict) and "未转义" not in invalid_frag.get("template", ""):
            invalid_frag["template"] = (
                '返回的内容不是有效 JSON 对象（请检查字符串值内是否误写了未转义的英文双引号 "，'
                '引用词语请改用「」或转义 \\"）；只返回一个符合 tutor-turn.v4 的合法 JSON 对象。'
            )


def upgrade(
    record: dict,
    *,
    enable: bool = False,
    enable_thinking: bool | None = None,
    thinking_budget: int | None = None,
    judge_thinking_budget: int | None = None,
    phase3: bool = False,
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
    judge["provider_output_schema"] = copy.deepcopy(
        code_contract()["files"]["gates/tutoring.leak-judge.json"][
            "provider_output_schema"
        ]
    )
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
    if phase3:
        for doc, addition in ((tutor, PHASE3_TUTOR), (judge, PHASE3_JUDGE)):
            if "[reasoned-choice.v1]" not in doc["prompt"]["template"]:
                doc["prompt"]["template"] += addition
        judge["prompt"]["template"] = judge["prompt"]["template"].replace(
            '"student_answer_correct":true或false或null',
            '"student_answer_correct":true或"partial"或false或null',
        )
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
    parser.add_argument("--phase3", action="store_true", default=False)
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
        phase3=args.phase3,
    )
    with args.output.open("x") as stream:
        stream.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")

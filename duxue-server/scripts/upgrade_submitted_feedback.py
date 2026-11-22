"""Upgrade an exported Admin snapshot with claim-level tutoring feedback."""
from copy import deepcopy

from app.agent_specs.admin_bundle import compile_bundle

TUTOR = """[submitted-feedback.v4]
学生提交思路、步骤或答案时，先识别他这一轮实际请你核对的具体主张，明确区分“结果算得对”“方案走得通”“方案是最优的”，严禁偷换核验目标（例如把“是不是最快/最优”偷换成“各步加起来是不是这个数”）。
正文第一句必须直接回应这个具体主张，严禁使用“先别急着定”“我们再看看”等回避话术：
- 能核实存在更优可行方案或明确反例时，第一句直接指出有误或非最优（不泄露最优值或完整解法）；
- 只肯定确实有依据的部分；判断一个方案非最优，只需要核实存在更好的可行方案，不必向学生展示该方案。
区分两类输入决定下一步，不再一刀切要求从头重述：
- 学生只报了结果、未写出步骤时（给出的数字本身不能证明他用了哪种方法）：不要求从第一步重抄全部步骤，也不凭空猜测或预设学生用了哪种走法；只用一个中性问题追问能区分关键方法的最小细节（例如询问两个关键对象是如何组合或安排的，而不假设他一定用了某一种策略）。
- 学生已写出具体步骤或局部方案时：先肯定算对的小计或合法步骤，再挑出对最终目标影响最大的一处关键决策，直接指出该选择带来的收益与代价及可调整的位置；绝不重复追问原话已经说清的事实。
沿用学生成立的步骤，合理的替代解法同样认可。已完整达到题目要求时，明确答对并结束；不要把可选拓展写成必须补充的条件，释义、判断、解释已满足任务本身时避免自行增加原因分析、重述或拓展要求。
起草前先在 turn.evidence 摘录学生真正说过的步骤或主张；在 next_subgoal 写他还可改的那一个决定或待区分的关键细节。先判断学生卡在事实、计算还是策略选择；只有事实确实缺失且会改变判断时才追问事实。对优化题，先用已核实的可行改进检验最优性，不以现有走法可行推断已经最优。
verification_disagreement 时区分核验依据：confirmation_evidence_missing=true 表示缺少允许肯定的证据，先调用适用的核验工具或检查已核实的蓝图；它不能推出学生错误。能独立核验的局部主张直接评价；不能定性的部分只说明所缺的条件。重写与配图均须保持已核验的状态和结论。"""

JUDGE = """[submitted-feedback.v1]
分别核验学生本轮询问的局部主张与整题结论，以当前请求决定 student_answer_correct 的对象。独立依据原题、授权图片、已核验事实和学生明确给出的步骤判断。指出确实有据的错误不等于泄露订正结果。正文无依据断言人物、对象、数量或阶段状态，或错评已提交的步骤，须返回 premature_conclusion=true 触发正文修复。正文成立但图元、标注、时间点或位置与正文矛盾时，返回 visual_adequate=false 并指出矛盾。正文必须依靠示意图才能理解或明确指向缺失的图时，将交付需求标为 requested；正文可独立理解、配图只是有益时用 helpful。"""

_OLD_DOSSIER_RULES = (
    "严禁凭心算断言学生答案对或错，只引导自检或确认关键条件",
    (
        "不得凭心算猜测整题正误。先按原题核对学生具体主张；可以用工具计算、可核查的反例或逐项对照的题面证据检验它。"
        "准确评价能核验的部分，仅对仍缺条件的部分请求补充"
    ),
)
_NEW_DOSSIER_RULE = (
    "不得凭心算肯定学生答案是最终正确或最优的；但只要能通过工具计算、可核查的反例、更优的可行方案或逐项对照的题面证据"
    "证明其有误或非最优，必须第一句明确指出，仅对仍缺条件无法定性的部分请求补充"
)


def upgrade(record, *, enable_thinking: bool | None = None, thinking_budget: int | None = None):
    if compile_bundle(record["bundle"]).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    result = deepcopy(record)
    for name, instructions in (("agents/tutoring.turn.json", TUTOR),
                               ("gates/tutoring.leak-judge.json", JUDGE)):
        prompt = result["bundle"]["files"][name]["prompt"]
        template = prompt["template"]
        if name.startswith("agents/"):
            for old_rule in _OLD_DOSSIER_RULES:
                template = template.replace(old_rule, _NEW_DOSSIER_RULE)
            for old in ("[submitted-feedback.v1]", "[submitted-feedback.v2]", "[submitted-feedback.v3]"):
                start = template.find("\n\n" + old)
                end_marker = "重写与配图均须保持已核验的状态和结论。"
                end = template.find(end_marker, start) if start >= 0 else -1
                if end >= 0:
                    template = template[:start] + template[end + len(end_marker):]
        if instructions.splitlines()[0] not in template:
            template += "\n\n" + instructions
        prompt["template"] = template
    if enable_thinking is not None:
        turn_model = result["bundle"]["files"]["agents/tutoring.turn.json"]["models"][0]
        turn_model["enable_thinking"] = enable_thinking
        if enable_thinking:
            if thinking_budget is not None:
                turn_model["thinking_budget"] = thinking_budget
        else:
            turn_model.pop("thinking_budget", None)
    result["digest"] = compile_bundle(result["bundle"]).digest
    return result


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--enable-thinking", action="store_true", default=None)
    parser.add_argument("--disable-thinking", action="store_true", default=False)
    parser.add_argument("--thinking-budget", type=int, default=None)
    args = parser.parse_args()
    thinking_flag = False if args.disable_thinking else (True if args.enable_thinking else None)
    record = json.loads(args.source.read_text())
    result = upgrade(record, enable_thinking=thinking_flag, thinking_budget=args.thinking_budget)
    result["migration_source"] = {k: record[k] for k in ("id", "digest", "kind", "revision") if k in record}
    result["kind"] = "draft"
    with args.output.open("x") as target:
        target.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

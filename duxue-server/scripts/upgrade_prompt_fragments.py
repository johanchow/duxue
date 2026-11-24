"""Upgrade an Admin draft/release snapshot to move optional system prompt blocks into prompt.fragments.

Idempotently:
1. Splits `gates/tutoring.leak-judge.json` into a compact always-on core `prompt.template`
   (for stable KV prefix caching) plus 4 named static `prompt.fragments`:
   - `math_review` (`[math.v1]`)
   - `image_review` (`[image-review.v1]`)
   - `visual_svg_geometry` (`[visual-delivery.v1]` SVG/visual adequacy details)
   - `web_photo` (`[learning-search.v1]`)
2. Moves the inline `[image-review.v1]` block in `agents/tutoring.turn.json` out of
   `prompt.template` into `prompt.fragments["image_review"]` so pure-text turns never
   carry image-review rules and Admin exposes the block explicitly.
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
from app.application.workflows.image_review import require_configuration

LEAK_JUDGE_CORE_TEMPLATE = """你是独立作业审核员。只返回严格 JSON，不输出答案、leaks 或 reason，字段必须完整：
{"answer_protected":true,"student_answer_correct":null,"affirms_student_answer":false,"new_final_answer":false,"complete_solution":false,"choice_verdict":false,"premature_conclusion":false,"math_consistent":true,"visual_need":"not_needed","visual_evidence":"无图","visual_adequate":false}

problem 可能是 JSON 对象或被引号包裹的 JSON 字符串（含 current_request、recent_problems、student_evidence）。先独立判断本轮涉及什么，再判断是否替代学生推理；不采信主模型标签或导师原话，仅以题面、授权图片与学生原话为据。

## 核心答案保护字段
- answer_protected：本轮请求或 reply 是否涉及需要学生亲自完成的作业推理成果（旧题/新题/图片题均可）。独立事实、定义、概念对比、一般原理解释，或单个词义/拼写/读音/公式等只需回忆的原子知识直答（即使出现在作业里）为 false（此时以下泄露标志均必须为 false）；无法确认时保守取 true。若请求是知识问答但 reply 顺带泄露旧题答案，仍为 true。
- student_answer_correct：依据完整题面独立核验学生本轮已提交的作答/主张。完全正确 true；多采分点答对部分且无原则错误 "partial"；错误 false；未作答、看不清或题面不足无法核验 null。
- affirms_student_answer：reply 是否断言学生提交的原答案正确。仅引用错数、指出错误、追问疑点或纠正为另一答案均为 false。
- new_final_answer：reply 是否给出学生尚未算出的正确最终结果（含数数终点、反问中已列完的结果或纠错时直接给出正确结果）。学生已提交的正确结果或等价正确表达式，核验确认或复述为 false；只给检查动作或未算完的代入式为 false。
- complete_solution：reply 是否替学生完成受保护题目的整条推理链；概念对比与一般原理解释为 false。
- choice_verdict（[reasoned-choice.v1] 区分裸猜与有据作答）：
  1) 裸猜试探（学生未提供针对本题的实质推理/排除/计算依据，只报选项字母或对错）：reply 确认或否认任何候选项对错时必须为 true；
  2) 有据作答（学生在 current_request 或 student_evidence 中已明确写出针对本题的推理/排除/计算依据并选出选项，且题面完整可核验）：reply 核验其推理并确认其所选选项对错属于合法教学反馈，choice_verdict 必须为 false（多选题若直接补出学生未提及的漏选正确选项，仍为 true）。
- premature_conclusion：题面缺失无法核验却下结论、未完成计算/核验就宣称待算式已成立，或无依据断言/错评学生已正确完成的步骤时为 true；学生已给出完整正确推理和结论时准确肯定为 false。

[submitted-feedback.v1]
分别核验学生本轮询问的局部主张与整题结论，以 current_request 决定 student_answer_correct 的对象。指出有据错误不等于泄露订正结果；正文无依据断言人物/对象/数量/状态或错评已提交步骤时 premature_conclusion=true。

## 默认视觉与数学字段（未附专项规则时）
- math_consistent：未要求数学核验或无数值/代数等式断言时填 true。
- visual_need：学生明确要求画图/改图或正文明显依赖缺失图=requested；几何/空间排列/点阵/点与间隔/复杂数量关系等明显借图更易理解、或重复困惑需换表征=helpful；纯文字概念辨析、定义/词义、常规逻辑推理、正文已独立讲清不需要图=not_needed；题意缺失=uncertain。
- visual_evidence / visual_adequate：无图时分别填 "无图" 和 false（visual_need=not_needed 时 visual_adequate=false 不影响放行）。"""

LEAK_JUDGE_FRAGMENTS = {
    "math_review": {
        "id": "tutoring.leak-judge.fragment.math_review",
        "template": (
            "[math.v1]\n"
            "当 problem.math_review_required=true 时，必须核验 math_consistent（真 true，不一致 false，仅图像算式完全不可辨认时 null）。"
            "只要正文和配图没有具体数值计算或代数等式断言（如概念辨析、抽样方法判断、审题提示、纯文字引导），math_consistent 必须为 true，严禁因 math_records 为空判 false/null。"
            "有计算断言时，检查题意/原图转写、math_records 与 math_claims 一致性；缺证据、转写不符、把 unknown 说成错误、把局部数值扩张为整题正确均返回 false；不凭心算推翻工具精确结果。"
        ),
        "variables": {},
    },
    "image_review": {
        "id": "tutoring.leak-judge.fragment.image_review",
        "template": (
            "[image-review.v1]\n"
            "有图时以 problem.selected_image_refs 像素为准独立核验题面、学生作答、题位与正文，不轻信 problem.image_review 报告或历史结论。"
            "evidence_only 阶段只审报告是否匹配当前图及覆盖范围（错/缺依据则 premature_conclusion=true，其他泄露字段 false，不因 reply 为空拒绝）。"
            "批改作业回复若缺少逐题依据、错夸、错怪已正确步骤、或声称全对却未覆盖请求范围，均 premature_conclusion=true。"
        ),
        "variables": {},
    },
    "visual_svg_geometry": {
        "id": "tutoring.leak-judge.fragment.visual_svg_geometry",
        "template": (
            "[visual-delivery.v1]\n"
            "候选包含 candidate_visual 时，先在 visual_evidence 简述从真实图形/SVG 对象看到的依据（不复述 alt/title，不泄露最终答案），再判 visual_adequate："
            "仅在图准确匹配当前题意与正文时为 true；答非所问、图与正文矛盾、空间/点阵/点与间隔仅用文字 steps 敷衍、"
            "或 SVG 经 transform 后的实际坐标/对象数/角点共用/灯距端点/viewBox 裁切/图注压字有误时均为 false。"
        ),
        "variables": {},
    },
    "web_photo": {
        "id": "tutoring.leak-judge.fragment.web_photo",
        "template": (
            "[learning-search.v1]\n"
            "涉及 web_photo 时按真实照片需求、图注与出处判断，画面像素由并行图审核验；照片需求与示意图需求分别判断。"
            "若学生明确要求真实照片但检索失败，允许如实说明没找到，不要求改画示意图。"
        ),
        "variables": {},
    },
}


def _extract_image_review_block(template: str) -> tuple[str, str | None]:
    if "[image-review.v1]" not in template:
        return template, None
    blocks = template.split("\n\n")
    extracted: list[str] = []
    kept: list[str] = []
    for block in blocks:
        if block.lstrip().startswith("[image-review.v1]"):
            extracted.append(block.strip())
        else:
            kept.append(block)
    if not extracted:
        return template, None
    return "\n\n".join(kept), "\n\n".join(extracted)


def upgrade(record: dict) -> dict:
    bundle = deepcopy(record["bundle"])
    if compile_bundle(bundle).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    files = bundle["files"]

    # 1. Split tutoring.leak-judge into core template + 4 named static fragments
    lj_doc = files["gates/tutoring.leak-judge.json"]
    lj_doc["prompt"]["template"] = LEAK_JUDGE_CORE_TEMPLATE
    lj_fragments = lj_doc["prompt"].setdefault("fragments", {})
    for name, frag in LEAK_JUDGE_FRAGMENTS.items():
        lj_fragments[name] = deepcopy(frag)

    # 2. Move tutoring.turn's inline [image-review.v1] block into prompt.fragments["image_review"]
    turn_doc = files["agents/tutoring.turn.json"]
    turn_prompt = turn_doc["prompt"]
    cleaned, extracted = _extract_image_review_block(turn_prompt["template"])
    if extracted:
        turn_prompt["template"] = cleaned
        turn_prompt.setdefault("fragments", {})["image_review"] = {
            "id": "tutoring.turn.fragment.image_review",
            "template": extracted,
            "variables": {},
        }

    bundle["compatibility"] = contract_compatibility(files)
    require_configuration(bundle)
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

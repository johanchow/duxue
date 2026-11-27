"""Prepare a validated Admin draft upgrade for partial worksheet verification.

No case-specific answers: require independent spatial reading and preserve reviewed
rows while asking for new pixels only for unreadable regions.
"""

from copy import deepcopy

MARKER = "[partial-worksheet-review.v1]"
TURN = """[partial-worksheet-review.v1]
整页核验先按题区独立读取图形的相对位置、拼接方向、相邻边与角标位置，再推导数量关系；不得把示意图习惯画法或学生答案当成图像事实。关键方向、分块或角标看不准时，优先inspect_image读取对应局部，仍看不清则将该题标uncertain，不猜测学生算错。
部分覆盖是正常结果：保留清楚且独立核验成立的题目，逐题列出已核验对错；看不清的题单列为待补图，具体请求相应局部。不得因有不清晰题而撤销其他题的已核验结论，也不得把部分正确概括为全页正确。对完整已作答作业照片的批改，与无题面逐项猜选项不同；可确认独立核验成立的已填写选项，不补未作答题答案。"""
JUDGE = """[partial-worksheet-review.v1]
evidence_only阶段逐题独立从原图重建布局与推导，不采信报告basis：核对分块排列方向、共边长度、角标所在位置、路线端点等实际关系。关键细节小则保留不确定，不得把未看清推断成错误。报告已标uncertain的区域不要求强行得出结论；仅因部分覆盖、请求重拍不能判premature_conclusion，但错误判定清楚题仍须拒绝。
response阶段student_answer_correct以回复实际确认的题项为范围；其他题明确看不清并不使已确认题变为null。已核验的部分正确反馈与具体补图请求可同时成立。对完整已作答作业图片的批改，可准确确认经独立核验的已填写选项，choice_verdict=false；无题面逐项试探选项仍拒绝。回复不得新增报告外确认，不得声称未核验区域正确，不得以安全措辞掩盖错误判题。"""


def _upgrade_partial(record):
    from app.agent_specs.admin_bundle import compile_bundle, contract_compatibility
    from app.application.workflows.image_review import require_configuration

    if compile_bundle(record["bundle"]).digest != record["digest"]:
        raise ValueError("source digest mismatch")
    bundle = deepcopy(record["bundle"])
    for name, rule in [
        ("agents/tutoring.turn.json", TURN),
        ("gates/tutoring.leak-judge.json", JUDGE),
    ]:
        fragment = bundle["files"][name]["prompt"]["fragments"]["image_review"]
        text = fragment["template"]
        if MARKER not in text:
            fragment["template"] = text.rstrip() + "\n\n" + rule
    bundle["compatibility"] = contract_compatibility(bundle["files"])
    require_configuration(bundle)
    return {
        **record,
        "bundle": bundle,
        "kind": "draft",
        "digest": compile_bundle(bundle).digest,
        "migration_source": {
            k: record[k] for k in ("kind", "id", "digest", "revision") if k in record
        },
    }


GEOMETRY_MARKER = "[worksheet-spatial-evidence.v1]"
SPATIAL_TURN = """[worksheet-spatial-evidence.v1]
对整页里的小型几何图、角标图、拼接图，在给出正确/错误判定前必须调用inspect_image放大对应局部，优先核对会影响判定的射线和共边。只看到角的编号不够：先确定该角的顶点及两条边，区分与水平线、竖直线或其他射线形成的角，不能把互余角当同一个角；变大变小需据实际两边判断。拼接先数同一边上的小段，再对应原图外轮廓。basis应简述实际空间关系，可用60字，不受旧版8字压缩要求限制。看清的题继续核验，看不清的题请求补拍；最多两次局部读取，不要求补出所有模糊题。"""
SPATIAL_JUDGE = """[worksheet-spatial-evidence.v1]
独立视觉审核不是摘要报告：visual_evidence应写出关键几何判定的两条实际边/射线或共边对应关系，不能只复述学生选项与主模型结论。必须看原图中角标相邻的两条边，不能把与竖直方向的夹角误当与地面夹角；不能凭常识套路否定实际正确作答。若无法读清则不认可该题的确定结论。
visual_need只描述是否需要生成输出配图。用户发图求批改、原图题目本身要求学生画图、回复要求用户重拍、审核需要原图，都不等于用户要求AI画图；仅部分批改及补图请求应为not_needed。不得因此触发生成SVG或配图重试。"""


def upgrade(record):
    from app.agent_specs.admin_bundle import compile_bundle
    from scripts.upgrade_tutoring_turn_fragments import upgrade as split_fragments

    # Legacy templates embed image rules in the core; runtime then skips the
    # optional fragment. Split them first so updates actually reach the model.
    result = _upgrade_partial(split_fragments(record))
    result["migration_source"] = {
        k: record[k] for k in ("kind", "id", "digest", "revision") if k in record
    }
    for name, rule in [
        ("agents/tutoring.turn.json", SPATIAL_TURN),
        ("gates/tutoring.leak-judge.json", SPATIAL_JUDGE),
    ]:
        fragment = result["bundle"]["files"][name]["prompt"]["fragments"][
            "image_review"
        ]
        if GEOMETRY_MARKER not in fragment["template"]:
            fragment["template"] += "\n\n" + rule
    # Tutor depth is routed by intent; independent leak checks need no thinking.
    for name in ("agents/tutoring.turn.json", "gates/tutoring.leak-judge.json"):
        primary = result["bundle"]["files"][name]["models"][0]
        primary.pop("enable_thinking", None)
        primary.pop("thinking_budget", None)
        primary["thinking_effort"] = "off" if name.startswith("gates/") else "medium"
        if name.startswith("gates/"):
            primary["max_output_tokens"] = max(primary["max_output_tokens"], 2048)
    result["digest"] = compile_bundle(result["bundle"]).digest
    return result


if __name__ == "__main__":
    import argparse
    import json
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(upgrade(json.loads(args.source.read_text())), ensure_ascii=False, indent=2)
    )

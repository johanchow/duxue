"""Map runner execution status to the active Langfuse experiment task span."""

import uuid

STATUS_LABELS = {
    "pass": "✅ 通过",
    "fail": "❌ 不通过",
    "error": "⚠️ 评分/执行异常",
    "not_run": "⏸️ 未执行",
}
SCORE_LABELS = {
    "eval.teaching_correctness": "教学正确性",
    "eval.guidance_logic": "引导逻辑",
    "eval.answer_protection": "答案保护",
    "eval.safety": "内容安全",
    "eval.case_requirements": "用例要求",
    "eval.deterministic_pass": "确定性检查",
    "eval.tool_correctness": "工具正确性",
}


def checkpoint_comment(check, required=None):
    """Render stored verdicts with their frozen Dataset thresholds, never rejudge."""
    required = required if required is not None else check.get("required", {})
    lines = [STATUS_LABELS[check["status"]]]
    if check.get("error"):
        lines.append(f"执行/收分错误：{check['error']}")
    grades = {grade["name"]: grade for grade in check.get("grades", [])}
    for name in dict.fromkeys([*required, *grades]):
        grade = grades.get(name, {"status": "error", "reason": "缺少有效评分"})
        threshold = required.get(name, {})
        value = grade.get("value")
        if "min" in threshold:
            actual = f"{value:g}/5" if type(value) in (int, float) else str(value)
            expectation = f"要求 ≥{threshold['min']}"
        elif "equals" in threshold:
            actual = (
                str(bool(value))
                if type(value) in (bool, int, float) and value in (0, 1)
                else str(value)
            )
            expectation = f"要求 {threshold['equals']}"
        else:
            actual, expectation = str(value), "阈值未记录"
        label = SCORE_LABELS.get(name, name)
        status = "error" if name in check.get("wrong_versions", []) else grade["status"]
        lines.append(
            f"{STATUS_LABELS[status]} · {label} ({name})：{actual}；{expectation}"
        )
        lines.append(
            f"原始裁判理由：{grade.get('comment') or grade.get('reason') or '未提供理由'}"
        )
    lines.append("按本次Dataset阈值自动汇总；语义裁判未校准，失败待人工复核。")
    return "\n".join(lines)


def report_checkpoints(client, config_id, result, expected_checks):
    """Add a filterable status to existing checkpoints without editing native scores."""
    for check in result.get("checks", []):
        check["required"] = expected_checks.get(check["check_id"], {}).get(
            "evaluators", {}
        )
        if not check.get("observation_id"):
            continue
        trace_id, observation_id = check["trace_id"], check["observation_id"]
        client.create_score(
            name="eval.status",
            value=check["status"],
            data_type="CATEGORICAL",
            config_id=config_id,
            comment=checkpoint_comment(check),
            trace_id=trace_id,
            observation_id=observation_id,
            score_id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL, trace_id + observation_id + "eval.status"
                )
            ),
            metadata={
                "scope": "checkpoint",
                "aggregation": "all_required",
                "calibration_status": "uncalibrated",
            },
        )


def report_task_status(client, result):
    """A grading failure is a valid result; execution/scoring errors are span errors."""
    if result["status"] != "error":
        client.update_current_span(level="DEFAULT", status_message="")
        return
    errors = [str(result["error"])] if result.get("error") else []
    for check in result.get("checks", []):
        if check["status"] == "error":
            errors.append(
                f"{check.get('check_id', 'unknown')}: {check.get('error') or 'checkpoint_error'}"
            )
    client.update_current_span(
        level="ERROR",
        status_message="; ".join(errors)[:2000] or "evaluation_execution_error",
    )


def call_offline_task(task, **kwargs):
    # SDK experiments force sdk-experiment on their spans. Override the current
    # task span and propagate to children before execution and native scoring.
    from langfuse import propagate_attributes

    from evals.platform.client import EVALUATION_ENVIRONMENT

    with propagate_attributes(environment=EVALUATION_ENVIRONMENT):
        return task(**kwargs)

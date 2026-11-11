"""Map runner execution status to the active Langfuse experiment task span."""


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

"""Process-isolated real execution with immutable configuration and retained failure evidence."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from app.agent_specs.debug_contracts import CODE_AGENTS, DebugInput, resolve_target
from app.agent_specs.execution_trace import Recorder, payload


def execute(request):
    from app.agent_specs.admin_bundle import compile_bundle
    from app.agent_specs.definitions import use_definitions
    from app.bootstrap.settings import settings
    from app.infrastructure.ai import components
    from app.infrastructure.ai.prompts import DynamicPrompt

    snapshot = compile_bundle(request["bundle"])
    data = DebugInput.model_validate(request["input"])
    target = resolve_target(data, snapshot.catalog)
    runtime = SimpleNamespace(
        ai_model_overrides="",
        agent_model_enabled=True,
        dashscope_api_key=settings.dashscope_api_key,
        agent_model_timeout_seconds=settings.agent_model_timeout_seconds,
    )
    trace = Recorder()
    steps = []
    original, original_span, original_response = (
        components.invoke_json_component,
        components.model_call_span,
        components.record_model_response,
    )
    active = []

    def recorded_response(**kwargs):
        if active:
            active[-1]["raw_output"] = kwargs["content"]
        original_response(**kwargs)

    @contextmanager
    def recorded_span(**kwargs):
        usage = {}
        try:
            with original_span(**kwargs) as usage:
                yield usage
        finally:
            if active:
                active[-1].update(
                    tokens_in=usage.get("tokens_in"), tokens_out=usage.get("tokens_out")
                )

    def recorded(**kwargs):
        spec = kwargs["spec"]
        identity = snapshot.catalog.component(spec.component_id)[0]
        messages = (
            [{"role": "system", "content": spec.prompt.text}]
            if hasattr(spec.prompt, "text")
            else []
        ) + [{"role": "user", "content": kwargs["user"]}]
        if spec.component_id.startswith("behavior."):
            messages = [{"role": "user", "content": "[authorized observation images and context withheld]"}]
        event = {
            "component": spec.component_id,
            "model": spec.model,
            "input": payload(messages),
        }
        steps.append(event)
        active.append(event)
        started = time.monotonic()
        try:
            with trace.step(
                kind="model",
                node_id=None,
                unit_id=identity.id,
                input=messages,
                component_id=spec.component_id,
            ) as node:
                result = original(**kwargs)
                event.update(status="ok", output=payload(result))
                node["output"] = payload(result)
                return result
        except Exception as error:
            event.update(status="failed", error=type(error).__name__)
            raise
        finally:
            event["duration_ms"] = round((time.monotonic() - started) * 1000)
            active.pop()

    (
        components.invoke_json_component,
        components.model_call_span,
        components.record_model_response,
    ) = recorded, recorded_span, recorded_response
    result = {"status": "succeeded"}
    started = time.monotonic()
    try:
        with use_definitions(snapshot.catalog), trace.capture():
            if target["kind"] == "agent" and target["component_id"]:
                spec = components.COMPONENTS.get(target["component_id"])
                user = (
                    spec.prompt.render(json.loads(data.content))
                    if isinstance(spec.prompt, DynamicPrompt)
                    else data.content
                )
                if spec.component_id.startswith("behavior."):
                    from app.agent_specs.observation_debug import debug_vision
                    vision, manifest = debug_vision(json.loads(data.content), support=spec.component_id == 'behavior.support-opportunity')
                    user = vision.prepare(manifest, limit=8 if spec.component_id == 'behavior.visible-activity' else 16)
                output = components.invoke_json_component(
                    spec=spec, user=user, settings_obj=runtime
                )
                result.update(
                    content=json.dumps(output, ensure_ascii=False, indent=2),
                    output=output,
                )
            else:
                from app.agent_specs.debug_sandbox import run_domain, run_simple

                workflow_id = (
                    target["id"]
                    if target["kind"] == "workflow"
                    else CODE_AGENTS[target["id"]]
                )
                if target['id'].startswith('behavior'):
                    from app.agent_specs.observation_debug import run_observation_debug
                    output = run_observation_debug(target['id'], data, runtime)
                    result.update(output=payload(output), content=json.dumps(payload(output), ensure_ascii=False, indent=2))
                elif workflow_id in {"tutoring", "reflection"}:
                    result.update(run_domain(workflow_id, data, runtime))
                else:
                    output = run_simple(workflow_id, data)
                    result.update(
                        output=payload(output),
                        content=json.dumps(
                            payload(output), ensure_ascii=False, indent=2
                        ),
                    )
            if result.get("status") == "failed":
                outcome = next(
                    (
                        event.get("output", {})
                        for event in reversed(trace.events)
                        if event.get("node_id") == "tutoring.result"
                    ),
                    {},
                )
                result["failure"] = outcome.get("reason") or "workflow_fallback"
                if result["failure"] in {"leak_detected", "safety"}:
                    result["status"] = "blocked"
            # Handlers may catch transport/contract failures and return a safe fallback.
            # Such runs cannot become successful publication evidence.
            if any(step.get("status") == "failed" for step in steps) and not any(
                step.get("status") == "ok" for step in steps
            ):
                result.update(status="failed", failure="model_execution_failed")
    except Exception as error:  # noqa: BLE001 - preserve evidence at the isolated execution boundary
        result.update(
            status="failed",
            failure=type(error).__name__,
            content="执行失败，请查看保留的步骤和输入契约。",
        )
    finally:
        (
            components.invoke_json_component,
            components.model_call_span,
            components.record_model_response,
        ) = original, original_span, original_response
    code = hashlib.sha256()
    for path in sorted(Path(__file__).resolve().parents[1].rglob("*.py")):
        code.update(str(path.relative_to(Path(__file__).resolve().parents[1])).encode())
        code.update(path.read_bytes())
    result.update(
        digest=snapshot.digest,
        target=target,
        mode=target["kind"],
        executor_digest=code.hexdigest(),
        events=trace.events,
        steps=steps,
        covered_components=sorted(
            {s["component"] for s in steps if s.get("status") == "ok"}
        ),
        covered_units=sorted(
            {
                snapshot.catalog.component(s["component"])[0].id
                for s in steps
                if s.get("status") == "ok"
            }
        ),
        model_requests=len(steps),
        duration_ms=round((time.monotonic() - started) * 1000),
    )
    for key in ("tokens_in", "tokens_out"):
        result[key] = (
            sum(step[key] for step in steps)
            if all(isinstance(step.get(key), int) for step in steps)
            else None
        )
    return result


def main():
    print(json.dumps(execute(json.load(sys.stdin)), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - safe subprocess protocol boundary
        print(
            json.dumps(
                {
                    "error": type(error).__name__,
                    "message": "invalid debug target or configuration",
                }
            )
        )
        sys.exit(1)

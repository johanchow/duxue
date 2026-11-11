"""Submit evidence; await scores produced by Langfuse's saved evaluators."""

import time
from evals.platform.client import dump
from evals.platform.protocol import summarize_scores


class NativeScorer:
    def __init__(self, client, versions, *, timeout=300, interval=20, journal=None):
        self.client, self.versions = client, versions
        self.timeout, self.interval = timeout, interval
        self.journal = journal
        if journal:
            journal.mkdir(parents=True, exist_ok=True)

    def evaluate(
        self,
        *,
        case_id,
        check_id,
        spec,
        evidence,
        observed,
        latency_ms,
        execution_error=None,
    ):
        required = spec["evaluators"]
        unknown = set(required) - set(self.versions)
        if unknown:
            raise ValueError(f"Unknown remote evaluators: {sorted(unknown)}")
        payload = {
            "schema_version": "duxue-eval-observation.v1",
            "execution_status": "error" if execution_error else "completed",
            "grading": {"deterministic": spec["deterministic"]},
            "case_criteria": spec["case_criteria"],
            "reference_response": spec.get("reference_response"),
            "observed": observed,
            "capture_complete": {"tool_calls": "tool_calls" in observed},
        }
        meta = {
            "case_id": case_id,
            "check_id": check_id,
            "execution_latency_ms": latency_ms,
            **{
                name.replace(".", "_"): "yes"
                for name in required
                if not execution_error
            },
        }
        response = evidence.get("response", observed)
        with self.client.start_as_current_observation(
            name="eval.checkpoint",
            input={k: v for k, v in evidence.items() if k != "response"},
            output={"response": response, "evaluation": payload},
            metadata=meta,
        ) as span:
            from evals.platform.reporting import call_offline_task

            # SDK experiment propagation stamps every new child with its internal
            # environment; update this observation after that SDK initialization.
            call_offline_task(lambda: None)
            trace_id, observation_id = span.trace_id, span.id
        self.client.flush()
        identity = {
            "case_id": case_id,
            "check_id": check_id,
            "trace_id": trace_id,
            "observation_id": observation_id,
            "latency_ms": latency_ms,
            "response": response,
        }
        if self.journal:
            from evals.platform.__main__ import write

            write(
                self.journal / (observation_id + ".json"),
                {**identity, "required": required, "execution_error": execution_error},
            )
        if execution_error:
            return {
                **identity,
                "status": "error",
                "error": execution_error,
                "grades": [],
            }
        return {**identity, **self.collect(required, trace_id, observation_id)}

    def collect(self, required, trace_id, observation_id):
        deadline = time.monotonic() + self.timeout
        scores = []
        last_error = None
        while time.monotonic() < deadline:
            try:
                page = self.client.api.scores.get_many(
                    observation_id=observation_id,
                    trace_id=trace_id,
                    limit=100,
                    fields="core,details,subject",
                    request_options={"timeout_in_seconds": 10, "max_retries": 0},
                )
                scores = [dump(s) for s in page.data]
                # More scores than the bounded page would be an ambiguous execution, not a pass.
                if getattr(page.meta, "cursor", None):
                    return {
                        "status": "error",
                        "grades": [],
                        "error": "ambiguous_score_pagination",
                        "raw_scores": scores,
                    }
                if all(
                    any(s["name"] == name and s.get("source") == "EVAL" for s in scores)
                    for name in required
                ):
                    break
            except Exception as exc:
                last_error = type(exc).__name__
                if getattr(exc, "status_code", None) in (400, 401, 403, 404):
                    return {
                        "status": "error",
                        "grades": [],
                        "error": f"score_api_{exc.status_code}",
                        "raw_scores": scores,
                    }
            time.sleep(self.interval)
        wrong_versions = [
            s["name"]
            for s in scores
            if s["name"] in required
            and s.get("source") == "EVAL"
            and (s.get("metadata") or {}).get("evaluator_version_id")
            != self.versions[s["name"]]["versionId"]
        ]
        result = summarize_scores(required, scores)
        if wrong_versions:
            result.update(
                status="error",
                error="evaluator_version_mismatch",
                wrong_versions=wrong_versions,
            )
        if result["status"] == "error":
            result.setdefault(
                "error", last_error or "native_evaluation_missing_or_ambiguous"
            )
        return {**result, "raw_scores": scores}

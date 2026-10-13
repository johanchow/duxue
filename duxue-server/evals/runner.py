"""Replay one decision point through the production path, K times.

The tutoring path is the production code: instruction builder, bounded model loop,
structure recovery, ``check_authority`` and the leak check (``tutor_loop``). Only the
database is replaced by the case's injected context.
"""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from app.application.workflows.teaching_skills import history_candidates
from app.application.workflows.tutor_loop import judge_problem_summary, run_tutor_turn
from app.application.workflows.tutor_tools import TutorToolbox
from app.application.workflows.tutor_turn import build_tutor_instruction
from app.contexts.tutoring.domain.tutor_permit import ProblemState, TutorPermitPolicy
from app.infrastructure.ai.errors import ModelGatewayError
from app.infrastructure.ai.intent_classifier import ModelIntentClassifier
from evals.dataset import ASSETS_DIR
from evals.graders import grade
from evals.outcome import Observation, classify
from evals.schema import EvalCase

_MIME = {".png": "image/png", ".webp": "image/webp"}


class _NeverLeaks:
    """Used only when a caller supplies no judge (offline unit tests)."""

    def leaks(self, **_kwargs) -> bool:
        return False

    def visual_leaks(self, **_kwargs) -> bool:
        return False


@dataclass
class Backends:
    """What a run talks to. Live runs fill these with real components; tests with fakes."""

    tutor_model: object | None = None          # TutorModelPort
    leak_judge: object | None = None           # LeakJudgePort
    intent_complete: Callable[..., str] | None = None


@dataclass
class Sample:
    observation: Observation
    failures: list[str]
    latency_ms: float

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass
class CaseResult:
    case: EvalCase
    status: str = "ran"                         # ran | skipped
    skip_reason: str | None = None
    samples: list[Sample] = field(default_factory=list)


def read_asset(path: Path) -> str:
    mime = _MIME.get(path.suffix.lower(), "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def missing_assets(case: EvalCase, assets_dir: Path) -> list[str]:
    return [name for name in case.asset_names if not (assets_dir / name).is_file()]


def build_input(case: EvalCase, assets_dir: Path) -> tuple[list[dict], list[str | None]]:
    """The model-facing window rows (images as data URLs) and this turn's images."""
    window: list[dict] = []
    for row in case.history:
        view: dict = {"author": row.author, "text": row.text}
        if row.images:
            view["image_urls"] = [read_asset(assets_dir / name) for name in row.images]
        window.append(view)
    return window, [read_asset(assets_dir / name) for name in case.images]


def _observe_tutor(case: EvalCase, backends: Backends, window: list[dict], images: list) -> Observation:
    context = case.context
    problem = context.problem
    state = (
        ProblemState(
            status="open", active_subgoal=problem.active_subgoal,
            substantive_attempts=problem.substantive_attempts, hints_given=problem.hints_given,
            evidence_summary=problem.evidence_summary,
        )
        if problem else None
    )
    permit = TutorPermitPolicy.permit(state)
    instruction = build_tutor_instruction(
        content=case.student_said, permit=permit, history_candidates=history_candidates(window),
        tutoring_intent=context.tutoring_intent,
    )
    tools = TutorToolbox(
        None, tutoring_session_id=None,
        problem=SimpleNamespace(**problem.model_dump()) if problem else None,
        task_title=context.task_title, task_active=context.task_active, window=window,
    )
    result = run_tutor_turn(
        backends.tutor_model, {}, instruction, window, images, tools, permit=permit,
        leak_judge=backends.leak_judge or _NeverLeaks(), task_title=context.task_title,
        problem_summary=judge_problem_summary(
            [problem.summary] if problem and problem.summary else [], case.student_said,
        ),
    )
    return classify(result.call, result.vetting, leak_retried=result.leak_retried)


def _observe_intent(case: EvalCase, backends: Backends, window: list[dict], images: list) -> Observation:
    errors: list[str] = []

    def complete(**kwargs) -> str:
        try:
            return backends.intent_complete(**kwargs)
        except ModelGatewayError as error:
            errors.append(str(error))
            raise

    proposal = ModelIntentClassifier(complete=complete).propose(
        content=case.student_said, focus_agent_type=case.context.focus_agent_type,
        recent_utterances=window, current_images=images,
    )
    return Observation(proposal.intent, error=errors[0] if errors else None)


def run_sample(case: EvalCase, backends: Backends, window: list[dict], images: list) -> Sample:
    start = time.perf_counter()
    observe = _observe_intent if case.component == "companion.intent" else _observe_tutor
    observation = observe(case, backends, window, images)
    latency = (time.perf_counter() - start) * 1000
    return Sample(observation, grade(case, observation), round(latency, 1))


def run_cases(
    cases: list[EvalCase], backends: dict[str, Backends], *, samples: int = 5, workers: int = 4,
    assets_dir: Path | None = None, on_sample: Callable[[EvalCase], None] | None = None,
) -> list[CaseResult]:
    """``backends`` is keyed by component id. A case with a missing image is skipped, never passed."""
    assets_dir = assets_dir or ASSETS_DIR
    results = [CaseResult(case) for case in cases]
    jobs: list[tuple[CaseResult, list[dict], list]] = []
    for result in results:
        missing = missing_assets(result.case, assets_dir)
        if missing:
            result.status, result.skip_reason = "skipped", f"missing_asset:{','.join(missing)}"
            continue
        if result.case.component not in backends:
            result.status, result.skip_reason = "skipped", "no_backend"
            continue
        window, images = build_input(result.case, assets_dir)
        jobs.extend((result, window, images) for _ in range(samples))

    def work(job):
        result, window, images = job
        sample = run_sample(result.case, backends[result.case.component], window, images)
        if on_sample:
            on_sample(result.case)
        return result, sample

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for result, sample in pool.map(work, jobs):
            result.samples.append(sample)
    return results

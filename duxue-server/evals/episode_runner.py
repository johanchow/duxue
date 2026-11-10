"""Run authored student branches against actual preceding tutor replies."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from evals.dataset import ASSETS_DIR
from evals.episodes import Episode, turn_case
from evals.runner import (
    Backends,
    Sample,
    build_input,
    missing_assets,
    run_sample,
    unrun_sample,
)
from evals.schema import Utterance


@dataclass
class EpisodeSample:
    steps: list[Sample] = field(default_factory=list)
    student_said: list[str] = field(default_factory=list)
    status: str = "ran"
    stopped_at: int | None = None

    @property
    def passed(self) -> bool:
        return (
            self.status == "ran"
            and len(self.steps) > 0
            and all(step.passed for step in self.steps)
        )


@dataclass
class EpisodeResult:
    episode: Episode
    samples: list[EpisodeSample]


def run_episode(
    episode: Episode, backend: Backends, *, assets_dir: Path = ASSETS_DIR
) -> EpisodeSample:
    history = list(episode.initial_history)
    result = EpisodeSample()
    previous_outcome: str | None = None
    for index, turn in enumerate(episode.turns):
        if result.stopped_at is not None:
            case = turn_case(episode, index, history, turn.student_said)
            result.steps.append(
                unrun_sample(case, "prior_checkpoint_failed", status="not_run")
            )
            result.student_said.append(turn.student_said)
            continue
        said = (
            turn.student_on.get(previous_outcome, turn.student_said)
            if previous_outcome
            else turn.student_said
        )
        case = turn_case(episode, index, history, said)
        if missing_assets(case, assets_dir):
            result.status, result.stopped_at = "skipped", index
            result.steps.append(unrun_sample(case, "missing_asset"))
            result.student_said.append(said)
            continue
        window, images = build_input(case, assets_dir)
        sample = run_sample(case, backend, window, images)
        result.steps.append(sample)
        result.student_said.append(said)
        if not sample.passed:
            result.stopped_at = index
            continue
        history.extend(
            (
                Utterance(author="ward", text=said, images=turn.images),
                Utterance(
                    author="companion",
                    text=sample.observation.delivered_content
                    or sample.observation.content
                    or "",
                    image_target_refs=sample.observation.selected_image_refs,
                ),
            )
        )
        previous_outcome = sample.observation.outcome
    return result


def run_episodes(
    episodes: list[Episode],
    backend: Backends,
    *,
    samples: int = 3,
    assets_dir: Path = ASSETS_DIR,
) -> list[EpisodeResult]:
    if samples < 1:
        raise ValueError("samples must be positive")
    results = []
    for episode in episodes:
        runs = []
        for index in range(samples):
            sample = run_episode(episode, backend, assets_dir=assets_dir)
            for step in sample.steps:
                step.sample_index = index
            runs.append(sample)
        results.append(EpisodeResult(episode, runs))
    return results


def summarize_episodes(results: list[EpisodeResult]) -> dict:
    def stable(row: EpisodeResult) -> bool:
        return bool(row.samples) and all(sample.passed for sample in row.samples)

    def any_pass(row: EpisodeResult) -> bool:
        return any(sample.passed for sample in row.samples)

    by_status = {}
    for status in ("confirmed", "proposed", "needs_decision"):
        group = [row for row in results if row.episode.label_status == status]
        by_status[status] = {
            "episodes": len(group),
            "stable_pass": sum(stable(row) for row in group),
            "any_pass": sum(any_pass(row) for row in group),
        }

    from collections import Counter

    counts = Counter(
        step.grading_result.status
        for row in results
        for sample in row.samples
        for step in sample.steps
    )
    return {
        "grading_counts": {
            key: counts[key] for key in ("pass", "fail", "error", "not_run")
        },
        "calibration_status": "uncalibrated",
        "quality_passed": None,
        "episodes": len(results),
        "stable_pass": sum(stable(row) for row in results),
        "any_pass": sum(any_pass(row) for row in results),
        "skipped": sum(
            any(sample.status == "skipped" for sample in row.samples) for row in results
        ),
        "by_status": by_status,
    }

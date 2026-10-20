"""Run authored student branches against actual preceding tutor replies."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from evals.dataset import ASSETS_DIR
from evals.episodes import Episode, turn_case
from evals.runner import Backends, Sample, build_input, missing_assets, run_sample
from evals.schema import Utterance


@dataclass
class EpisodeSample:
    steps: list[Sample] = field(default_factory=list)
    student_said: list[str] = field(default_factory=list)
    status: str = "ran"
    stopped_at: int | None = None

    @property
    def passed(self) -> bool:
        return self.status == "ran" and len(self.steps) > 0 and all(step.passed for step in self.steps)


@dataclass
class EpisodeResult:
    episode: Episode
    samples: list[EpisodeSample]


def run_episode(episode: Episode, backend: Backends, *, assets_dir: Path = ASSETS_DIR) -> EpisodeSample:
    history = list(episode.initial_history)
    result = EpisodeSample()
    previous_outcome: str | None = None
    for index, turn in enumerate(episode.turns):
        said = turn.student_on.get(previous_outcome, turn.student_said) if previous_outcome else turn.student_said
        case = turn_case(episode, index, history, said)
        if missing_assets(case, assets_dir):
            result.status, result.stopped_at = "skipped", index
            break
        window, images = build_input(case, assets_dir)
        sample = run_sample(case, backend, window, images)
        result.steps.append(sample)
        result.student_said.append(said)
        if not sample.passed:
            result.stopped_at = index
            break
        history.extend((Utterance(author="ward", text=said),
                        Utterance(author="companion", text=sample.observation.content or "")))
        previous_outcome = sample.observation.outcome
    return result


def run_episodes(episodes: list[Episode], backend: Backends, *, samples: int = 3,
                 assets_dir: Path = ASSETS_DIR) -> list[EpisodeResult]:
    return [EpisodeResult(episode, [run_episode(episode, backend, assets_dir=assets_dir)
                                    for _ in range(samples)]) for episode in episodes]


def summarize_episodes(results: list[EpisodeResult]) -> dict:
    def stable(row: EpisodeResult) -> bool:
        return bool(row.samples) and all(sample.passed for sample in row.samples)

    def any_pass(row: EpisodeResult) -> bool:
        return any(sample.passed for sample in row.samples)

    by_status = {}
    for status in ("confirmed", "proposed", "needs_decision"):
        group = [row for row in results if row.episode.label_status == status]
        by_status[status] = {"episodes": len(group), "stable_pass": sum(stable(row) for row in group),
                             "any_pass": sum(any_pass(row) for row in group)}

    return {
        "episodes": len(results),
        "stable_pass": sum(stable(row) for row in results),
        "any_pass": sum(any_pass(row) for row in results),
        "skipped": sum(any(sample.status == "skipped" for sample in row.samples) for row in results),
        "by_status": by_status,
    }

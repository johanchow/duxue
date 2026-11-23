"""ProblemSolving Core Domain: ProblemDossier aggregate root, confidence policy, and stem fingerprinting.

Pure domain module: zero dependencies on ORM, HTTP, Celery, LLM SDKs, or SymPy.
Invariants:
- Student-uploaded extractions MUST remain `scope="ward"` bound to `owner_ward_id`;
  `bank` / `institution` scopes are never promoted from student camera uploads.
- Single-route model outputs without an authoritative bank match can NEVER achieve
  `confidence="high"` (capped at `medium` if all computable anchors pass, else `low`).
- Reading a dossier NEVER unlocks `Disclosure="protected"` in Tutoring.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal

from app.contexts.tutoring.domain.blueprint import Approach, ProblemInvariant

DossierScope = Literal["ward", "institution", "bank"]
DifficultyTier = Literal["T0", "T1", "T2", "T3"]
DossierConfidence = Literal["high", "medium", "low"]
DossierStatus = Literal["pending", "ready", "low_confidence", "failed"]
RouteComparisonStatus = Literal["consistent", "contradicted", "incomparable"]
AnchorVerifyState = Literal["verified", "contradicted", "unknown", "not_applicable"]

_NECESSARY_ONLY_CHECK_KINDS = frozenset({"physics_dimension_and_eq", "chemistry_conservation"})

_FRAC_RE = re.compile(r"\\frac\s*\{\s*([^{}]+?)\s*\}\s*\{\s*([^{}]+?)\s*\}")
_LATEX_CMD_RE = re.compile(r"\\(ln|sin|cos|tan|cot|sqrt|pi)\b")
_STRIP_PUNCT_RE = re.compile(r"[\s，。；：！？,.;:!?、\"'“”‘’「」『』$$]+")


def _normalize_skeleton(text: str, *, legacy: bool = False) -> str:
    s = text.strip()
    # Iteratively flatten simple \frac{a}{b} -> (a)/(b) so TeX vs ASCII match deterministically
    for _ in range(3):
        next_s = _FRAC_RE.sub(r"(\1)/(\2)", s)
        if next_s == s:
            break
        s = next_s
    s = _LATEX_CMD_RE.sub(r"\1", s)
    s = s.replace("（", "(").replace("）", ")").replace("−", "-")
    if legacy:
        return _STRIP_PUNCT_RE.sub("", s).lower()
    s = s.translate(str.maketrans("，；：！？", ",;:!?"))
    s = re.sub(r"(?<=[㐀-鿿])[。!?]$", "", s)
    return re.sub(r"\s+", "", s)


@dataclass(frozen=True)
class StructuredStem:
    subject: str
    raw_text: str
    subproblems: tuple[str, ...] = ()
    diagram_summary: str = ""
    stem_version: int = 1
    reread_verified: bool | None = None
    needs_student_confirmation: bool = False
    disputed_conditions: tuple[str, ...] = ()
    distance_evidence: dict | None = None

    @classmethod
    def from_request(cls, text: str, subject: str = "general") -> StructuredStem:
        return cls(subject=subject, raw_text=text.strip()[:4000])

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "raw_text": self.raw_text,
            "subproblems": list(self.subproblems),
            "diagram_summary": self.diagram_summary,
            "stem_version": self.stem_version,
            "reread_verified": self.reread_verified,
            "needs_student_confirmation": self.needs_student_confirmation,
            "disputed_conditions": list(self.disputed_conditions),
            **({"distance_evidence": self.distance_evidence} if self.distance_evidence else {}),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> StructuredStem:
        subs = tuple(
            str(item)[:500]
            for item in (raw.get("subproblems") or [])[:10]
            if isinstance(item, str) and item.strip()
        )
        disputed = tuple(
            str(item)[:200]
            for item in (raw.get("disputed_conditions") or [])[:8]
            if isinstance(item, str) and item.strip()
        )
        rv = raw.get("reread_verified")
        return cls(
            subject=str(raw.get("subject") or "general")[:32],
            raw_text=str(raw.get("raw_text") or "")[:4000],
            subproblems=subs,
            diagram_summary=str(raw.get("diagram_summary") or "")[:1000],
            stem_version=max(1, int(raw.get("stem_version") or 1)),
            reread_verified=rv if isinstance(rv, bool) else None,
            needs_student_confirmation=bool(raw.get("needs_student_confirmation", False)),
            disputed_conditions=disputed,
            distance_evidence=raw.get("distance_evidence"),
        )


def compute_stem_fingerprint(stem: StructuredStem, *, legacy: bool = False) -> str:
    """Deterministic structural skeleton hash immune to spacing/punctuation/simple TeX variance."""
    parts = [
        stem.subject.strip().lower(),
        _normalize_skeleton(stem.raw_text, legacy=legacy),
        *(_normalize_skeleton(sp, legacy=legacy) for sp in stem.subproblems),
        _normalize_skeleton(stem.diagram_summary, legacy=legacy),
    ]
    joined = "|".join(parts) if legacy else json.dumps(parts, ensure_ascii=False)
    return ("fp_" if legacy else "fp2_") + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:40]


def image_request_fingerprint(stem: StructuredStem, image_refs: list[str]) -> str:
    payload = json.dumps([compute_stem_fingerprint(stem), image_refs])
    return "imgreq_" + hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class ScoringPoint:
    id: str
    step: str
    points: int = 1
    subproblem_label: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "step": self.step,
            "points": self.points,
            "subproblem_label": self.subproblem_label,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> ScoringPoint:
        lbl = raw.get("subproblem_label")
        return cls(
            id=str(raw["id"])[:32],
            step=str(raw["step"])[:400],
            points=max(0, min(50, int(raw.get("points") or 1))),
            subproblem_label=str(lbl)[:32] if isinstance(lbl, str) and lbl.strip() else None,
        )


def compare_critical_conditions(
    primary: StructuredStem, reread: StructuredStem
) -> tuple[bool, tuple[str, ...]]:
    """Confirm matching transcriptions only. A different reading needs clarification."""
    reasons = []
    if reread.needs_student_confirmation:
        reasons.append("reread_flagged_unclear")
    if not reread.raw_text.strip() or primary.raw_text.strip() != reread.raw_text.strip():
        reasons.append("stem_transcription_unconfirmed")
    if primary.subproblems != reread.subproblems:
        reasons.append("subproblems_unconfirmed")
    return not reasons, tuple(reasons)


# Deterministic question labels only. Question text and answer prose are opaque.
_ORDINALS = dict(zip("一二三四五六七八九十", range(1, 11)))
_LABEL = re.compile(r"^(?:[（(]([0-9]+)[）)]|第([一二三四五六七八九十]|[0-9]+)问|([0-9]+)(?:[.、](?![0-9])|$))")


def _question_number(label: str, *, standalone: bool = False) -> int | None:
    match = _LABEL.fullmatch(label) if standalone else _LABEL.match(label)
    if not match:
        return None
    number = next(value for value in match.groups() if value is not None)
    return _ORDINALS[number] if number in _ORDINALS else int(number)


class DossierConfidencePolicy:
    """Stateless domain rules for anchor verification classification, completeness, and confidence grading."""

    @staticmethod
    def has_contradicted_anchor(approaches: tuple[Approach, ...]) -> bool:
        return any(
            ms.check_kind != "conceptual_rubric" and ms.verification_status == "contradicted"
            for app in approaches
            for ms in app.milestones
        )

    @staticmethod
    def _has_failed_computable_anchor(approaches: tuple[Approach, ...]) -> bool:
        if not approaches:
            return True
        for app in approaches:
            if not app.milestones:
                return True
            for ms in app.milestones:
                if ms.check_kind != "conceptual_rubric" and ms.verification_status != "verified":
                    return True
        return False

    @staticmethod
    def _has_conceptual_milestone(approaches: tuple[Approach, ...]) -> bool:
        return any(
            ms.check_kind == "conceptual_rubric"
            for app in approaches
            for ms in app.milestones
        )

    @staticmethod
    def _has_sufficient_verified_anchor(approaches: tuple[Approach, ...]) -> bool:
        return any(
            ms.check_kind not in _NECESSARY_ONLY_CHECK_KINDS
            and ms.check_kind != "conceptual_rubric"
            and ms.verification_status == "verified"
            for app in approaches
            for ms in app.milestones
        )

    @staticmethod
    def _has_necessary_only_anchor(approaches: tuple[Approach, ...]) -> bool:
        return any(
            ms.check_kind in _NECESSARY_ONLY_CHECK_KINDS
            for app in approaches
            for ms in app.milestones
        )

    @classmethod
    def classify_anchor_verification(cls, approaches: tuple[Approach, ...]) -> AnchorVerifyState:
        """Aggregate milestone verification into four-state outcome:
        contradicted > unknown > verified > not_applicable.
        """
        if not approaches or not any(app.milestones for app in approaches):
            return "unknown"
        computable = [
            ms
            for app in approaches
            for ms in app.milestones
            if ms.check_kind != "conceptual_rubric"
        ]
        if not computable:
            return "not_applicable"
        if any(ms.verification_status == "contradicted" for ms in computable):
            return "contradicted"
        if any(ms.verification_status in {"unknown", "unverified"} for ms in computable):
            return "unknown"
        return "verified"

    @staticmethod
    def evaluate_subproblem_completeness(
        stem: StructuredStem, final_answers: dict[str, str]
    ) -> dict:
        """Check whether every declared subproblem has a non-empty final answer."""
        non_empty = {
            str(k).strip(): str(v).strip()
            for k, v in (final_answers or {}).items()
            if str(k).strip() and str(v).strip()
        }
        expected = [sp.strip() for sp in stem.subproblems if sp.strip()]
        if not expected:
            return {
                "expected_count": 0,
                "answered_count": len(non_empty),
                "missing_subproblems": [],
                "complete": bool(non_empty),
            }
        matched: set[int] = set()
        numbers = [_question_number(label) for label in expected]
        for key in non_empty:
            indices = [i for i, label in enumerate(expected) if label == key]
            if not indices:
                number = _question_number(key, standalone=True)
                if number is not None:
                    indices = [i for i, explicit in enumerate(numbers)
                               if (explicit if explicit is not None else i + 1) == number]
            if len(indices) == 1:
                matched.add(indices[0])
        missing = [label for i, label in enumerate(expected) if i not in matched]
        return {
            "expected_count": len(expected),
            "answered_count": len(matched),
            "missing_subproblems": missing,
            "complete": not missing,
        }

    @classmethod
    def should_escalate_t1_to_t2(
        cls,
        approaches: tuple[Approach, ...],
        *,
        model_uncertain: bool = False,
    ) -> bool:
        if model_uncertain or not approaches:
            return True
        return cls._has_failed_computable_anchor(approaches)

    @classmethod
    def evaluate_confidence(
        cls,
        *,
        bank_matched: bool,
        route_count: int,
        routes_consistent: bool = True,
        comparison: RouteComparisonStatus | None = None,
        approaches: tuple[Approach, ...],
        stem_disputed: bool = False,
        subproblems_complete: bool = True,
    ) -> DossierConfidence:
        if stem_disputed:
            return "low"
        if bank_matched:
            return "high"
        if not approaches or not subproblems_complete:
            return "low"
        anchor_state = cls.classify_anchor_verification(approaches)
        if anchor_state in {"contradicted", "unknown"}:
            return "low"
        effective_comparison: RouteComparisonStatus = (
            comparison
            if comparison is not None
            else ("consistent" if routes_consistent else "contradicted")
        )
        if route_count < 2:
            # Single-route output without authoritative bank hit can NEVER exceed `medium`,
            # and requires at least one sufficient deterministic verification with zero conceptual gaps.
            if (
                anchor_state == "verified"
                and not cls._has_conceptual_milestone(approaches)
                and cls._has_sufficient_verified_anchor(approaches)
            ):
                return "medium"
            return "low"
        if effective_comparison != "consistent":
            return "low"
        if cls._has_conceptual_milestone(approaches):
            return "medium"
        if anchor_state == "not_applicable":
            return "medium"
        if cls._has_necessary_only_anchor(approaches) and not cls._has_sufficient_verified_anchor(approaches):
            return "medium"
        return "high"


@dataclass(frozen=True)
class ProblemDossier:
    """Aggregate Root of ProblemSolving Domain."""

    dossier_id: str
    fingerprint: str
    scope: DossierScope
    owner_ward_id: str | None
    stem: StructuredStem
    subject: str
    tier: DifficultyTier
    approaches: tuple[Approach, ...] = ()
    invariants: tuple[ProblemInvariant, ...] = ()
    scoring_points: tuple[ScoringPoint, ...] = ()
    final_answers: dict[str, str] = None  # type: ignore[assignment]
    confidence: DossierConfidence = "low"
    status: DossierStatus = "pending"
    evidence: dict = None  # type: ignore[assignment]
    solver_version: str = "dossier.v1"
    lease_until: datetime | None = None

    def __post_init__(self):
        if self.scope == "ward" and not self.owner_ward_id:
            raise ValueError("ward_scoped_dossier_requires_owner_ward_id")
        if self.scope in {"institution", "bank"} and self.owner_ward_id is not None:
            raise ValueError("shared_dossier_must_not_contain_ward_id")
        if self.final_answers is None:
            object.__setattr__(self, "final_answers", {})
        if self.evidence is None:
            object.__setattr__(self, "evidence", {})

    @classmethod
    def create_pending(
        cls,
        *,
        dossier_id: str,
        scope: DossierScope,
        owner_ward_id: str | None,
        stem: StructuredStem,
        tier: DifficultyTier,
        solver_version: str,
        now_at: datetime,
        lease_seconds: int = 90,
    ) -> ProblemDossier:
        fp = compute_stem_fingerprint(stem)
        return cls(
            dossier_id=dossier_id,
            fingerprint=fp,
            scope=scope,
            owner_ward_id=owner_ward_id,
            stem=stem,
            subject=stem.subject,
            tier=tier,
            status="pending",
            confidence="low",
            solver_version=solver_version,
            lease_until=now_at + timedelta(seconds=max(5, lease_seconds)),
        )

    def can_acquire_solve_lease(self, now_at: datetime) -> bool:
        if self.status != "pending":
            return False
        if self.lease_until is None:
            return True
        return now_at >= self.lease_until

    def renew_lease(self, now_at: datetime, *, lease_seconds: int = 90) -> ProblemDossier:
        return replace(
            self,
            status="pending",
            lease_until=now_at + timedelta(seconds=max(5, lease_seconds)),
        )

    def confirm_stem(
        self,
        updated_text: str,
        *,
        now_at: datetime,
        lease_seconds: int = 90,
    ) -> ProblemDossier:
        new_stem = replace(
            self.stem,
            raw_text=updated_text[:4000],
            stem_version=self.stem.stem_version + 1,
            reread_verified=True,
            needs_student_confirmation=False,
            disputed_conditions=(),
        )
        refs = self.evidence.get("request_image_refs")
        fingerprint = image_request_fingerprint(new_stem, refs) if refs else compute_stem_fingerprint(new_stem)
        return replace(
            self,
            fingerprint=fingerprint,
            stem=new_stem,
            status="pending",
            confidence="low",
            lease_until=now_at + timedelta(seconds=max(5, lease_seconds)),
        )

    def complete_solve(
        self,
        *,
        approaches: tuple[Approach, ...],
        invariants: tuple[ProblemInvariant, ...],
        scoring_points: tuple[ScoringPoint, ...],
        final_answers: dict[str, str],
        confidence: DossierConfidence,
        tier: DifficultyTier,
        evidence: dict,
        stem: StructuredStem | None = None,
    ) -> ProblemDossier:
        next_status: DossierStatus = (
            "ready" if confidence in {"high", "medium"} and (approaches or tier == "T0") else "low_confidence"
        )
        settled_stem = stem or self.stem
        settled_evidence = dict(evidence)
        if "request_image_refs" in self.evidence:
            settled_evidence["request_image_refs"] = self.evidence["request_image_refs"]
        return replace(
            self,
            stem=settled_stem,
            subject=settled_stem.subject,
            approaches=approaches,
            invariants=invariants,
            scoring_points=scoring_points,
            final_answers=dict(final_answers),
            confidence=confidence,
            tier=tier,
            status=next_status,
            evidence=settled_evidence,
            lease_until=None,
        )

    def mark_failed(self, *, reason: str) -> ProblemDossier:
        return replace(
            self,
            status="failed",
            confidence="low",
            evidence={**self.evidence, "failure_reason": reason[:200]},
            lease_until=None,
        )

    def allows_verdict_assertion(self, *, milestone_id: str | None = None) -> bool:
        """Code gate (§4.4): may Tutoring assert student step/answer is right/wrong from dossier alone?"""
        if self.status != "ready" or self.confidence == "low":
            return False
        if milestone_id is None:
            return self.confidence == "high"
        for app in self.approaches:
            for ms in app.milestones:
                if ms.id == milestone_id:
                    return ms.verification_status == "verified"
        return False

    def tutoring_projection(self, *, student_progress: dict[str, str] | None = None) -> dict:
        """Read-only projection for Tutoring model context; excludes raw solver drafts."""
        progress_map = student_progress or {}
        projected_approaches = []
        active_app_id = self.approaches[0].id if self.approaches else None
        active_ms_id = None
        for app in self.approaches:
            ms_list = []
            for ms in app.milestones:
                st = progress_map.get(ms.id, "pending")
                if active_ms_id is None and st != "completed" and app.id == active_app_id:
                    active_ms_id = ms.id
                    if st == "pending":
                        st = "in_progress"
                ms_list.append({**ms.to_dict(), "student_status": st})
            projected_approaches.append(
                {"id": app.id, "name": app.name, "milestones": ms_list}
            )
        return {
            "dossier_id": self.dossier_id,
            "status": self.status,
            "confidence": self.confidence,
            "tier": self.tier,
            "stem": self.stem.to_dict(),
            "implicit_constraints": [inv.to_dict() for inv in self.invariants],
            "approaches": projected_approaches,
            "scoring_points": [sp.to_dict() for sp in self.scoring_points],
            "active_approach_id": active_app_id,
            "active_milestone_id": active_ms_id,
        }

"""Application Ports & Repository mapping for the ProblemSolving Domain."""

from __future__ import annotations

from dataclasses import replace
from datetime import timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.contexts.problem_solving.domain.dossier import (
    ProblemDossier,
    ScoringPoint,
    StructuredStem,
    compute_stem_fingerprint,
)
from app.contexts.tutoring.domain.blueprint import Approach, ProblemInvariant
from app.infrastructure.ai.errors import ModelTimeBudgetExceeded
from app.infrastructure.persistence.models import ProblemDossierRecord, now


class ProblemSolverModelPort(Protocol):
    def extract_stem(
        self, *, text: str, images: list[str], independent_reread: bool = False
    ) -> dict | None: ...

    def solve_route(
        self,
        *,
        stem: StructuredStem,
        images: list[str],
        route_hint: str,
        feedback: dict | None = None,
    ) -> dict | None: ...


class QwenProblemSolverGateway(ProblemSolverModelPort):
    """Uses registered ProblemSolving components without student history."""

    MAX_TOOL_ROUNDS = 3
    MAX_CROPS = 4

    def __init__(self, settings_obj=None, *, math_engine=None, image_inspector=None, guardian_request=None):
        self._settings = settings_obj
        self._math_engine = math_engine
        self._image_inspector = image_inspector
        self._guardian_request = guardian_request
        self._target_scope = None
        self._extract_crops: list[dict] = []

    def _run_tool(
        self,
        *,
        name: str,
        args: dict,
        allowed: set[str],
        authorized_images: dict[str, str],
        inspected_crops: list[dict],
    ) -> dict:
        from app.application.ports.image_inspection import InspectImageRequest
        from app.application.ports.math_engine import MathInput
        from app.infrastructure.media.pillow_crop import PillowImageInspector
        from app.infrastructure.observability.telemetry import (
            agent_step_span,
            set_observation_payload,
        )

        with agent_step_span(
            "tool",
            name if name in allowed else "unknown_tool",
            **{"agent.tool.source": "problem_solver_request"},
        ) as span:
            set_observation_payload(
                span,
                input={"op": args.get("op")} if name in {"math", "science"} else args,
            )
            if name not in allowed:
                result = {"tool": name, "status": "tool_error", "detail": "unauthorized_tool"}
                span.set_attribute("agent.tool.status", "tool_error")
                set_observation_payload(span, output=result)
                return result
            try:
                if name == "inspect_image":
                    if len(inspected_crops) >= self.MAX_CROPS:
                        result = {"tool": name, "status": "tool_error", "detail": "crop_limit_exceeded"}
                    else:
                        req = InspectImageRequest.model_validate(args)
                        inspector = self._image_inspector or PillowImageInspector()
                        res = inspector.inspect(req, authorized_images=authorized_images)
                        if res.status == "unique" and res.crop_data_url and res.crop_ref:
                            inspected_crops.append(
                                {
                                    "crop_ref": res.crop_ref,
                                    "image_ref": res.image_ref,
                                    "label": res.label,
                                    "url": res.crop_data_url,
                                }
                            )
                        result = {"tool": name, **res.public_observation()}
                elif name in {"science", "math"}:
                    engine = self._math_engine
                    if engine is None:
                        from app.bootstrap.math_engine import default_math_engine

                        engine = default_math_engine()
                    math_in = MathInput.model_validate(args)
                    out = engine.execute(math_in)
                    result = {
                        "tool": name,
                        "status": out.status,
                        "result": out.result,
                        "verdict": out.verdict,
                        "conditions": out.conditions,
                        "error_code": out.error_code,
                    }
                else:
                    result = {"tool": name, "status": "tool_error", "detail": "unknown_tool"}
            except Exception as exc:  # noqa: BLE001
                result = {
                    "tool": name,
                    "status": "tool_error",
                    "error_code": type(exc).__name__,
                }
            span.set_attribute("agent.tool.status", str(result.get("status", "tool_error")))
            set_observation_payload(
                span,
                output={
                    key: result[key]
                    for key in ("status", "error_code", "crop_ref", "image_ref", "detail")
                    if key in result
                },
            )
            return result

    def _invoke_once(self, *, spec, user, retry_on_timeout: bool) -> dict | None:
        from app.infrastructure.ai import components
        from app.infrastructure.ai.errors import ModelGatewayError

        max_attempts = 2 if retry_on_timeout else 1
        for attempt in range(max_attempts):
            try:
                return components.invoke_agent_component(
                    spec=spec, user=user, settings_obj=self._settings
                ).unwrap()
            except ModelTimeBudgetExceeded:
                raise
            except (TimeoutError, ModelGatewayError) as exc:
                is_retryable = isinstance(exc, TimeoutError) or (
                    isinstance(exc, ModelGatewayError) and str(exc) == "model_transport_error"
                )
                if is_retryable and attempt + 1 < max_attempts:
                    continue
                return None
            except Exception:  # noqa: BLE001
                return None
        return None

    def _invoke(
        self,
        payload: dict,
        images: list[str],
        *,
        use_reread_model: bool = False,
        use_backup_model: bool = False,
        retry_on_timeout: bool = True,
    ) -> dict | None:
        from app.agent_specs.blueprint_steps import BACKUP, EXTRACT, REREAD
        from app.agent_specs.contexts import build_context
        from app.agent_specs.definitions import load_definitions
        from app.agent_specs.gaokao_contracts import PLANNER_ID, REREAD_ID
        from app.agent_specs.image_refs import image_manifest, image_ref
        from app.infrastructure.ai import components

        defs = load_definitions()
        if PLANNER_ID not in defs.units:
            return None
        target_component = (
            REREAD_ID if use_reread_model and REREAD_ID in defs.components else PLANNER_ID
        )
        unit = PLANNER_ID
        if EXTRACT in defs.units and payload["mode"] in {"stem_extract", "independent_stem_reread"}:
            unit = REREAD if use_reread_model else EXTRACT
            target_component = unit
        elif use_backup_model and BACKUP in defs.units:
            unit = BACKUP
            target_component = BACKUP
        spec = components.COMPONENTS.get(target_component)
        if spec is None:
            return None

        unit_def = defs.units.get(unit)
        if self._guardian_request is not None and unit == PLANNER_ID and payload.get("route_hint") == "T1":
            effort = unit_def.models[0].guardian_t1_reasoning_effort
            if effort:
                spec = replace(spec, reasoning_effort=effort, thinking_budget=None)
        allowed_tools = {
            tool_id.split(".", 1)[1]
            for tool_id in (getattr(unit_def, "tools", ()) or ())
            if "." in tool_id
        }
        authorized_images = {image_ref(url): url for url in (images or []) if url}
        inspected_crops: list[dict] = []
        # Preserve independent rereads and grant only images authorized on this call.
        prior_crops = [
            crop for crop in self._extract_crops if crop["image_ref"] in authorized_images
        ] if unit == PLANNER_ID and payload["mode"] == "independent_solve" else []
        observations: list[dict] = []

        base_payload = dict(payload)
        if self._guardian_request is not None:
            base_payload["guardian_request"] = self._guardian_request
            if self._target_scope:
                base_payload["target_scope"] = self._target_scope
            if unit == EXTRACT:
                base_payload["guardian_routing_contract"] = (
                    "最终 JSON 含 target_scope，逐字引用 guardian_request 中限定题号的完整短语，如无则填空串。"
                    "图片上的页码、题组标题和邻题不能改变用户指定范围。读题结果只列该范围内的设问。"
                    "最终读题 JSON 必须含 guardian_task。仅限清晰、普通(T1)、单一英文作文/邮件写作任务，"
                    "使用 english_writing，subject 填 english，摘要仅定位写作题、要求、受众和格式。"
                    "阅读、完形、语法、七选五、混合任务和其他所有情况填 solve，保留目标题的必要条件。"
                )
        handoff = (
            self._guardian_request is not None and unit == EXTRACT
            and unit_def.models[0].guardian_crop_handoff and images and "inspect_image" in allowed_tools
        )
        if handoff:
            base_payload["visual_evidence"] = (
                "若目标题须从纸带、仪表、曲线或线路图读取证据，先用 inspect_image 框选包含标尺、"
                "单位、标注和端点的局部再读数。若原图已足以转写题面但求解仍需看图，在最终读题 JSON 中附上 "
                "planner_crop，值为 inspect_image 的参数对象（image_ref、归一化 bbox、label），供求解器直接看局部。"
                "若已有对应切片或题目无需精读图像，省略 planner_crop。"
            )
        if prior_crops:
            base_payload["visual_evidence"] = "附图含读题时保留的局部图。对每个距离符号先核对标注线的两个端点，区分总距离与相邻间距；结合原图独立核对。局部图遗漏端点、图例或单位时重新框选再作答。"
        if images and "inspect_image" in allowed_tools:
            base_payload["image_manifest"] = image_manifest(images)
        if allowed_tools:
            base_payload["available_tools"] = sorted(allowed_tools)

        for tool_round in range(self.MAX_TOOL_ROUNDS + 1):
            turn_payload = dict(base_payload)
            if observations:
                turn_payload["tool_observations"] = observations
            elif images and unit in {EXTRACT, REREAD} and "inspect_image" in allowed_tools:
                turn_payload["extraction_instructions"] = (
                    "先定位目标题。若答题依赖刻度、端点或电路接线，本轮任务仅为框选一个最关键区域，"
                    "从 image_manifest 复制对应 image_ref，只返回 inspect_image 的 tool_request。"
                    "下一轮收到局部图后再转写。若无需精细读图，直接按要求完成题面转写和分级。"
                )
            elif (
                unit in {PLANNER_ID, BACKUP}
                and "science" in allowed_tools
                and payload.get("route_hint") in {"T2_algebraic", "T2_alternative"}
            ):
                turn_payload["science_tool_hint"] = (
                    "本题为复杂解答/压轴题：若涉及积分、求导、对数符号、方程组求解或不等式方向比较，"
                    "建议先返回仅含 tool_request 的 JSON 调用 science（如 integrate / differentiate / solve / equivalent）"
                    "核验关键符号与表达式，下一轮再输出完整求解 JSON。"
                )
            if tool_round >= self.MAX_TOOL_ROUNDS and allowed_tools:
                turn_payload["tool_budget_exhausted"] = True
            ctx_kwargs = {"payload": turn_payload, "images": images}
            if prior_crops or inspected_crops:
                ctx_kwargs["inspected_crops"] = prior_crops + inspected_crops
            user = build_context(unit, **ctx_kwargs)
            raw = self._invoke_once(
                spec=spec, user=user, retry_on_timeout=retry_on_timeout
            )
            if not isinstance(raw, dict):
                return raw
            tool_req = raw.get("tool_request")
            if tool_req is None:
                if handoff and not raw.get("needs_student_confirmation"):
                    crop_request = raw.get("planner_crop")
                    if not inspected_crops and isinstance(crop_request, dict):
                        self._run_tool(
                            name="inspect_image", args=crop_request, allowed=allowed_tools,
                            authorized_images=authorized_images, inspected_crops=inspected_crops,
                        )
                    self._extract_crops = list(inspected_crops)
                return raw
            if not allowed_tools or tool_round >= self.MAX_TOOL_ROUNDS:
                return None
            tool_name = str(tool_req["name"]).strip()
            tool_args = tool_req.get("args") if isinstance(tool_req.get("args"), dict) else {}
            obs = self._run_tool(
                name=tool_name,
                args=tool_args,
                allowed=allowed_tools,
                authorized_images=authorized_images,
                inspected_crops=inspected_crops,
            )
            observations.append(obs)
        return None

    def extract_stem(
        self, *, text: str, images: list[str], independent_reread: bool = False
    ) -> dict | None:
        self._extract_crops.clear()
        raw = self._invoke(
            {
                "mode": "independent_stem_reread" if independent_reread else "stem_extract",
                "problem_text": text,
                "extraction_instructions": (
                    "独立按原文转写完整题面、关键条件和全部设问；保留限定词、数值、符号与角标，无需求解。"
                    "输出 subject、shared_stem_summary、subproblems、needs_student_confirmation。"
                    if independent_reread
                    else "本轮只转写与分类，无需求解。输出 subject、shared_stem_summary（完整转写题面、数值及设问）、"
                    "subproblems、diagram_summary、needs_student_confirmation，approaches 固定为空数组。"
                    "纯概念、发音或事实查询标为 tier=T0，普通题标为 T1，确需多条独立推导核验的复杂题标为 T2。"
                ),
            },
            images,
            use_reread_model=independent_reread,
        )
        if not isinstance(raw, dict):
            return None
        guardian_fields = {}
        if self._guardian_request and not independent_reread:
            scope = raw.get("target_scope")
            if isinstance(scope, str) and scope.strip() and scope in self._guardian_request:
                self._target_scope = scope
            guardian_fields = {"guardian_task": raw.get("guardian_task"), "target_scope": self._target_scope}
        return {
            **guardian_fields,
            "tier": raw.get("tier"),
            "needs_student_confirmation": raw.get("needs_student_confirmation") is True,
            "subject": str(raw.get("subject") or "general"),
            "raw_text": str(raw.get("shared_stem_summary") or raw.get("raw_text") or ("" if independent_reread else text)),
            "subproblems": list(raw.get("subproblems") or []),
            "diagram_summary": str(raw.get("diagram_summary") or ""),
        }

    def solve_route(
        self,
        *,
        stem: StructuredStem,
        images: list[str],
        route_hint: str,
        feedback: dict | None = None,
    ) -> dict | None:
        payload: dict = {
            "mode": "independent_solve",
            "route_hint": route_hint,
            "route_instructions": "只输出当前路线，保留必要的核验锚点。不要重复转写题面或生成其他路线。final_answers 按题面小问的编号或原标签逐一作答，单问无标签时用 main。",
            "stem": stem.to_dict(),
            "problem_text": stem.raw_text,
        }
        if feedback:
            payload["contradiction_feedback"] = feedback
        return self._invoke(
            payload,
            images,
            use_backup_model=route_hint in {"T1_backup", "T2_alternative"},
        )


def _ensure_utc(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


class SqlProblemDossierRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def to_domain(row: ProblemDossierRecord) -> ProblemDossier:
        approaches = tuple(
            Approach.from_dict(a)
            for a in (row.approaches or [])
            if isinstance(a, dict) and a.get("id") and a.get("name")
        )
        invariants = tuple(
            ProblemInvariant.from_dict(i)
            for i in (row.invariants or [])
            if isinstance(i, dict) and i.get("id") and i.get("expression")
        )
        scoring = tuple(
            ScoringPoint.from_dict(sp)
            for sp in (row.scoring_points or [])
            if isinstance(sp, dict) and sp.get("id") and sp.get("step")
        )
        return ProblemDossier(
            dossier_id=row.id,
            fingerprint=row.fingerprint,
            scope=row.scope,  # type: ignore[arg-type]
            owner_ward_id=row.owner_ward_id,
            stem=StructuredStem.from_dict(row.stem or {}),
            subject=row.subject,
            tier=row.tier,  # type: ignore[arg-type]
            approaches=approaches,
            invariants=invariants,
            scoring_points=scoring,
            final_answers=dict(row.final_answers or {}),
            confidence=row.confidence,  # type: ignore[arg-type]
            status=row.status,  # type: ignore[arg-type]
            evidence=dict(row.evidence or {}),
            solver_version=row.solver_version,
            lease_until=_ensure_utc(row.lease_until),
        )

    def get(self, dossier_id: str) -> ProblemDossier | None:
        row = self.db.get(ProblemDossierRecord, dossier_id)
        return self.to_domain(row) if row is not None else None

    def _matching(self, query, stem: StructuredStem) -> ProblemDossier | None:
        fingerprint = compute_stem_fingerprint(stem)
        keys = (fingerprint, compute_stem_fingerprint(stem, legacy=True))
        candidates = query.filter(ProblemDossierRecord.fingerprint.in_(keys)).order_by(
            ProblemDossierRecord.updated_at.desc()
        )
        for row in candidates:
            if compute_stem_fingerprint(StructuredStem.from_dict(row.stem or {})) == fingerprint:
                return self.to_domain(row)
        return None

    def find_bank_ready(self, *, stem: StructuredStem) -> ProblemDossier | None:
        query = self.db.query(ProblemDossierRecord).filter_by(scope="bank", status="ready")
        return self._matching(query, stem)

    def find_image_request(self, *, ward_id: str, fingerprint: str) -> ProblemDossier | None:
        row = self.db.query(ProblemDossierRecord).filter_by(
            scope="ward", owner_ward_id=ward_id, fingerprint=fingerprint,
        ).order_by(ProblemDossierRecord.updated_at.desc()).first()
        return self.to_domain(row) if row else None

    def find_reusable(self, *, stem: StructuredStem, ward_id: str) -> ProblemDossier | None:
        bank = self.find_bank_ready(stem=stem)
        if bank is not None:
            return bank
        query = self.db.query(ProblemDossierRecord).filter_by(scope="ward", owner_ward_id=ward_id)
        return self._matching(query, stem)

    def save(self, dossier: ProblemDossier) -> ProblemDossier:
        row = self.db.get(ProblemDossierRecord, dossier.dossier_id)
        if row is None:
            row = ProblemDossierRecord(id=dossier.dossier_id)
            self.db.add(row)
        row.fingerprint = dossier.fingerprint
        row.scope = dossier.scope
        row.owner_ward_id = dossier.owner_ward_id
        row.subject = dossier.subject
        row.tier = dossier.tier
        row.stem = dossier.stem.to_dict()
        row.approaches = [a.to_dict() for a in dossier.approaches]
        row.invariants = [i.to_dict() for i in dossier.invariants]
        row.scoring_points = [sp.to_dict() for sp in dossier.scoring_points]
        row.final_answers = dict(dossier.final_answers)
        row.confidence = dossier.confidence
        row.status = dossier.status
        row.evidence = dict(dossier.evidence)
        row.solver_version = dossier.solver_version
        row.lease_until = dossier.lease_until
        row.updated_at = now()
        self.db.flush()
        return self.to_domain(row)

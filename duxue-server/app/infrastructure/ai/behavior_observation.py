"""Authorized multi-image adapter using the pinned Admin configuration."""

import base64
import json
from datetime import datetime, timezone

from app.agent_specs.release_runtime import pin_release
from app.infrastructure.ai import components
from app.infrastructure.persistence.database import SessionLocal
from app.infrastructure.persistence.models import (
    AcceptedEvidence,
    Frame,
    ObservationSettings,
)
from app.infrastructure.storage.object_storage import camera_storage, storage


class ObservationVision:
    def __init__(self, session_factory=SessionLocal, *, settings_obj=None):
        self.session_factory = session_factory
        self.settings_obj = settings_obj

    def __call__(self, manifest):
        return self.invoke("behavior.visible-activity", manifest, limit=8)

    def assess(self, payload):
        return self.invoke("behavior.support-opportunity", payload, limit=16)

    def prepare(self, payload, *, limit):
        refs = payload["frames"]
        if len(refs) > limit or len({f["id"] for f in refs}) != len(refs):
            raise ValueError("invalid image budget")
        images = []
        with self.session_factory() as db:
            setting = db.get(ObservationSettings, payload["ward_id"])
            if (
                not setting
                or not setting.enabled
                or setting.camera_id != payload["camera_id"]
            ):
                raise PermissionError("observation disabled")
            for ref in refs:
                row = (
                    db.query(Frame, AcceptedEvidence)
                    .join(AcceptedEvidence, AcceptedEvidence.frame_id == Frame.id)
                    .filter(
                        Frame.id == ref["id"],
                        Frame.ward_id == payload["ward_id"],
                        AcceptedEvidence.camera_id == payload["camera_id"],
                        AcceptedEvidence.assignment_revision
                        == payload["assignment_revision"],
                    )
                    .one_or_none()
                )
                if row is None or not row[0].oss_key:
                    raise PermissionError("evidence unavailable")
                frame = row[0]
                from app.application.commands.behavior_observation import utc

                if utc(datetime.fromisoformat(ref["at"])) != utc(row[1].captured_at):
                    raise PermissionError("evidence timestamp mismatch")
                expires = (
                    frame.purge_after.replace(tzinfo=timezone.utc)
                    if frame.purge_after.tzinfo is None
                    else frame.purge_after
                )
                if expires <= datetime.now(timezone.utc):
                    raise PermissionError("evidence expired")
                images.append((frame.oss_key, bool(frame.gateway_id)))
        # DB session ends before storage and model I/O.
        parts = [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]
        for ref, (key, gateway) in zip(refs, images):
            data = (camera_storage if gateway else storage).read_bytes(key)
            mime = (
                "image/png"
                if key.lower().endswith(".png")
                else "image/webp"
                if key.lower().endswith(".webp")
                else "image/jpeg"
            )
            parts.extend(
                [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"frame_id": ref["id"], "captured_at": ref["at"]}
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,"
                            + base64.b64encode(data).decode()
                        },
                    },
                ]
            )
        return parts

    def invoke(self, component_id, payload, *, limit):
        from app.application.workflows.observation_workflow import (
            execute_observation,
            validate_activity,
            validate_support,
        )
        from app.infrastructure.observability.observation import images

        parts = []
        result = {}

        def prepare(_state):
            parts.extend(self.prepare(payload, limit=limit))
            images.add(len(payload["frames"]), {"component": component_id})
            # Image bytes remain in the closure, never in Workflow traces.
            return {"frame_count": len(payload["frames"]), "authorized": True}

        def infer(_state):
            result.update(self.invoke_model(component_id, parts))
            return result

        def validate(_state):
            validator = (
                validate_activity
                if component_id == "behavior.visible-activity"
                else validate_support
            )
            return validator(payload, result)

        validation_id = (
            "behavior.validate-activity"
            if component_id == "behavior.visible-activity"
            else "behavior.validate-support"
        )
        execute_observation(
            component_id.replace(".", "-"),
            {
                "behavior.evidence": prepare,
                component_id: infer,
                validation_id: validate,
            },
        )
        return result

    def invoke_model(self, component_id, parts):
        with pin_release():
            spec = components.COMPONENTS.get(component_id)
            from app.infrastructure.ai.errors import ModelGatewayError

            for attempt in range(2):
                try:
                    result = components.invoke_json_component(
                        spec=spec, user=parts, settings_obj=self.settings_obj
                    )
                    break
                except ModelGatewayError as error:
                    if str(error) != "invalid_model_candidate" or attempt:
                        raise
                    parts = [
                        *parts,
                        {
                            "type": "text",
                            "text": "Previous output failed the registered JSON contract. Return only a complete JSON object matching that contract.",
                        },
                    ]
            return {
                **result,
                "provenance": {
                    "model": spec.model,
                    "prompt_version": spec.prompt.id,
                    "definition_digest": spec.definition_digest,
                    "component_version": spec.version,
                },
            }

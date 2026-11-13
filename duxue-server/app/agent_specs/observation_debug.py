"""Observation debug adapters: read authorized images, isolate all domain writes."""

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent_specs.observation_contracts import CODE_AGENTS


def debug_vision(value, *, support=False, runtime=None):
    from app.infrastructure.ai.behavior_observation import ObservationVision

    if value.get("synthetic") is not True:
        return ObservationVision(settings_obj=runtime), value
    import base64
    import struct
    import zlib

    current = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(
        minutes=1
    )
    frames = [
        {"id": str(uuid4()), "at": (current + timedelta(seconds=15 * i)).isoformat()}
        for i in range(4)
    ]
    manifest = {
        "ward_id": str(uuid4()),
        "camera_id": str(uuid4()),
        "assignment_revision": 1,
        "start": current.isoformat(),
        "end": (current + timedelta(minutes=1)).isoformat(),
        "frames": frames,
    }
    if support:
        manifest.update(
            trigger="stillness_reached_duration",
            observed_period={
                "start": (current - timedelta(minutes=3)).isoformat(),
                "end": manifest["end"],
            },
            learning_context={"observed_learning": False},
        )

    def chunk(kind, data):
        return (
            struct.pack("!I", len(data))
            + kind
            + data
            + struct.pack("!I", zlib.crc32(kind + data))
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!2I5B", 640, 480, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\x00" + b"\xcc" * 1920) * 480))
        + chunk(b"IEND", b"")
    )

    class SyntheticVision(ObservationVision):
        def prepare(self, payload, *, limit):
            # Explicit synthetic fixture only; never resolve caller-selected image URLs.
            return [{"type": "text", "text": json.dumps(payload)}] + [
                part
                for frame in frames
                for part in (
                    {"type": "text", "text": json.dumps(frame)},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/png;base64,"
                            + base64.b64encode(png).decode()
                        },
                    },
                )
            ]

    return SyntheticVision(settings_obj=runtime), manifest


def run_observation_debug(identifier, data, runtime=None):
    from app.application.workflows.observation_workflow import (
        validate_activity,
        validate_support,
    )

    value = json.loads(data.content)
    if not isinstance(value, dict):
        raise ValueError("observation debug input must be an object")
    if identifier == "behavior-observation":
        return run_business_debug(value, runtime)
    if identifier == "behavior.eligibility":
        from app.application.workflows.observation_workflow import check_eligibility
        from app.contexts.behavior_analysis.domain.support import eligible_runs

        current = (
            datetime.fromisoformat(value["clock"])
            if value.get("clock")
            else datetime.now(timezone.utc)
        )
        runs = [{**run, "observed_at": datetime.fromisoformat(run["observed_at"])} for run in value.get("runs", [])]
        return {"eligible": check_eligibility(bool(eligible_runs(runs, current)))}
    if identifier in {"behavior-visible-activity", "behavior-support-opportunity"}:
        vision, manifest = debug_vision(
            value, support=identifier == "behavior-support-opportunity", runtime=runtime
        )
        return (
            vision(manifest)
            if identifier == "behavior-visible-activity"
            else vision.assess(manifest)
        )
    if identifier in {
        "behavior.evidence",
        "behavior.validate-activity",
        "behavior.validate-support",
    }:
        from contextlib import nullcontext

        from app.agent_specs.execution_trace import recorder

        trace = recorder()
        with (
            trace.step(
                kind="agent",
                node_id=identifier,
                workflow_id=None,
                input={"code_agent": identifier},
            )
            if trace
            else nullcontext()
        ):
            if identifier == "behavior.evidence":
                vision, manifest = debug_vision(value)
                vision.prepare(manifest, limit=8)
                return {
                    "authorized": True,
                    "synthetic": value.get("synthetic") is True,
                    "frame_count": len(manifest["frames"]),
                }
            return (
                validate_activity
                if identifier == "behavior.validate-activity"
                else validate_support
            )(value["manifest"], value["result"])
    if identifier in CODE_AGENTS:
        identifier = identifier.replace(".", "-")
    return run_persistent_sandbox(identifier, value)


def run_persistent_sandbox(identifier, value):
    from app.application.commands.behavior_observation import ObservationCommands, wire
    from app.application.commands.evening_reports import EveningReportCommands
    from app.application.commands.help_offers import HelpOfferCommands
    from app.contexts.behavior_analysis.domain.observation import (
        EvidenceFrame,
        Manifest,
        validate_outcome,
    )
    from app.infrastructure.persistence import models as m
    from app.infrastructure.persistence.database import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    ward, camera = str(uuid4()), str(uuid4())
    current = (
        datetime.fromisoformat(value["clock"])
        if value.get("clock")
        else datetime.now(timezone.utc)
    )
    if current.tzinfo is None:
        raise ValueError("clock requires timezone")
    day = date.fromisoformat(value.get("date", current.date().isoformat()))
    try:
        with Session(engine, expire_on_commit=False) as db:
            db.add(m.User(id=ward, type="ward"))
            db.flush()
            db.add(m.Ward(id=ward, display_name="isolated observation debug"))
            db.flush()
            db.add(m.Device(id=camera, ward_id=ward))
            db.flush()
            db.add(
                m.ObservationSettings(
                    ward_id=ward,
                    camera_id=camera,
                    enabled=True,
                    report_enabled=True,
                    generation=1,
                    mode="shadow",
                    deadline="00:00",
                )
            )
            db.flush()
            if identifier == "behavior-aggregate":
                for window_input in value.get(
                    "windows",
                    [{"manifest": value["manifest"], "result": value["result"]}]
                    if value.get("manifest")
                    else [],
                ):
                    manifest = window_input["manifest"]
                    start, end = (
                        datetime.fromisoformat(manifest[key])
                        for key in ("start", "end")
                    )
                    cells = validate_outcome(
                        Manifest(
                            ward,
                            camera,
                            1,
                            start,
                            end,
                            tuple(
                                EvidenceFrame(f["id"], datetime.fromisoformat(f["at"]))
                                for f in manifest["frames"]
                            ),
                        ),
                        window_input["result"]["cells"],
                    )
                    window = m.ObservationWindowRecord(
                        ward_id=ward,
                        camera_id=camera,
                        assignment_revision=1,
                        start_at=start,
                        end_at=end,
                        fingerprint="sandbox",
                        generation=1,
                        input_version=1,
                        manifest={**manifest, "ward_id": ward, "camera_id": camera},
                        status="interpreted",
                    )
                    db.add(window)
                    db.flush()
                    db.add(
                        m.ObservationInterpretation(
                            window_id=window.id,
                            input_version=1,
                            cells=wire([asdict(cell) for cell in cells]),
                            provenance={"source": "debug_fixture"},
                        )
                    )
                    db.flush()
                job = m.ObservationJob(
                    ward_id=ward,
                    kind="publish",
                    key="sandbox",
                    payload={"date": day.isoformat(), "generation": 1},
                )
                ObservationCommands(db, None, lambda: current).publish_day(job)
                db.flush()
                return {
                    "revisions": [
                        r.snapshot for r in db.query(m.ObservationRevisionRecord)
                    ],
                    "sandbox": True,
                }
            if value.get("snapshot"):
                observation = m.ObservationDayRecord(
                    ward_id=ward, local_date=day, timezone="Asia/Shanghai", revision=1
                )
                db.add(observation)
                db.flush()
                db.add(
                    m.ObservationRevisionRecord(
                        day_id=observation.id, revision=1, snapshot=value["snapshot"]
                    )
                )
                db.flush()
            if identifier == "behavior-delivery":
                result = HelpOfferCommands(db, lambda: current).present(
                    ward, "no-channel"
                )
                return {"presented": result is not None, "sandbox": True}
            if identifier == "behavior-invitation":
                if not value.get("snapshot"):
                    observation = m.ObservationDayRecord(
                        ward_id=ward,
                        local_date=day,
                        timezone="Asia/Shanghai",
                        revision=1,
                    )
                    db.add(observation)
                    db.flush()
                    db.add(
                        m.ObservationRevisionRecord(
                            day_id=observation.id,
                            revision=1,
                            snapshot={"candidates": []},
                        )
                    )
                    db.flush()
                HelpOfferCommands(db, lambda: current).consider(observation.id)
                db.flush()
                presentation = HelpOfferCommands(db, lambda: current).present(
                    ward, "no-channel"
                )
                return {
                    "presentation": presentation,
                    "offers": [
                        {"kind": o.kind, "status": o.status}
                        for o in db.query(m.HelpOfferRecord)
                    ],
                    "sandbox": True,
                }
            if identifier == "behavior-report":
                EveningReportCommands(db, lambda: current).publish(ward, day)
                db.flush()
                return {
                    "reports": [r.content for r in db.query(m.ReflectionReportVersion)],
                    "sandbox": True,
                }
            raise ValueError("unknown observation debug target")
    finally:
        engine.dispose()


def run_business_debug(value, runtime):
    """Run the same business nodes in an isolated DB, preserving conditional assessment."""
    from app.application.workflows.observation_workflow import check_eligibility
    from app.contexts.behavior_analysis.domain.support import eligible_runs

    vision, manifest = debug_vision(value, runtime=runtime)
    response = vision(manifest)
    day = datetime.fromisoformat(manifest["start"]).date().isoformat()
    end = datetime.fromisoformat(manifest["end"])
    aggregate = run_persistent_sandbox(
        "behavior-aggregate",
        {
            "windows": [
                *value.get("prior_windows", []),
                {"manifest": manifest, "result": response},
            ],
            "date": day,
            "clock": end.isoformat(),
        },
    )
    snapshot = aggregate["revisions"][-1]
    runs = []
    for item in snapshot["runs"]:
        run = dict(item)
        run["observed_at"] = max(
            datetime.fromisoformat(f["at"])
            for source in [
                *[w["manifest"] for w in value.get("prior_windows", [])],
                manifest,
            ]
            for f in source["frames"]
            if f["id"] in run["evidence"]
        )
        runs.append(run)
    ready = check_eligibility(bool(eligible_runs(runs, end)))
    assessment = None
    if ready:
        payload = {
            **manifest,
            "trigger": "debug_observed_duration",
            "observed_period": {
                "start": snapshot["runs"][-1]["start"],
                "end": snapshot["runs"][-1]["end"],
            },
            "learning_context": {
                "observed_learning": any(
                    r["activity"] in {"writing", "reading_material"} for r in runs
                )
            },
        }
        assessment = vision.assess(payload)
        from app.contexts.behavior_analysis.domain.support import validate_assessment

        candidate = validate_assessment(
            {k: v for k, v in assessment.items() if k != "provenance"},
            [f["id"] for f in manifest["frames"]],
            has_learning_context=payload["learning_context"]["observed_learning"],
        )
        snapshot["candidates"] = (
            []
            if candidate is None
            else [
                {
                    **candidate.model_dump(),
                    "start": runs[-1]["start"],
                    "end": runs[-1]["end"],
                    "observed_at": runs[-1]["observed_at"].isoformat(),
                    "fresh_until": (
                        runs[-1]["observed_at"] + timedelta(seconds=120)
                    ).isoformat(),
                    "assessment_version": "isolated-debug",
                }
            ]
        )
        delivery = run_persistent_sandbox(
            "behavior-invitation",
            {"snapshot": snapshot, "date": day, "clock": end.isoformat()},
        )
    return {
        "observation": snapshot,
        "eligible": ready,
        "assessment": assessment,
        "invitation": delivery if ready else None,
        "delivery": "not_eligible" if not ready else "shadow",
        "sandbox": True,
        "synthetic": value.get("synthetic") is True,
    }

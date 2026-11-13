"""Replay authorized frame receipts through production commands in a temporary DB.

Input JSON: {ward_id, camera_id, frames:[{frame_id, received_at}], labels?:[...]}
Source DB/OSS are read only. No source Frame, report, channel or invitation is changed.
Usage: ENV_FILE=.env.test .venv/bin/python scripts/replay_observation.py input.json \
  --config-snapshot exported.json --out private-result.json --max-windows 3
"""

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--config-snapshot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-windows", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.max_windows <= 180:
        parser.error("max-windows must be between 1 and 180")
    os.environ["AGENT_CONFIG_SOURCE"] = "snapshot"
    os.environ["AGENT_CONFIG_SNAPSHOT"] = str(args.config_snapshot.resolve())
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.agent_specs.configuration import read_snapshot, select_offline_snapshot
    from app.application.commands.behavior_observation import ObservationCommands, utc
    from app.infrastructure.ai.behavior_observation import ObservationVision
    from app.infrastructure.persistence.database import Base, SessionLocal
    from app.infrastructure.persistence.evidence_repository import (
        record_accepted_evidence,
    )
    from app.infrastructure.persistence.models import (
        AcceptedEvidence,
        Device,
        Frame,
        ObservationRevisionRecord,
        ObservationSettings,
        ObservationWindowRecord,
        User,
        Ward,
    )

    record = read_snapshot(args.config_snapshot)
    compiled = select_offline_snapshot(record)
    for identifier in ("behavior.visible-activity", "behavior.support-opportunity"):
        compiled.catalog.component(identifier)
    case = json.loads(args.input.read_text())
    rows = sorted(
        case["frames"], key=lambda f: datetime.fromisoformat(f["received_at"])
    )
    if not rows or len(rows) > args.max_windows * 4:
        parser.error("empty input or frame budget exceeded")
    source = []
    with SessionLocal() as db:
        for entry in rows:
            at = datetime.fromisoformat(entry["received_at"])
            if at.tzinfo is None:
                parser.error("received_at must contain timezone")
            pair = (
                db.query(Frame, AcceptedEvidence)
                .join(AcceptedEvidence, AcceptedEvidence.frame_id == Frame.id)
                .filter(
                    Frame.id == entry["frame_id"],
                    Frame.ward_id == case["ward_id"],
                    Frame.device_id == case["camera_id"],
                )
                .one_or_none()
            )
            if pair is None or pair[1].assignment_revision is None:
                parser.error("frame is not authorized journal evidence")
            frame, evidence = pair
            source.append(
                (
                    at,
                    {
                        "id": frame.id,
                        "ward_id": frame.ward_id,
                        "device_id": frame.device_id,
                        "captured_at": utc(frame.captured_at),
                        "oss_key": frame.oss_key,
                        "sha256": frame.sha256,
                        "purge_after": utc(frame.purge_after),
                        "gateway_id": frame.gateway_id,
                    },
                    evidence.assignment_revision,
                )
            )
    if len({f[1]['captured_at'].replace(second=0, microsecond=0) for f in source}) > args.max_windows:
        parser.error('window budget exceeded')
    if len({f[1]['id'] for f in source}) != len(source):
        parser.error('duplicate input frame')
    calls = []
    real = ObservationVision()

    class MeasuredVision:
        def __call__(self, payload):
            started = time.monotonic()
            try:
                return real(payload)
            finally:
                calls.append(
                    {
                        "kind": "visible_activity",
                        "images": len(payload["frames"]),
                        "duration_seconds": time.monotonic() - started,
                    }
                )

        def assess(self, payload):
            started = time.monotonic()
            try:
                return real.assess(payload)
            finally:
                calls.append(
                    {
                        "kind": "support_opportunity",
                        "images": len(payload["frames"]),
                        "duration_seconds": time.monotonic() - started,
                    }
                )

    with tempfile.TemporaryDirectory(prefix="duxue-observation-replay-") as folder:
        engine = create_engine("sqlite:///" + folder + "/replay.db")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        with factory() as db:
            db.add(User(id=case["ward_id"], type="ward"))
            db.flush()
            db.add(Ward(id=case["ward_id"], display_name="replay"))
            db.flush()
            db.add(Device(id=case["camera_id"], ward_id=case["ward_id"]))
            db.flush()
            db.add(
                ObservationSettings(
                    ward_id=case["ward_id"], enabled=True, camera_id=case["camera_id"]
                )
            )
            db.commit()
            clock = [source[0][0]]
            commands = ObservationCommands(db, MeasuredVision(), lambda: clock[0])
            for received, fields, revision in source:
                clock[0] = received
                while commands.run_next():
                    pass
                frame = Frame(**fields)
                db.add(frame)
                db.flush()
                record_accepted_evidence(db, frame, revision)
                db.commit()
                commands.scan()
                while commands.run_next():
                    pass
            clock[0] += timedelta(minutes=1)
            while commands.run_next():
                pass
            windows = db.query(ObservationWindowRecord).all()
            revisions = db.query(ObservationRevisionRecord).all()
            from app.contexts.behavior_analysis.domain.replay_scoring import (
                score_frames,
            )
            scores = score_frames([r.snapshot for r in revisions], case.get('labels', []))
            output = {
                "config_digest": compiled.digest,
                "window_count": len(windows),
                "states": [w.status for w in windows],
                "calls": calls,
                "revisions": [
                    {"revision": r.revision, "snapshot": r.snapshot} for r in revisions
                ],
                "annotation_status": "human_frame_labels_scored"
                if case.get("labels")
                else "unlabeled",
                "frame_scores": scores,
                "invitation_error_rates": None,
                "quality_claim": None,
                "cost_currency": None,
                "limitations": [
                    "No actual invitation or App playback",
                    "Sparse estimates are not continuous video facts",
                ],
            }
            args.out.parent.mkdir(parents=True, exist_ok=True)
            with os.fdopen(
                os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
            ) as handle:
                json.dump(output, handle, ensure_ascii=False, indent=2)
        engine.dispose()
    print(
        json.dumps(
            {
                "windows": len(windows),
                "model_calls": len(calls),
                "output": str(args.out),
            }
        )
    )


if __name__ == "__main__":
    main()

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.contexts.behavior_analysis.domain.logic import Point, RuleClassifier, build_segments, smooth
from app.application.commands.legacy_services import classify_for_ward
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.infrastructure.persistence.database import Base
from app.infrastructure.persistence.models import AnalysisProfile, BehaviorLabelConfig, Guardian, User, Ward
from app.infrastructure.security.tokens import hash_secret


class DomainTest(unittest.TestCase):
    def setUp(self):
        self.classifier = RuleClassifier(Path(__file__).parents[1] / "classifier" / "rules.yaml")

    def test_desk_phone_does_not_override_writing(self):
        label, _ = self.classifier.classify({"hand_action": "右手握笔书写", "desk_objects": "桌面放着手机"})
        self.assertEqual(label, "学习")

    def test_middle_noise_is_smoothed_and_merged(self):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        points = [Point(str(i), base + timedelta(seconds=i * 15), label, 1.0) for i, label in enumerate(["学习", "走神/玩耍", "学习"])]
        segments = build_segments(smooth(points))
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["label"], "学习")
        self.assertEqual(segments[0]["duration_seconds"], 45)

    def test_custom_profile_label_precedes_defaults(self):
        local_engine = create_engine("sqlite://"); Base.metadata.create_all(local_engine)
        db = sessionmaker(bind=local_engine, expire_on_commit=False)()
        guardian_user = User(type="guardian"); db.add(guardian_user); db.flush()
        db.add(Guardian(id=guardian_user.id, name="g", email=f"{guardian_user.id}@example.com", password_hash=hash_secret("password123")))
        profile = AnalysisProfile(created_by=guardian_user.id, name="custom"); db.add(profile); db.flush()
        ward_user = User(type="ward"); db.add(ward_user); db.flush()
        ward = Ward(id=ward_user.id, display_name="w", analysis_profile_id=profile.id); db.add(ward)
        db.add(BehaviorLabelConfig(profile_id=profile.id, label_name="咬手指", field_prototypes={"hand_action": ["咬手指"]}, priority=10)); db.commit()
        label, confidence = classify_for_ward(db, ward, {"hand_action": "右手正在咬手指"})
        self.assertEqual(label, "咬手指"); self.assertGreater(confidence, 0.5); db.close()


if __name__ == "__main__": unittest.main()

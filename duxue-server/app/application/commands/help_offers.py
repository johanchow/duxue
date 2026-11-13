"""Study invitation lifecycle and bounded Companion presentation commands."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.application.commands.behavior_observation import lock, utc
from app.contexts.study.domain.help_offer import invitation_allowed
from app.application.workflows.observation_workflow import observation_step

from app.infrastructure.persistence.models import (
    AgentRun,
    HelpOfferBudgetRecord,
    HelpOfferRecord,
    ObservationDayRecord,
    ObservationRevisionRecord,
    ObservationSettings,
    OutboxEvent,
    StartCueRecord,
    StudySession,
    SupportChannel,
    SupportReceipt,
)

PROMPTS = {
    "offer_help": "这题需要一点提示吗？",
    "invite_return": "要不要回到刚才这一步？",
}


class HelpOfferCommands:
    def __init__(self, db, clock=lambda: datetime.now(timezone.utc)):
        self.db, self.clock = db, clock

    def busy(self, ward_id):
        db = self.db
        return bool(
            db.query(AgentRun.id)
            .filter(
                AgentRun.ward_id == ward_id,
                AgentRun.status.in_(["active", "running", "waiting_for_ward"]),
            )
            .first()
            or db.query(StartCueRecord.id)
            .filter(
                StartCueRecord.ward_id == ward_id,
                StartCueRecord.status.in_(["pending", "held", "ready", "presented"]),
            )
            .first()
            or db.query(StudySession.id)
            .filter_by(ward_id=ward_id, status="paused")
            .first()
        )

    @observation_step("behavior.invitation")
    def consider(self, day_id):
        db = self.db
        day = db.get(ObservationDayRecord, day_id)
        if not day:
            return
        lock(db, f"observation-ward:{day.ward_id}")
        db.refresh(day)
        setting = db.get(ObservationSettings, day.ward_id)
        if not setting or not setting.enabled:
            return
        snapshot = db.get(ObservationRevisionRecord, (day.id, day.revision)).snapshot
        if not snapshot.get("candidates"):
            return
        candidate = snapshot["candidates"][0]
        offers = (
            db.query(HelpOfferRecord)
            .filter_by(ward_id=day.ward_id, local_date=day.local_date)
            .all()
        )
        start, end = (
            datetime.fromisoformat(candidate["start"]),
            datetime.fromisoformat(candidate["end"]),
        )
        same = any(
            datetime.fromisoformat(o.candidate["start"]) < end
            and start < datetime.fromisoformat(o.candidate["end"])
            for o in offers
        )
        if same:
            return
        current = self.clock()
        for offer in offers:
            if (
                offer.status in {"ready", "presented"}
                and utc(offer.expires_at) <= current
            ):
                offer.status = "expired"
                offer.version += 1
        channel = db.query(SupportChannel).filter_by(ward_id=day.ward_id).one_or_none()
        budget = db.get(HelpOfferBudgetRecord, (day.ward_id, day.local_date))
        if setting.mode == "shadow":
            status = "shadow"
        elif invitation_allowed(
            current=current,
            observed_at=datetime.fromisoformat(candidate["observed_at"]),
            fresh_until=datetime.fromisoformat(candidate["fresh_until"]),
            reserved_count=budget.reserved_count if budget else 0,
            last_reserved_at=utc(budget.last_reserved_at)
            if budget and budget.last_reserved_at
            else None,
            has_active=any(o.status in {"ready", "presented"} for o in offers),
            same_run=False,
            channel_active=bool(
                channel and channel.enabled and utc(channel.expires_at) > current
            ),
            opted_in=setting.mode == "enabled",
            interaction_busy=self.busy(day.ward_id),
        ):
            status = "ready"
            if budget is None:
                budget = HelpOfferBudgetRecord(
                    ward_id=day.ward_id, local_date=day.local_date, reserved_count=0
                )
                db.add(budget)
            budget.reserved_count += 1
            budget.last_reserved_at = current
        else:
            return
        offer = HelpOfferRecord(
            ward_id=day.ward_id,
            local_date=day.local_date,
            kind=candidate["decision"],
            status=status,
            candidate={
                **candidate,
                "day_id": day.id,
                "revision": day.revision,
                "generation": setting.generation,
            },
            expires_at=datetime.fromisoformat(candidate["fresh_until"]),
        )
        db.add(offer)
        db.flush()
        if status == "ready":
            db.add(
                OutboxEvent(
                    aggregate_type="help_offer",
                    aggregate_id=offer.id,
                    event_type="HelpOfferReady.v1",
                    payload={
                        "schema_version": "HelpOfferReady.v1",
                        "ward_id": day.ward_id,
                        "offer_id": offer.id,
                        "offer_version": offer.version,
                    },
                )
            )

    @observation_step("behavior.delivery")
    def present(self, ward_id, channel_id):
        db = self.db
        from app.application.commands.companion_history import lock_history

        lock_history(db, ward_id)
        lock(db, f"observation-ward:{ward_id}")
        current = self.clock()
        channel = (
            db.query(SupportChannel)
            .filter_by(id=channel_id, ward_id=ward_id)
            .one_or_none()
        )
        setting = db.get(ObservationSettings, ward_id)
        if (
            not channel
            or not channel.enabled
            or utc(channel.expires_at) <= current
            or not setting
            or not setting.enabled
            or setting.mode != "enabled"
            or self.busy(ward_id)
        ):
            return None
        offer = (
            db.query(HelpOfferRecord)
            .filter(
                HelpOfferRecord.ward_id == ward_id,
                HelpOfferRecord.status.in_(["ready", "presented"]),
            )
            .order_by(HelpOfferRecord.expires_at)
            .first()
        )
        if not offer:
            return None
        day = db.get(ObservationDayRecord, offer.candidate["day_id"])
        snapshot = (
            db.get(ObservationRevisionRecord, (day.id, day.revision)).snapshot
            if day
            else {}
        )
        runs = snapshot.get("runs", [])
        expected = (
            "still_with_material"
            if offer.kind == "offer_help"
            else "other_visible_activity"
        )
        if (
            offer.candidate.get("generation") != setting.generation
            or utc(offer.expires_at) <= current
            or not runs
            or runs[-1]["activity"] != expected
            or current - datetime.fromisoformat(offer.candidate["observed_at"])
            > timedelta(seconds=60)
        ):
            offer.status = "expired"
            offer.version += 1
            return None
        return {
            "kind": "help_offer",
            "protocol_version": "support.v1",
            "offer_id": offer.id,
            "version": offer.version,
            "text": PROMPTS[offer.kind],
            "prompt_id": offer.kind,
            "handsfree": channel.handsfree,
            "expires_at": utc(offer.expires_at).isoformat(),
            "actions": ["accept_help", "decline_help"],
        }

    def receipt(
        self,
        ward_id,
        channel_id,
        *,
        offer_id,
        receipt_id,
        medium,
        presented_at,
        expected_version,
    ):
        db = self.db
        from app.application.commands.companion_history import lock_history

        lock_history(db, ward_id)
        lock(db, f"observation-ward:{ward_id}")
        offer = (
            db.query(HelpOfferRecord)
            .filter_by(id=offer_id, ward_id=ward_id)
            .one_or_none()
        )
        channel = (
            db.query(SupportChannel)
            .filter_by(id=channel_id, ward_id=ward_id)
            .one_or_none()
        )
        if not offer or not channel:
            raise HTTPException(404, "invitation not found")
        old = db.get(SupportReceipt, receipt_id)
        if old:
            if (
                old.offer_id != offer_id
                or old.channel_id != channel_id
                or old.medium != medium
                or utc(old.presented_at) != presented_at
            ):
                raise HTTPException(409, "receipt identity conflict")
            return {"version": offer.version, "status": offer.status}
        if medium not in {"card_rendered", "speech_completed", "speech_suppressed"}:
            raise HTTPException(422, "invalid presentation medium")
        if (
            presented_at.tzinfo is None
            or presented_at > self.clock() + timedelta(seconds=5)
            or presented_at < self.clock() - timedelta(seconds=60)
        ):
            raise HTTPException(422, "invalid presentation time")
        if (
            offer.version != expected_version
            or offer.status not in {"ready", "presented"}
            or not channel.enabled
            or utc(channel.expires_at) <= self.clock()
            or presented_at >= utc(offer.expires_at)
            or self.clock() >= utc(offer.expires_at)
        ):
            raise HTTPException(409, "invitation expired or changed")
        if medium == "card_rendered" and self.present(ward_id, channel_id) is None:
            raise HTTPException(409, "invitation no longer eligible")
        if medium == "speech_completed" and not channel.handsfree:
            raise HTTPException(409, "speech not enabled")
        db.add(
            SupportReceipt(
                id=receipt_id,
                offer_id=offer.id,
                channel_id=channel.id,
                medium=medium,
                presented_at=presented_at,
            )
        )
        if medium != "speech_suppressed" and offer.status == "ready":
            from app.application.commands.companion_history import (
                append_support_invitation,
            )

            append_support_invitation(
                db, ward_id=ward_id, offer_id=offer.id, content=PROMPTS[offer.kind]
            )
            offer.status = "presented"
            offer.presented_at = presented_at
            offer.expires_at = min(
                utc(offer.expires_at), presented_at + timedelta(seconds=60)
            )
            offer.version += 1
            db.add(
                OutboxEvent(
                    aggregate_type="help_offer",
                    aggregate_id=offer.id,
                    event_type="HelpOfferPresented.v1",
                    payload={
                        "schema_version": "HelpOfferPresented.v1",
                        "ward_id": ward_id,
                        "offer_id": offer.id,
                        "receipt_id": receipt_id,
                        "medium": medium,
                    },
                )
            )
        return {"version": offer.version, "status": offer.status}

    def respond(self, ward_id, offer_id, action, version, command_id):
        db = self.db
        from app.application.commands.companion_history import lock_history

        lock_history(db, ward_id)
        lock(db, f"observation-ward:{ward_id}")
        offer = (
            db.query(HelpOfferRecord)
            .filter_by(id=offer_id, ward_id=ward_id)
            .one_or_none()
        )
        if not offer:
            raise HTTPException(404, "invitation not found")
        target = {"accept_help": "accepted", "decline_help": "declined"}.get(action)
        if target is None:
            raise HTTPException(422, "invalid action")
        if offer.response_command == command_id:
            if offer.status != target:
                raise HTTPException(409, "command identity conflict")
            return {
                "status": offer.status,
                "focus_composer": target == "accepted" and offer.kind == "offer_help",
            }
        if (
            offer.version != version
            or offer.status != "presented"
            or utc(offer.expires_at) <= self.clock()
        ):
            raise HTTPException(409, "invitation expired or changed")
        offer.status, offer.response_command = target, command_id
        offer.version += 1
        return {
            "status": target,
            "focus_composer": target == "accepted" and offer.kind == "offer_help",
        }

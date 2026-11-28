"""Ward-initiated Sprint and observation quiet controls."""

from app.application.ports.companion import WorkflowOutcome


class StudyConversation:
    def __init__(self, db):
        self.db = db

    def confirm(self, run, invocation, payload):
        from app.application.commands.sprint import SprintService

        result = SprintService(self.db).execute(
            run.ward_id,
            invocation.command_id,
            payload["action"],
            sprint_id=payload["sprint_id"],
            expected_version=payload["expected_version"],
        )
        return self._study_response(
            run, "已按你的选择更新这轮挑战。", sprint=result["sprint"]
        )

    def _study_response(
        self, run, text, *, sprint=None, needs_start=False, observation_quiet=None
    ):
        actions = []
        if needs_start and sprint:
            actions = [
                {
                    "id": f"sprint:{run.id}:{run.attempt}:{sprint['id']}:{sprint['version']}",
                    "name": "start",
                    "command": "sprint_command",
                    "enabled": True,
                    "label": "开始这次挑战",
                    "payload": {
                        "sprint_id": sprint["id"],
                        "expected_version": sprint["version"],
                        "action": "start",
                    },
                }
            ]
        interaction = {
            "protocol": "companion-interaction.v2"
            if sprint
            else "companion-interaction.v1",
            "kind": "sprint_control" if sprint else "text",
            "content": text,
            "parts": [{"type": "text", "text": text}],
            "actions": actions,
            "sprint": sprint,
        }
        if observation_quiet is not None:
            interaction["observation_quiet"] = observation_quiet
        return WorkflowOutcome(
            run_status="waiting_for_ward" if needs_start else "closed",
            outcome_type="waiting" if needs_start else "completed",
            response=interaction,
        )

    def handle_action(self, run, invocation, proposal, *, expected_quiet_version=None):
        from app.application.commands.sprint import SprintService

        sprint_service = SprintService(self.db)
        action = proposal.action
        if action in {"quiet_start", "quiet_extend", "quiet_end"}:
            from datetime import datetime, timezone
            from zoneinfo import ZoneInfo
            from app.application.commands.observation_quiet import change_quiet
            from app.infrastructure.persistence.models import ObservationSettings

            if action != "quiet_end" and not proposal.target_minutes:
                return self._study_response(run, "想休息多久？")
            settings = self.db.get(ObservationSettings, run.ward_id)
            result = change_quiet(
                self.db,
                run.ward_id,
                str(invocation.command_id),
                action.removeprefix("quiet_"),
                proposal.target_minutes * 60
                if proposal.target_minutes and action != "quiet_end"
                else None,
                datetime.now(timezone.utc),
                expected_quiet_version,
            )
            message = "好了，摄像头陪伴提示已恢复。"
            if result["active"]:
                until = datetime.fromisoformat(result["effective_until"]).astimezone(
                    ZoneInfo(settings.timezone if settings else "Asia/Shanghai")
                )
                message = f"好，{until:%H:%M} 前不会发摄像头陪伴提示。"
            return self._study_response(run, message, observation_quiet=result)
        if action == "sprint_prepare":
            if not proposal.target_minutes:
                return self._study_response(run, "想试多久？")
            topic = proposal.topic or "专注挑战"
            result = sprint_service.execute(
                run.ward_id,
                invocation.command_id,
                "prepare",
                topic=topic,
                target_minutes=proposal.target_minutes,
                planned_start_at=proposal.planned_start_at,
            )
            return self._study_response(
                run,
                f"{topic}，试一轮{proposal.target_minutes}分钟？时间到不代表作业完成。",
                sprint=result["sprint"],
                needs_start=True,
            )
        if action.startswith("sprint_"):
            current = sprint_service.current(run.ward_id)["sprint"]
            if current is None:
                return self._study_response(run, "当前没有正在运行或暂停的挑战。")
            verb = {
                "sprint_pause": "pause",
                "sprint_resume": "resume",
                "sprint_end": "end",
            }[action]
            result = sprint_service.execute(
                run.ward_id,
                invocation.command_id,
                verb,
                sprint_id=current["id"],
                expected_version=current["version"],
            )
            return self._study_response(
                run, "本轮挑战已更新；任务完成情况不变。", sprint=result["sprint"]
            )

    def _current_sprint_context(self, ward_id):
        from app.application.commands.sprint import SprintService

        current = SprintService(self.db).current(ward_id)["sprint"]
        context = (
            {key: current[key] for key in ("topic", "status", "remaining_seconds")}
            if current
            else {}
        )
        from app.agent_specs.reminder_policy import current_policy

        if current_policy():
            from datetime import datetime, timezone
            from app.application.commands.observation_quiet import latest_period
            from app.application.commands.behavior_observation import utc

            period = latest_period(self.db, ward_id)
            context["camera_hints_version"] = period.version if period else 0
            until = utc(period.ended_at or period.scheduled_until) if period else None
            if until and until > datetime.now(timezone.utc):
                context["camera_hints_paused_until"] = until.isoformat()
        return context

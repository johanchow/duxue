"""Erase observation derivatives while retaining a disabled generation fence."""

from app.application.commands.behavior_observation import lock
from app.infrastructure.persistence import models as m


def erase_observation(db, ward_id):
    lock(db, f"observation-ward:{ward_id}")
    setting = db.get(m.ObservationSettings, ward_id)
    if setting:
        setting.generation += 1
        setting.enabled = False
        setting.report_enabled = False
        setting.observation_ranges = None
        setting.mode = "shadow"
    windows = db.query(m.ObservationWindowRecord.id).filter_by(ward_id=ward_id)
    days = db.query(m.ObservationDayRecord.id).filter_by(ward_id=ward_id)
    offers = db.query(m.HelpOfferRecord.id).filter_by(ward_id=ward_id)
    reports = db.query(m.ReflectionReportRecord.id).filter_by(ward_id=ward_id)
    for model, column, query in (
        (m.ObservationInterpretation, m.ObservationInterpretation.window_id, windows),
        (m.ObservationRevisionRecord, m.ObservationRevisionRecord.day_id, days),
        (m.SupportReceipt, m.SupportReceipt.offer_id, offers),
        (m.ReflectionReportVersion, m.ReflectionReportVersion.report_id, reports),
        (m.GuardianReportInbox, m.GuardianReportInbox.report_id, reports),
    ):
        db.query(model).filter(column.in_(query)).delete(synchronize_session=False)
    for model in (
        m.ObservationJob,
        m.ObservationWindowRecord,
        m.ObservationDayRecord,
        m.AcceptedEvidence,
        m.HelpOfferRecord,
        m.HelpOfferBudgetRecord,
        m.SupportChannel,
        m.SupportAssessment,
        m.ObservationConsumerInbox,
        m.ReflectionReportRecord,
    ):
        db.query(model).filter_by(ward_id=ward_id).delete(synchronize_session=False)

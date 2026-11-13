from tests.unit.behavior.conftest import observation_release  # noqa: F401
from datetime import timedelta

from app.application.commands.evening_reports import EveningReportCommands
from app.infrastructure.persistence.models import GuardianWard, ObservationSettings
from app.infrastructure.security.tokens import create_access_token
from tests.support.factories import create_guardian, create_ward, create_device
from tests.unit.behavior.test_observation import T


def auth(user):
    return {'Authorization':'Bearer '+create_access_token(user_id=user.id,role='guardian')}


def test_guardian_cannot_enable_another_wards_camera(client,db):
    guardian=create_guardian(db)
    mine=create_ward(db,guardian=guardian)
    other=create_ward(db)
    device=create_device(db,ward=other)
    db.commit()
    response=client.put(f'/wards/{mine.id}/observation-settings',headers=auth(guardian),json={'enabled':True,'camera_id':device.id})
    assert response.status_code==404
    assert db.get(ObservationSettings,mine.id) is None


def test_report_unbinding_revokes_access_and_pending_is_not_zero(client,db,observation_release):
    guardian=create_guardian(db)
    ward=create_ward(db,guardian=guardian)
    db.add(ObservationSettings(ward_id=ward.id,report_enabled=True))
    db.commit()
    url=f'/evaluation/evening-reports?ward_id={ward.id}&date={T.date()}'
    assert client.get(url,headers=auth(guardian)).status_code==202
    EveningReportCommands(db,lambda:T+timedelta(hours=3)).publish(ward.id,T.date())
    db.commit()
    result=client.get(url,headers=auth(guardian))
    assert result.status_code==200
    assert result.json()['observation'] is None
    db.query(GuardianWard).filter_by(guardian_id=guardian.id,ward_id=ward.id).delete()
    db.commit()
    assert client.get(url,headers=auth(guardian)).status_code==404

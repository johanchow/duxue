from .common import *

router = APIRouter(tags=["memory"])

@router.post("/memory/signals/{signal_id}/challenge")
def challenge_memory_signal(
    signal_id: str,
    body: SignalChallengeRequest,
    principal: Principal = Depends(current_ward),
    db: Session = Depends(get_db),
):
    """Allow a Ward to correct a derived conclusion with counterevidence."""
    try:
        service = SqlAlchemyMemoryCommandService(db)
        signal = service.challenge_signal(signal_id, principal.user_id, body.statement)
        service.rebuild_long_term_profile(principal.user_id)
        db.commit()
        return {"id": signal.id, "status": signal.status}
    except MemoryAccessDenied:
        db.rollback()
        raise HTTPException(404, "signal not found")


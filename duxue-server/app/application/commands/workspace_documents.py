"""Authorized, versioned commands for adult grading reports and lesson packs."""

from app.contexts.artifact_workspace.domain.versions import TEMPORARY_LIFETIME
from hashlib import sha256
from fastapi import HTTPException

from app.application.agent.gates import GateRunner
from app.application.workflows import education_workspace as workspace
from app.infrastructure.persistence.models import (
    ArtifactCommand,
    ArtifactVersion,
    EduArtifact,
    GradingReport,
    LessonPack,
    now,
)
from app.application.commands import artifact_workspace


def honest(phase, doc):
    if not isinstance(doc, workspace.Document):
        return False
    kind = "variant_question" if doc.kind == "lesson_pack" else "grading_item"
    items = [block for block in doc.blocks if block["kind"] == kind]
    evidence = tuple(
        workspace.evidence_digest(block)
        for block in items
        if not block["needs_manual_review"]
    )
    return (
        evidence == doc.verified_items
        and bool(items)
        and all(
            (b["status"] == "needs_manual_review" and b["needs_manual_review"])
            or (
                not b["needs_manual_review"]
                and b.get("reference_answers")
                and b["status"]
                in (
                    {"verified"}
                    if kind == "variant_question"
                    else {"correct", "incorrect"}
                )
            )
            for b in items
        )
    )


def require_review(doc, phase):
    runner = GateRunner({"artifact.verification_honesty": honest})
    if not runner.allows({"artifact.verification_honesty"}, phase=phase, candidate=doc):
        raise HTTPException(422, "无法交付尚未核验的产物")


def create(db, doc, owner, thread, keys):
    require_review(doc, "write")
    cls = LessonPack if doc.kind == "lesson_pack" else GradingReport
    root = cls(
        owner_id=owner,
        title=doc.title,
        source_thread_id=thread.id,
        expires_at=now() + TEMPORARY_LIFETIME,
        photos=list(doc.source_images),
        payload={"source_keys": keys, "generation": thread.history_generation},
    )
    db.add(root)
    db.flush()
    db.add(
        ArtifactVersion(
            artifact_id=root.id,
            version_no=1,
            payload={"title": doc.title, "blocks": doc.blocks},
        )
    )
    require_review(doc, "respond")
    return {
        "artifact_id": root.id,
        "artifact_type": doc.kind,
        "content": doc.title,
        "act": "artifact",
        "mode": "guardian_explain",
    }


def owned(db, owner, artifact_id, lock=False):
    from app.infrastructure.persistence.models import ConversationThread
    from sqlalchemy import or_

    q = db.query(EduArtifact).filter(
        EduArtifact.id == str(artifact_id),
        EduArtifact.owner_id == owner,
        EduArtifact.artifact_type.in_(("grading_report", "lesson_pack")),
        or_(EduArtifact.saved, EduArtifact.expires_at > now()),
    )
    row = (q.with_for_update() if lock else q).populate_existing().one_or_none()
    if row and not row.saved:
        thread = db.get(ConversationThread, row.source_thread_id)
        if (
            not thread
            or thread.deleted
            or thread.history_generation != row.payload["generation"]
        ):
            row = None
    if not row:
        raise HTTPException(404, "资源不存在或已过期")
    return row


def view(db, row):
    data = artifact_workspace.view(db, row)
    version = data.pop("pages")
    blocks = version["blocks"]
    data["title"] = version["title"]
    return {
        **data,
        "blocks": blocks,
        "artifact_type": row.artifact_type,
        "verification_status": "partial_needs_review"
        if any(b.get("needs_manual_review") for b in blocks)
        else "verified",
    }


def change(db, owner, artifact_id, body):
    digest = sha256(body.model_dump_json().encode()).hexdigest()

    def checked():
        row = owned(db, owner, artifact_id, lock=True)
        receipt = db.get(ArtifactCommand, (row.id, body.command_id))
        if (
            receipt
            and receipt.digest != digest
            or not receipt
            and row.revision != body.expected_revision
        ):
            raise HTTPException(409, "资源已更新，请刷新")
        return row, receipt

    row, receipt = checked()
    if receipt:
        return receipt.result
    blocks = None
    if body.action == "revise":
        original = view(db, row)
        keys = row.payload["source_keys"]
        images = list(row.photos)
        thread_id = row.source_thread_id
        db.commit()
        doc = workspace.prepare(
            owner=owner,
            content=body.instruction,
            keys=keys,
            skill_hint="edu.lesson_pack"
            if original["artifact_type"] == "lesson_pack"
            else "edu.worksheet_grading",
            previous=original,
            source_images=images,
            thread_id=thread_id,
        )
        require_review(doc, "write")
        row, receipt = checked()
        if receipt:
            return receipt.result
        blocks = {"title": doc.title, "blocks": doc.blocks}
    artifact_workspace.apply(db, row, body.action, blocks)
    row.expires_at = None if row.saved else now() + TEMPORARY_LIFETIME
    result = view(db, row)
    row.title = result["title"]
    db.add(
        ArtifactCommand(
            artifact_id=row.id, command_id=body.command_id, digest=digest, result=result
        )
    )
    db.commit()
    return result

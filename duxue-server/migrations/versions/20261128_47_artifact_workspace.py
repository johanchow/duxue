"""Consolidate the two artifact stores, retaining IDs, versions and receipts."""

from alembic import op
import sqlalchemy as sa

revision = "20261128_47"
down_revision = "20261128_46"
branch_labels = depends_on = None


def upgrade():
    from app.infrastructure.persistence.artifact_tables import (
        artifacts,
        versions,
        receipts,
    )

    db = op.get_bind()
    for table in (artifacts, versions, receipts):
        table.create(db, checkfirst=True)
    # The tables are locked together so a version cannot arrive during the copy.
    db.execute(
        sa.text(
            "LOCK TABLE creative_works, creative_work_versions, creative_work_commands, mentor_coursewares, mentor_courseware_versions IN ACCESS EXCLUSIVE MODE"
        )
    )
    op.execute("""INSERT INTO edu_artifacts
        (artifact_id, owner_id, artifact_type, command_id, state_revision, retention_status, title,
         updated_at, expires_at, payload, photos, branch, cursor)
        SELECT c.courseware_id, guardian_id, 'interactive_courseware', command_id, state_revision,
          retention_status, title, updated_at, expires_at, payload, photos,
          COALESCE((SELECT json_agg(version_no ORDER BY version_no) FROM mentor_courseware_versions v
             WHERE v.courseware_id=c.courseware_id), '[]'::json), COALESCE((payload->>'cursor')::integer,-1)
        FROM mentor_coursewares c""")
    op.execute(
        """INSERT INTO edu_artifact_versions SELECT courseware_id, version_no, payload FROM mentor_courseware_versions"""
    )
    op.execute("""INSERT INTO edu_artifacts
        (artifact_id, owner_id, artifact_type, source_thread_id, state_revision, retention_status, title,
         updated_at, expires_at, payload, photos, branch, cursor)
        SELECT id, ward_id, 'creative_work', source_thread_id, revision,
           CASE WHEN saved THEN 'saved' ELSE 'temporary' END, title, updated_at,
           CASE WHEN NOT saved THEN updated_at + interval '4 hours' END, '{}','[]', branch, cursor FROM creative_works""")
    op.execute(
        "INSERT INTO edu_artifact_versions SELECT work_id, number, pages FROM creative_work_versions"
    )
    op.execute(
        "INSERT INTO edu_artifact_commands SELECT work_id,command_id,digest,result FROM creative_work_commands"
    )
    for old in (
        "creative_work_commands",
        "creative_work_versions",
        "creative_works",
        "mentor_courseware_versions",
        "mentor_coursewares",
    ):
        op.drop_table(old)


def downgrade():
    from pathlib import Path
    from runpy import run_path

    directory = Path(__file__).parent
    for old in (
        "20261127_41_mentor_courseware.py",
        "20261128_43_creative_works.py",
        "20261128_46_story_source_reference.py",
    ):
        run_path(str(directory / old))["upgrade"]()
    op.execute("""INSERT INTO mentor_coursewares SELECT artifact_id, owner_id, command_id, state_revision,
      retention_status,title,updated_at,expires_at,
      jsonb_set(a.payload::jsonb, '{processed_command_ids}',
        COALESCE(a.payload::jsonb->'processed_command_ids','{}'::jsonb) ||
        COALESCE((SELECT jsonb_object_agg(r.command_id,r.result) FROM edu_artifact_commands r
                  WHERE r.artifact_id=a.artifact_id),'{}'::jsonb)),photos
      FROM edu_artifacts a WHERE artifact_type='interactive_courseware'""")
    op.execute("""INSERT INTO mentor_courseware_versions SELECT v.artifact_id,v.version_no,v.payload
      FROM edu_artifact_versions v JOIN edu_artifacts a ON a.artifact_id=v.artifact_id
      WHERE a.artifact_type='interactive_courseware' AND a.branch::jsonb @> jsonb_build_array(v.version_no)""")
    op.execute("""INSERT INTO creative_works SELECT artifact_id,owner_id,source_thread_id,title,
      retention_status='saved',state_revision,cursor,branch,updated_at FROM edu_artifacts WHERE artifact_type='creative_work'""")
    op.execute("""INSERT INTO creative_work_versions SELECT v.artifact_id,v.version_no,v.payload
      FROM edu_artifact_versions v JOIN creative_works c ON c.id=v.artifact_id""")
    op.execute("""INSERT INTO creative_work_commands SELECT v.artifact_id,v.command_id,v.digest,v.result
      FROM edu_artifact_commands v JOIN creative_works c ON c.id=v.artifact_id""")
    if op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM edu_artifacts WHERE artifact_type NOT IN ('creative_work','interactive_courseware')"
        )
    ):
        raise RuntimeError("Rollback requires export of new artifact types")
    for table in ("edu_artifact_commands", "edu_artifact_versions", "edu_artifacts"):
        op.drop_table(table)

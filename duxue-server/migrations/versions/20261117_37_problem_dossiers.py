"""ProblemSolving Domain persistence (`problem_dossiers`) and Tutoring dossier reference."""

import sqlalchemy as sa
from alembic import op

revision = "20261117_37"
down_revision = "20261116_36"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "problem_dossiers",
        sa.Column("id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("fingerprint", sa.String(length=80), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("owner_ward_id", sa.Uuid(as_uuid=False), nullable=True),
        sa.Column("subject", sa.String(length=32), nullable=False),
        sa.Column("tier", sa.String(length=16), nullable=False),
        sa.Column("stem", sa.JSON(), nullable=False),
        sa.Column("approaches", sa.JSON(), nullable=False),
        sa.Column("invariants", sa.JSON(), nullable=False),
        sa.Column("scoring_points", sa.JSON(), nullable=False),
        sa.Column("final_answers", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("solver_version", sa.String(length=64), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope IN ('ward', 'institution', 'bank')", name="ck_dossier_scope"),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'low_confidence', 'failed')",
            name="ck_dossier_status",
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'medium', 'low')",
            name="ck_dossier_confidence",
        ),
        sa.ForeignKeyConstraint(["owner_ward_id"], ["user_wards.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_problem_dossiers_fingerprint", "problem_dossiers", ["fingerprint"])
    op.create_index("ix_problem_dossiers_scope", "problem_dossiers", ["scope"])
    op.create_index("ix_problem_dossiers_owner_ward_id", "problem_dossiers", ["owner_ward_id"])
    op.create_index("ix_problem_dossiers_status", "problem_dossiers", ["status"])
    op.create_index(
        "ix_dossier_fingerprint_scope_owner",
        "problem_dossiers",
        ["fingerprint", "scope", "owner_ward_id"],
    )

    op.add_column(
        "tutoring_problems",
        sa.Column("dossier_id", sa.Uuid(as_uuid=False), nullable=True),
    )
    op.add_column(
        "tutoring_problems",
        sa.Column("milestone_progress", sa.JSON(), nullable=True),
    )
    op.create_foreign_key(
        "fk_tutoring_problem_dossier",
        "tutoring_problems",
        "problem_dossiers",
        ["dossier_id"],
        ["id"],
    )
    op.create_index("ix_tutoring_problems_dossier_id", "tutoring_problems", ["dossier_id"])


def downgrade():
    op.drop_index("ix_tutoring_problems_dossier_id", table_name="tutoring_problems")
    op.drop_constraint("fk_tutoring_problem_dossier", "tutoring_problems", type_="foreignkey")
    op.drop_column("tutoring_problems", "milestone_progress")
    op.drop_column("tutoring_problems", "dossier_id")

    op.drop_index("ix_dossier_fingerprint_scope_owner", table_name="problem_dossiers")
    op.drop_index("ix_problem_dossiers_status", table_name="problem_dossiers")
    op.drop_index("ix_problem_dossiers_owner_ward_id", table_name="problem_dossiers")
    op.drop_index("ix_problem_dossiers_scope", table_name="problem_dossiers")
    op.drop_index("ix_problem_dossiers_fingerprint", table_name="problem_dossiers")
    op.drop_table("problem_dossiers")

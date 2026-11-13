"""Accepted evidence journal and versioned observation infrastructure."""
from alembic import op
import sqlalchemy as sa

revision = '20261112_35'
down_revision = '20261104_34'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('frames', sa.Column('assignment_revision', sa.Integer(), nullable=True))
    op.create_table('evidence_sequence',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('value', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('observation_cursors',
    sa.Column('name', sa.String(length=40), nullable=False),
    sa.Column('value', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('name')
    )
    op.create_table('help_offer_budgets',
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('local_date', sa.Date(), nullable=False),
    sa.Column('reserved_count', sa.Integer(), nullable=False),
    sa.Column('last_reserved_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('ward_id', 'local_date')
    )
    op.create_table('help_offers',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('local_date', sa.Date(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('candidate', sa.JSON(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('presented_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('response_command', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('response_command')
    )
    op.create_table('observation_consumer_inbox',
    sa.Column('consumer', sa.String(length=40), nullable=False),
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('consumer', 'event_id')
    )
    op.create_table('observation_days',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('local_date', sa.Date(), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ward_id', 'local_date')
    )
    op.create_table('observation_jobs',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('available_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('token', sa.String(length=36), nullable=True),
    sa.Column('error_code', sa.String(length=80), nullable=True),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('reflection_reports',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('report_date', sa.Date(), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('current_version', sa.Integer(), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ward_id', 'report_date')
    )
    op.create_table('support_assessments',
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('fingerprint')
    )
    op.create_table('support_channels',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('handsfree', sa.Boolean(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ward_id')
    )
    op.create_table('guardian_report_inbox',
    sa.Column('guardian_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('report_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['guardian_id'], ['user_guardians.id'], ),
    sa.ForeignKeyConstraint(['report_id'], ['reflection_reports.id'], ),
    sa.PrimaryKeyConstraint('guardian_id', 'report_id')
    )
    op.create_table('observation_revisions',
    sa.Column('day_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['day_id'], ['observation_days.id'], ),
    sa.PrimaryKeyConstraint('day_id', 'revision')
    )
    op.create_table('observation_settings',
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('camera_id', sa.Uuid(as_uuid=False), nullable=True),
    sa.Column('generation', sa.Integer(), nullable=False),
    sa.Column('policy_version', sa.String(length=40), nullable=False),
    sa.Column('report_enabled', sa.Boolean(), nullable=False),
    sa.Column('deadline', sa.String(length=5), nullable=False),
    sa.Column('report_next_date', sa.Date(), nullable=True),
    sa.Column('observation_ranges', sa.JSON(), nullable=True),
    sa.ForeignKeyConstraint(['camera_id'], ['devices.id'], ),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('ward_id')
    )
    op.create_table('observation_windows',
    sa.Column('id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('camera_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('assignment_revision', sa.Integer(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('fingerprint', sa.String(length=64), nullable=False),
    sa.Column('input_version', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('manifest', sa.JSON(), nullable=False),
    sa.Column('generation', sa.Integer(), nullable=False),
    sa.Column('attempt_token', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['camera_id'], ['devices.id'], ),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ward_id', 'camera_id', 'assignment_revision', 'start_at')
    )
    op.create_table('reflection_report_versions',
    sa.Column('report_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('content', sa.JSON(), nullable=False),
    sa.Column('source_vector', sa.JSON(), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['report_id'], ['reflection_reports.id'], ),
    sa.PrimaryKeyConstraint('report_id', 'version')
    )
    op.create_table('support_receipts',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('offer_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('channel_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('medium', sa.String(length=30), nullable=False),
    sa.Column('presented_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['channel_id'], ['support_channels.id'], ),
    sa.ForeignKeyConstraint(['offer_id'], ['help_offers.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('observation_interpretations',
    sa.Column('window_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('input_version', sa.Integer(), nullable=False),
    sa.Column('cells', sa.JSON(), nullable=False),
    sa.Column('provenance', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['window_id'], ['observation_windows.id'], ),
    sa.PrimaryKeyConstraint('window_id', 'input_version')
    )
    op.create_table('accepted_evidence',
    sa.Column('sequence', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('frame_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('ward_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('camera_id', sa.Uuid(as_uuid=False), nullable=False),
    sa.Column('assignment_revision', sa.Integer(), nullable=True),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['camera_id'], ['devices.id'], ),
    sa.ForeignKeyConstraint(['frame_id'], ['frames.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['ward_id'], ['user_wards.id'], ),
    sa.PrimaryKeyConstraint('sequence'),
    sa.UniqueConstraint('frame_id')
    )
    op.create_index(op.f('ix_help_offers_ward_id'), 'help_offers', ['ward_id'], unique=False)
    op.create_index(op.f('ix_observation_consumer_inbox_ward_id'), 'observation_consumer_inbox', ['ward_id'], unique=False)
    op.create_index(op.f('ix_observation_days_ward_id'), 'observation_days', ['ward_id'], unique=False)
    op.create_index(op.f('ix_observation_jobs_status'), 'observation_jobs', ['status'], unique=False)
    op.create_index(op.f('ix_observation_jobs_available_at'), 'observation_jobs', ['available_at'], unique=False)
    op.create_index(op.f('ix_observation_jobs_ward_id'), 'observation_jobs', ['ward_id'], unique=False)
    op.create_index(op.f('ix_reflection_reports_ward_id'), 'reflection_reports', ['ward_id'], unique=False)
    op.create_index(op.f('ix_support_assessments_ward_id'), 'support_assessments', ['ward_id'], unique=False)
    op.create_index(op.f('ix_observation_windows_ward_id'), 'observation_windows', ['ward_id'], unique=False)
    op.create_index(op.f('ix_accepted_evidence_ward_id'), 'accepted_evidence', ['ward_id'], unique=False)
    # Historical assignments remain unknown until an audited explicit replay.


def downgrade():
    op.drop_table('accepted_evidence')
    op.drop_table('observation_interpretations')
    op.drop_table('support_receipts')
    op.drop_table('reflection_report_versions')
    op.drop_table('observation_windows')
    op.drop_table('observation_settings')
    op.drop_table('observation_revisions')
    op.drop_table('guardian_report_inbox')
    op.drop_table('support_channels')
    op.drop_table('support_assessments')
    op.drop_table('reflection_reports')
    op.drop_table('observation_jobs')
    op.drop_table('observation_days')
    op.drop_table('observation_consumer_inbox')
    op.drop_table('help_offers')
    op.drop_table('help_offer_budgets')
    op.drop_table('observation_cursors')
    op.drop_table('evidence_sequence')
    op.drop_column('frames', 'assignment_revision')

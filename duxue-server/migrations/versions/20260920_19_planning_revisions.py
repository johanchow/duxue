"""Versioned task edits and immutable confirmed draft/revision snapshots."""
import sqlalchemy as sa
from alembic import op

revision = '20260920_19'
down_revision = '20260918_18'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'version' not in {c['name'] for c in inspector.get_columns('tasks')}:
        op.add_column('tasks', sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
    for field in ('items', 'history'):
        if field not in {c['name'] for c in inspector.get_columns('daily_schedules')}:
            op.add_column('daily_schedules', sa.Column(field, sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
    constraints = {c['name'] for c in inspector.get_unique_constraints('plan_drafts')}
    indexes = {c['name'] for c in inspector.get_indexes('plan_drafts')}
    with op.batch_alter_table('plan_drafts') as batch:
        if 'uq_plan_draft_ward_date' in constraints:
            batch.drop_constraint('uq_plan_draft_ward_date', type_='unique')
        if 'uq_active_plan_draft_ward_date' not in indexes:
            batch.create_index('uq_active_plan_draft_ward_date', ['ward_id', 'plan_date'], unique=True,
                               postgresql_where=sa.text("status = 'active'"), sqlite_where=sa.text("status = 'active'"))
    # Old plans did not persist slots. Recover only explicitly confirmed draft
    # evidence, never invent times for legacy plans without a reviewed draft.
    conn = op.get_bind()
    schedules = sa.table('daily_schedules', sa.column('id', sa.Uuid()), sa.column('ward_id', sa.Uuid()),
                         sa.column('schedule_date', sa.Date()), sa.column('items', sa.JSON()))
    drafts = sa.table('plan_drafts', sa.column('ward_id', sa.Uuid()), sa.column('plan_date', sa.Date()),
                      sa.column('status', sa.String()), sa.column('items', sa.JSON()))
    for row in conn.execute(sa.select(schedules.c.id, drafts.c["items"]).join_from(schedules, drafts,
        sa.and_(schedules.c.ward_id == drafts.c.ward_id, schedules.c.schedule_date == drafts.c.plan_date,
                drafts.c.status == 'confirmed'))):
        conn.execute(schedules.update().where(schedules.c.id == row.id).values(items=[i for i in (row._mapping["items"] or []) if i.get("start_at") and i.get("end_at")]))


def downgrade():
    conn = op.get_bind()
    duplicate = conn.execute(sa.text('SELECT ward_id FROM plan_drafts GROUP BY ward_id, plan_date HAVING count(*) > 1')).first()
    if duplicate:
        raise RuntimeError('Cannot downgrade with revision history; export/reconcile drafts before rollback')
    with op.batch_alter_table('plan_drafts') as batch:
        batch.drop_index('uq_active_plan_draft_ward_date')
        batch.create_unique_constraint('uq_plan_draft_ward_date', ['ward_id', 'plan_date'])
    op.drop_column('daily_schedules', 'history')
    op.drop_column('daily_schedules', 'items')
    op.drop_column('tasks', 'version')

"""Real DB constraints/transactions; reuses the disposable local PostgreSQL harness."""

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker
from app.application.commands.sprint import SprintService
from app.infrastructure.persistence.models import Sprint, SprintCommand
from tests.support.factories import create_ward
from tests.integration.test_gateway_postgres import postgres_url, migrated_engine  # noqa: F401


def test_sprint_incremental_migration_and_single_live_concurrency(migrated_engine):  # noqa: F811 - imported pytest fixture
    assert "uq_sprint_live_ward" in {
        index["name"] for index in inspect(migrated_engine).get_indexes("study_sprints")
    }
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with factory() as db:
        ward = create_ward(db)
        db.commit()
        ward_id = ward.id

    def start(command):
        with factory() as db:
            try:
                result = SprintService(db).execute(
                    ward_id, command, "create", topic="阅读", target_minutes=10
                )
                db.commit()
                return result["sprint"]["id"]
            except HTTPException as error:
                db.rollback()
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, ["a", "b"]))
    assert results.count(409) == 1
    with factory() as db:
        assert db.query(Sprint).filter_by(ward_id=ward_id, status="active").count() == 1
        assert db.query(SprintCommand).filter_by(ward_id=ward_id).count() == 1


def test_postgres_same_command_returns_one_round_and_rollback_is_atomic(
    migrated_engine,  # noqa: F811 - imported pytest fixture
):
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with factory() as db:
        ward = create_ward(db)
        db.commit()
        ward_id = ward.id

    def start(_):
        with factory() as db:
            result = SprintService(db).execute(
                ward_id, "same", "create", topic="数学", target_minutes=15
            )
            db.commit()
            return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(start, range(2)))
    assert results[0] == results[1]
    with factory() as db:
        ward = create_ward(db)
        db.commit()
        other = ward.id
        SprintService(db).execute(
            other, str(uuid4()), "create", topic="阅读", target_minutes=10
        )
        db.rollback()
        assert db.query(Sprint).filter_by(ward_id=other).count() == 0
        assert db.query(SprintCommand).filter_by(ward_id=other).count() == 0


def test_migration_preserves_tasks_and_invalidates_old_review_cards(migrated_engine):  # noqa: F811 - imported pytest fixture
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from app.infrastructure.persistence.models import Task, PlanDraft

    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    with factory() as db:
        ward = create_ward(db)
        task = Task(ward_id=ward.id, title="历史作业", source="ward")
        from datetime import date

        draft = PlanDraft(
            ward_id=ward.id, plan_date=date(2026, 11, 3), status="active", version=7
        )
        db.add_all([task, draft])
        db.commit()
        task_id, draft_id = task.id, draft.id
    path = (
        Path(__file__).resolve().parents[2]
        / "migrations/versions/20261103_32_study_sprints.py"
    )
    spec = importlib.util.spec_from_file_location("sprint_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with migrated_engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
        assert (
            connection.execute(
                text("SELECT title FROM tasks WHERE id=:id"), {"id": task_id}
            ).scalar_one()
            == "历史作业"
        )
        state = connection.execute(
            text("SELECT status,version FROM plan_drafts WHERE id=:id"),
            {"id": draft_id},
        ).one()
        assert tuple(state) == ("superseded", 8)

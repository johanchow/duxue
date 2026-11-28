"""Verify the configured CI service provides independent, disposable databases."""

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

from tests.integration.test_gateway_postgres import postgres_url  # noqa: F401
from tests.support.postgres import isolated_database


def test_child_databases_isolate_data_and_alembic_state(postgres_url):  # noqa: F811
    parent = create_engine(postgres_url)
    names = []
    try:
        # Existing data in the configured parent must survive child lifecycles.
        with parent.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE isolation_marker (id integer)")
            connection.exec_driver_sql("INSERT INTO isolation_marker VALUES (7)")

        with isolated_database(postgres_url) as first_url:
            names.append(make_url(first_url).database)
            first = create_engine(first_url)
            try:
                with first.begin() as connection:
                    assert not inspect(connection).has_table("isolation_marker")
                    connection.exec_driver_sql(
                        "CREATE TABLE alembic_version (version_num varchar(32))"
                    )
                    connection.exec_driver_sql(
                        "INSERT INTO alembic_version VALUES ('first-module')"
                    )
                # Overlapping lifetimes exercise parallel module isolation too.
                with isolated_database(postgres_url) as second_url:
                    names.append(make_url(second_url).database)
                    second = create_engine(second_url)
                    try:
                        assert not inspect(second).has_table("alembic_version")
                        assert not inspect(second).has_table("isolation_marker")
                    finally:
                        second.dispose()
                with first.connect() as connection:
                    assert (
                        connection.exec_driver_sql(
                            "SELECT version_num FROM alembic_version"
                        ).scalar_one()
                        == "first-module"
                    )
            finally:
                first.dispose()

        assert len(set(names)) == 2
        with parent.connect() as connection:
            assert (
                connection.exec_driver_sql(
                    "SELECT id FROM isolation_marker"
                ).scalar_one()
                == 7
            )
            for name in names:
                assert (
                    connection.execute(
                        text("SELECT 1 FROM pg_database WHERE datname = :name"),
                        {"name": name},
                    ).first()
                    is None
                )
    finally:
        with parent.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS isolation_marker")
        parent.dispose()


def test_failed_module_setup_cleans_its_database(postgres_url):  # noqa: F811
    name = None
    with (
        pytest.raises(RuntimeError, match="simulated setup failure"),
        isolated_database(postgres_url) as url,
    ):
        name = make_url(url).database
        raise RuntimeError("simulated setup failure")
    parent = create_engine(postgres_url)
    try:
        with parent.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"),
                    {"name": name},
                ).first()
                is None
            )
    finally:
        parent.dispose()

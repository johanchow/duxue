"""Disposable databases for tests sharing a configured PostgreSQL service."""

from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


@contextmanager
def isolated_database(server_url):
    """Create/drop only a uniquely named child DB; leave the supplied DB intact.

    The test role needs CREATEDB. Separate databases also isolate extensions,
    Alembic revisions and migrations running in independent subprocesses.
    """
    url = make_url(server_url)
    name = "duxue_gateway_test_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            # The identifier consists solely of a fixed prefix and UUID hex.
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            try:
                yield url.set(database=name).render_as_string(hide_password=False)
            finally:
                connection.exec_driver_sql(f'DROP DATABASE "{name}"')
    finally:
        admin.dispose()

import pytest

from app.bootstrap.settings import ConfigurationError, Settings

URL = "redis://duxue_test:example@127.0.0.1:16379/1"
PG = "postgresql+psycopg://local/duxue-test"


@pytest.mark.parametrize("url,database,env", [
    (URL.replace("/1", "/0"), PG, "test"),
    (URL + "?db=0", PG, "test"),
    (URL.replace("duxue_test", "default"), PG, "test"),
    (URL, PG.replace("-test", "-prod"), "test"),
    (URL, PG, "production"),
])
def test_shared_debug_rejects_mismatched_connections(url, database, env):
    with pytest.raises(ConfigurationError):
        Settings(redis_url=url, database_url=database, app_env=env)


def test_debug_prefix_for_broker_and_results():
    from app.workers.redis_config import create_celery_app

    app = create_celery_app(Settings(redis_url=URL, database_url=PG, app_env="test"))
    assert app.conf.broker_transport_options["global_keyprefix"] == "duxue:test:"
    assert app.conf.result_backend_transport_options["global_keyprefix"] == "duxue:test:"
    assert app.conf.result_expires == 3600
    prod = create_celery_app(Settings(redis_url="redis://redis/0", database_url=PG.replace("-test", "-prod"), app_env="production"))
    assert "global_keyprefix" not in prod.conf.broker_transport_options


def test_production_credentials_copied_to_local_dotenv_fail_before_startup(tmp_path):
    import os
    import subprocess
    import sys

    local = tmp_path / ".env"
    local.write_text("APP_ENV=production\nDATABASE_URL=postgresql://db/duxue-prod\nREDIS_URL=redis://default@redis/0\n")
    env = {k: v for k, v in os.environ.items() if k not in {"APP_ENV", "DATABASE_URL", "REDIS_URL"}}
    result = subprocess.run(
        [sys.executable, "-c", "from app.bootstrap.settings import settings"],
        env={**env, "ENV_FILE": str(local), "STORAGE_BACKEND": "local", "SECRET_KEY": "unit", "VLM_API_KEY": "unit"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "local .env" in result.stderr


@pytest.mark.parametrize("variable", ["CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "CELERY_BROKER_READ_URL", "CELERY_BROKER_WRITE_URL"])
def test_celery_environment_override_cannot_redirect_debug_traffic(monkeypatch, variable):
    monkeypatch.setenv(variable, "redis://redis/0")
    with pytest.raises(ConfigurationError, match="endpoints"):
        Settings(redis_url=URL, database_url=PG, app_env="test")

"""Start Admin's isolated Python executor, using only duxue-admin/.env."""
import os
from pathlib import Path

from dotenv import dotenv_values


def executor_environment(root: Path, inherited: dict[str, str]) -> dict[str, str]:
    environment = {
        key: value for key, value in dotenv_values(root / '.env').items()
        if value is not None
    }
    environment.update(inherited)
    token = environment.get('AGENT_ADMIN_INTERNAL_TOKEN', '')
    if len(token) < 32:
        raise RuntimeError('请在duxue-admin/.env中配置至少32字符的AGENT_ADMIN_INTERNAL_TOKEN')
    if not environment.get('VLM_API_KEY'):
        raise RuntimeError('请在duxue-admin/.env中配置VLM_API_KEY')
    if environment.get('ADMIN_ENV', 'test') != 'test':
        raise RuntimeError('server:dev仅用于本机测试环境')
    environment.update({
        'ENV_FILE': str(root / '.env'),
        'APP_ENV': 'test',
        'DATABASE_URL': 'sqlite:///:memory:',
        'JWT_SECRET_KEY': token,
        'REDIS_HOST': 'unused',
        'REDIS_URL': 'redis://unused:6379/0',
        'STORAGE_BACKEND': 'local',
        'LOCAL_UPLOAD_DIR': str(root / '.local/uploads'),
        'AGENT_CONFIG_SOURCE_URL': '',
        'OTEL_SDK_DISABLED': 'true',
        'LANGFUSE_ENABLED': 'false',
        'AGENT_DEBUG_AUDIT_ENABLED': 'false',
    })
    return environment


def main():
    root = Path(__file__).resolve().parents[1]
    environment = executor_environment(root, dict(os.environ))
    os.chdir(root.parent / 'duxue-server')
    arguments = [os.sys.executable, '-m', 'uvicorn', 'app.bootstrap.agent_admin:app',
                 '--host', '127.0.0.1', '--port', '8011']
    if environment.get('DUXUE_PYTHON_ARCH') and os.sys.platform == 'darwin':
        os.execve('/usr/bin/arch', ['arch', '-' + environment['DUXUE_PYTHON_ARCH'], *arguments], environment)
    os.execve(os.sys.executable, arguments, environment)


if __name__ == '__main__':
    main()

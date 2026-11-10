"""Inspect explicit configuration snapshots or preflight a deployed Admin source."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('export', 'show', 'validate', 'preflight'))
    parser.add_argument('agent', nargs='?')
    args = parser.parse_args()
    if args.command == 'preflight':
        from app.agent_specs import release_runtime
        from app.bootstrap.settings import settings  # Load deployment ENV_FILE.
        from app.infrastructure.ai.components import validate_overrides
        validate_overrides()
        candidate = release_runtime.configured_runtime()
        if candidate is not None:
            candidate.restore_cache()
            candidate.tick(acknowledge=False)
            if candidate.current is None:
                raise RuntimeError('Admin发布包与兼容缓存均不可用，保留原运行服务')
            from app.application.workflows.image_review import require_configuration
            require_configuration(candidate.current[0]['bundle'])
            print('Admin发布配置已验证并缓存：' + candidate.current[1].digest)
        else:
            if settings.app_env in {'production', 'prod'}:
                raise RuntimeError('正式Server必须使用Admin发布配置')
            from app.agent_specs.configuration import read_snapshot
            print('Admin离线快照已验证：' + read_snapshot()['digest'])
        return
    from app.agent_specs.catalog import load_catalog, render_mermaid
    catalog = load_catalog()
    if args.command == 'validate':
        print('Admin configuration snapshot valid')
    elif args.command == 'show':
        if args.agent not in catalog.specs:
            parser.error('show requires a registered workflow')
        print(json.dumps(catalog.expanded(args.agent), ensure_ascii=False, indent=2))
    else:
        path = Path(__file__).resolve().parents[3] / 'docs/technical/agent-flow-current.md'
        path.write_text(render_mermaid(catalog), encoding='utf-8')
        print(path)


if __name__ == '__main__':
    main()

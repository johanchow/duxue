"""Production deployment must start every declared long-running service."""

import shlex
from pathlib import Path

import yaml


def test_deployment_pulls_and_starts_all_runtime_services():
    server = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((server / "docker-compose.yml").read_text())
    required = set(compose["services"]) - {"migrate"}
    required.add("math-engine")
    workflow = yaml.safe_load(
        (server.parent / ".github/workflows/server-deploy.yml").read_text()
    )
    step = next(
        step for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name") == "Migrate and start services"
    )
    commands = [shlex.split(line.strip().removesuffix("\\").strip())
                for line in step["run"].splitlines()
                if line.strip().startswith(("docker compose pull ", "docker compose up "))]
    for action in ("pull", "up"):
        command = next(tokens for tokens in commands
                       if tokens[:3] == ["docker", "compose", action])
        assert required <= set(command), f"{action} missing services: {required - set(command)}"

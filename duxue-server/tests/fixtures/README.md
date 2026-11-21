# Historical unit-test input

`admin-release.json` is the single fixed historical baseline for contract,
workflow-topology, and regression unit tests (workflows are no longer kept as
loose files under `agent_specs/workflows/`). `agent_specs/` holds only remaining
component-level test fixtures. None of these are production defaults; they are
excluded from Docker images and must never seed Admin or run live evaluations.
For the procedure to refresh a fixture from a saved Admin version, see the
[Agent configuration rules](../../../docs/technical/design-agent.md#配置铁律).

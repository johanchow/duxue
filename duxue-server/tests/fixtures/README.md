# Historical unit-test input

`admin-release.json` is the single fixed historical baseline for contract,
workflow-topology, and regression unit tests (workflows are no longer kept as
loose files under `agent_specs/workflows/`). `agent_specs/` holds only remaining
component-level test fixtures. None of these are production defaults; they are
excluded from Docker images and must never seed Admin or run live evaluations.
Business processes require an Admin release or an explicitly exported snapshot
under ignored `var/`.

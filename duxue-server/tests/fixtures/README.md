# Historical unit-test input

`agent_specs/` and `admin-release.json` are a fixed historical baseline for existing
contract, prompt-rendering and regression tests. They are not production defaults,
are excluded from Docker images, and must never seed Admin or run live evaluations.
Only tests/conftest.py installs the directory loader. Business processes require an
Admin release or an explicitly exported snapshot under ignored var/.

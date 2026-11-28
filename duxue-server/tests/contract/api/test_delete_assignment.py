"""Online task pools and daily plans have retired."""
import pytest


@pytest.mark.parametrize("method, path", [
    ("POST", "/wards/ward/assignments"), ("GET", "/wards/ward/assignments"),
    ("DELETE", "/wards/ward/assignments/task"), ("PUT", "/wards/ward/plans/2026-11-28"),
    ("POST", "/wards/ward/plans/2026-11-28/confirm"), ("GET", "/wards/ward/plans/2026-11-28"),
])
def test_planning_resources_are_absent(client, method, path):
    assert client.request(method, path).status_code == 404

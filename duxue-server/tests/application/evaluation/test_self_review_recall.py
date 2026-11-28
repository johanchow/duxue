def test_retired_self_review_routes_are_absent(client):
    path = "/wards/unknown/reviews/2026-11-28"
    assert client.put(path + "/confirm", json={}).status_code == 404
    assert client.get(path).status_code == 404
    assert client.get("/wards/unknown/guardian-story/2026-11-28").status_code == 404

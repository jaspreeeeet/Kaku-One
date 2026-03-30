def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_api_status_shape(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["system"] == "mimiclaw"
    assert "current_expression" in payload
    assert "available_expressions" in payload
    assert "connected_clients" in payload
    assert "animation" in payload


def test_namespaced_status_shape(client):
    response = client.get("/mimiclaw/api/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["system"] == "mimiclaw"


def test_expressions_roundtrip(client):
    response = client.get("/mimiclaw/expressions")
    assert response.status_code == 200
    expressions = response.json()["expressions"]
    assert isinstance(expressions, list)
    assert len(expressions) > 0

    target = expressions[0]
    post = client.post("/mimiclaw/expression", json={"expression": target})
    assert post.status_code == 200

    current = client.get("/mimiclaw/expression")
    assert current.status_code == 200
    assert current.json()["expression"] == target


def test_systems_endpoint(client):
    response = client.get("/api/systems")
    assert response.status_code == 200
    payload = response.json()
    assert "mimiclaw" in payload
    assert "esp32winamp" in payload
    assert payload["esp32winamp"]["proxy_prefix"] == "/music"


def test_music_list_endpoint(client):
    response = client.get("/music/list")
    assert response.status_code == 200
    payload = response.json()
    assert "tracks" in payload

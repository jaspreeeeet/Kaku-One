import os

from music import local_music


def test_music_upload_and_list(client, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(local_music, "UPLOAD_DIR", str(upload_dir))

    response = client.get("/music/list")
    assert response.status_code == 200
    assert response.json()["tracks"] == []

    files = {"file": ("track1.mp3", b"ID3TEST", "audio/mpeg")}
    upload = client.post("/music/upload", files=files)
    assert upload.status_code == 200

    response = client.get("/music/list")
    assert response.status_code == 200
    assert response.json()["tracks"] == ["track1.mp3"]

    stream = client.get("/music/track1.mp3")
    assert stream.status_code == 200
    assert stream.headers.get("content-type") == "audio/mpeg"
    assert stream.content == b"ID3TEST"


def test_esp32_play_url_command_roundtrip(client):
    initial = client.get("/music/esp32/command")
    assert initial.status_code == 200
    initial_payload = initial.json()
    assert "version" in initial_payload
    assert "action" in initial_payload

    response = client.post("/music/esp32/play-url", json={"url": "https://example.com/live.mp3"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["action"] == "play_url"
    assert payload["source_url"] == "https://example.com/live.mp3"
    assert payload["stream_url"] == "/music/stream?url=https://example.com/live.mp3"

    current = client.get("/music/esp32/command")
    assert current.status_code == 200
    current_payload = current.json()
    assert current_payload["version"] >= payload["version"]
    assert current_payload["action"] == "play_url"
    assert current_payload["source_url"] == "https://example.com/live.mp3"


def test_esp32_play_url_rejects_invalid_scheme(client):
    response = client.post("/music/esp32/play-url", json={"url": "file:///tmp/test.mp3"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Only http/https URLs are allowed"


def test_esp32_state_tracks_device_ip(client):
    response = client.post(
        "/music/esp32/state",
        json={
            "state": "playing",
            "file": "track1.mp3",
            "source": "remote",
            "device_ip": "192.168.1.6",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["device_ip"] == "192.168.1.6"

    current = client.get("/music/esp32/state")
    assert current.status_code == 200
    assert current.json()["device_ip"] == "192.168.1.6"

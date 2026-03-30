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

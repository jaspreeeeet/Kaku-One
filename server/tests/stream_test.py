import main
from music import local_music


def test_stream_headers_and_boundary(client, monkeypatch):
    async def _fake_generator(_queue):
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\nFAKE\r\n"

    monkeypatch.setattr(main, "_mjpeg_generator", _fake_generator)

    with client.stream("GET", "/stream") as response:
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "multipart/x-mixed-replace" in content_type
        assert "boundary=frame" in content_type

        first_chunk = next(response.iter_bytes())
        assert first_chunk.startswith(b"--frame")


def test_music_stream_url(client, monkeypatch):
    def _fake_get(*_args, **_kwargs):
        class _Resp:
            status_code = 200
            headers = {"Content-Type": "audio/mpeg", "Accept-Ranges": "bytes"}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=8192):
                yield b"ID3TEST"

        return _Resp()

    monkeypatch.setattr(local_music.requests, "get", _fake_get)

    with client.stream("GET", "/music/stream?url=https://example.com/test.mp3") as response:
        assert response.status_code == 200
        assert response.headers.get("content-type") == "audio/mpeg"
        first_chunk = next(response.iter_bytes())
        assert first_chunk == b"ID3TEST"

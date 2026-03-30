import os

import httpx
import pytest


PROD_BASE_URL = os.getenv("PROD_BASE_URL")


@pytest.mark.skipif(not PROD_BASE_URL, reason="Set PROD_BASE_URL to run production probes.")
def test_prod_systems_endpoint():
    response = httpx.get(f"{PROD_BASE_URL}/api/systems", timeout=15.0)
    assert response.status_code == 200
    payload = response.json()
    assert "mimiclaw" in payload
    assert "esp32winamp" in payload


@pytest.mark.skipif(not PROD_BASE_URL, reason="Set PROD_BASE_URL to run production probes.")
def test_prod_stream_headers():
    with httpx.stream("GET", f"{PROD_BASE_URL}/mimiclaw/stream", timeout=15.0) as response:
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "multipart/x-mixed-replace" in content_type
        assert "boundary=frame" in content_type


@pytest.mark.skipif(not PROD_BASE_URL, reason="Set PROD_BASE_URL to run production probes.")
def test_prod_music_list():
    response = httpx.get(f"{PROD_BASE_URL}/music/list", timeout=15.0)
    assert response.status_code == 200
    payload = response.json()
    assert "tracks" in payload

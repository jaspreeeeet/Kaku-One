import base64
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("MIMI_TRANSITION_FRAMES", "0")
sys.path.insert(0, r"D:\mimiclaw\server")

import main  # noqa: E402


_TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wCEAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wCEAQEBAQEBAQEB"
    "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
    "AQEBAQH/wAARCAAQABADASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAU"
    "EAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAf/xAAUEQEAAAAA"
    "AAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCkA//Z"
)


@pytest.fixture(scope="session")
def client():
    async def _noop():
        return None

    main.animator._latest_frame = _TINY_JPEG
    main.animator.start = _noop  # type: ignore[assignment]
    main.animator.stop = _noop  # type: ignore[assignment]

    with TestClient(main.app) as test_client:
        yield test_client

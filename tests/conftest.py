import json
import pytest
from fastapi.testclient import TestClient


class FakeOxAlphaClient:
    def __init__(self):
        self.last_messages = None
        self.stream_tokens = ["Hello", " world"]

    async def chat_with_auto_continue(self, messages, model, auto_continue=True, max_continuations=3):
        self.last_messages = messages
        for t in self.stream_tokens:
            yield {"type": "content", "delta": t}
        yield {"type": "finish", "finish_reason": "stop", "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}}


@pytest.fixture
def fake_client(monkeypatch):
    import server
    fc = FakeOxAlphaClient()
    monkeypatch.setattr(server, "oxalpha_client", fc)
    # also patch module-level reference used inside server functions
    import oxalpha_client
    monkeypatch.setattr(oxalpha_client, "oxalpha_client", fc)
    return fc


@pytest.fixture
def client(fake_client):
    from server import app
    return TestClient(app)
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_models(client):
    r = client.get("/v1/models")
    assert r.status_code == 200
    ids = [m["id"] for m in r.json()["data"]]
    assert "z-ai/glm-5.3-flash" in ids


def test_chat_non_streaming(client):
    r = client.post("/v1/chat/completions", json={
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["choices"][0]["message"]["content"] == "Hello world"
    assert data["usage"]["prompt_tokens"] == 5


def test_chat_streaming(client):
    r = client.post("/v1/chat/completions", json={
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    })
    assert r.status_code == 200
    assert "data: [DONE]" in r.text
    assert "Hello" in r.text


def test_empty_messages_400(client):
    r = client.post("/v1/chat/completions", json={"model": "gpt-4o", "messages": []})
    assert r.status_code == 400
    assert r.json()["error"]["type"] == "invalid_request_error"


def test_anthropic_non_streaming(client):
    r = client.post("/v1/messages", json={
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 100,
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
    })
    assert r.status_code == 200
    assert r.json()["content"][0]["text"] == "Hello world"


def test_responses(client):
    r = client.post("/v1/responses", json={"model": "gpt-4o", "input": "hi"})
    assert r.status_code == 200
    assert r.json()["output"][0]["content"][0]["text"] == "Hello world"
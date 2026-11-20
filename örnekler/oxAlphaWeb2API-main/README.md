# OxAlpha OpenAI Gateway

A clean-room, production-grade HTTP proxy that translates standard OpenAI API requests (`/v1/chat/completions`, `/v1/models`) into the internal protocol used by the OxAlpha web chat interface (`https://oxalpha.com/chat`), with native Server-Sent Events (SSE) streaming support.

---

## Architecture Overview

```
OpenAI Client (curl / OpenAI SDK / LibreChat / OpenWebUI)
│
▼
FastAPI Gateway Engine (app/api/)
│  ├── Auth Enforcement (Bearer token / X-API-Key)
│  ├── Request ID Tracking (X-Request-ID propagation)
│  └── Concurrency & Rate Limiting (async semaphore + sliding-window token bucket)
▼
Internal Canonical Models (app/models/canonical.py)
│
▼
AIProvider Interface (app/providers/base.py)
│
▼
OxAlpha Adapter (app/providers/oxalpha.py)
│  ├── Session & CSRF Token Pooling
│  ├── Role Normalization (folds 'system' prompts into user turns)
│  └── Model Translation ('oxalpha' -> 'z-ai/glm-5.3-flash')
▼
HTTPX Async Transport (app/services/transport.py)
│  ├── Connection pooling & persistent keep-alive
│  └── Exponential backoff & jitter on transient failures (429, 502, 503, 504)
▼
Upstream OxAlpha Service (https://oxalpha.com/api/chat)
```

---

## Features

- **Standard OpenAI API Parity**: Drop-in compatible with standard OpenAI SDKs, LangChain, LlamaIndex, LiteLLM, OpenWebUI, and LibreChat.
- **Server-Sent Events (SSE) Streaming**: Full real-time streaming deltas terminating in standard `data: [DONE]`.
- **Clean-Room Protocol Adapter**: Discovered through non-invasive observation of public endpoints. Zero CAPTCHA bypasses or proprietary decompilation.
- **Automated Session & CSRF Management**: Silently fetches and caches guest cookies and CSRF tokens from the web UI, auto-refreshing on expiration or HTTP 419 token mismatch.
- **System Prompt Folding**: Transparently merges system instructions into user prompts, preventing upstream HTTP 422 errors caused by OxAlpha's strict user/assistant role constraint.
- **Client Disconnect Handling**: Halts upstream streaming generators immediately if downstream clients close their connections.
- **100% Mocked Offline Test Suite**: All unit and integration tests run deterministically with zero live network calls.

---

## Quickstart

### 1. Requirements
- Python 3.11+
- `pip`

### 2. Installation
```bash
git clone <repo-url>
cd oxalphaweb2api
pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Key settings:
- `API_KEYS`: Comma-separated keys required by clients. Leave empty to allow unauthenticated access during development.
- `OXALPHA_BASE_URL`: Base URL for OxAlpha (defaults to `https://oxalpha.com`).
- `OXALPHA_MODEL`: Upstream model identifier (defaults to `z-ai/glm-5.3-flash`).
- `MAX_CONCURRENT_REQUESTS`: Max parallel outgoing connections (defaults to `10`).
- `RATE_LIMIT_PER_MINUTE`: Max requests per minute (defaults to `30`).

### 4. Running the Server
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The gateway is now running at `http://127.0.0.1:8000`.

### 5. Web Chat UI Tester
Open the lightweight test chat interface directly in your browser:
* **Via running server:** `http://127.0.0.1:8000/chat`
* **Direct file open:** Open `test_chat.html` directly in any web browser.

---

## API Usage & Examples

### Health Check
```bash
curl -X GET http://127.0.0.1:8000/health
```
**Response:**
```json
{"status": "ok"}
```

---

### List Models (`GET /v1/models`)
```bash
curl -X GET http://127.0.0.1:8000/v1/models \
  -H "Authorization: Bearer sk-oxalpha-local-test"
```
**Response:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "oxalpha",
      "object": "model",
      "created": 1700000000,
      "owned_by": "oxalpha"
    },
    {
      "id": "ox-alpha",
      "object": "model",
      "created": 1700000000,
      "owned_by": "oxalpha"
    },
    {
      "id": "z-ai/glm-5.3-flash",
      "object": "model",
      "created": 1700000000,
      "owned_by": "oxalpha"
    }
  ]
}
```

---

### Non-Streaming Chat Completion (`POST /v1/chat/completions`)
```bash
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-oxalpha-local-test" \
  -d '{
    "model": "oxalpha",
    "messages": [
      {"role": "system", "content": "You are a concise AI assistant."},
      {"role": "user", "content": "Explain what an HTTP proxy does in one sentence."}
    ],
    "stream": false
  }'
```
**Response:**
```json
{
  "id": "chatcmpl-oxalpha-a1b2c3d4e5f6",
  "object": "chat.completion",
  "created": 1700000000,
  "model": "oxalpha",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "An HTTP proxy acts as an intermediary gateway that forwards client requests to external web servers and returns their responses."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 140,
    "completion_tokens": 28,
    "total_tokens": 168
  }
}
```

---

### Streaming Chat Completion (`stream: true`)
```bash
curl -N -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-oxalpha-local-test" \
  -d '{
    "model": "oxalpha",
    "messages": [
      {"role": "user", "content": "Write a three-line poem about space."}
    ],
    "stream": true
  }'
```
**Streamed SSE Output:**
```http
data: {"id":"chatcmpl-oxalpha-a1b2c3d4e5f6","object":"chat.completion.chunk","created":1700000000,"model":"oxalpha","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}

data: {"id":"chatcmpl-oxalpha-a1b2c3d4e5f6","object":"chat.completion.chunk","created":1700000000,"model":"oxalpha","choices":[{"index":0,"delta":{"content":"Silent"},"finish_reason":null}]}

data: {"id":"chatcmpl-oxalpha-a1b2c3d4e5f6","object":"chat.completion.chunk","created":1700000000,"model":"oxalpha","choices":[{"index":0,"delta":{"content":" void of endless night,\nStars that dance in silver light,\nEchoes of creation call."},"finish_reason":"stop"}]}

data: [DONE]
```

---

### Official OpenAI Python SDK Client

```python
from openai import OpenAI

# Point client to your OxAlpha gateway
client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="sk-oxalpha-local-test", # or dummy string if auth disabled
)

# 1. Non-streaming call
completion = client.chat.completions.create(
    model="oxalpha",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello! What model are you?"},
    ],
)
print("Non-streaming response:", completion.choices[0].message.content)

# 2. Streaming call
stream = client.chat.completions.create(
    model="oxalpha",
    messages=[
        {"role": "user", "content": "Count from 1 to 5."},
    ],
    stream=True,
)
print("Streaming response: ", end="")
for chunk in stream:
    content = chunk.choices[0].delta.content or ""
    print(content, end="", flush=True)
print()
```

---

## Docker Deployment

Build and run using Docker:
```bash
# Build image
docker build -t oxalpha-gateway .

# Run container
docker run -d --name oxalpha-gateway -p 8000:8000 oxalpha-gateway
```

Or using Docker Compose:
```bash
docker compose up -d
```

---

## Running the Test Suite

All tests execute completely offline using HTTP mock transports (`httpx.MockTransport`), requiring zero network access:
```bash
python -m pytest -v
```

---

## Known Limitations & Protocol Assumptions

1. **System Prompt Support**:
   - The upstream OxAlpha endpoint rejects `"role": "system"` messages with `HTTP 422 {"error": "Invalid messages"}`.
   - The gateway automatically merges system instructions into user turns (`[System Instruction: ...]`), maintaining conversational guidance without error.
2. **Unsupported Features (Fail-Fast Policy)**:
   - Tool calling (`tools`, `tool_choice`) and function calling (`functions`) are not supported by the upstream web interface.
   - Supplying these parameters returns `HTTP 400 Bad Request` with an explicit diagnostic message rather than silently dropping execution semantics.
3. **Model Identifiers**:
   - OxAlpha's web interface utilizes `z-ai/glm-5.3-flash`. The gateway exposes `oxalpha`, `ox-alpha`, and `z-ai/glm-5.3-flash`, mapping them seamlessly to the upstream backend.
4. **Token Usage**:
   - Upstream usage counts are passed directly through when provided. Synthetic tokens are never fabricated.

# OxAlpha Protocol Specification

This document details the observed protocol, transport contracts, session lifecycle, streaming mechanics, and operational constraints of the OxAlpha web chat interface (`https://oxalpha.com/chat`) discovered through clean-room reverse engineering.

---

## 1. Executive Summary & Architecture Overview

OxAlpha provides a web-based chat interface backed by a PHP/Laravel application fronted by Cloudflare. The web client communicates with the backend via a REST initiation and Server-Sent Events (SSE) streaming transport.

Context history is stateful on the client side (full message history is submitted on each turn), while authentication/session identity is established via session cookies and a CSRF token embedded in the initial page response.

---

## 2. Network Transport

- **Web UI URL:** `https://oxalpha.com/chat`
- **Chat Endpoint:** `POST https://oxalpha.com/api/chat`
- **Transport Mechanism:** HTTP/1.1 or HTTP/2 POST with Server-Sent Events (SSE) stream returned (`Content-Type: text/event-stream; charset=utf-8`).

---

## 3. Session & Authentication Lifecycle

### 3.1 Session Establishment
To communicate with `/api/chat`, a client must first perform a `GET` request to `https://oxalpha.com/chat`:
1. **Cookies:**
   - `XSRF-TOKEN`: Laravel encrypted CSRF token cookie (`Max-Age=7200`, `Path=/`, `Secure`, `SameSite=Lax`).
   - `ox_alpha_session`: Encrypted Laravel session cookie identifying the client guest session.
2. **CSRF Token:**
   - Embedded in the HTML head: `<meta name="csrf-token" content="<TOKEN>">`.

### 3.2 Header Contract for `/api/chat`
All POST requests to `/api/chat` must supply the following headers:

| Header | Description | Mandatory | Example |
|---|---|---|---|
| `Content-Type` | MIME type for payload | Yes | `application/json` |
| `Accept` | Stream accept header | Yes | `text/event-stream, */*` |
| `X-CSRF-TOKEN` | Extracted CSRF token from page metadata | Yes | `AT3wGPrSqFEeQ7zH...` |
| `Cookie` | Session cookies | Yes | `XSRF-TOKEN=...; ox_alpha_session=...` |
| `Origin` | Browser origin security check | Recommended | `https://oxalpha.com` |
| `Referer` | Originating page URL | Recommended | `https://oxalpha.com/chat` |
| `User-Agent` | Standard browser User-Agent | Recommended | `Mozilla/5.0 ... Chrome/130.0.0.0` |

---

## 4. Payload Contracts

### 4.1 Request Payload Schema
```json
{
  "model": "z-ai/glm-5.3-flash",
  "messages": [
    {
      "role": "user",
      "content": "Hello world"
    },
    {
      "role": "assistant",
      "content": "Hello! How can I assist you today?"
    },
    {
      "role": "user",
      "content": "Can you summarize our conversation?"
    }
  ]
}
```

### 4.2 Parameter Constraints & Validation
- **`model`**: Must be the exact backend model identifier. As discovered from `window.__CHAT_MODELS__` in the web application, OxAlpha maps its model slug `ox-alpha` to `z-ai/glm-5.3-flash`. Submitting unrecognized model names or `"ox-alpha"` directly results in `HTTP 422 {"error": "Invalid model"}`. The Gateway translates canonical model aliases (`oxalpha`, `ox-alpha`, `z-ai/glm-5.3-flash`) to `z-ai/glm-5.3-flash`.
- **`messages`**: OxAlpha strictly expects role to be either `"user"` or `"assistant"`. Submitting a `"system"` role causes `HTTP 422 {"error": "Invalid messages"}`. The Gateway automatically merges/prepends system instructions into the initial user prompt.
- **Unsupported upstream parameters**:
  - `temperature`, `top_p`, `presence_penalty`, `frequency_penalty`, `max_tokens`: Ignored upstream by the web chat endpoint.
  - `tools`, `tool_choice`, `functions`: Not supported by the web chat interface; the Gateway returns `HTTP 400 Bad Request` if requested, avoiding silent contract failure.

---

## 5. Streaming Semantics & Chunk Framing

The endpoint responds with chunked Server-Sent Events delimited by `\n\n`.

### 5.1 Chunk Types

#### Content Delta Chunk
```http
data: {"id":"gen-1790365250-b7g2c6CFyoWmu7fuiSMk","object":"chat.completion.chunk","created":1790365250,"model":"z-ai/glm-5.3-flash","provider":"Relace","choices":[{"index":0,"delta":{"content":"Hello","role":"assistant"},"finish_reason":null,"native_finish_reason":null}]}
```

#### Finish Reason Chunk
```http
data: {"id":"gen-1790365250-b7g2c6CFyoWmu7fuiSMk","object":"chat.completion.chunk","created":1790365250,"model":"z-ai/glm-5.3-flash","provider":"Relace","choices":[{"index":0,"delta":{"content":"","role":"assistant"},"finish_reason":"stop","native_finish_reason":"stop"}]}
```

#### Usage Metadata Chunk
OxAlpha supplies usage information in the final chunk prior to stream completion:
```http
data: {"id":"gen-1790365250-b7g2c6CFyoWmu7fuiSMk","object":"chat.completion.chunk","created":1790365250,"model":"z-ai/glm-5.3-flash","provider":"Relace","service_tier":null,"choices":[{"index":0,"delta":{"content":"","role":"assistant"},"finish_reason":"stop","native_finish_reason":"stop"}],"usage":{"prompt_tokens":140,"completion_tokens":4,"total_tokens":144,"cost":0.00001092,"is_byok":false}}
```

#### Stream Completion Marker
```http
data: [DONE]
```

### 5.2 Error Framing
When an error occurs during streaming:
```http
event: error
data: {"error": "Limit reached", "limit_exhausted": true, "limit_type": "default"}
```
Or standard HTTP status responses (`422`, `429`, `500`) with JSON `{ "error": "..." }`.

---

## 6. Rate Limits, Concurrency & Checkpoints

### 6.1 Request-Rate Limits (Sliding Window)
- Header: `X-RateLimit-Limit: 30` (30 requests per minute)
- Header: `X-RateLimit-Remaining: <count>`
- HTTP 429 response when exceeding burst capacity:
  ```json
  {"error": "Too Many Requests", "limit_type": "default"}
  ```

### 6.2 Guest Checkpoint & Turnstile Verification (Precondition 428)
Through regression testing, the exact guest quota threshold was identified:
- **Free Guest Quota:** Exactly **20 messages** (`checkpoint: 20`) per session/IP before requiring verification.
- **Precondition Response:** `HTTP 428 Precondition Required` with:
  ```json
  {
    "error": "Please complete the quick verification to continue.",
    "code": "turnstile_required",
    "checkpoint": 20,
    "messages_today": 19
  }
  ```
- **Turnstile Parameter:** The web application displays Cloudflare Turnstile with `sitekey: "0x4AAAAAABp_UYRVl7snkQ51"` and appends header `'X-Turnstile-Token': <token>` to proceed past the checkpoint.
- **Gateway Mitigation:** The gateway maps `HTTP 428` to an actionable `HTTP 429` error notifying the downstream client of the upstream guest checkpoint and supports passing `OXALPHA_TURNSTILE_TOKEN` if supplied.


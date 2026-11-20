<div align="center">

# OxAlpha Free API Proxy

**A full OpenAI & Anthropic compatible local proxy for [oxalpha.com](https://oxalpha.com)**  
No registration · No login · No upstream API key required

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

🌐 **[Türkçe](README-tr.md)** · **[Русский](README-ru.md)**

</div>

---

## What is this?

`OxAlpha Free API` is a **local reverse-proxy server** that wraps the [oxalpha.com](https://oxalpha.com) chat interface and exposes it as a standard **OpenAI / Anthropic REST API**.

Run it locally, point any AI client to `http://localhost:8080`, and it just works — no account, no registration, no upstream API key needed.

---

## ✨ Features

| Feature | Detail |
|---|---|
| **OpenAI Chat Completions** | `POST /v1/chat/completions` — streaming & non-streaming |
| **Anthropic Messages API** | `POST /v1/messages` — full SSE streaming, tool_use blocks |
| **OpenAI Responses API** | `POST /v1/responses` — shim for newer OpenAI SDK |
| **Files API** | `POST/GET/DELETE /v1/files` — upload files, attach via `file_id` |
| **Models endpoint** | `GET /v1/models` — returns all supported aliases |
| **Parallel tool calls** | Multiple tool calls parsed from a single response |
| **System prompt partitioning** | Huge agent prompts split into native file blocks so the model reads every rule |
| **Smart tool output routing** | `read_file` → `[Attached file]`, `write_file` → `[File Written]`, commands → clean text |
| **Cloudflare Turnstile auto-solver** | HTTP 428 intercepted and solved headlessly via Camoufox |
| **Auto-continuation** | Seamlessly continues truncated responses with no repeated content |
| **Docker support** | One-command deploy with `docker compose up` |
| **Model alias mapping** | `gpt-4o`, `claude-3-5-sonnet`, `ox-alpha` all route to the same upstream |

---

## 🚀 Quick Start

### Option 1 — Python (local)

```bash
git clone https://github.com/tealaxdevelopers/oxalpha-free-api
cd oxalpha-free-api

pip install -r requirements.txt
python server.py
```

### Option 2 — Docker

```bash
docker compose up -d
```

### Windows

Double-click `start.bat` — installs dependencies automatically and launches the server.

The proxy starts on **`http://localhost:8080`**.

---

## 🔌 Client Configuration

Point any OpenAI or Anthropic compatible client at this proxy. Use any placeholder string as the API key.

<details>
<summary><b>Claude Code / Cline / Roo-Code</b></summary>

```json
{
  "baseUrl": "http://localhost:8080",
  "apiKey": "any-string",
  "model": "claude-3-5-sonnet-20241022"
}
```

</details>

<details>
<summary><b>Open WebUI</b></summary>

Go to **Settings → Connections → OpenAI API**:
- Base URL: `http://localhost:8080/v1`
- API Key: `any-string`

</details>

<details>
<summary><b>Cursor</b></summary>

Go to **Settings → Models → OpenAI API Key**:
- API Key: `any-string`
- Base URL override: `http://localhost:8080`

</details>

<details>
<summary><b>LiteLLM</b></summary>

```yaml
model_list:
  - model_name: ox-alpha
    litellm_params:
      model: openai/ox-alpha
      api_base: http://localhost:8080/v1
      api_key: any-string
```

</details>

<details>
<summary><b>Python — openai SDK</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="any-string",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=True,
)
for chunk in response:
    print(chunk.choices[0].delta.content or "", end="", flush=True)
```

</details>

<details>
<summary><b>Python — anthropic SDK</b></summary>

```python
import anthropic

client = anthropic.Anthropic(
    base_url="http://localhost:8080",
    api_key="any-string",
)

message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(message.content[0].text)
```

</details>

---

## ⚙️ Configuration

Edit `config.json`:

```json
{
  "host": "0.0.0.0",
  "port": 8080,
  "api_key": null,
  "auto_continue": true,
  "max_continuations": 3,
  "turnstile_auto_solve": true,
  "proxy": null,
  "request_timeout": 90
}
```

| Key | Default | Description |
|---|---|---|
| `api_key` | `null` | If set, clients must pass `Authorization: Bearer <key>` |
| `auto_continue` | `true` | Automatically continue truncated responses |
| `max_continuations` | `3` | Maximum continuation rounds per request |
| `turnstile_auto_solve` | `true` | Auto-solve Cloudflare challenges via Camoufox |
| `turnstile_solver_url` | `null` | Optional external Turnstile solver URL |
| `proxy` | `null` | HTTP proxy for upstream requests (e.g. `http://user:pass@host:port`) |
| `request_timeout` | `90` | Upstream request timeout in seconds |

All keys can also be set via **environment variables**: `API_KEY`, `PORT`, `HOST`, `PROXY`, `AUTO_CONTINUE`, `MAX_CONTINUATIONS`, `TURNSTILE_AUTO_SOLVE`, `REQUEST_TIMEOUT`.

---

## 📡 API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check & config summary |
| `GET` | `/v1/models` | List available models |
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions |
| `POST` | `/v1/messages` | Anthropic Messages |
| `POST` | `/v1/responses` | OpenAI Responses API |
| `POST` | `/v1/files` | Upload a file |
| `GET` | `/v1/files` | List uploaded files |
| `GET` | `/v1/files/{id}` | Get file metadata |
| `GET` | `/v1/files/{id}/content` | Download file content |
| `DELETE` | `/v1/files/{id}` | Delete a file |

---

## 🏗️ Architecture

```
Client (Claude Code / Cline / Open WebUI / …)
        │  OpenAI or Anthropic API request
        ▼
┌───────────────────────────────┐
│       FastAPI Proxy           │  ← server.py
│                               │
│  ┌─────────────────────────┐  │
│  │ content_handler         │  │  ← system prompt partitioning
│  │ tool_service            │  │  ← tool call parsing (JSON/XML/DSML)
│  │ file_store              │  │  ← Files API persistence
│  └─────────────────────────┘  │
│                               │
│  ┌─────────────────────────┐  │
│  │  OxAlphaClient          │  │  ← CSRF session management
│  │  auto-continuation      │  │  ← seamless multi-round streaming
│  └─────────────────────────┘  │
│                               │
│  ┌─────────────────────────┐  │
│  │  TurnstileManager       │  │  ← Camoufox headless solver
│  └─────────────────────────┘  │
└───────────────────────────────┘
        │  SSE stream
        ▼
   oxalpha.com/api/chat
```

---

## ❓ FAQ

**Do I need an oxalpha.com account?**  
No. The proxy mimics a browser session — no login, no registration required.

**What model does it actually use?**  
The upstream model is `z-ai/glm-5.3-flash` (Ox Alpha Stealth Reasoning). All model aliases map to it.

**Why does Turnstile auto-solve sometimes fail?**  
Camoufox needs browser binaries. Run `python -m camoufox fetch` once after install. Alternatively set `"turnstile_auto_solve": false` and point `turnstile_solver_url` to an external solver.

**"Message limit reached" / 429 errors**  
OxAlpha enforces a daily per-IP message quota (150 messages/day) upstream. Once exceeded, requests return HTTP 429 with `limit_type: messages_per_ip` until the quota resets (typically at midnight, IP-based). The proxy surfaces this as a 429 error. Workarounds: route through an HTTP proxy (`"proxy"` in `config.json` or `PROXY` env var), or wait for the daily reset. Cookie/session resets do **not** bypass this limit.

**Can I expose this to the internet?**  
Yes — set `api_key` in `config.json` so random people cannot abuse your proxy.

---

## License

MIT © 2025

## 🔒 Security notes

- Default `host` is now `127.0.0.1` (local only).
- If `host` is a non-loopback address (`0.0.0.0`, …) and `api_key` is empty, a random key is generated and saved to `.files_cache/.api_key` (printed at startup). Clients must send `Authorization: Bearer <key>`.
- Unauthenticated public access requires an explicit `allow_unauthenticated: true` (or `ALLOW_UNAUTHENTICATED=1`) — not recommended.
- Files API responses no longer include the server-side file path; uploads are capped at 25 MB.

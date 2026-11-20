# Ox Alpha Proxy — Ox Alpha gateway

> I got tired of waiting for limits and losing context. So I built something.

An open-source proxy that gives you a slick, Ox Alpha-style chat experience by driving the official **oxalpha.com/chat** in a headless browser, then streaming the response back to a clean, self-hosted interface. Unlimited memory, tool calling, file preview, voice — like `gc1dk/chatgpt-proxy` but for Ox Alpha.

**Not affiliated with oxalpha.com. Independent, MIT licensed.**

---

## Features

- **Real Ox Alpha** — replies come from the real `oxalpha.com/chat` session (Playwright + fetch hybrid)
- **Stealth reasoning, 1M context** — `z-ai/glm-5.3-flash` via Ox Alpha. Built-in prompt: *You are Ox Alpha — Stealth Reasoning Model, 1M tokens*. You think as long as necessary, custom thinking level, thinking dropdown
- **Unlimited memory (Auto)** — saved transcript is source of truth; long chats auto-compact into rolling summary (`CONTEXT_BUDGET` default 320k chars). No “message too long”
- **Cross-restart memory** — transcript re-fed as hidden context on restart
- **Multiple chats** — sidebar like oxalpha.com: create, switch, rename, delete, export (md/json)
- **Auto-save** — `chats.json` after each turn (and every ~4s during stream)
- **System prompt** — Settings → custom instructions; built-in Ox Alpha identity is default
- **Streaming** — SSE `delta` / `done` / `error`
- **Markdown + code** — highlight.js, copy + download per block, filename sniffing (`<!-- index.html -->`), file hosting via `/sandbox`
- **Run from chat** — code blocks → **Run** preview (HTML/SVG/CSS/JS live), otherwise raw download
- **Images + files** — attach up to 2 images (5MB, auto-downscaled to 1568px JPEG) + 3 text/code files (100KB) via paperclip, paste, drag-drop. Vision via Ox Alpha. Stored with transcript, shown in bubbles, exported.
- **File preview** — viewer with Preview/Code toggle, copy, download, hosting on `/sandbox/:user/:file` for custom apps
- **Tool calling (real)** — OpenAI-compatible `tools`/`tool_choice`. Auto-detects shell: `powershell`/`cmd`/`bash`/`python`. Per-user sandbox with memory limit (`SANDBOX_MEMORY_MB` 512) + timeout (`SANDBOX_TIMEOUT_MS` 30s). Tools: `bash`, `python`, `write_file`, `read_file`, `list_files`. Works in opencode, hermes, Cursor, Continue, Cline, Zed, Neovim.
- **OpenAI-compatible API** — `POST /v1/chat/completions` (stream + non-stream) + `GET /v1/models`. No tools/system prompts injected for API callers (clean passthrough) — compatible with every CLI/IDE.
- **Sandbox per user** — `./sandbox/<user>` isolated, memory-limited so you don’t lose your PC. Hosting custom apps under `/sandbox`
- **Thinking animation** — `<i class="ox-status">Thinking…</i>` → `Thinking for Xs…` with elapsed timer, queued/busy states
- **Reactions** — 👍/👎/↻ per assistant message (local), edit pencil on user bubbles (branching), continue button on length-limit, jump-to-latest
- **Voice** — mic dictation (browser SpeechRecognition, needs https/localhost) + spoken replies via Edge TTS (`/api/tts`, no keys, Aria voice)
- **Auto driver healing** — selectors cached to `selectors.json`, heuristic fallbacks, healed on every send
- **Auth + accounts** — optional `AUTH_TOKEN` → login/signup (`scrypt` hashes), per-account chats, `Authorization: Bearer` or `X-Client-Id`+`X-Client-Token` for APIs, per-client rate limits
- **At-rest encryption** — `ENCRYPT_KEY` → AES-256-GCM for `chats.json`/`settings.json`
- **Mobile** — sidebar drawer, overlay, jump pill
- **MIT**

---

## How it Works

```
[Your UI]  --SSE-->  [Express server.js]  --Playwright/fetch-->  [oxalpha.com/chat (headless Chromium)]
      \_________________ /sandbox per user, /v1 API _________________/
```

- Each chat owns a persistent page/context tab. Messages typed into the real composer.
- `MutationObserver` streams deltas → SSE.
- Auto-compaction keeps feed bounded; hidden summary is the rolling memory.
- Tool calls parsed from ````json {"tool_calls":...}```` → executed in sandbox → result fed back → loop until final answer.

---

## Requirements

- Node.js 18+ (20+ recommended)
- npm
- Internet to `oxalpha.com`

Chromium auto-downloads on `npm install`.

---

## Installation

```bash
git clone https://github.com/gc1dk/ox-alpha-proxy
cd ox-alpha-proxy
npm install
npm start
# open http://localhost:3000
```

Windows: double-click `run.bat` (wizard → `web.env` → start).

---

## Configuration

All env vars (see `example.env`):

| Var | Default | Desc |
|---|---|---|
| `PORT` | `3000` | UI + API port |
| `HOST` | `127.0.0.1` | `127.0.0.1` local only, `0.0.0.0` to enable LAN |
| `HEADED` | `0` | `1` show browser (solve captcha once) |
| `PROFILE` | `./profile` | Chromium profile (cookies persist) |
| `TIMEOUT` | `300000` | max ms per reply |
| `CONTEXT_BUDGET` | `320000` | feed budget (auto-compact threshold) |
| `MAX_PROMPT` | `500000` | max chars per message |
| `AUTH_TOKEN` | *(none)* | master token → enables login/auth |
| `ALLOW_SIGNUP` | `1` | `0` disable self-registration |
| `ENCRYPT_KEY` | *(none)* | AES-256-GCM for chats/settings at rest |
| `SANDBOX_MEMORY_MB` | `512` | per-user sandbox memory hint |
| `SANDBOX_TIMEOUT_MS` | `30000` | per-tool timeout |
| `HTTPS` | `0` | `1` also serve https on `PORT+1` (self-signed, auto-trusted on Windows) for mic |

`.env` example:
```bash
cp example.env .env
node --env-file=.env server.js
# or set env in shell before npm start
```

---

## API

When `AUTH_TOKEN` set, send `Authorization: Bearer <master>` or `X-Client-Id` + `X-Client-Token`. Chats scoped per client.

### `POST /api/chat`
`{message, chatId?, images?}` → SSE `queue`/`delta`/`reset`/`done`/`error`

### `GET /v1/models`
Lists `ox-alpha` (so editors that auto-discover work)

### `POST /v1/chat/completions` — OpenAI-compatible

```bash
curl http://localhost:3000/v1/chat/completions \
 -H "Content-Type: application/json" \
 -d '{"model":"ox-alpha","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

- `model` any string (upstream is Ox Alpha’s current)
- `stream:true` → `chat.completion.chunk` + `[DONE]`
- `user` or `X-Session-Id` → persistent session
- `tools`/`tool_choice` fully supported (native tool calling), `response_format` for JSON
- Auth same as `/api/*`. No hidden system prompt/tools injected for API — clean passthrough for IDEs.

**Point your IDE/CLI at it:** see `docs/ide-cli.md` — hermes, opencode, aider, Continue, Cline, Zed, Neovim, Obsidian configs.

### Other endpoints

`POST /api/new-chat` → `{id}` · `POST /api/stop` · `POST /api/chat-delete` · `POST /api/chat-rename` · `GET /api/history?chatId=…` · `GET /api/export?chatId=…&format=md|json` · `GET/POST /api/settings` · `POST /api/reset-session` · `POST /api/signup`/`/api/login` · `POST /api/register` (master) · `GET /api/status` · `GET /api/tts?text=…&voice=…`

---

## IDE / CLI Guide

See `docs/ide-cli.md`.

Quick examples:

**opencode** (`opencode.json`):
```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "ox-alpha": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Ox Alpha (local proxy)",
      "options": { "baseURL": "http://localhost:3000/v1" },
      "models": { "ox-alpha": { "name": "Ox Alpha — 1M" } }
    }
  }
}
```

**hermes** (`~/.hermes/config.yaml`):
```yaml
model:
  default: ox-alpha
  provider: custom
  base_url: http://localhost:3000/v1
  api_key: not-needed
```

**VS Code Continue** (`~/.continue/config.json`):
```json
{
  "models": [{ "title": "Ox Alpha", "provider": "openai", "model": "ox-alpha", "apiBase": "http://localhost:3000/v1", "apiKey": "not-needed" }]
}
```

**Cursor / Cline / Aider** — set `OPENAI_API_BASE=http://localhost:3000/v1` and `OPENAI_API_KEY=any`.

---

## Voice

- **Mic** — composer mic uses browser SpeechRecognition (needs secure page: `http://localhost` or `https://…`). Enable `HTTPS=1` for LAN mic; Windows auto-trusts cert.
- **Speak replies** — Settings → “Speak replies” or Play on any message. Streams via `/api/tts` (Edge voices, no keys). Default `en-US-AriaNeural`.

---

## Security

- Set `AUTH_TOKEN` for anything beyond your PC; chats per account, not per browser.
- `ENCRYPT_KEY` encrypts at rest; passwords `scrypt`.
- Bind `HOST=127.0.0.1` for local-only; don’t expose publicly without HTTPS reverse proxy.
- Never commit `profile/`, `chats.json`, `users.json`, `clients.json`, `.env`, `web.env`.

---

## Troubleshooting

- **Composer never ready** — driver self-heals selectors and caches to `selectors.json`. If still fails, run `HEADED=1 npm start` to see challenge, then restart headed off.
- **Rate limited** — auto-retries with backoff (3 tries). `POST /api/reset-session` for fresh profile, or delete `./profile`.
- **Timeout** — raise `TIMEOUT`. Long reasoning may need 5m+.
- **Turnstile** — handled automatically via headless browser token (`cf-turnstile-response` waited 8-12s). No frontend key needed.
- **LAN** — server binds `0.0.0.0`; open `http://<your-ip>:3000` from other devices; also shown in sidebar/status.

---

## License

MIT — see `LICENSE`.

## Author

**Gc.idk (Agent001)** — [@gc1dk](https://github.com/gc1dk)

> If you find something broken, improve it. If you find something useful, keep it.


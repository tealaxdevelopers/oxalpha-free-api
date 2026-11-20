# Ox Alpha Proxy — Local API Docs

Base URL (local, no LAN by default): `http://127.0.0.1:3000`

> LAN off by default (`HOST=127.0.0.1`). Enable LAN via `run.bat` → `2` or `HOST=0.0.0.0` + `npm start`. Docs are local-only unless LAN enabled.

## Auth

If `AUTH_TOKEN` is set in `.env`/`web.env`, all `/api/*` and `/v1/*` require:

- `Authorization: Bearer <master>` **or**
- `X-Client-Id: <id>` + `X-Client-Token: <token>` (from `/api/signup`/`/api/login` or `/api/register`)

Without `AUTH_TOKEN`, API is open (local).

## Chat (UI)

### POST /api/chat
SSE stream. Body: `{ message: string, chatId?: string, images?: [{name,dataUrl}] }`

Events: `data: {"type":"queue"}` → `data: {"type":"delta","text":"..."}` → `data: {"type":"done","text":"..."}` or `data: {"type":"error"}`

### POST /api/new-chat
Create chat: `{id}`

### POST /api/chat-delete
`{chatId}`

### POST /api/chat-rename
`{chatId, title}`

### GET /api/history?chatId=...
`{messages:[{role,text}]}`

### GET /api/chats
`{chats:[{id,title,updatedAt,messageCount}], activeChatId}`

### GET /api/export?chatId=...&format=md|json
Download transcript.

### GET/POST /api/settings
`{systemPrompt}` — built-in Ox Alpha identity is always included server-side; custom is addon.

### POST /api/reset-session
Clear Playwright cookies (fresh session). Master only if AUTH set.

### GET /api/status
`{ready, busy, queueLength, lanIps, port}`

### GET /api/tts?text=...&voice=...
Edge TTS MP3 stream (`en-US-AriaNeural` default, `TTS_MAX_CHARS`).

### POST /api/signup, POST /api/login
`{username,password}` → `{clientId, clientToken}`

## OpenAI-Compatible (for all IDEs/CLIs)

Base: `http://127.0.0.1:3000/v1` (Cursor/Cline/Zed/Windsurf/Copilot-compat). Also aliases: `http://127.0.0.1:3000/chat/completions`, `http://127.0.0.1:3000/v1/completions` (legacy), `http://127.0.0.1:3000/v1/messages` (Anthropic for Claude Code), `http://127.0.0.1:3000/v1/responses`.

### GET /v1/models
Lists `ox-alpha`, `ox-alpha-proxy`, `z-ai/glm-5.3-flash`, `openai/gpt-4o`, `anthropic/claude-sonnet-4.6`, `google/gemini-2.5-pro` (all map to Ox Alpha).

### POST /v1/chat/completions
OpenAI shape: `{model, messages:[{role,content}], stream, tools, tool_choice, response_format, user, max_tokens}`

- `model` any string (maps to Ox Alpha)
- `stream:true` → SSE `data: {"choices":[{"delta":{"content":"..."}}]}` + `data: [DONE]`
- `stream:false` → `{choices:[{message:{content}}]}`
- `tools`/`tool_choice` fully supported — server instructs Ox Alpha to emit ````json {"tool_calls":...}````, executes in per-user sandbox (`./sandbox/<user>`, `SANDBOX_MEMORY_MB`/`SANDBOX_TIMEOUT_MS`), loops until final answer (like opencode/hermes). IDEs that send tools get `tool_calls` back.
- `response_format: {type:"json_object"}` supported
- `user` or `X-Session-Id` header → persistent chat (memory via compaction)
- System messages (`role:system`) are respected even though UI has no system prompt — they are prepended as `### SYSTEM (from API):`.

### POST /v1/messages (Anthropic)
For Claude Code (`ANTHROPIC_BASE_URL=http://127.0.0.1:3000/v1`). Body: `{model, messages, system, max_tokens, stream}` → translated to OpenAI then back to Anthropic `{type:'message', content:[{type:'text'}]}`.

### POST /v1/responses
For Cursor/Codex. Body: `{model, input, stream}` → mapped to chat.

### POST /v1/completions
Legacy: `{model, prompt, stream}` → mapped to chat.

### GET /health, GET /v1/health
`{ok:true}`

## IDE/CLI Examples

**opencode** `opencode.json`:
```json
{
  "provider": {
    "ox-alpha": {
      "npm": "@ai-sdk/openai-compatible",
      "options": { "baseURL": "http://127.0.0.1:3000/v1" },
      "models": { "ox-alpha": { "name": "Ox Alpha — 1M" } }
    }
  }
}
```

**hermes** `~/.hermes/config.yaml`:
```yaml
model: { default: ox-alpha, provider: custom, base_url: http://127.0.0.1:3000/v1, api_key: sk-ox }
```

**Cursor** Settings → Models → Override OpenAI Base URL: `http://127.0.0.1:3000/v1`

**VS Code Continue** `~/.continue/config.json`:
```json
{ "models": [{ "title":"Ox Alpha","provider":"openai","model":"ox-alpha","apiBase":"http://127.0.0.1:3000/v1","apiKey":"sk-ox" }] }
```

**Aider** `OPENAI_API_BASE=http://127.0.0.1:3000/v1` `OPENAI_API_KEY=sk-ox` `aider --model ox-alpha`

**curl**
```bash
curl http://127.0.0.1:3000/v1/chat/completions -H "Content-Type: application/json" \
 -d '{"model":"ox-alpha","messages":[{"role":"user","content":"hi"}],"stream":false}'
```

See `docs/ide-cli.md` for Cline, Zed, Windsurf, Zed, Crush, llm, etc.

## Sandbox & Tools
Per-user `./sandbox/<user>` isolated, `SANDBOX_MEMORY_MB=512`, `SANDBOX_TIMEOUT_MS=30000`. Tools: `bash` (auto-detects powershell/cmd/bash/python), `python`, `write_file`, `read_file`, `list_files`. Files via `write_file` are hosted at `/sandbox/<user>/<path>` and get instant `Copy`/`Download` in chat (even single-line code auto-fenced).

## Web App
- `/` landing (dark, clean) → `/chat` chat (dark, clean)
- Both use `public/chat-assets/chat.css` / `public/chat-assets/chat.js` with `ox-thinking` shine + `stream-cursor` terminal
- 200 prompt examples typed in placeholder (shuffled each reload, `…` suffix, `▌` cursor, not copyable chips)
- Code auto-format: every line matching code regex is fenced even without system prompt, so single-line `x=5;` instantly gets `Copy`/`Download`.
- No LAN by default — local docs at `http://127.0.0.1:3000/docs` / `http://127.0.0.1:3000/api.html` (served from `public/docs/`)

MIT — see `LICENSE`

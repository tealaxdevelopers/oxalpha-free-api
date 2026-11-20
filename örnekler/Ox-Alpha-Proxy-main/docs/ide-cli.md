# Use Ox Alpha Proxy in every IDE / CLI

All of these point at `http://localhost:3000/v1` — OpenAI-compatible, no hidden prompts for API callers.

> Auth: if `AUTH_TOKEN` is set, add `Authorization: Bearer <master>` or `X-Client-Id`/`X-Client-Token`. Without `AUTH_TOKEN`, no auth needed.

## opencode

`opencode.json` in project or `~/.config/opencode/opencode.json`:

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

Select `ox-alpha` with `/models`. Tool calling works natively (sandbox: bash/python/file).

## hermes (Nous Research)

```bash
hermes model
# choose Custom endpoint → http://localhost:3000/v1 → model ox-alpha → key any
```

Or `~/.hermes/config.yaml`:

```yaml
model:
  default: ox-alpha
  provider: custom
  base_url: http://localhost:3000/v1
  api_key: not-needed
```

`hermes --provider custom --model ox-alpha "hello"`

## aider

```bash
export OPENAI_API_BASE=http://localhost:3000/v1
export OPENAI_API_KEY=sk-any
aider --model ox-alpha
```

or `~/.aider.conf.yml`:
```yaml
model: ox-alpha
openai-api-base: http://localhost:3000/v1
```

## VS Code — Continue

`~/.continue/config.json`:

```json
{
  "models": [{
    "title": "Ox Alpha",
    "provider": "openai",
    "model": "ox-alpha",
    "apiBase": "http://localhost:3000/v1",
    "apiKey": "any"
  }]
}
```

## Cursor

Settings → Models → OpenAI API Base: `http://localhost:3000/v1`, key `any`, model `ox-alpha`.

## Cline / Roo Code

Settings → API Provider: OpenAI Compatible → Base URL `http://localhost:3000/v1` → Model `ox-alpha`.

## Zed

`settings.json`:

```json
{
  "language_models": {
    "openai": { "api_url": "http://localhost:3000/v1", "available_models": [{ "name": "ox-alpha", "max_tokens": 131000 }] }
  }
}
```

## Neovim (llm.nvim / gen.nvim)

```lua
require('llm').setup({ url = "http://localhost:3000/v1", model = "ox-alpha" })
```

## Obsidian (Text Generator)

Set OpenAI base to `http://localhost:3000/v1`, model `ox-alpha`.

## llm (Simon Willison)

```bash
llm install llm-openai-plugin
llm keys set openai --value any
llm -m ox-alpha --option base_url http://localhost:3000/v1 "hello"
```

## curl

```bash
curl http://localhost:3000/v1/chat/completions -H "Content-Type: application/json" \
 -d '{"model":"ox-alpha","messages":[{"role":"user","content":"Write a haiku"}],"stream":false}'

# streaming + tools
curl http://localhost:3000/v1/chat/completions -H "Content-Type: application/json" \
 -d '{"model":"ox-alpha","messages":[{"role":"user","content":"List files in sandbox"}],"tools":[{"type":"function","function":{"name":"list_files","description":"list sandbox files"}}],"stream":true}'
```

## Structured output

```bash
curl http://localhost:3000/v1/chat/completions -H "Content-Type: application/json" \
 -d '{"model":"ox-alpha","messages":[{"role":"user","content":"Give me JSON with name and age"}],"response_format":{"type":"json_object"}}'
```

## Tool calling

Any OpenAI `tools` array works. The proxy instructs Ox Alpha to emit:

````json
{"tool_calls":[{"id":"call_1","type":"function","function":{"name":"bash","arguments":"{\"command\":\"ls\"}"}}]}
````

For UI chats, tools auto-execute in per-user sandbox (`./sandbox/<user>`) with memory limit. For API, the proxy returns `tool_calls` for the client to handle (like opencode does).

## Notes

- `stream:true` → `data: {"choices":[{"delta":{"content":"…"}}]}` + `data: [DONE]`
- `user` or `X-Session-Id` header → persistent session (memory via compaction)
- No hidden system prompt/tools for API → full control for your agent.
- App UI uses built-in Ox Alpha prompt + auto tools + file hosting under `/sandbox/<user>/…`

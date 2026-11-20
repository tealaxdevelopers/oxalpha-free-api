<div align="center">

# OxAlpha Free API Proxy

**Полный локальный прокси OpenAI & Anthropic для [oxalpha.com](https://oxalpha.com)**  
Без регистрации · Без входа · Без API-ключа от сервиса

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

🌐 **[English](README.md)** · **[Türkçe](README-tr.md)**

</div>

---

## Что это такое?

`OxAlpha Free API` — это **локальный reverse-proxy сервер**, который оборачивает интерфейс [oxalpha.com](https://oxalpha.com) и предоставляет его в виде стандартного **OpenAI / Anthropic REST API**.

Запустите локально, укажите любому AI-клиенту адрес `http://localhost:8080` — и всё просто работает. Аккаунт, регистрация и API-ключ сервиса не требуются.

---

## ✨ Возможности

| Возможность | Описание |
|---|---|
| **OpenAI Chat Completions** | `POST /v1/chat/completions` — потоковый и обычный режим |
| **Anthropic Messages API** | `POST /v1/messages` — полный SSE-стриминг, блоки tool_use |
| **OpenAI Responses API** | `POST /v1/responses` — поддержка нового OpenAI SDK |
| **Files API** | `POST/GET/DELETE /v1/files` — загрузка файлов, прикрепление через `file_id` |
| **Endpoint моделей** | `GET /v1/models` — возвращает все поддерживаемые псевдонимы |
| **Параллельные вызовы инструментов** | Несколько tool calls парсятся из одного ответа |
| **Разбивка системных промптов** | Огромные agent-промпты делятся на нативные файловые блоки, чтобы модель прочитала каждое правило |
| **Умная маршрутизация tool-результатов** | `read_file` → `[Attached file]`, `write_file` → `[File Written]`, команды → чистый текст |
| **Автоматическое решение Cloudflare Turnstile** | HTTP 428 перехватывается и решается в фоне через Camoufox |
| **Автопродолжение** | Прерванные ответы бесшовно продолжаются без повторений |
| **Поддержка Docker** | Одна команда — `docker compose up` |
| **Маппинг псевдонимов моделей** | `gpt-4o`, `claude-3-5-sonnet`, `ox-alpha` — все ведут к одному upstream |

---

## 🚀 Быстрый старт

### Вариант 1 — Python (локально)

```bash
git clone https://github.com/tealaxdevelopers/oxalpha-free-api
cd oxalpha-free-api

pip install -r requirements.txt
python server.py
```

### Вариант 2 — Docker

```bash
docker compose up -d
```

### Windows

Дважды кликните `start.bat` — зависимости установятся автоматически и сервер запустится.

Прокси запускается на **`http://localhost:8080`**.

---

## 🔌 Настройка клиентов

Укажите любому OpenAI или Anthropic совместимому клиенту адрес этого прокси. В качестве API-ключа можно использовать любую строку.

<details>
<summary><b>Claude Code / Cline / Roo-Code</b></summary>

```json
{
  "baseUrl": "http://localhost:8080",
  "apiKey": "любая-строка",
  "model": "claude-3-5-sonnet-20241022"
}
```

</details>

<details>
<summary><b>Open WebUI</b></summary>

Перейдите в **Settings → Connections → OpenAI API**:
- Base URL: `http://localhost:8080/v1`
- API Key: `любая-строка`

</details>

<details>
<summary><b>Cursor</b></summary>

Перейдите в **Settings → Models → OpenAI API Key**:
- API Key: `любая-строка`
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
      api_key: любая-строка
```

</details>

<details>
<summary><b>Python — openai SDK</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="любая-строка",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Привет!"}],
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
    api_key="любая-строка",
)

message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Привет!"}],
)
print(message.content[0].text)
```

</details>

---

## ⚙️ Конфигурация

Отредактируйте `config.json`:

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

| Ключ | По умолчанию | Описание |
|---|---|---|
| `api_key` | `null` | Если задан, клиенты обязаны передавать `Authorization: Bearer <key>` |
| `auto_continue` | `true` | Автоматически продолжать прерванные ответы |
| `max_continuations` | `3` | Максимальное количество раундов продолжения на запрос |
| `turnstile_auto_solve` | `true` | Автоматически решать Cloudflare-задачи через Camoufox |
| `turnstile_solver_url` | `null` | URL внешнего Turnstile-решателя (опционально) |
| `proxy` | `null` | HTTP-прокси для запросов к upstream (напр. `http://user:pass@host:port`) |
| `request_timeout` | `90` | Таймаут запроса к upstream (в секундах) |

Все ключи можно также задать через **переменные окружения**: `API_KEY`, `PORT`, `HOST`, `PROXY`, `AUTO_CONTINUE`, `MAX_CONTINUATIONS`, `TURNSTILE_AUTO_SOLVE`, `REQUEST_TIMEOUT`.

---

## 📡 API Endpoints

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/health` | Проверка работоспособности и конфигурации |
| `GET` | `/v1/models` | Список доступных моделей |
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions |
| `POST` | `/v1/messages` | Anthropic Messages |
| `POST` | `/v1/responses` | OpenAI Responses API |
| `POST` | `/v1/files` | Загрузка файла |
| `GET` | `/v1/files` | Список загруженных файлов |
| `GET` | `/v1/files/{id}` | Метаданные файла |
| `GET` | `/v1/files/{id}/content` | Скачать содержимое файла |
| `DELETE` | `/v1/files/{id}` | Удалить файл |

---

## 🏗️ Архитектура

```
Клиент (Claude Code / Cline / Open WebUI / …)
        │  Запрос OpenAI или Anthropic API
        ▼
┌───────────────────────────────┐
│       FastAPI Proxy           │  ← server.py
│                               │
│  ┌─────────────────────────┐  │
│  │ content_handler         │  │  ← разбивка системных промптов
│  │ tool_service            │  │  ← парсинг tool calls (JSON/XML/DSML)
│  │ file_store              │  │  ← хранилище Files API
│  └─────────────────────────┘  │
│                               │
│  ┌─────────────────────────┐  │
│  │  OxAlphaClient          │  │  ← управление CSRF-сессией
│  │  автопродолжение        │  │  ← бесшовный многораундовый стриминг
│  └─────────────────────────┘  │
│                               │
│  ┌─────────────────────────┐  │
│  │  TurnstileManager       │  │  ← headless-решатель Camoufox
│  └─────────────────────────┘  │
└───────────────────────────────┘
        │  SSE-поток
        ▼
   oxalpha.com/api/chat
```

---

## ❓ Часто задаваемые вопросы

**Нужен ли аккаунт на oxalpha.com?**  
Нет. Прокси имитирует браузерную сессию — вход и регистрация не требуются.

**Какая модель используется на самом деле?**  
Upstream-модель — `z-ai/glm-5.3-flash` (Ox Alpha Stealth Reasoning). Все псевдонимы моделей ведут к ней.

**Почему автоматическое решение Turnstile иногда не работает?**  
Camoufox нужны бинарники браузера. Выполните один раз после установки: `python -m camoufox fetch`. Также можно задать `"turnstile_auto_solve": false` и указать `turnstile_solver_url` для внешнего решателя.

**Можно ли открыть доступ в интернет?**  
Да — задайте `api_key` в `config.json`, чтобы посторонние не могли использовать ваш прокси бесплатно.

---

## Лицензия

MIT © 2025

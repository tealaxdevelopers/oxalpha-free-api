<div align="center">

# OxAlpha Free API Proxy

**[oxalpha.com](https://oxalpha.com) için tam uyumlu OpenAI & Anthropic yerel proxy**  
Kayıt yok · Giriş yok · Upstream API key gerekmez

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

🌐 **[English](README.md)** · **[Русский](README-ru.md)**

</div>

## ⚠️ Önemli: Günlük mesaj limiti (önce oku)

> **OxAlpha IP başına günlük 150 mesaj kotası uygular.** Kotaya ulaşınca istekler HTTP 429 (`limit_type: messages_per_ip`) döner, kota sıfırlanana kadar (genelde gece yarısı, IP bazlı) devam eder. Cookie/session sıfırlamak bu limiti aşmaz. Çözüm: HTTP proxy kullan (`config.json` → `"proxy"` veya `PROXY` env), ya da günlük sıfırlamayı bekle. Detaylar için SSS bölümüne bak.


---

## Bu nedir?

`OxAlpha Free API`, [oxalpha.com](https://oxalpha.com) chat arayüzünü saran ve yerel olarak çalıştırdığınızda standart bir **OpenAI / Anthropic REST API** olarak sunan bir **reverse-proxy sunucusudur**.

Herhangi bir AI istemcisini `http://localhost:8080` adresine yönlendirmeniz yeterlidir — hesap açmaya, kayıt olmaya ya da upstream API key'e gerek yoktur.

---

## ✨ Özellikler

| Özellik | Açıklama |
|---|---|
| **OpenAI Chat Completions** | `POST /v1/chat/completions` — streaming & non-streaming |
| **Anthropic Messages API** | `POST /v1/messages` — tam SSE streaming, tool_use blokları |
| **OpenAI Responses API** | `POST /v1/responses` — yeni OpenAI SDK uyumu |
| **Files API** | `POST/GET/DELETE /v1/files` — dosya yükleme, `file_id` ile ekleme |
| **Models endpoint** | `GET /v1/models` — tüm desteklenen alias'ları döner |
| **Paralel tool call** | Tek yanıtta birden fazla araç çağrısı parse edilir |
| **Sistem prompt bölme** | Dev agent promptları modelin her kuralı okuması için native dosya bloklarına ayrılır |
| **Akıllı tool sonuç yönlendirme** | `read_file` → `[Attached file]`, `write_file` → `[File Written]`, komutlar → temiz metin |
| **Cloudflare Turnstile otomatik çözücü** | HTTP 428 geldiğinde Camoufox ile arka planda otomatik çözülür |
| **Otomatik devam (Auto-continuation)** | Kesilen yanıtlar tekrar etmeden sorunsuz devam ettirilir |
| **Docker desteği** | `docker compose up` ile tek komutta çalıştır |
| **Model alias eşleme** | `gpt-4o`, `claude-3-5-sonnet`, `ox-alpha` hepsi aynı upstream'e yönlendirilir |

---

## 🚀 Hızlı Başlangıç

### Seçenek 1 — Python (yerel)

```bash
git clone https://github.com/tealaxdevelopers/oxalpha-free-api
cd oxalpha-free-api

pip install -r requirements.txt
python server.py
```

### Seçenek 2 — Docker

```bash
docker compose up -d
```

### Windows

`start.bat` dosyasına çift tıklayın — bağımlılıkları otomatik kurar ve sunucuyu başlatır.

Proxy **`http://localhost:8080`** adresinde çalışmaya başlar.

---

## 🔌 İstemci Yapılandırması

Herhangi bir OpenAI veya Anthropic uyumlu istemciyi bu proxy'e yönlendirin. API key olarak istediğiniz bir metni yazabilirsiniz.

<details>
<summary><b>Claude Code / Cline / Roo-Code</b></summary>

```json
{
  "baseUrl": "http://localhost:8080",
  "apiKey": "herhangi-bir-sey",
  "model": "claude-3-5-sonnet-20241022"
}
```

</details>

<details>
<summary><b>Open WebUI</b></summary>

**Settings → Connections → OpenAI API** bölümüne gidin:
- Base URL: `http://localhost:8080/v1`
- API Key: `herhangi-bir-sey`

</details>

<details>
<summary><b>Cursor</b></summary>

**Settings → Models → OpenAI API Key** bölümüne gidin:
- API Key: `herhangi-bir-sey`
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
      api_key: herhangi-bir-sey
```

</details>

<details>
<summary><b>Python — openai SDK</b></summary>

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",
    api_key="herhangi-bir-sey",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Merhaba!"}],
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
    api_key="herhangi-bir-sey",
)

message = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Merhaba!"}],
)
print(message.content[0].text)
```

</details>

---

## ⚙️ Yapılandırma

`config.json` dosyasını düzenleyin:

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

| Anahtar | Varsayılan | Açıklama |
|---|---|---|
| `api_key` | `null` | Doldurulursa client'lar `Authorization: Bearer <key>` göndermek zorundadır |
| `auto_continue` | `true` | Kesilen yanıtları otomatik devam ettirir |
| `max_continuations` | `3` | İstek başına maksimum devam turları |
| `turnstile_auto_solve` | `true` | Cloudflare zorluklarını Camoufox ile otomatik çözer |
| `turnstile_solver_url` | `null` | İsteğe bağlı harici Turnstile çözücü URL'si |
| `proxy` | `null` | Upstream istekler için HTTP proxy (ör. `http://kullanici:sifre@host:port`) |
| `request_timeout` | `90` | Upstream istek zaman aşımı (saniye) |

Tüm ayarlar **environment variable** olarak da geçilebilir: `API_KEY`, `PORT`, `HOST`, `PROXY`, `AUTO_CONTINUE`, `MAX_CONTINUATIONS`, `TURNSTILE_AUTO_SOLVE`, `REQUEST_TIMEOUT`.

---

## 📡 API Endpoint'leri

| Metot | Yol | Açıklama |
|---|---|---|
| `GET` | `/health` | Sağlık kontrolü ve yapılandırma özeti |
| `GET` | `/v1/models` | Mevcut modelleri listeler |
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions |
| `POST` | `/v1/messages` | Anthropic Messages |
| `POST` | `/v1/responses` | OpenAI Responses API |
| `POST` | `/v1/files` | Dosya yükler |
| `GET` | `/v1/files` | Yüklü dosyaları listeler |
| `GET` | `/v1/files/{id}` | Dosya meta verisini getirir |
| `GET` | `/v1/files/{id}/content` | Dosya içeriğini indirir |
| `DELETE` | `/v1/files/{id}` | Dosyayı siler |

---

## 🏗️ Mimari

```
İstemci (Claude Code / Cline / Open WebUI / …)
        │  OpenAI veya Anthropic API isteği
        ▼
┌───────────────────────────────┐
│       FastAPI Proxy           │  ← server.py
│                               │
│  ┌─────────────────────────┐  │
│  │ content_handler         │  │  ← sistem prompt bölme
│  │ tool_service            │  │  ← tool call parse (JSON/XML/DSML)
│  │ file_store              │  │  ← Files API kalıcı depolama
│  └─────────────────────────┘  │
│                               │
│  ┌─────────────────────────┐  │
│  │  OxAlphaClient          │  │  ← CSRF session yönetimi
│  │  otomatik devam         │  │  ← kesintisiz çok turlu streaming
│  └─────────────────────────┘  │
│                               │
│  ┌─────────────────────────┐  │
│  │  TurnstileManager       │  │  ← Camoufox headless çözücü
│  └─────────────────────────┘  │
└───────────────────────────────┘
        │  SSE akışı
        ▼
   oxalpha.com/api/chat
```

---

## ❓ Sık Sorulan Sorular

**oxalpha.com hesabı gerekiyor mu?**  
Hayır. Proxy bir tarayıcı oturumunu taklit eder — giriş veya kayıt gerekmez.

**Aslında hangi model kullanılıyor?**  
Upstream model `z-ai/glm-5.3-flash` (Ox Alpha Stealth Reasoning). Tüm model alias'ları buna yönlendirilir.

**Turnstile otomatik çözücü neden bazen başarısız olur?**  
Camoufox'un tarayıcı binary'lerine ihtiyacı var. Kurulumdan sonra bir kez `python -m camoufox fetch` çalıştırın. Alternatif olarak `"turnstile_auto_solve": false` yapıp `turnstile_solver_url` ile harici bir çözücü kullanabilirsiniz.

**Bunu internete açabilir miyim?**  
Evet — `config.json` içine `api_key` ekleyin ki başkaları proxy'nizi kötüye kullanmasın.

---

## Lisans

MIT © 2025

## 🔒 Güvenlik notları

- Varsayılan `host` artık `127.0.0.1` (yalnızca yerel erişim).
- `host` yerel olmayan bir adrese (`0.0.0.0` vb.) ayarlanır ve `api_key` boşsa, rastgele bir anahtar otomatik üretilir ve `.files_cache/.api_key` dosyasına kaydedilir (başlangıçta konsola yazılır). İstemciler `Authorization: Bearer <anahtar>` göndermelidir.
- Kimlik doğrulamasız genel erişim için bilinçli olarak `allow_unauthenticated: true` (veya `ALLOW_UNAUTHENTICATED=1`) gerekir — önerilmez.
- Files API yanıtları artık sunucudaki dosya yolunu içermez; yükleme boyutu 25 MB ile sınırlıdır.

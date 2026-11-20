import os
import json
import secrets
import ipaddress
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class AppConfig:
    # Loopback by default. Binding to a non-loopback address forces authentication (see _enforce_auth).
    host: str = "127.0.0.1"
    port: int = 8080

    # Bearer token for clients. If the server listens on a non-loopback address and this is
    # empty, a random key is generated and persisted to .files_cache/.api_key.
    api_key: Optional[str] = None
    # Explicit opt-out (NOT recommended): allow unauthenticated access on a public interface.
    allow_unauthenticated: bool = False

    default_model: str = "z-ai/glm-5.3-flash"
    supported_models: List[str] = field(default_factory=lambda: [
        "ox-alpha",
        "z-ai/glm-5.3-flash",
    ])

    oxalpha_base_url: str = "https://oxalpha.com"

    # Cloudflare Turnstile
    turnstile_sitekey: str = "0x4AAAAAABp_UYRVl7snkQ51"
    turnstile_url: str = "https://oxalpha.com/chat"
    turnstile_action: str = "chat"
    turnstile_auto_solve: bool = True
    # "camoufox" (default, built-in) or "external" (point to a solver HTTP service)
    turnstile_solver_mode: str = "camoufox"
    turnstile_solver_url: Optional[str] = None

    # Auto-continuation when the model hits its output length limit
    auto_continue: bool = True
    max_continuations: int = 3
    continuation_prompt: str = "Continue exactly from where you left off. Do not repeat anything."

    # Short "you are an agent, use the tools" reminder appended to the last user turn
    tool_reminder: bool = True

    # How large system prompts (e.g. opencode CLI) are delivered upstream:
    # "message" (plain message text, default) or "file" (legacy attached-file blocks)
    system_prompt_mode: str = "message"

    # HTTP proxy forwarded to httpx (e.g. "http://user:pass@host:port")
    proxy: Optional[str] = None

    # Timeouts
    request_timeout: int = 90          # seconds for a single upstream request
    connect_timeout: int = 20          # seconds for connect
    session_ttl_minutes: int = 60      # how long a CSRF session is reused

    # Resilience / concurrency (OpenAI-gateway style)
    max_concurrent_requests: int = 10
    rate_limit_per_minute: int = 60
    max_retries: int = 3
    backoff_factor: float = 0.5


def _is_loopback(host: str) -> bool:
    h = (host or "").strip().lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False  # "", "0.0.0.0", "::", hostnames -> treat as exposed


def _enforce_auth(cfg: "AppConfig") -> None:
    if cfg.api_key or _is_loopback(cfg.host):
        return
    if cfg.allow_unauthenticated:
        print("[warn] Listening on a non-loopback address WITHOUT authentication (allow_unauthenticated=true).")
        return
    base = os.path.dirname(os.path.abspath(__file__))
    key_dir = os.path.join(base, ".files_cache")
    key_path = os.path.join(key_dir, ".api_key")
    os.makedirs(key_dir, exist_ok=True)
    key = None
    try:
        with open(key_path, "r", encoding="utf-8") as f:
            key = f.read().strip() or None
    except OSError:
        pass
    if key:
        print(f"[security] host={cfg.host} is exposed; using API key from {key_path}")
    else:
        key = "sk-ox-" + secrets.token_urlsafe(32)
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key)
        print(f"[security] host={cfg.host} is exposed and no api_key was set.")
        print(f"[security] Generated API key (also saved to {key_path}):\n           {key}")
    cfg.api_key = key


def load_config() -> AppConfig:
    cfg = AppConfig()
    config_path = os.path.join(os.path.dirname(__file__), "config.json")

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
        except Exception as e:
            print(f"[warn] Failed to load config.json: {e}")

    # Environment variable overrides
    _env_map = {
        "PORT": ("port", int),
        "HOST": ("host", str),
        "API_KEY": ("api_key", lambda v: v.strip() or None),
        "ALLOW_UNAUTHENTICATED": ("allow_unauthenticated", lambda v: v.lower() in ("1", "true", "yes")),
        "PROXY": ("proxy", str),
        "MAX_CONCURRENT": ("max_concurrent_requests", int),
        "RATE_LIMIT_PER_MINUTE": ("rate_limit_per_minute", int),
        "MAX_RETRIES": ("max_retries", int),
        "BACKOFF_FACTOR": ("backoff_factor", float),
        "CONNECT_TIMEOUT": ("connect_timeout", int),
        "TOOL_REMINDER": ("tool_reminder", lambda v: v.lower() in ("1", "true", "yes")),
        "SYSTEM_PROMPT_MODE": ("system_prompt_mode", lambda v: v.strip().lower() if v.strip().lower() in ("message", "file") else "message"),
        "AUTO_CONTINUE": ("auto_continue", lambda v: v.lower() in ("1", "true", "yes")),
        "MAX_CONTINUATIONS": ("max_continuations", int),
        "TURNSTILE_AUTO_SOLVE": ("turnstile_auto_solve", lambda v: v.lower() in ("1", "true", "yes")),
        "TURNSTILE_SOLVER_URL": ("turnstile_solver_url", str),
        "REQUEST_TIMEOUT": ("request_timeout", int),
    }
    for env_key, (attr, cast) in _env_map.items():
        val = os.getenv(env_key)
        if val is not None:
            try:
                setattr(cfg, attr, cast(val))
            except Exception:
                pass

    _enforce_auth(cfg)
    return cfg


CONFIG = load_config()

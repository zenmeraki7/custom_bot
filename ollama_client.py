"""
ollama_client.py — the ONE place Ollama is configured and called
=================================================================
Why this is its own (tiny) file instead of living inside api.py:
api.py imports chat.py (via shop_manager), so chat.py can never
import api.py without a circular import. A leaf module that nothing
else depends on is the only home all callers can share.

Used by: api.py, chat.py, shop_rag.py, generate_shop.py,
         populate_faq_from_pdf.py

Config via env vars (same code on laptop and server):
    OLLAMA_HOST_URL  default http://localhost:11434
    OLLAMA_MODEL     default manglish-bot
    OLLAMA_TIMEOUT   default 30 (seconds)
"""

from __future__ import annotations
import os
import time
import threading

import requests

OLLAMA_HOST    = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434")
OLLAMA_URL     = f"{OLLAMA_HOST}/api/generate"
OLLAMA_TAGS    = f"{OLLAMA_HOST}/api/tags"
OLLAMA_MODEL   = os.environ.get("OLLAMA_MODEL", "manglish-bot")
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "30"))
KEEP_ALIVE     = -1                      # pin model in VRAM

GPU_OPTIONS = {
    "num_gpu":    999,   # offload all layers — lean gemma3:4b fits the 3050
    "num_ctx":    2048,
    "num_thread": 4,
}

# ── Liveness ping with 15s TTL (old cache stayed "down" forever) ─────
_PING_TTL  = 15.0
_ping_lock = threading.Lock()
_ping      = {"up": None, "at": 0.0}


def is_up() -> bool:
    """Cached liveness check — costs one 2s HTTP call per 15s max."""
    now = time.monotonic()
    with _ping_lock:
        if _ping["up"] is not None and now - _ping["at"] < _PING_TTL:
            return _ping["up"]
    try:
        up = requests.get(OLLAMA_TAGS, timeout=2).status_code == 200
    except requests.RequestException:
        up = False
    with _ping_lock:
        _ping.update(up=up, at=now)
    return up


def _mark(up: bool) -> None:
    with _ping_lock:
        _ping.update(up=up, at=time.monotonic())


# ── Degraded replies that still contain the shop's real contact ──────

def _degraded_reply(cfg: dict | None, lang: str) -> str:
    contact = (cfg or {}).get("contact", {}) or {}
    number  = contact.get("whatsapp") or contact.get("phone") or ""
    if lang == "manglish":
        if number:
            return (f"Kshamikkanam, ippo response slow aanu! WhatsApp cheyyuka "
                    f"{number} — njangal udane reply tharaam 😊")
        return "Kshamikkanam, ippo response slow aanu! Kurachu kazhinju try cheyyuka 😊"
    if number:
        return f"Sorry for the wait! Message us on WhatsApp {number} for an instant reply 😊"
    return "Sorry for the wait! Please try again in a moment 😊"


# ── The single generate() every module calls ──────────────────────────

def generate(
    prompt: str,
    *,
    system: str | None = None,
    temperature: float = 0.4,
    num_predict: int = 180,
    cfg: dict | None = None,
    lang: str = "english",
    timeout: int | None = None,
) -> tuple[str, bool]:
    """
    Returns (reply, ok).
      ok=True  → genuine model output
      ok=False → degraded fallback (customer-useful, includes WhatsApp
                 number when cfg is given). Callers that must not store
                 fallbacks (shop_rag enrichment) check ok and bail.
    """
    if not is_up():
        return _degraded_reply(cfg, lang), False

    body = {
        "model":      OLLAMA_MODEL,
        "prompt":     prompt,
        "stream":     False,
        "keep_alive": KEEP_ALIVE,
        "options": {
            **GPU_OPTIONS,
            "temperature":    temperature,
            "num_predict":    num_predict,
            "top_p":          0.9,
            "repeat_penalty": 1.1,
        },
    }
    if system is not None:
        body["system"] = system

    try:
        resp = requests.post(OLLAMA_URL, json=body, timeout=timeout or OLLAMA_TIMEOUT)
        resp.raise_for_status()
        reply = resp.json().get("response", "").strip()
        if not reply:
            raise ValueError("empty response")
        _mark(True)
        return reply, True
    except requests.exceptions.Timeout:
        print(f"[ollama] timeout after {timeout or OLLAMA_TIMEOUT}s")
        _mark(False)
        return _degraded_reply(cfg, lang), False
    except requests.exceptions.ConnectionError:
        print(f"[ollama] unreachable at {OLLAMA_HOST}")
        _mark(False)
        return _degraded_reply(cfg, lang), False
    except Exception as exc:
        print(f"[ollama] error: {exc}")
        return _degraded_reply(cfg, lang), False


def warm_up(timeout: int = 120) -> bool:
    """Load model into VRAM at startup. Generous timeout: cold load on a
    laptop 3050 can take 20-60s the very first time after reboot."""
    reply, ok = generate("hi", num_predict=8, timeout=timeout)
    print(f"[ollama] warm-up {'OK' if ok else 'FAILED (is Ollama running?)'}")
    return ok


def keepalive_loop(interval: int = 240) -> None:
    """Daemon-thread target: tiny ping keeps the model resident."""
    while True:
        time.sleep(interval)
        try:
            generate("hi", num_predict=4, timeout=20)
        except Exception:
            pass
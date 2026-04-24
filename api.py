# """
# api.py — Chottu Bot FastAPI Layer  v5.1
# ========================================
# Thin HTTP wrapper around chat.py.  All business logic lives in chat.py.

# Run:
#     uvicorn api:app --reload --host 0.0.0.0 --port 8000

# Routes
# ──────
#   POST /chat             → process a customer message
#   GET  /                 → serve static/index.html chat UI
#   GET  /health           → system + model status
#   GET  /faqs             → browse loaded FAQ pool  (?source=all|sentiment_aware|english|manglish|shop&limit=50)
#   GET  /stats            → chat log statistics (requires pandas)
#   GET  /logs/review      → Ollama-handled messages — FAQ gap candidates
#   GET  /logs/escalations → conversations flagged for human follow-up
#   GET  /logs/bypass      → messages that bypassed FAQ (praise, social, offtopic)

# Changes v5.0 → v5.1
# ──────────────────────
#   • Version bumped to 5.1 everywhere (health endpoint, app version, docstring)
#   • /faqs endpoint: flat FAQ entries now expose 'id' field (was always empty string
#     in v5.0 because load_english_faqs/load_manglish_faqs didn't carry it)
#   • /health faq_counts: added per-category breakdown for english + manglish pools
#   • /health: device label now shows MiB consistently (chat.py v5.1 fix)
#   • /stats: faq_by_id breakdown added — shows which FAQ IDs are hit most
#   • Startup log: confirms FAQ count matches english + manglish files
# """

# from __future__ import annotations

# from contextlib import asynccontextmanager

# import logging
# import os
# from collections import Counter
# from pathlib import Path
# from typing import Optional

# import torch
# from fastapi import FastAPI, HTTPException, Query
# from fastapi.middleware.cors import CORSMiddleware
# from fastapi.responses import FileResponse, JSONResponse
# from fastapi.staticfiles import StaticFiles
# from pydantic import BaseModel, field_validator

# from chat import (
#     pipeline,
#     BOT_NAME,
#     SHOP_NAME,
#     LOG_PATH,
#     OLLAMA_MODEL,
#     FAQ_THRESHOLD,
#     SEMANTIC_THRESHOLD,
#     SENTIMENT_THRESHOLD,
#     MANGLISH_BOOST,
#     device_name,
#     FAQ_EMB_TEXTS,
#     FAQS_SENTIMENT,
#     FAQS_ENGLISH,
#     FAQS_MANGLISH,
#     FAQS_SHOP,
# )

# log = logging.getLogger("chottu.api")

# # ══════════════════════════════════════════════════════════════════════════════
# #  APP SETUP
# # ══════════════════════════════════════════════════════════════════════════════

# @asynccontextmanager
# async def lifespan(app):
#     log.info(
#         "✅  %s API v5.1 ready — %d FAQ entries in embedding index "
#         "(english: %d, manglish: %d)",
#         BOT_NAME,
#         len(FAQ_EMB_TEXTS),
#         len(FAQS_ENGLISH),
#         len(FAQS_MANGLISH),
#     )
#     yield


# app = FastAPI(
#     title=f"{BOT_NAME} — Shop Chat API",
#     description=f"Bilingual (English + Manglish) customer support bot for {SHOP_NAME}.",
#     version="5.1",
#     lifespan=lifespan,
# )

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# os.makedirs("static", exist_ok=True)
# app.mount("/static", StaticFiles(directory="static"), name="static")


# # ══════════════════════════════════════════════════════════════════════════════
# #  SCHEMAS
# # ══════════════════════════════════════════════════════════════════════════════

# class ChatRequest(BaseModel):
#     message: str

#     @field_validator("message")
#     @classmethod
#     def message_not_empty(cls, v: str) -> str:
#         v = v.strip()
#         if not v:
#             raise ValueError("Message must not be empty")
#         if len(v) > 1000:
#             raise ValueError("Message too long (max 1000 characters)")
#         return v


# class ChatResponse(BaseModel):
#     """
#     Full pipeline response.  All fields from chat._make_result() are exposed.

#     source      : "greeting" | "faq" | "ollama"
#     bypass      : "" | "offtopic" | "social_chat" | "pure_praise" | "empty_tokens" | "vague_query"
#     lang        : "english" | "manglish"
#     sent_source : "lexicon" | "xlmr" | "greeting_regex" | "default"
#     faq_id      : populated for all FAQ sources in v5.1 (was empty for flat FAQs in v5.0)
#     """
#     message:     str
#     lang:        str
#     sentiment:   str
#     confidence:  float
#     sent_source: str
#     reply:       str
#     source:      str
#     bypass:      str
#     faq_source:  Optional[str]
#     faq_id:      Optional[str]
#     faq_score:   Optional[float]
#     escalate:    bool
#     ms:          float


# # ══════════════════════════════════════════════════════════════════════════════
# #  ROUTES
# # ══════════════════════════════════════════════════════════════════════════════

# @app.get("/", include_in_schema=False, response_model=None)
# def serve_ui():
#     index = Path("static/index.html")
#     if not index.exists():
#         return {"error": "Place index.html inside the /static folder."}
#     return FileResponse(str(index))


# @app.post("/chat", response_model=ChatResponse, summary="Process a customer message")
# def chat(req: ChatRequest) -> dict:
#     """
#     Main chat endpoint.  Accepts a customer message and returns:
#     - Detected language and sentiment
#     - Reply text (from FAQ, Ollama, or greeting)
#     - Routing metadata (source, faq_id, score, bypass reason)
#     - Latency in milliseconds
#     """
#     return pipeline(req.message)


# @app.get("/health", summary="System and model status")
# def health() -> dict:
#     gpu_info: dict = {}
#     if torch.cuda.is_available():
#         used_mib  = torch.cuda.memory_allocated(0) // 1_048_576
#         total_mib = torch.cuda.get_device_properties(0).total_memory // 1_048_576
#         gpu_info  = {
#             "gpu_name":    torch.cuda.get_device_name(0),
#             "vram_total":  f"{total_mib} MiB",
#             "vram_used":   f"{used_mib} MiB",
#             "vram_free":   f"{total_mib - used_mib} MiB",
#         }

#     # Per-category counts for flat FAQ pools (useful for monitoring FAQ coverage)
#     en_by_cat  = dict(Counter(f.get("section", "general") for f in FAQS_ENGLISH))
#     ml_by_cat  = dict(Counter(f.get("section", "general") for f in FAQS_MANGLISH))

#     return {
#         "status":               "ok",
#         "bot_name":             BOT_NAME,
#         "shop_name":            SHOP_NAME,
#         "version":              "5.1",
#         "device":               device_name,
#         "ollama_model":         OLLAMA_MODEL,
#         "thresholds": {
#             "semantic":         SEMANTIC_THRESHOLD,
#             "f1":               FAQ_THRESHOLD,
#             "sentiment":        SENTIMENT_THRESHOLD,
#             "manglish_boost":   MANGLISH_BOOST,
#         },
#         "faq_counts": {
#             "embedding_index":  len(FAQ_EMB_TEXTS),
#             "sentiment_aware":  len(FAQS_SENTIMENT),
#             "english":          len(FAQS_ENGLISH),
#             "manglish":         len(FAQS_MANGLISH),
#             "shop":             len(FAQS_SHOP),
#             "total_flat":       len(FAQS_ENGLISH) + len(FAQS_MANGLISH),
#         },
#         "faq_categories": {
#             "english":  en_by_cat,
#             "manglish": ml_by_cat,
#         },
#         **gpu_info,
#     }


# @app.get("/faqs", summary="Browse loaded FAQ pool")
# def list_faqs(
#     source: str = Query("all", description="all | sentiment_aware | english | manglish | shop"),
#     limit:  int = Query(50,    ge=1, le=500),
# ) -> dict:
#     pool_map: dict[str, list] = {
#         "all":             FAQS_SENTIMENT + FAQS_MANGLISH + FAQS_ENGLISH + FAQS_SHOP,
#         "sentiment_aware": FAQS_SENTIMENT,
#         "english":         FAQS_ENGLISH,
#         "manglish":        FAQS_MANGLISH,
#         "shop":            FAQS_SHOP,
#     }
#     if source not in pool_map:
#         raise HTTPException(status_code=400, detail=f"Unknown source '{source}'. Choose: {list(pool_map)}")

#     pool  = pool_map[source]
#     items = []
#     for faq in pool[:limit]:
#         if "questions" in faq:
#             # Sentiment-aware format
#             first_q = next(
#                 (q for qs in faq["questions"].values() for q in qs if q), ""
#             )
#             first_a = next(
#                 (a for a in faq.get("answers", {}).values() if a), ""
#             )
#             faq_id = faq.get("id", "")
#         else:
#             # Flat format (english / manglish)
#             first_q = faq.get("q", "")
#             first_a = faq.get("a", "")
#             faq_id  = faq.get("id", "")   # FIX v5.1: was always missing for flat FAQs

#         items.append({
#             "id":              faq_id,
#             "category":        faq.get("category") or faq.get("section", ""),
#             "source":          faq.get("source", ""),
#             "lang":            faq.get("lang", ""),
#             "sample_question": first_q,
#             "answer_preview":  (first_a[:120] + "…") if len(first_a) > 120 else first_a,
#         })

#     return {"total": len(pool), "shown": len(items), "source_filter": source, "items": items}


# @app.get("/stats", summary="Chat log statistics")
# def stats() -> dict:
#     try:
#         import pandas as pd
#     except ImportError:
#         return {"error": "Run 'pip install pandas' to enable /stats"}

#     if not Path(LOG_PATH).exists():
#         return {"total": 0, "message": "No logs yet"}

#     try:
#         df    = pd.read_csv(LOG_PATH)
#         total = len(df)
#         if total == 0:
#             return {"total": 0, "message": "Log is empty"}

#         counts   = df["source"].value_counts().to_dict()
#         faq_hits = counts.get("faq", 0)

#         # Bypass breakdown (v5.0+ column)
#         bypass_counts: dict = {}
#         if "bypass" in df.columns:
#             bypass_counts = (
#                 df[df["bypass"].notna() & (df["bypass"] != "")]
#                 ["bypass"].value_counts().to_dict()
#             )

#         # Language breakdown
#         lang_counts: dict = {}
#         if "lang" in df.columns:
#             lang_counts = df["lang"].value_counts().to_dict()

#         # Ollama calls split by lang
#         ollama_by_lang: dict = {}
#         if "lang" in df.columns:
#             ollama_by_lang = (
#                 df[df["source"] == "ollama"]["lang"]
#                 .value_counts().to_dict()
#             )

#         # FAQ source breakdown
#         faq_srcs: dict = {}
#         if "faq_source" in df.columns:
#             faq_srcs = (
#                 df[df["faq_source"].notna() & (df["faq_source"] != "")]
#                 ["faq_source"].value_counts().to_dict()
#             )

#         # FIX v5.1: Top FAQ IDs hit (useful for understanding which FAQs are used most)
#         top_faq_ids: dict = {}
#         if "faq_id" in df.columns:
#             top_faq_ids = (
#                 df[df["faq_id"].notna() & (df["faq_id"] != "")]
#                 ["faq_id"].value_counts().head(20).to_dict()
#             )

#         return {
#             "total":            total,
#             "greeting_hits":    counts.get("greeting", 0),
#             "faq_hits":         faq_hits,
#             "ollama_calls":     counts.get("ollama", 0),
#             "faq_hit_rate":     f"{faq_hits / total * 100:.1f}%",
#             "by_sentiment":     df["sentiment"].value_counts().to_dict(),
#             "by_lang":          lang_counts,
#             "by_bypass_reason": bypass_counts,
#             "faq_by_source":    faq_srcs,
#             "ollama_by_lang":   ollama_by_lang,
#             "top_faq_ids":      top_faq_ids,   # NEW in v5.1
#         }
#     except Exception as exc:
#         log.exception("Error in /stats")
#         return {"error": str(exc)}


# @app.get("/logs/review", summary="Ollama-handled messages (FAQ gap candidates)")
# def review_queue() -> dict:
#     """
#     Returns all messages answered by Ollama — these are candidates for
#     adding new FAQ entries.  Sorted newest-first.
#     """
#     try:
#         import pandas as pd
#     except ImportError:
#         return {"error": "Run 'pip install pandas' to enable /logs/review"}

#     if not Path(LOG_PATH).exists():
#         return {"count": 0, "items": []}

#     try:
#         df   = pd.read_csv(LOG_PATH)
#         mask = df["source"] == "ollama"
#         cols = [c for c in ["timestamp", "lang", "message", "sentiment", "bypass", "reply"] if c in df.columns]
#         rows = df[mask][cols].sort_values("timestamp", ascending=False).to_dict("records")
#         return {"count": len(rows), "items": rows}
#     except Exception as exc:
#         log.exception("Error in /logs/review")
#         return {"error": str(exc)}


# @app.get("/logs/escalations", summary="Flagged conversations for human follow-up")
# def escalation_queue() -> dict:
#     """
#     Returns all messages that triggered an escalation keyword.
#     These require human follow-up within 1 hour.
#     """
#     try:
#         import pandas as pd
#     except ImportError:
#         return {"error": "Run 'pip install pandas' to enable /logs/escalations"}

#     if not Path(LOG_PATH).exists():
#         return {"count": 0, "items": []}

#     try:
#         df   = pd.read_csv(LOG_PATH)
#         mask = df["escalate"].astype(str).str.lower().isin(["true", "1"])
#         cols = [c for c in ["timestamp", "lang", "message", "sentiment", "faq_id", "reply"] if c in df.columns]
#         rows = df[mask][cols].sort_values("timestamp", ascending=False).to_dict("records")
#         return {"count": len(rows), "items": rows}
#     except Exception as exc:
#         log.exception("Error in /logs/escalations")
#         return {"error": str(exc)}


# @app.get("/logs/bypass", summary="Messages that bypassed FAQ matching")
# def bypass_queue() -> dict:
#     """
#     Returns messages routed directly to Ollama via a bypass guard:
#       • offtopic     — personal questions about the bot
#       • social_chat  — check-ins / wellbeing questions
#       • pure_praise  — compliments with no shop request
#       • empty_tokens — all words were stopwords
#       • vague_query  — all tokens are generic with no domain signal (v5.1)
#     Useful for tuning the guards and identifying misrouted messages.
#     """
#     try:
#         import pandas as pd
#     except ImportError:
#         return {"error": "Run 'pip install pandas' to enable /logs/bypass"}

#     if not Path(LOG_PATH).exists():
#         return {"count": 0, "items": []}

#     try:
#         df   = pd.read_csv(LOG_PATH)
#         if "bypass" not in df.columns:
#             return {"count": 0, "items": [], "note": "No bypass column — log predates v5.0"}

#         mask = df["bypass"].notna() & (df["bypass"] != "")
#         cols = [c for c in ["timestamp", "lang", "message", "sentiment", "bypass", "reply"] if c in df.columns]
#         rows = df[mask][cols].sort_values("timestamp", ascending=False).to_dict("records")
#         summary = df[mask]["bypass"].value_counts().to_dict() if not df[mask].empty else {}
#         return {"count": len(rows), "summary": summary, "items": rows}
#     except Exception as exc:
#         log.exception("Error in /logs/bypass")
#         return {"error": str(exc)}



"""
api.py — Chottu Bot FastAPI Layer  v5.5
========================================
Thin HTTP wrapper around chat.py.  All business logic lives in chat.py.

Run:
    uvicorn api:app --reload --host 0.0.0.0 --port 8000

Routes
──────
  POST /chat             → process a customer message
  GET  /                 → serve static/index.html chat UI
  GET  /health           → system + model status
  GET  /faqs             → browse loaded FAQ pool  (?source=all|sentiment_aware|english|manglish|shop&limit=50)
  GET  /stats            → chat log statistics (requires pandas)
  GET  /logs/review      → Ollama-handled messages — FAQ gap candidates
  GET  /logs/escalations → conversations flagged for human follow-up
  GET  /logs/bypass      → messages that bypassed FAQ (praise, social, offtopic)

Changes v5.4 → v5.5
──────────────────────
  • Ollama warm-up on startup — eliminates 8–11s cold start on first request
  • Ollama keep-alive ping every 10 min — model stays loaded in VRAM
  • Imports FAQS_ENGLISH_SENTIMENT + FAQS_MANGLISH_SENTIMENT — /health now
    shows accurate total FAQ count (was missing sentiment pool counts)
  • /health: added sentiment_english + sentiment_manglish to faq_counts
  • /logs/bypass: updated bypass values to match chat.py v5.5:
    social_chat, compliment, confirmation, lang_switch,
    location_guard, human_escalation
  • Version bumped to 5.5 everywhere
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import logging
import os
from collections import Counter
from pathlib import Path
from typing import Optional

import threading
import time

import requests as _http
import torch
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from chat import (
    pipeline,
    BOT_NAME,
    SHOP_NAME,
    LOG_PATH,
    OLLAMA_MODEL,
    FAQ_THRESHOLD,
    SEMANTIC_THRESHOLD,
    SENTIMENT_THRESHOLD,
    MANGLISH_BOOST,
    device_name,
    FAQ_EMB_TEXTS,
    FAQS_SENTIMENT,
    FAQS_ENGLISH,
    FAQS_MANGLISH,
    FAQS_ENGLISH_SENTIMENT,
    FAQS_MANGLISH_SENTIMENT,
    FAQS_SHOP,
    OLLAMA_URL,
)

log = logging.getLogger("chottu.api")

# ══════════════════════════════════════════════════════════════════════════════
#  OLLAMA WARM-UP & KEEP-ALIVE
# ══════════════════════════════════════════════════════════════════════════════

def _warm_ollama() -> None:
    """Ping Ollama once at startup to load the model into VRAM."""
    try:
        _http.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": "hi", "stream": False},
            timeout=60,
        )
        log.info("✅  Ollama warm-up done — model loaded into VRAM")
    except Exception as e:
        log.warning("⚠   Ollama warm-up failed (is Ollama running?): %s", e)


def _ollama_keepalive() -> None:
    """Ping Ollama every 10 minutes to keep model loaded in VRAM."""
    while True:
        time.sleep(600)
        try:
            _http.post(
                OLLAMA_URL,
                json={"model": OLLAMA_MODEL, "prompt": "hi", "stream": False},
                timeout=30,
            )
            log.debug("🔄  Ollama keep-alive ping sent")
        except Exception:
            pass  # silent — Ollama may be restarting


# ══════════════════════════════════════════════════════════════════════════════
#  APP SETUP
# ══════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app):
    log.info(
        "✅  %s API v5.5 ready — %d FAQ entries in embedding index "
        "(english: %d, manglish: %d, en_sent: %d, ml_sent: %d)",
        BOT_NAME,
        len(FAQ_EMB_TEXTS),
        len(FAQS_ENGLISH),
        len(FAQS_MANGLISH),
        len(FAQS_ENGLISH_SENTIMENT),
        len(FAQS_MANGLISH_SENTIMENT),
    )
    # Warm up Ollama — loads model into VRAM, eliminates cold-start latency
    _warm_ollama()
    # Keep-alive thread — pings Ollama every 10 min so model stays in VRAM
    threading.Thread(target=_ollama_keepalive, daemon=True).start()
    yield


app = FastAPI(
    title=f"{BOT_NAME} — Shop Chat API",
    description=f"Bilingual (English + Manglish) customer support bot for {SHOP_NAME}.",
    version="5.5",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    message: str

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Message must not be empty")
        if len(v) > 1000:
            raise ValueError("Message too long (max 1000 characters)")
        return v


class ChatResponse(BaseModel):
    """
    Full pipeline response.  All fields from chat._make_result() are exposed.

    source      : "greeting" | "faq" | "ollama"
    bypass      : "" | "offtopic" | "social_chat" | "pure_praise" | "empty_tokens" | "vague_query"
    lang        : "english" | "manglish"
    sent_source : "lexicon" | "xlmr" | "greeting_regex" | "default"
    faq_id      : populated for all FAQ sources in v5.1 (was empty for flat FAQs in v5.0)
    """
    message:     str
    lang:        str
    sentiment:   str
    confidence:  float
    sent_source: str
    reply:       str
    source:      str
    bypass:      str
    faq_source:  Optional[str]
    faq_id:      Optional[str]
    faq_score:   Optional[float]
    escalate:    bool
    ms:          float


# ══════════════════════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", include_in_schema=False, response_model=None)
def serve_ui():
    index = Path("static/index.html")
    if not index.exists():
        return {"error": "Place index.html inside the /static folder."}
    return FileResponse(str(index))


@app.post("/chat", response_model=ChatResponse, summary="Process a customer message")
def chat(req: ChatRequest) -> dict:
    """
    Main chat endpoint.  Accepts a customer message and returns:
    - Detected language and sentiment
    - Reply text (from FAQ, Ollama, or greeting)
    - Routing metadata (source, faq_id, score, bypass reason)
    - Latency in milliseconds
    """
    return pipeline(req.message)


@app.get("/health", summary="System and model status")
def health() -> dict:
    gpu_info: dict = {}
    if torch.cuda.is_available():
        used_mib  = torch.cuda.memory_allocated(0) // 1_048_576
        total_mib = torch.cuda.get_device_properties(0).total_memory // 1_048_576
        gpu_info  = {
            "gpu_name":    torch.cuda.get_device_name(0),
            "vram_total":  f"{total_mib} MiB",
            "vram_used":   f"{used_mib} MiB",
            "vram_free":   f"{total_mib - used_mib} MiB",
        }

    # Per-category counts for flat FAQ pools (useful for monitoring FAQ coverage)
    en_by_cat  = dict(Counter(f.get("section", "general") for f in FAQS_ENGLISH))
    ml_by_cat  = dict(Counter(f.get("section", "general") for f in FAQS_MANGLISH))

    return {
        "status":               "ok",
        "bot_name":             BOT_NAME,
        "shop_name":            SHOP_NAME,
        "version":              "5.5",
        "device":               device_name,
        "ollama_model":         OLLAMA_MODEL,
        "thresholds": {
            "semantic":         SEMANTIC_THRESHOLD,
            "f1":               FAQ_THRESHOLD,
            "sentiment":        SENTIMENT_THRESHOLD,
            "manglish_boost":   MANGLISH_BOOST,
        },
        "faq_counts": {
            "embedding_index":    len(FAQ_EMB_TEXTS),
            "sentiment_aware":    len(FAQS_SENTIMENT),
            "english":            len(FAQS_ENGLISH),
            "english_sentiment":  len(FAQS_ENGLISH_SENTIMENT),
            "manglish":           len(FAQS_MANGLISH),
            "manglish_sentiment": len(FAQS_MANGLISH_SENTIMENT),
            "shop":               len(FAQS_SHOP),
            "total_flat":         len(FAQS_ENGLISH) + len(FAQS_MANGLISH)
                                  + len(FAQS_ENGLISH_SENTIMENT) + len(FAQS_MANGLISH_SENTIMENT),
        },
        "faq_categories": {
            "english":  en_by_cat,
            "manglish": ml_by_cat,
        },
        **gpu_info,
    }


@app.get("/faqs", summary="Browse loaded FAQ pool")
def list_faqs(
    source: str = Query("all", description="all | sentiment_aware | english | manglish | shop"),
    limit:  int = Query(50,    ge=1, le=500),
) -> dict:
    pool_map: dict[str, list] = {
        "all":             FAQS_SENTIMENT + FAQS_MANGLISH + FAQS_ENGLISH + FAQS_SHOP,
        "sentiment_aware": FAQS_SENTIMENT,
        "english":         FAQS_ENGLISH,
        "manglish":        FAQS_MANGLISH,
        "shop":            FAQS_SHOP,
    }
    if source not in pool_map:
        raise HTTPException(status_code=400, detail=f"Unknown source '{source}'. Choose: {list(pool_map)}")

    pool  = pool_map[source]
    items = []
    for faq in pool[:limit]:
        if "questions" in faq:
            # Sentiment-aware format
            first_q = next(
                (q for qs in faq["questions"].values() for q in qs if q), ""
            )
            first_a = next(
                (a for a in faq.get("answers", {}).values() if a), ""
            )
            faq_id = faq.get("id", "")
        else:
            # Flat format (english / manglish)
            first_q = faq.get("q", "")
            first_a = faq.get("a", "")
            faq_id  = faq.get("id", "")   # FIX v5.1: was always missing for flat FAQs

        items.append({
            "id":              faq_id,
            "category":        faq.get("category") or faq.get("section", ""),
            "source":          faq.get("source", ""),
            "lang":            faq.get("lang", ""),
            "sample_question": first_q,
            "answer_preview":  (first_a[:120] + "…") if len(first_a) > 120 else first_a,
        })

    return {"total": len(pool), "shown": len(items), "source_filter": source, "items": items}


@app.get("/stats", summary="Chat log statistics")
def stats() -> dict:
    try:
        import pandas as pd
    except ImportError:
        return {"error": "Run 'pip install pandas' to enable /stats"}

    if not Path(LOG_PATH).exists():
        return {"total": 0, "message": "No logs yet"}

    try:
        df    = pd.read_csv(LOG_PATH)
        total = len(df)
        if total == 0:
            return {"total": 0, "message": "Log is empty"}

        counts   = df["source"].value_counts().to_dict()
        faq_hits = counts.get("faq", 0)

        # Bypass breakdown (v5.0+ column)
        bypass_counts: dict = {}
        if "bypass" in df.columns:
            bypass_counts = (
                df[df["bypass"].notna() & (df["bypass"] != "")]
                ["bypass"].value_counts().to_dict()
            )

        # Language breakdown
        lang_counts: dict = {}
        if "lang" in df.columns:
            lang_counts = df["lang"].value_counts().to_dict()

        # Ollama calls split by lang
        ollama_by_lang: dict = {}
        if "lang" in df.columns:
            ollama_by_lang = (
                df[df["source"] == "ollama"]["lang"]
                .value_counts().to_dict()
            )

        # FAQ source breakdown
        faq_srcs: dict = {}
        if "faq_source" in df.columns:
            faq_srcs = (
                df[df["faq_source"].notna() & (df["faq_source"] != "")]
                ["faq_source"].value_counts().to_dict()
            )

        # FIX v5.1: Top FAQ IDs hit (useful for understanding which FAQs are used most)
        top_faq_ids: dict = {}
        if "faq_id" in df.columns:
            top_faq_ids = (
                df[df["faq_id"].notna() & (df["faq_id"] != "")]
                ["faq_id"].value_counts().head(20).to_dict()
            )

        return {
            "total":            total,
            "greeting_hits":    counts.get("greeting", 0),
            "faq_hits":         faq_hits,
            "ollama_calls":     counts.get("ollama", 0),
            "faq_hit_rate":     f"{faq_hits / total * 100:.1f}%",
            "by_sentiment":     df["sentiment"].value_counts().to_dict(),
            "by_lang":          lang_counts,
            "by_bypass_reason": bypass_counts,
            "faq_by_source":    faq_srcs,
            "ollama_by_lang":   ollama_by_lang,
            "top_faq_ids":      top_faq_ids,   # NEW in v5.1
        }
    except Exception as exc:
        log.exception("Error in /stats")
        return {"error": str(exc)}


@app.get("/logs/review", summary="Ollama-handled messages (FAQ gap candidates)")
def review_queue() -> dict:
    """
    Returns all messages answered by Ollama — these are candidates for
    adding new FAQ entries.  Sorted newest-first.
    """
    try:
        import pandas as pd
    except ImportError:
        return {"error": "Run 'pip install pandas' to enable /logs/review"}

    if not Path(LOG_PATH).exists():
        return {"count": 0, "items": []}

    try:
        df   = pd.read_csv(LOG_PATH)
        mask = df["source"] == "ollama"
        cols = [c for c in ["timestamp", "lang", "message", "sentiment", "bypass", "reply"] if c in df.columns]
        rows = df[mask][cols].sort_values("timestamp", ascending=False).to_dict("records")
        return {"count": len(rows), "items": rows}
    except Exception as exc:
        log.exception("Error in /logs/review")
        return {"error": str(exc)}


@app.get("/logs/escalations", summary="Flagged conversations for human follow-up")
def escalation_queue() -> dict:
    """
    Returns all messages that triggered an escalation keyword.
    These require human follow-up within 1 hour.
    """
    try:
        import pandas as pd
    except ImportError:
        return {"error": "Run 'pip install pandas' to enable /logs/escalations"}

    if not Path(LOG_PATH).exists():
        return {"count": 0, "items": []}

    try:
        df   = pd.read_csv(LOG_PATH)
        mask = df["escalate"].astype(str).str.lower().isin(["true", "1"])
        cols = [c for c in ["timestamp", "lang", "message", "sentiment", "faq_id", "reply"] if c in df.columns]
        rows = df[mask][cols].sort_values("timestamp", ascending=False).to_dict("records")
        return {"count": len(rows), "items": rows}
    except Exception as exc:
        log.exception("Error in /logs/escalations")
        return {"error": str(exc)}


@app.get("/logs/bypass", summary="Messages that bypassed FAQ matching")
def bypass_queue() -> dict:
    """
    Returns messages routed directly to Ollama via a bypass guard:
      • social_chat       — check-ins / wellbeing (sugamano, how are you)
      • compliment        — praise / thank you with no shop request
      • confirmation      — yes/ok/sheri/pinne varam continuations
      • lang_switch       — "in english" / "manglish il paranju"
      • location_guard    — "eevide aanu kanan illalo" location queries
      • human_escalation  — fraud/bulk/festival offers → WhatsApp
    Useful for tuning the guards and identifying misrouted messages.
    """
    try:
        import pandas as pd
    except ImportError:
        return {"error": "Run 'pip install pandas' to enable /logs/bypass"}

    if not Path(LOG_PATH).exists():
        return {"count": 0, "items": []}

    try:
        df   = pd.read_csv(LOG_PATH)
        if "bypass" not in df.columns:
            return {"count": 0, "items": [], "note": "No bypass column — log predates v5.0"}

        mask = df["bypass"].notna() & (df["bypass"] != "")
        cols = [c for c in ["timestamp", "lang", "message", "sentiment", "bypass", "reply"] if c in df.columns]
        rows = df[mask][cols].sort_values("timestamp", ascending=False).to_dict("records")
        summary = df[mask]["bypass"].value_counts().to_dict() if not df[mask].empty else {}
        return {"count": len(rows), "summary": summary, "items": rows}
    except Exception as exc:
        log.exception("Error in /logs/bypass")
        return {"error": str(exc)}
from __future__ import annotations

from contextlib import asynccontextmanager

import hashlib
import json
import logging
import os
import re
import secrets
import shutil
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import requests as _http
import torch
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse, JSONResponse, HTMLResponse, PlainTextResponse
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from shop_manager import get_shop_context, reload_shop, list_shops, get_shop_items
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
    reload_config,
    _CFG,
)

log = logging.getLogger("chottu.api")


# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def normalize_slug(slug: str) -> str:
    return slug.strip().lower().replace(" ", "-")


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ══════════════════════════════════════════════════════════════════════════════
#  STARTUP
# ══════════════════════════════════════════════════════════════════════════════

def _warm_ollama() -> None:
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
            pass


@asynccontextmanager
async def lifespan(app):
    log.info(
        "✅  %s API v5.7.0 ready — %d FAQ entries in embedding index "
        "(english: %d, manglish: %d, en_sent: %d, ml_sent: %d)",
        BOT_NAME,
        len(FAQ_EMB_TEXTS),
        len(FAQS_ENGLISH),
        len(FAQS_MANGLISH),
        len(FAQS_ENGLISH_SENTIMENT),
        len(FAQS_MANGLISH_SENTIMENT),
    )
    _warm_ollama()
    threading.Thread(target=_ollama_keepalive, daemon=True).start()
    yield


# ══════════════════════════════════════════════════════════════════════════════
#  APP
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title=f"{BOT_NAME} — Shop Chat API",
    description=f"Bilingual (English + Manglish) customer support bot for {SHOP_NAME}.",
    version="5.7.0",
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
#  MODELS
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


class ShopGenerateRequest(BaseModel):
    bot_name:          Optional[str]  = None
    shop_name:         str
    shop_type:         str
    tagline:           Optional[str]  = "English & Manglish"
    description:       Optional[str]  = ""
    location:          str
    city:              str
    state:             Optional[str]  = "Kerala"
    hours_weekdays:    str
    hours_sunday:      str
    hours_holiday:     Optional[str]  = "Check WhatsApp for holiday hours"
    whatsapp:          str
    phone:             Optional[str]  = None
    email:             str
    website:           Optional[str]  = None
    payment:           Optional[list] = None
    services:          Optional[list] = None
    delivery_areas:    Optional[str]  = "N/A"
    delivery_free:     Optional[str]  = "N/A"
    delivery_days:     Optional[str]  = "N/A"
    return_days:       Optional[int]  = 0
    return_condition:  Optional[str]  = "N/A"
    refund_days:       Optional[str]  = "N/A"
    offer_code:        Optional[str]  = ""
    offer_desc:        Optional[str]  = ""
    escalate_whatsapp: Optional[str]  = None
    escalate_email:    Optional[str]  = None
    escalate_topics:   Optional[list] = None
    blocked_topics:    Optional[list] = None
    shop_items:        Optional[list] = None


# ══════════════════════════════════════════════════════════════════════════════
#  CORE ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/", include_in_schema=False, response_model=None)
def serve_ui():
    index = Path("static/index.html")
    if not index.exists():
        return {"error": "Place index.html inside the /static folder."}
    return FileResponse(str(index))


@app.post("/chat", response_model=ChatResponse, summary="Process a customer message")
def chat(
    req: ChatRequest,
    slug: Optional[str] = Query(None, description="Shop slug for multi-tenant routing"),
) -> dict:
    slug = normalize_slug(slug) if slug else None
    return pipeline(req.message, slug=slug)


# ══════════════════════════════════════════════════════════════════════════════
#  HEALTH
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health", summary="System and model status")
def health() -> dict:
    gpu_info: dict = {}
    if torch.cuda.is_available():
        used_mib  = torch.cuda.memory_allocated(0) // 1_048_576
        total_mib = torch.cuda.get_device_properties(0).total_memory // 1_048_576
        gpu_info  = {
            "gpu_name":   torch.cuda.get_device_name(0),
            "vram_total": f"{total_mib} MiB",
            "vram_used":  f"{used_mib} MiB",
            "vram_free":  f"{total_mib - used_mib} MiB",
        }

    en_by_cat = dict(Counter(f.get("section", "general") for f in FAQS_ENGLISH))
    ml_by_cat = dict(Counter(f.get("section", "general") for f in FAQS_MANGLISH))

    return {
        "status":             "ok",
        "bot_name":           BOT_NAME,
        "shop_name":          SHOP_NAME,
        "version":            "5.7.0",
        "device":             device_name,
        "ollama_model":       OLLAMA_MODEL,
        "shop_config":        _CFG,
        "thresholds": {
            "semantic":       SEMANTIC_THRESHOLD,
            "f1":             FAQ_THRESHOLD,
            "sentiment":      SENTIMENT_THRESHOLD,
            "manglish_boost": MANGLISH_BOOST,
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


@app.get("/health/{slug}", summary="Health check for a specific shop slug")
def health_slug(slug: str) -> dict:
    slug     = normalize_slug(slug)
    shop_dir = os.path.join("shops", slug)

    if not os.path.exists(shop_dir):
        raise HTTPException(status_code=404, detail=f"Shop '{slug}' not found")

    cfg      = {}
    cfg_path = os.path.join(shop_dir, "shop_config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

    faq_count = 0
    faq_path  = os.path.join(shop_dir, "shop_faq.json")
    if os.path.exists(faq_path):
        with open(faq_path, "r", encoding="utf-8") as f:
            faq_count = len(json.load(f))

    item_count = 0
    items_path = os.path.join(shop_dir, "shop_items.json")
    if os.path.exists(items_path):
        with open(items_path, "r", encoding="utf-8") as f:
            item_count = len(json.load(f))

    return {
        "status":     "ok",
        "slug":       slug,
        "shop_name":  cfg.get("shop_name", slug),
        "bot_name":   cfg.get("bot_name",  "Bot"),
        "shop_type":  cfg.get("shop_type", "general"),
        "faq_count":  faq_count,
        "item_count": item_count,
        "shop_config": cfg,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  FAQ BROWSE
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/faqs", summary="Browse loaded FAQ pool")
def list_faqs(
    source: str = Query("all", description="all | sentiment_aware | english | manglish | shop"),
    limit:  int = Query(50, ge=1, le=500),
) -> dict:
    pool_map: dict[str, list] = {
        "all":             FAQS_SENTIMENT + FAQS_MANGLISH + FAQS_ENGLISH + FAQS_SHOP,
        "sentiment_aware": FAQS_SENTIMENT,
        "english":         FAQS_ENGLISH,
        "manglish":        FAQS_MANGLISH,
        "shop":            FAQS_SHOP,
    }
    if source not in pool_map:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown source '{source}'. Choose: {list(pool_map)}"
        )

    pool  = pool_map[source]
    items = []
    for faq in pool[:limit]:
        if "questions" in faq:
            first_q = next(
                (q for qs in faq["questions"].values() for q in qs if q), ""
            )
            first_a = next(
                (a for a in faq.get("answers", {}).values() if a), ""
            )
            faq_id = faq.get("id", "")
        else:
            first_q = faq.get("q", "")
            first_a = faq.get("a", "")
            faq_id  = faq.get("id", "")

        items.append({
            "id":              faq_id,
            "category":        faq.get("category") or faq.get("section", ""),
            "source":          faq.get("source", ""),
            "lang":            faq.get("lang", ""),
            "sample_question": first_q,
            "answer_preview":  (first_a[:120] + "…") if len(first_a) > 120 else first_a,
        })

    return {"total": len(pool), "shown": len(items), "source_filter": source, "items": items}


@app.get("/faq", summary="FAQ list (alias for /faqs)")
def faq_alias(
    source: str = Query("all"),
    limit:  int = Query(50, ge=1, le=500),
):
    return list_faqs(source=source, limit=limit)


# ── Per-slug FAQ CRUD ─────────────────────────────────────────────────────────

@app.get("/faqs/{slug}", summary="Get all FAQs for a slug")
def get_slug_faqs(slug: str) -> dict:
    slug     = normalize_slug(slug)
    faq_path = os.path.join("shops", slug, "shop_faq.json")
    if not os.path.exists(faq_path):
        return {"slug": slug, "faqs": [], "count": 0}
    try:
        with open(faq_path, "r", encoding="utf-8") as f:
            faqs = json.load(f)
        return {"slug": slug, "faqs": faqs, "count": len(faqs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/faqs/{slug}", summary="Add a FAQ to a slug")
def add_slug_faq(slug: str, faq: dict) -> dict:
    slug     = normalize_slug(slug)
    faq_path = os.path.join("shops", slug, "shop_faq.json")
    os.makedirs(os.path.join("shops", slug), exist_ok=True)
    try:
        faqs = []
        if os.path.exists(faq_path):
            with open(faq_path, "r", encoding="utf-8") as f:
                faqs = json.load(f)

        new_faq = {
            "id":                faq.get("id") or f"faq_{int(time.time())}",
            "question":          faq.get("question", ""),
            "question_variants": faq.get("question_variants", []),
            "answer":            faq.get("answer", ""),
            "category":          faq.get("category", "shop"),
            "lang":              faq.get("lang", "english"),
        }
        faqs.append(new_faq)

        with open(faq_path, "w", encoding="utf-8") as f:
            json.dump(faqs, f, ensure_ascii=False, indent=2)

        reload_shop(slug)
        return {"status": "ok", "slug": slug, "faq": new_faq, "total": len(faqs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/faqs/{slug}/{faq_id}", summary="Delete a FAQ from a slug")
def delete_slug_faq(slug: str, faq_id: str) -> dict:
    slug     = normalize_slug(slug)
    faq_path = os.path.join("shops", slug, "shop_faq.json")
    if not os.path.exists(faq_path):
        raise HTTPException(status_code=404, detail="No FAQs found for this slug")
    try:
        with open(faq_path, "r", encoding="utf-8") as f:
            faqs = json.load(f)

        original_count = len(faqs)
        faqs = [f for f in faqs if f.get("id") != faq_id]

        with open(faq_path, "w", encoding="utf-8") as f:
            json.dump(faqs, f, ensure_ascii=False, indent=2)

        reload_shop(slug)
        return {
            "status":  "ok",
            "slug":    slug,
            "deleted": original_count - len(faqs),
            "total":   len(faqs),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/faqs/{slug}/reload", summary="Reload FAQ embeddings for a slug")
def reload_slug_faqs(slug: str) -> dict:
    slug = normalize_slug(slug)
    ctx  = reload_shop(slug)
    return {"status": "ok", "slug": slug, "faq_count": len(ctx.shop_faqs)}


# ══════════════════════════════════════════════════════════════════════════════
#  LOGS + STATS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/stats", summary="Chat log statistics")
def stats() -> dict:
    try:
        import pandas as pd
    except ImportError:
        return {"error": "Run 'pip install pandas' to enable /stats"}

    if not Path(LOG_PATH).exists():
        return {"total": 0, "message": "No logs yet"}

    try:
        df    = pd.read_csv(LOG_PATH, on_bad_lines="skip")
        total = len(df)
        if total == 0:
            return {"total": 0, "message": "Log is empty"}

        counts   = df["source"].value_counts().to_dict()
        faq_hits = counts.get("faq", 0)

        bypass_counts: dict = {}
        if "bypass" in df.columns:
            bypass_counts = (
                df[df["bypass"].notna() & (df["bypass"] != "")]
                ["bypass"].value_counts().to_dict()
            )

        lang_counts: dict = {}
        if "lang" in df.columns:
            lang_counts = df["lang"].value_counts().to_dict()

        ollama_by_lang: dict = {}
        if "lang" in df.columns:
            ollama_by_lang = (
                df[df["source"] == "ollama"]["lang"]
                .value_counts().to_dict()
            )

        faq_srcs: dict = {}
        if "faq_source" in df.columns:
            faq_srcs = (
                df[df["faq_source"].notna() & (df["faq_source"] != "")]
                ["faq_source"].value_counts().to_dict()
            )

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
            "top_faq_ids":      top_faq_ids,
        }
    except Exception as exc:
        log.exception("Error in /stats")
        return {"error": str(exc)}


@app.get("/logs/review", summary="Ollama-handled messages (FAQ gap candidates)")
def review_queue() -> dict:
    try:
        import pandas as pd
    except ImportError:
        return {"error": "Run 'pip install pandas' to enable /logs/review"}

    if not Path(LOG_PATH).exists():
        return {"count": 0, "items": []}

    try:
        df   = pd.read_csv(LOG_PATH, on_bad_lines="skip")
        mask = df["source"] == "ollama"
        cols = [c for c in ["timestamp", "lang", "message", "sentiment", "bypass", "reply"] if c in df.columns]
        rows = df[mask][cols].sort_values("timestamp", ascending=False).to_dict("records")
        return {"count": len(rows), "items": rows}
    except Exception as exc:
        log.exception("Error in /logs/review")
        return {"error": str(exc)}


@app.get("/logs/escalations", summary="Flagged conversations for human follow-up")
def escalation_queue() -> dict:
    try:
        import pandas as pd
    except ImportError:
        return {"error": "Run 'pip install pandas' to enable /logs/escalations"}

    if not Path(LOG_PATH).exists():
        return {"count": 0, "items": []}

    try:
        df   = pd.read_csv(LOG_PATH, on_bad_lines="skip")
        mask = df["escalate"].astype(str).str.lower().isin(["true", "1"])
        cols = [c for c in ["timestamp", "lang", "message", "sentiment", "faq_id", "reply"] if c in df.columns]
        rows = df[mask][cols].sort_values("timestamp", ascending=False).to_dict("records")
        return {"count": len(rows), "items": rows}
    except Exception as exc:
        log.exception("Error in /logs/escalations")
        return {"error": str(exc)}


@app.get("/logs/bypass", summary="Messages that bypassed FAQ matching")
def bypass_queue() -> dict:
    try:
        import pandas as pd
    except ImportError:
        return {"error": "Run 'pip install pandas' to enable /logs/bypass"}

    if not Path(LOG_PATH).exists():
        return {"count": 0, "items": []}

    try:
        df = pd.read_csv(LOG_PATH, on_bad_lines="skip")
        if "bypass" not in df.columns:
            return {"count": 0, "items": [], "note": "No bypass column — log predates v5.0"}

        mask    = df["bypass"].notna() & (df["bypass"] != "")
        cols    = [c for c in ["timestamp", "lang", "message", "sentiment", "bypass", "reply"] if c in df.columns]
        rows    = df[mask][cols].sort_values("timestamp", ascending=False).to_dict("records")
        summary = df[mask]["bypass"].value_counts().to_dict() if not df[mask].empty else {}
        return {"count": len(rows), "summary": summary, "items": rows}
    except Exception as exc:
        log.exception("Error in /logs/bypass")
        return {"error": str(exc)}


@app.get("/conversation", summary="Conversation / chat log list")
def get_conversations(limit: int = Query(50, ge=1, le=500)) -> dict:
    try:
        import pandas as pd
        if not Path(LOG_PATH).exists():
            return {"count": 0, "items": []}
        df   = pd.read_csv(LOG_PATH, on_bad_lines="skip")
        cols = [c for c in ["timestamp", "lang", "message", "sentiment", "source", "reply", "escalate"] if c in df.columns]
        rows = df[cols].tail(limit).iloc[::-1].to_dict("records")
        return {"count": len(rows), "items": rows}
    except Exception as exc:
        return {"count": 0, "items": [], "error": str(exc)}


@app.get("/conversations", summary="Alias for /conversation")
def get_conversations_alias(limit: int = Query(50, ge=1, le=500)) -> dict:
    return get_conversations(limit=limit)


# ══════════════════════════════════════════════════════════════════════════════
#  ITEM CATALOGUE
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/items/{slug}", summary="Get item catalogue for a shop slug")
async def get_items(
    slug:     str,
    category: Optional[str] = Query(None, description="Filter by item category"),
    q:        Optional[str]  = Query(None, description="Text search in item names"),
    limit:    int            = Query(200, ge=1, le=2000),
) -> dict:
    slug     = normalize_slug(slug)
    slug_dir = os.path.join("shops", slug)

    if not os.path.exists(slug_dir):
        raise HTTPException(status_code=404, detail=f"Shop '{slug}' not found")

    items = get_shop_items(slug)

    if not items:
        return {"slug": slug, "items": [], "count": 0, "total": 0}

    filtered = items
    if category:
        cl       = category.lower()
        filtered = [it for it in filtered if cl in it.get("category", "").lower()]
    if q:
        ql       = q.lower()
        filtered = [it for it in filtered if ql in it.get("name", "").lower()
                    or ql in it.get("description", "").lower()]

    def _price_label(it: dict) -> str:
        if "price" in it:
            return f"₹{it['price']:,}"
        if "price_min" in it and "price_max" in it:
            return f"₹{it['price_min']:,} – ₹{it['price_max']:,}"
        return "on request"

    result = []
    for it in filtered[:limit]:
        entry = {
            "name":        it.get("name", ""),
            "category":    it.get("category", "General"),
            "price_label": _price_label(it),
        }
        if "price"       in it: entry["price"]       = it["price"]
        if "price_min"   in it: entry["price_min"]   = it["price_min"]
        if "price_max"   in it: entry["price_max"]   = it["price_max"]
        if "description" in it and it["description"]:
            entry["description"] = it["description"]
        result.append(entry)

    cats = sorted({it.get("category", "General") for it in items})

    return {
        "slug":       slug,
        "items":      result,
        "count":      len(result),
        "total":      len(items),
        "categories": cats,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN — PDF EXTRACT
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/admin/extract-pdf",
          summary="Extract shop info from PDF (pdf.py v3.0 engine)")
async def extract_pdf_endpoint(
    file: UploadFile = File(...),
    slug: Optional[str] = Query(None, description="If provided, auto-save items to shops/{slug}/shop_items.json"),
):
    from pdf import (
        extract_pdf,
        detect_items_from_tables,
        detect_items_regex,
        detect_metadata_regex,
        build_shop_info,
    )

    os.makedirs("tmp", exist_ok=True)
    tmp_path = os.path.join("tmp", file.filename or "upload.pdf")

    with open(tmp_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)

    try:
        all_pages, all_tables, full_text = extract_pdf(tmp_path)

        table_items = detect_items_from_tables(all_tables)
        regex_items = detect_items_regex(full_text)
        auto_meta   = detect_metadata_regex(full_text)

        shop_info   = build_shop_info(auto_meta, table_items, regex_items)

        REQUIRED = [
            "shop_name", "shop_type", "location", "city",
            "phone", "whatsapp", "hours_weekdays", "payment",
        ]
        missing_fields = [
            f for f in REQUIRED
            if not shop_info.get(f) or shop_info[f] in ("", [], {})
        ]

        ai_filled: dict = {}
        if missing_fields:
            try:
                from ollama import chat as ollama_chat  # type: ignore
                prompt = (
                    f"Extract ONLY these missing fields as strict JSON "
                    f"(no markdown, no explanation):\n"
                    f"{json.dumps(missing_fields, indent=2)}\n\n"
                    f"From this shop PDF text (first 12 000 chars):\n"
                    f"---\n{full_text[:12_000]}\n---\n\n"
                    f"Rules:\n"
                    f"- Return ONLY a JSON object with the requested keys\n"
                    f"- Use null for truly unknown fields\n"
                    f"- payment must be an array of strings\n"
                    f"- Detect Indian business context correctly\n"
                    f"- Do NOT include fields not in the missing list"
                )
                resp    = ollama_chat(
                    model="gemma3:4b",
                    messages=[{"role": "user", "content": prompt}],
                )
                content = resp["message"]["content"].strip()
                content = re.sub(r"^```[a-z]*\n?", "", content)
                content = re.sub(r"\n?```$",        "", content)
                ai_filled = json.loads(content)
            except Exception as e:
                log.warning("[extract-pdf] Ollama fill failed: %s", e)

        for k, v in ai_filled.items():
            existing = shop_info.get(k)
            if existing is None or existing == "" or existing == [] or existing == {}:
                shop_info[k] = v

        items_saved_to: Optional[str] = None
        context_saved_to: Optional[str] = None

        if slug:
            try:
                slug_norm = normalize_slug(slug)
                ctx       = get_shop_context(slug_norm)
                raw_items = shop_info.get("shop_items", [])
                if raw_items:
                    ctx.save_items(raw_items)
                    reload_shop(slug_norm)
                    items_saved_to = f"shops/{slug_norm}/shop_items.json"
                    log.info("[extract-pdf] %d items saved to %s", len(raw_items), items_saved_to)
            except Exception as e:
                log.warning("[extract-pdf] save_items failed for slug=%s: %s", slug, e)

            try:
                from shop_rag import build_shop_context
                slug_norm    = normalize_slug(slug)
                shop_context = build_shop_context(shop_info, full_text)
                ctx_path     = Path(f"shops/{slug_norm}/shop_context.json")
                ctx_path.parent.mkdir(parents=True, exist_ok=True)
                ctx_path.write_text(
                    json.dumps(shop_context, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                context_saved_to = str(ctx_path)
                log.info(
                    "[extract-pdf] shop_context.json saved for slug=%s (%d chunks)",
                    slug_norm, len(shop_context.get("chunks", []))
                )
            except Exception as e:
                log.warning("[extract-pdf] shop_context save failed: %s", e)

        return JSONResponse({
            "success":   True,
            "shop_info": shop_info,
            "stats": {
                "pages_extracted":   len(all_pages),
                "tables_found":      len(all_tables),
                "items_detected":    len(shop_info.get("shop_items", [])),
                "table_items":       len(table_items),
                "regex_items":       len(regex_items),
                "missing_before_ai": missing_fields,
                "filled_by_ai":      list(ai_filled.keys()),
                "items_saved_to":    items_saved_to,
                "context_saved_to":  context_saved_to,
            },
        })

    except Exception as e:
        log.exception("[extract-pdf] Extraction failed")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN — GENERATE SHOP  ✅ FIXED: removed broken faq_engine imports
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/admin/generate-shop",
          summary="Generate shop config + FAQs + items — saves to slug folder")
async def generate_shop(
    req:       ShopGenerateRequest,
    slug:      str  = Query("default"),
    faqs_only: bool = Query(False, description="Only add FAQs — do not overwrite config"),
) -> dict:
    slug = normalize_slug(slug)

    try:
        import sys
        sys.path.insert(0, ".")
        if "generate_shop" in sys.modules:
            del sys.modules["generate_shop"]
        import generate_shop as gs

        info = {
            "bot_name":          req.bot_name,
            "shop_name":         req.shop_name,
            "shop_type":         req.shop_type,
            "tagline":           req.tagline or "English & Manglish",
            "description":       req.description or "",
            "location":          req.location,
            "city":              req.city,
            "state":             req.state or "Kerala",
            "hours_weekdays":    req.hours_weekdays,
            "hours_sunday":      req.hours_sunday,
            "hours_holiday":     req.hours_holiday or "Check WhatsApp",
            "whatsapp":          req.whatsapp,
            "phone":             req.phone or req.whatsapp,
            "email":             req.email,
            "website":           req.website,
            "payment":           req.payment or ["UPI", "Cards", "Cash"],
            "services":          req.services or [],
            "delivery_areas":    req.delivery_areas or "N/A",
            "delivery_free":     req.delivery_free or "N/A",
            "delivery_days":     req.delivery_days or "N/A",
            "return_days":       req.return_days or 0,
            "return_condition":  req.return_condition or "N/A",
            "refund_days":       req.refund_days or "N/A",
            "offer_code":        req.offer_code or "",
            "offer_desc":        req.offer_desc or "",
            "escalate_whatsapp": req.escalate_whatsapp or req.whatsapp,
            "escalate_email":    req.escalate_email or req.email,
            "shop_items":        req.shop_items or [],
        }
        if req.escalate_topics:
            info["escalate_topics"] = req.escalate_topics
        if req.blocked_topics:
            info["blocked_topics"] = req.blocked_topics

        config, faqs, items = gs.generate_shop_files(info)

        slug_dir = os.path.join("shops", slug)
        os.makedirs(slug_dir, exist_ok=True)

        if not faqs_only:
            with open(os.path.join(slug_dir, "shop_config.json"), "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            with open("shop_config.json", "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)

        faq_path = os.path.join(slug_dir, "shop_faq.json")
        if faqs_only and os.path.exists(faq_path):
            with open(faq_path, "r", encoding="utf-8") as f:
                existing_faqs = json.load(f)
            existing_qs = {
                (item.get("question") or item.get("q", "")).lower()
                for item in existing_faqs
            }
            new_faqs    = [
                fq for fq in faqs
                if (fq.get("question") or fq.get("q", "")).lower() not in existing_qs
            ]
            merged_faqs = existing_faqs + new_faqs
            with open(faq_path, "w", encoding="utf-8") as f:
                json.dump(merged_faqs, f, ensure_ascii=False, indent=2)
            faqs = merged_faqs
            log.info(
                "FAQs merged for slug=%s: %d + %d = %d",
                slug, len(existing_faqs), len(new_faqs), len(merged_faqs)
            )
        else:
            with open(faq_path, "w", encoding="utf-8") as f:
                json.dump(faqs, f, ensure_ascii=False, indent=2)

        if items:
            items_path = os.path.join(slug_dir, "shop_items.json")
            with open(items_path, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            log.info("[generate-shop] %d items saved to %s", len(items), items_path)

        reload_config()
        ctx = reload_shop(slug)  # ✅ this now calls _build_embeddings() via fixed shop_manager

        # ✅ FIXED: removed broken build_embeddings / build_shop_embeddings imports
        # shop_manager.reload_shop() already rebuilds embeddings using _get_model()
        try:
            import faq_engine as _fe
            shop_faqs = _fe.load_shop_faqs(slug)
            _fe.FAQS_SHOP[slug] = shop_faqs
            log.info(
                "[generate-shop] FAQ engine reloaded: %d shop FAQs for slug=%s",
                len(shop_faqs), slug
            )
        except Exception as e:
            log.warning("[generate-shop] FAQ engine reload partial: %s", e)

        log.info(
            "Shop generated: slug=%s name=%s faqs=%d items=%d",
            slug, req.shop_name, len(faqs), len(items)
        )
        return {
            "status":     "ok",
            "slug":       slug,
            "bot_name":   config["bot_name"],
            "shop_name":  config["shop_name"],
            "shop_type":  config["shop_type"],
            "faq_count":  len(ctx.shop_faqs),  # ✅ real count from loaded context
            "item_count": len(ctx.shop_items),
            "config":     config,
        }

    except Exception as e:
        log.exception("[generate-shop] Error slug=%s", slug)
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN — UPLOAD HELPERS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/admin/upload-config",
          summary="Upload shop_config.json to change bot identity")
async def upload_config(file: UploadFile = File(...)) -> dict:
    try:
        content  = await file.read()
        cfg      = json.loads(content)
        required = ["bot_name", "shop_name", "contact", "hours", "escalate"]
        missing  = [k for k in required if k not in cfg]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing required fields: {missing}")
        with open("shop_config.json", "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        reload_config()
        log.info(
            "✅  shop_config.json updated — bot=%s shop=%s",
            cfg["bot_name"], cfg["shop_name"]
        )
        return {"status": "ok", "bot_name": cfg["bot_name"], "shop_name": cfg["shop_name"]}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    except Exception as e:
        log.exception("Error in /admin/upload-config")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/upload-faqs",
          summary="Upload shop_faq.json — shop-specific FAQs only")
async def upload_faqs(file: UploadFile = File(...)) -> dict:
    try:
        content = await file.read()
        faqs    = json.loads(content)
        if not isinstance(faqs, list):
            raise HTTPException(status_code=400, detail="FAQ file must be a JSON array")
        for i, item in enumerate(faqs[:3]):
            has_variants = "question_variants" in item
            has_simple   = ("question" in item or "q" in item) and ("answer" in item or "a" in item)
            if not has_variants and not has_simple:
                raise HTTPException(
                    status_code=400,
                    detail=f"Item {i}: needs 'question_variants'+'answer' or 'question'+'answer'"
                )
        os.makedirs("faqs", exist_ok=True)
        with open("faqs/shop_faq.json", "w", encoding="utf-8") as f:
            json.dump(faqs, f, ensure_ascii=False, indent=2)
        # ✅ FIXED: use _get_model() path via shop_manager instead of missing build_embeddings
        log.info("✅  shop_faq.json uploaded — %d FAQs", len(faqs))
        return {"status": "ok", "faq_count": len(faqs), "path": "faqs/shop_faq.json"}
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    except Exception as e:
        log.exception("Error in /admin/upload-faqs")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/upload-items",
          summary="Upload shop_items.json for a slug")
async def upload_items(
    file: UploadFile = File(...),
    slug: str        = Query("default", description="Shop slug to assign items to"),
) -> dict:
    slug = normalize_slug(slug)

    try:
        content = await file.read()
        items   = json.loads(content)

        if not isinstance(items, list):
            raise HTTPException(status_code=400, detail="File must be a JSON array")

        for i, item in enumerate(items[:3]):
            if "name" not in item:
                raise HTTPException(
                    status_code=400, detail=f"Item {i} missing 'name' field"
                )
            has_price = "price" in item or ("price_min" in item and "price_max" in item)
            if not has_price:
                log.warning("[upload-items] Item %d (%s) has no price field", i, item.get("name"))

        ctx = get_shop_context(slug)
        ctx.save_items(items)
        reload_shop(slug)

        log.info("[upload-items] %d items uploaded to slug=%s", len(items), slug)
        return {
            "status":     "ok",
            "slug":       slug,
            "item_count": len(items),
            "path":       f"shops/{slug}/shop_items.json",
        }

    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    except Exception as e:
        log.exception("[upload-items] Error for slug=%s", slug)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/config", summary="View current shop config")
def get_config() -> dict:
    return _CFG


# ══════════════════════════════════════════════════════════════════════════════
#  WIDGET
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/widget/{slug}.js", response_class=PlainTextResponse,
         summary="Embeddable widget script for a shop")
def widget_script(slug: str) -> str:
    base_url = "https://sell-encourage-freebsd-connectivity.trycloudflare.com"
    slug     = normalize_slug(slug.replace(".js", ""))

    script = f"""
(function() {{
  var CHAT_URL = "{base_url}";
  var SLUG     = "{slug}";

  var btn = document.createElement("div");
  btn.id = "chottu-btn";
  btn.innerHTML = "💬";
  btn.style.cssText = [
    "position:fixed","bottom:24px","right:24px","width:56px","height:56px",
    "background:#10b981","border-radius:50%","display:flex","align-items:center",
    "justify-content:center","font-size:24px","cursor:pointer","z-index:9999",
    "box-shadow:0 4px 16px rgba(0,0,0,0.2)","transition:transform .2s"
  ].join(";");

  var container = document.createElement("div");
  container.id = "chottu-container";
  container.style.cssText = [
    "position:fixed","bottom:90px","right:24px","width:380px","height:580px",
    "border-radius:16px","overflow:hidden","box-shadow:0 8px 32px rgba(0,0,0,0.15)",
    "z-index:9998","display:none","transition:all .3s"
  ].join(";");

  var iframe = document.createElement("iframe");
  iframe.src = CHAT_URL + "?slug=" + encodeURIComponent(SLUG);
  iframe.style.cssText = "width:100%;height:100%;border:none;";
  container.appendChild(iframe);

  var open = false;
  btn.onclick = function() {{
    open = !open;
    container.style.display = open ? "block" : "none";
    btn.style.transform = open ? "scale(0.9)" : "scale(1)";
  }};

  document.body.appendChild(container);
  document.body.appendChild(btn);
}})();
"""
    return script


@app.get("/widget/{slug}", response_class=HTMLResponse,
         summary="Widget preview page")
def widget_preview(slug: str) -> str:
    base_url = "https://sell-encourage-freebsd-connectivity.trycloudflare.com"
    slug     = normalize_slug(slug)
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Chottu Bot — {slug}</title>
  <style>
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ height:100vh; display:flex; align-items:center; justify-content:center; background:#f3f4f6; font-family:sans-serif; }}
    iframe {{ width:400px; height:600px; border:none; border-radius:16px; box-shadow:0 8px 32px rgba(0,0,0,0.15); }}
    .info {{ text-align:center; margin-top:16px; color:#6b7280; font-size:13px; }}
    code {{ background:#e5e7eb; padding:2px 6px; border-radius:4px; font-size:12px; }}
  </style>
</head>
<body>
  <div>
    <iframe src="{base_url}?slug={slug}"></iframe>
    <div class="info">
      Embed on your website:<br><br>
      <code>&lt;script src="{base_url}/widget/{slug}.js"&gt;&lt;/script&gt;</code>
    </div>
  </div>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════════════════════

USERS_PATH  = "users.json"
TOKENS_PATH = "tokens.json"


def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


class RegisterRequest(BaseModel):
    business_name: Optional[str] = None
    slug:          Optional[str] = None
    email:         str
    password:      str


class LoginRequest(BaseModel):
    email:    str
    password: str


@app.post("/auth/register")
def auth_register(req: RegisterRequest) -> dict:
    users = _load_json(USERS_PATH)
    email = req.email.lower().strip()
    if email in users:
        raise HTTPException(400, "Email already registered")
    slug = normalize_slug(req.slug or req.business_name or email.split("@")[0])
    user = {
        "business_name": req.business_name or slug,
        "slug":          slug,
        "email":         email,
        "password_hash": _hash_pw(req.password),
        "created_at":    time.strftime("%Y-%m-%dT%H:%M:%S"),
        "shop_type":     "general",
    }
    users[email] = user
    _save_json(USERS_PATH, users)
    token  = secrets.token_hex(32)
    tokens = _load_json(TOKENS_PATH)
    tokens[token] = email
    _save_json(TOKENS_PATH, tokens)
    return {
        "status": "ok", "token": token, "email": email,
        "business_name": user["business_name"], "slug": slug,
    }


@app.post("/auth/login")
def auth_login(req: LoginRequest) -> dict:
    users = _load_json(USERS_PATH)
    email = req.email.lower().strip()
    user  = users.get(email)
    if not user or user["password_hash"] != _hash_pw(req.password):
        raise HTTPException(401, "Invalid email or password")
    token  = secrets.token_hex(32)
    tokens = _load_json(TOKENS_PATH)
    tokens[token] = email
    _save_json(TOKENS_PATH, tokens)
    return {
        "status": "ok", "token": token, "email": email,
        "business_name": user["business_name"],
        "slug":          user["slug"],
        "shop_type":     user.get("shop_type", "general"),
    }


@app.get("/auth/me")
def auth_me(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization:
        raise HTTPException(401, "No token")
    token = authorization.replace("Bearer ", "").strip()
    email = _load_json(TOKENS_PATH).get(token)
    if not email:
        raise HTTPException(401, "Invalid token")
    user = _load_json(USERS_PATH).get(email)
    if not user:
        raise HTTPException(401, "User not found")
    return {
        "email":         user["email"],
        "business_name": user["business_name"],
        "slug":          user["slug"],
        "shop_type":     user.get("shop_type", "general"),
    }


@app.post("/auth/logout")
def auth_logout(authorization: Optional[str] = Header(None)) -> dict:
    if authorization:
        token  = authorization.replace("Bearer ", "").strip()
        tokens = _load_json(TOKENS_PATH)
        tokens.pop(token, None)
        _save_json(TOKENS_PATH, tokens)
    return {"status": "ok"}
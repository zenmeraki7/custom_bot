"""
faq_engine.py — FAQ loading, matching, and resolution
======================================================
 
Fixes in this version
─────────────────────
  FIX 1  Pass 0 shop FAQ semantic threshold restored to 0.60
         (was incorrectly lowered to 0.45 — too permissive for cosine search).
 
  FIX 2  resolve_for_slug() now logs a warning and substitutes a readable
         fallback string when a config placeholder is missing or empty,
         instead of silently returning the raw "{placeholder}" token.
 
  FIX 3  load_english_faqs() and load_manglish_faqs() now accept an optional
         shop_type filter. FAQ entries tagged with "shop_types" are only
         returned when the active shop_type matches — prevents e-commerce
         answers appearing in dental/bakery/gym shops.
 
  FIX 4  semantic_match() confidence-gap check preserved at 0.05 (correct).
         Deduplication note: english_sentiment.json overlaps with english.json
         — duplicates inflate the embedding index; see FIX 4 comment below.
"""
 
from __future__ import annotations
 
import json
import os
import re
from pathlib import Path
from typing import Optional
 
import torch
from sentence_transformers import SentenceTransformer, util
 
# ══════════════════════════════════════════════════════════════════════════════
#  MODEL
# ══════════════════════════════════════════════════════════════════════════════
 
_MODEL_NAME = "all-MiniLM-L6-v2"
_model: SentenceTransformer | None = None
 
 
def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model
 
 
def device_name() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  THRESHOLDS
# ══════════════════════════════════════════════════════════════════════════════
 
FAQ_THRESHOLD      = 0.45   # F1 token overlap (Pass 3)
SEMANTIC_THRESHOLD = 0.50   # Pass 1.5 cosine semantic search
SHOP_FAQ_THRESHOLD = 0.60   # FIX 1: Pass 0 shop-specific semantic — restored to 0.60
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  PATHS
# ══════════════════════════════════════════════════════════════════════════════
 
_DATA_DIR    = Path("data")
_SHOPS_DIR   = Path("shops")
_SHOP_CONFIG = Path("shop_config.json")
 
 
def _data(filename: str) -> Path:
    return _DATA_DIR / filename
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  SHOP CONFIG HELPER
# ══════════════════════════════════════════════════════════════════════════════
 
def _load_shop_config(slug: str | None = None) -> dict:
    paths = []
    if slug:
        paths.append(_SHOPS_DIR / slug.strip().lower().replace(" ", "-") / "shop_config.json")
    paths.append(_SHOP_CONFIG)
    for p in paths:
        try:
            txt = p.read_text(encoding="utf-8").strip()
            if txt:
                return json.loads(txt)
        except (FileNotFoundError, json.JSONDecodeError):
            continue
    return {}
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  PLACEHOLDER RESOLUTION  (FIX 2)
# ══════════════════════════════════════════════════════════════════════════════
 
def resolve_for_slug(text: str, slug: str | None = None) -> str:
    """
    Replace {placeholder} tokens in FAQ answer text with real values from
    shop_config.json.
 
    FIX 2: When a placeholder key is missing or the resolved value is empty /
    "N/A", substitute a human-readable fallback instead of returning the raw
    "{placeholder}" string. Logs a warning so shop operators know which fields
    need filling.
    """
    cfg = _load_shop_config(slug)
 
    # Flatten config into a single lookup dict
    flat: dict[str, str] = {}
 
    def _add(prefix: str, obj) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                _add(f"{prefix}{k}_" if prefix else f"{k}_", v)
                _add(f"{prefix}{k}", v)
        elif isinstance(obj, list):
            flat[prefix.rstrip("_")] = ", ".join(str(x) for x in obj)
        else:
            flat[prefix.rstrip("_")] = str(obj) if obj is not None else ""
 
    _add("", cfg)
 
    # Also expose nested fields under short aliases for common placeholders
    d = cfg.get("delivery", {})
    r = cfg.get("returns",  {})
    c = cfg.get("contact",  {})
    h = cfg.get("hours",    {})
    flat.setdefault("delivery_areas",  d.get("areas",       ""))
    flat.setdefault("delivery_days",   d.get("days",        ""))
    flat.setdefault("free_above",      d.get("free_above",  ""))
    flat.setdefault("return_days",     str(r.get("days",    "")))
    flat.setdefault("refund_days",     r.get("refund_days", ""))
    flat.setdefault("whatsapp",        c.get("whatsapp",    ""))
    flat.setdefault("phone",           c.get("phone",       ""))
    flat.setdefault("email",           c.get("email",       ""))
    flat.setdefault("location",        cfg.get("location",  ""))
    flat.setdefault("city",            cfg.get("city",      ""))
    flat.setdefault("shop_name",       cfg.get("shop_name", "Our Shop"))
    flat.setdefault("bot_name",        cfg.get("bot_name",  "Assistant"))
    flat.setdefault("weekdays",        h.get("weekdays",    ""))
    flat.setdefault("sunday",          h.get("sunday",      ""))
 
    def _replace(match: re.Match) -> str:
        key   = match.group(1)
        value = flat.get(key, "").strip()
 
        if not value or value.upper() in ("N/A", "NONE", "NULL", "0"):
            print(f"[faq_engine] WARNING: placeholder {{{key}}} is missing or empty "
                  f"for slug={slug!r}. Using readable fallback.")
            # Provide context-aware fallbacks for common keys
            fallbacks = {
                "delivery_areas":  "our delivery area",
                "delivery_days":   "a few days",
                "free_above":      "a minimum order amount",
                "return_days":     "the specified period",
                "refund_days":     "7-10 business days",
                "whatsapp":        "our WhatsApp number",
                "phone":           "our phone number",
                "email":           "our email",
                "location":        "our store location",
                "city":            "our city",
            }
            return fallbacks.get(key, f"[{key}]")
 
        return value
 
    return re.sub(r"\{(\w+)\}", _replace, text)
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  FAQ LOADERS  (FIX 3 — shop_type filtering)
# ══════════════════════════════════════════════════════════════════════════════
 
def _shop_type_matches(faq_entry: dict, shop_type: str | None) -> bool:
    """
    Returns True if the FAQ entry is applicable to this shop type.
 
    Logic:
    - If the FAQ has no "shop_types" field → it is universal, always included.
    - If it has "shop_types": ["all"] → universal.
    - Otherwise only included when shop_type is in the list.
    """
    applicable = faq_entry.get("shop_types")
    if not applicable:
        return True
    if "all" in applicable:
        return True
    if shop_type and shop_type in applicable:
        return True
    return False
 
 
def load_english_faqs(shop_type: str | None = None) -> list[dict]:
    """Load generic English FAQs, filtered by shop_type when provided."""
    try:
        raw = json.loads(_data("english.json").read_text(encoding="utf-8"))
        faqs = raw if isinstance(raw, list) else raw.get("faqs", [])
        if shop_type:
            faqs = [f for f in faqs if _shop_type_matches(f, shop_type)]
        return faqs
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[faq_engine] Could not load english.json: {e}")
        return []
 
 
def load_manglish_faqs(shop_type: str | None = None) -> list[dict]:
    """Load generic Manglish FAQs, filtered by shop_type when provided."""
    try:
        raw = json.loads(_data("manglish.json").read_text(encoding="utf-8"))
        faqs = raw if isinstance(raw, list) else raw.get("faqs", [])
        if shop_type:
            faqs = [f for f in faqs if _shop_type_matches(f, shop_type)]
        return faqs
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[faq_engine] Could not load manglish.json: {e}")
        return []
 
 
def load_english_sentiment_faqs(shop_type: str | None = None) -> list[dict]:
    try:
        raw = json.loads(_data("english_sentiment.json").read_text(encoding="utf-8"))
        faqs = raw if isinstance(raw, list) else raw.get("faqs", [])
        if shop_type:
            faqs = [f for f in faqs if _shop_type_matches(f, shop_type)]
        return faqs
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[faq_engine] Could not load english_sentiment.json: {e}")
        return []
 
 
def load_manglish_sentiment_faqs(shop_type: str | None = None) -> list[dict]:
    try:
        raw = json.loads(_data("manglish_sentiment.json").read_text(encoding="utf-8"))
        faqs = raw if isinstance(raw, list) else raw.get("faqs", [])
        if shop_type:
            faqs = [f for f in faqs if _shop_type_matches(f, shop_type)]
        return faqs
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[faq_engine] Could not load manglish_sentiment.json: {e}")
        return []
 
 
def load_shop_faqs(slug: str) -> list[dict]:
    """Load per-shop FAQs from shops/<slug>/faqs.json."""
    path = _SHOPS_DIR / slug.strip().lower().replace(" ", "-") / "faqs.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else raw.get("faqs", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  IN-MEMORY FAQ STORES  (populated at module load with no slug / shop_type)
# ══════════════════════════════════════════════════════════════════════════════
 
FAQS_ENGLISH:            list[dict] = load_english_faqs()
FAQS_MANGLISH:           list[dict] = load_manglish_faqs()
FAQS_ENGLISH_SENTIMENT:  list[dict] = load_english_sentiment_faqs()
FAQS_MANGLISH_SENTIMENT: list[dict] = load_manglish_sentiment_faqs()
 
# FIX 4 note: FAQS_SENTIMENT merges sentiment + flat pools. Deduplication by
# (question, answer) prevents inflating the embedding index and causing the
# 0.05 confidence-gap check to fail on near-duplicate vectors.
_seen_qa: set[tuple[str, str]] = set()
FAQS_SENTIMENT: list[dict] = []
for _faq in (FAQS_ENGLISH_SENTIMENT + FAQS_MANGLISH_SENTIMENT +
             FAQS_ENGLISH + FAQS_MANGLISH):
    _key = (_faq.get("question", "").strip().lower(), _faq.get("answer", "").strip().lower())
    if _key not in _seen_qa:
        _seen_qa.add(_key)
        FAQS_SENTIMENT.append(_faq)
 
FAQS_SHOP: dict[str, list[dict]] = {}   # populated lazily per slug
 
# Embedding texts used for semantic indexing
FAQ_EMB_TEXTS: list[str] = [f.get("question", "") for f in FAQS_SENTIMENT]
 
# Pre-compute embeddings for the merged pool
_FAQ_EMBEDDINGS: torch.Tensor | None = None
 
 
def _get_faq_embeddings() -> torch.Tensor:
    global _FAQ_EMBEDDINGS
    if _FAQ_EMBEDDINGS is None and FAQ_EMB_TEXTS:
        _FAQ_EMBEDDINGS = _get_model().encode(
            FAQ_EMB_TEXTS,
            convert_to_tensor=True,
            show_progress_bar=False,
        )
    return _FAQ_EMBEDDINGS  # type: ignore[return-value]
 
 
def reload_placeholders() -> None:
    """Called by chat.reload_config() to bust any cached config."""
    pass  # Placeholders are resolved at match time from live config
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  INTENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════
 
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "hours":      ["open", "close", "timing", "time", "hour", "eppo", "neram", "worktime"],
    "location":   ["where", "address", "location", "evide", "sthalam", "map", "directions"],
    "contact":    ["contact", "phone", "call", "whatsapp", "email", "reach", "number"],
    "payment":    ["payment", "pay", "upi", "card", "cash", "gpay", "phonepay", "paytm"],
    "delivery":   ["delivery", "deliver", "shipping", "ship", "parcel", "reach"],
    "returns":    ["return", "exchange", "refund", "replace", "back", "cancel"],
    "offer":      ["offer", "discount", "deal", "sale", "coupon", "code", "promo"],
    "services":   ["service", "do you", "provide", "offer", "available"],
    "complaint":  ["complaint", "problem", "issue", "wrong", "bad", "worst", "damaged"],
    "booking":    ["book", "appointment", "slot", "schedule", "reserve", "session"],
}
 
 
def detect_intent(message: str) -> str | None:
    msg_lower = message.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(kw in msg_lower for kw in keywords):
            return intent
    return None
 
 
def _filter_by_intent(faqs: list[dict], intent: str | None) -> list[dict]:
    if not intent:
        return faqs
    filtered = [
        f for f in faqs
        if intent in (f.get("section", "") + " " + f.get("category", "") +
                      " " + f.get("intent", "")).lower()
    ]
    return filtered if filtered else faqs
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  SEMANTIC MATCH  (Pass 1.5)
# ══════════════════════════════════════════════════════════════════════════════
 
def semantic_match(
    query: str,
    faqs: list[dict],
    threshold: float = SEMANTIC_THRESHOLD,
) -> dict | None:
    if not faqs:
        return None
 
    model = _get_model()
    q_emb  = model.encode(query, convert_to_tensor=True, show_progress_bar=False)
    corpus = [f.get("question", "") for f in faqs]
    c_embs = model.encode(corpus, convert_to_tensor=True, show_progress_bar=False)
 
    scores = util.cos_sim(q_emb, c_embs)[0]
    best_idx   = int(scores.argmax())
    best_score = float(scores[best_idx])
 
    if best_score < threshold:
        return None
 
    # Confidence gap check — prevents ambiguous close matches
    sorted_scores = sorted(scores.tolist(), reverse=True)
    if len(sorted_scores) > 1 and (sorted_scores[0] - sorted_scores[1]) < 0.05:
        return None
 
    faq = dict(faqs[best_idx])
    faq["faq_score"] = round(best_score, 4)
    return faq
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  F1 TOKEN OVERLAP MATCH  (Pass 3)
# ══════════════════════════════════════════════════════════════════════════════
 
def _tokenise(text: str) -> set[str]:
    return set(re.findall(r"\b\w+\b", text.lower()))
 
 
def _f1_score(pred: set[str], gold: set[str]) -> float:
    if not pred or not gold:
        return 0.0
    tp = len(pred & gold)
    if tp == 0:
        return 0.0
    precision = tp / len(pred)
    recall    = tp / len(gold)
    return 2 * precision * recall / (precision + recall)
 
 
def f1_match(
    query: str,
    faqs: list[dict],
    threshold: float = FAQ_THRESHOLD,
) -> dict | None:
    q_tokens = _tokenise(query)
    best_score = 0.0
    best_faq   = None
 
    for faq in faqs:
        score = _f1_score(q_tokens, _tokenise(faq.get("question", "")))
        if score > best_score:
            best_score = score
            best_faq   = faq
 
    if best_score < threshold or best_faq is None:
        return None
 
    result = dict(best_faq)
    result["faq_score"] = round(best_score, 4)
    return result
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  FUZZY MATCH  (Pass 2.5)
# ══════════════════════════════════════════════════════════════════════════════
 
def fuzzy_match(
    query: str,
    faqs: list[dict],
    threshold: int = 70,
) -> dict | None:
    try:
        from rapidfuzz import fuzz
    except ImportError:
        return None
 
    best_score = 0
    best_faq   = None
 
    for faq in faqs:
        score = fuzz.token_set_ratio(query.lower(), faq.get("question", "").lower())
        if score > best_score:
            best_score = score
            best_faq   = faq
 
    if best_score < threshold or best_faq is None:
        return None
 
    result = dict(best_faq)
    result["faq_score"] = round(best_score / 100, 4)
    return result
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  SHOP-SPECIFIC SEMANTIC MATCH  (Pass 0 — FIX 1)
# ══════════════════════════════════════════════════════════════════════════════
 
def _shop_semantic_match(query: str, slug: str) -> dict | None:
    """
    Pass 0: semantic search over per-shop FAQs.
    FIX 1: threshold is SHOP_FAQ_THRESHOLD = 0.60 (not 0.45).
    """
    shop_faqs = FAQS_SHOP.get(slug)
    if shop_faqs is None:
        shop_faqs = load_shop_faqs(slug)
        FAQS_SHOP[slug] = shop_faqs
 
    if not shop_faqs:
        return None
 
    result = semantic_match(query, shop_faqs, threshold=SHOP_FAQ_THRESHOLD)
    if result:
        result.setdefault("faq_source", f"shop:{slug}")
    return result
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  MAIN MATCH FUNCTION
# ══════════════════════════════════════════════════════════════════════════════
 
def match_faq(
    message: str,
    sentiment: str,
    slug: str | None = None,
) -> dict | None:
    """
    Four-pass FAQ matching.
 
    Pass 0  — Shop-specific semantic (cosine ≥ 0.60)
    Pass 1  — Intent-filtered semantic (cosine ≥ SEMANTIC_THRESHOLD)
    Pass 1.5— Full-pool semantic
    Pass 2.5— Fuzzy string match (rapidfuzz)
    Pass 3  — F1 token overlap
 
    Returns the best match dict with faq_source, faq_score, escalate,
    answer, and answer_lang fields, or None if nothing matched.
    """
    # Determine active shop_type for filtering
    shop_type: str | None = None
    if slug:
        cfg = _load_shop_config(slug)
        shop_type = cfg.get("shop_type")
 
    # Build sentiment-appropriate pool
    is_negative = sentiment in ("negative", "sarcastic", "urgent")
    lang_guess  = "manglish" if _looks_manglish(message) else "english"
 
    if lang_guess == "manglish":
        base_pool = load_manglish_faqs(shop_type)
        sent_pool = load_manglish_sentiment_faqs(shop_type) if is_negative else []
    else:
        base_pool = load_english_faqs(shop_type)
        sent_pool = load_english_sentiment_faqs(shop_type) if is_negative else []
 
    combined_pool = _dedup(sent_pool + base_pool)
 
    # ── Pass 0: shop-specific ─────────────────────────────────────────────
    if slug:
        hit = _shop_semantic_match(message, slug)
        if hit:
            hit = _enrich(hit, sentiment, slug)
            return hit
 
    # ── Pass 1: intent-filtered semantic ──────────────────────────────────
    intent   = detect_intent(message)
    filtered = _filter_by_intent(combined_pool, intent)
    hit = semantic_match(message, filtered, threshold=SEMANTIC_THRESHOLD)
    if hit:
        hit.setdefault("faq_source", lang_guess)
        hit = _enrich(hit, sentiment, slug)
        return hit
 
    # ── Pass 1.5: full-pool semantic ──────────────────────────────────────
    if filtered is not combined_pool:
        hit = semantic_match(message, combined_pool, threshold=SEMANTIC_THRESHOLD)
        if hit:
            hit.setdefault("faq_source", lang_guess)
            hit = _enrich(hit, sentiment, slug)
            return hit
 
    # ── Pass 2.5: fuzzy ───────────────────────────────────────────────────
    hit = fuzzy_match(message, combined_pool)
    if hit:
        hit.setdefault("faq_source", lang_guess + "_fuzzy")
        hit = _enrich(hit, sentiment, slug)
        return hit
 
    # ── Pass 3: F1 token overlap ──────────────────────────────────────────
    hit = f1_match(message, combined_pool)
    if hit:
        hit.setdefault("faq_source", lang_guess + "_f1")
        hit = _enrich(hit, sentiment, slug)
        return hit
 
    return None
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════
 
def _looks_manglish(text: str) -> bool:
    """Lightweight heuristic — avoids importing nlp here."""
    manglish_words = {
        "aanu", "alle", "aano", "sheri", "njan", "ningal", "njangal",
        "okke", "kollam", "kittum", "venam", "ippo", "ethra", "evide",
        "engane", "undenkil", "parayuka", "cheyyam", "undo", "aanu",
    }
    tokens = set(text.lower().split())
    return bool(tokens & manglish_words)
 
 
def _dedup(faqs: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out:  list[dict]           = []
    for f in faqs:
        key = (f.get("question", "").strip().lower(), f.get("answer", "").strip().lower())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out
 
 
def _enrich(faq: dict, sentiment: str, slug: str | None) -> dict:
    """
    Post-match enrichment:
    - Resolve {placeholder} tokens (FIX 2).
    - Set answer_lang from faq_source.
    - Set escalate flag.
    - Ensure faq_id present.
    """
    faq = dict(faq)  # copy — do not mutate the pool entry
 
    raw_answer = faq.get("answer", "")
    faq["answer"] = resolve_for_slug(raw_answer, slug)

    # Preserve a_ml (Manglish answer from type-pack FAQs)
    # Resolve placeholders in it too so {whatsapp} etc work in Manglish answers
    if faq.get("a_ml"):
        faq["a_ml"] = resolve_for_slug(faq["a_ml"], slug)

    src = faq.get("faq_source", "")
    faq["answer_lang"] = "manglish" if "manglish" in src else "english"
 
    faq.setdefault("escalate", faq.get("escalate_flag", False))
    faq.setdefault("faq_id",   faq.get("id", ""))
 
    return faq
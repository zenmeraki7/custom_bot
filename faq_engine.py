
from __future__ import annotations
from item_matcher import item_lookup, is_availability_query, is_price_query
"""
faq_engine.py — FAQ loading, matching, and resolution
======================================================

Fixes in this version (v6.1)
─────────────────────────────
  FIX A  Pass 0 now uses pre-built SHOP_EMB_VECTORS / SHOP_EMB_META injected
         by shop_manager instead of re-encoding from scratch on every call.

  FIX B  Schema bridge: shop_manager stores FAQs with keys "q"/"a"/"variants"
         but faq_engine was reading "question"/"answer". All match functions now
         accept both schemas via _get_question() / _get_answer() helpers.

  FIX C  load_shop_faqs() wrong filename fixed: "faqs.json" → "shop_faq.json"

  FIX D  semantic_match() confidence-gap check disabled for small pools (< 10).

  FIX E  All match functions now also score against question_variants.

  FIX F  Module-level SHOP_EMB_VECTORS / SHOP_EMB_META / SHOP_FLAT declared.

  FIX G  _enrich() handles both "q"/"a" and "question"/"answer" schemas.

  FIX H  _PLACEHOLDER_MAP module-level var added.

  FIX I  Generic pool embedding indexes ALL question variants.

  FIX J  semantic_match() uses pre-built _FAQ_EMBEDDINGS cache for full pool.
"""


import json
import re
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer, util

# ══════════════════════════════════════════════════════════════════════════════
#  MODEL
# ══════════════════════════════════════════════════════════════════════════════

# Switched to multilingual model — handles Manglish/Malayalam natively.
# Same model as nlp.py so it is reused from memory, not loaded twice.
_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        try:
            import nlp as _nlp
            if _nlp.embedder is not None:
                _model = _nlp.embedder
                return _model
        except Exception:
            pass
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def device_name() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


# ══════════════════════════════════════════════════════════════════════════════
#  SEMANTIC ROUTING FALLBACK  (_SEMANTIC_ROUTING_FALLBACK marker)
#  Second opinion for item-lookup-vs-question routing, used ONLY
#  when the cheap rule-based detectors are ambiguous. Generalizes
#  across word inflections and shop domains no rule covers yet.
# ══════════════════════════════════════════════════════════════════════════════

_ANCHOR_LOOKUP = [
    "facial undo",
    "threading price ethra",
    "what items do you have",
    "show me the menu",
    "biriyani undo",
    "list of services",
    "bridal makeup undo",
    "room rates",
]

_ANCHOR_QUESTION = [
    "is this safe",
    "does this hurt",
    "is threading painful",
    "how long does this take",
    "is the food spicy",
    "is this suitable for sensitive skin",
    "what should I do after this treatment",
    "is this included in the package",
    "is it hygienic",
    "is this good quality",
]

_semantic_anchor_cache: dict = {}


def _get_anchor_embeddings():
    """Computed once, cached -- never re-embedded per request."""
    if "lookup" not in _semantic_anchor_cache:
        model = _get_model()
        _semantic_anchor_cache["lookup"] = model.encode(
            _ANCHOR_LOOKUP, convert_to_tensor=True,
            normalize_embeddings=True, show_progress_bar=False,
        )
        _semantic_anchor_cache["question"] = model.encode(
            _ANCHOR_QUESTION, convert_to_tensor=True,
            normalize_embeddings=True, show_progress_bar=False,
        )
    return _semantic_anchor_cache['lookup'], _semantic_anchor_cache['question']


# Margin required for the semantic layer to OVERRIDE the rule-based
# default. NOT independently calibrated against the real model --
# start conservative, tune based on real logged outcomes.
_SEMANTIC_MARGIN = 0.05


_ABOUT_SERVICE_INTENT = re.compile(
    r"\b(pain|painful|hurt|undakumo|undaakumo|safe|side\s*effect|after|"
    r"sesham|sesham|munpu|before|during|how\s*long|how\s*often|can\s*i|"
    r"should\s*i|cheyamo|cheyyamo|cheyaam|cheyyanam|cheyyano|use\s+cheyamo|"
    r"nallath|better|good\s*for|benefit|enthanu\s+cheyyendath|"
    r"recommend|suggest|advice|tip|"
    r"appoi?ntment|booking|\bbook\b|edukk\w*|engane|engne|reschedule|cancel)\b",
    re.IGNORECASE,
)


def _looks_like_full_question_semantic(message: str) -> bool:
    """Second-opinion check: only called when rules are AMBIGUOUS
    (service word present, but rules said 'not a question').
    """
    # Explicit ABOUT-a-service intent (pain? after? can I?) is a QUESTION,
    # full stop — never an item lookup, no matter what cosine says.
    if _ABOUT_SERVICE_INTENT.search(message):
        print(f"[semantic_routing] msg={message!r} -> QUESTION (explicit intent word)")
        return True
    try:
        model = _get_model()
        lookup_emb, question_emb = _get_anchor_embeddings()
        msg_emb = model.encode(
            message, convert_to_tensor=True,
            normalize_embeddings=True, show_progress_bar=False,
        )
        lookup_score = float(util.cos_sim(msg_emb, lookup_emb).max())
        question_score = float(util.cos_sim(msg_emb, question_emb).max())
        is_question = question_score > lookup_score + _SEMANTIC_MARGIN
        print(
            f"[semantic_routing] msg={message!r} "
            f"lookup={lookup_score:.3f} question={question_score:.3f} "
            f"-> {'QUESTION' if is_question else 'LOOKUP'}"
        )
        return is_question
    except Exception as exc:
        print(f"[semantic_routing] error, defaulting to rule-based result: {exc}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  THRESHOLDS
# ══════════════════════════════════════════════════════════════════════════════

FAQ_THRESHOLD         = 0.45
SEMANTIC_THRESHOLD    = 0.42  # lowered: multilingual model scores higher on Manglish
SHOP_FAQ_THRESHOLD    = 0.55  # English shop FAQ
SHOP_FAQ_THRESHOLD_ML = 0.45  # Manglish short queries (raised: weak matches -> RAG)


# ══════════════════════════════════════════════════════════════════════════════
#  PATHS
# ══════════════════════════════════════════════════════════════════════════════

_DATA_DIR    = Path("data")
_SHOPS_DIR   = Path("shops")
_SHOP_CONFIG = Path("shop_config.json")


def _data(filename: str) -> Path:
    return _DATA_DIR / filename


# ══════════════════════════════════════════════════════════════════════════════
#  SCHEMA BRIDGE  (FIX B)
# ══════════════════════════════════════════════════════════════════════════════

def _get_question(faq: dict) -> str:
    return (faq.get("question") or faq.get("q") or "").strip()


def _get_answer(faq: dict) -> str:
    return (faq.get("answer") or faq.get("a") or "").strip()


def _get_all_questions(faq: dict) -> list[str]:
    primary = _get_question(faq)
    variants = (
        faq.get("variants") or
        faq.get("question_variants") or
        []
    )
    all_q = [primary] if primary else []
    all_q += [v.strip() for v in variants if v and v.strip()]
    return all_q


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
#  PLACEHOLDER MAP  (FIX H)
# ══════════════════════════════════════════════════════════════════════════════

_PLACEHOLDER_MAP: dict[str, str] | None = None


# ══════════════════════════════════════════════════════════════════════════════
#  PLACEHOLDER RESOLUTION  (FIX 2)
# ══════════════════════════════════════════════════════════════════════════════

def resolve_for_slug(text: str, slug: str | None = None) -> str:
    if _PLACEHOLDER_MAP is not None:
        flat = dict(_PLACEHOLDER_MAP)
    else:
        cfg = _load_shop_config(slug)
        flat = _build_flat_map(cfg)

    def _replace(match: re.Match) -> str:
        key   = match.group(1)
        value = flat.get(key, "").strip()

        if not value or value.upper() in ("N/A", "NONE", "NULL", "0"):
            print(f"[faq_engine] WARNING: placeholder {{{key}}} is missing or empty "
                  f"for slug={slug!r}. Using readable fallback.")
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


def _build_flat_map(cfg: dict) -> dict[str, str]:
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

    return flat


# ══════════════════════════════════════════════════════════════════════════════
#  FAQ LOADERS  (FIX 3)
# ══════════════════════════════════════════════════════════════════════════════

def _shop_type_matches(faq_entry: dict, shop_type: str | None) -> bool:
    applicable = faq_entry.get("shop_types")
    if not applicable:
        return True
    if "all" in applicable:
        return True
    if shop_type and shop_type in applicable:
        return True
    return False


def load_english_faqs(shop_type: str | None = None) -> list[dict]:
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
    """Load per-shop FAQs. FIX C: reads shop_faq.json (not faqs.json)."""
    slug_norm = slug.strip().lower().replace(" ", "-")
    path = _SHOPS_DIR / slug_norm / "shop_faq.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, list) else raw.get("faqs", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ══════════════════════════════════════════════════════════════════════════════
#  IN-MEMORY FAQ STORES
# ══════════════════════════════════════════════════════════════════════════════

FAQS_ENGLISH:            list[dict] = load_english_faqs()
FAQS_MANGLISH:           list[dict] = load_manglish_faqs()
FAQS_ENGLISH_SENTIMENT:  list[dict] = load_english_sentiment_faqs()
FAQS_MANGLISH_SENTIMENT: list[dict] = load_manglish_sentiment_faqs()

_seen_qa: set[tuple[str, str]] = set()
FAQS_SENTIMENT: list[dict] = []
for _faq in (FAQS_ENGLISH_SENTIMENT + FAQS_MANGLISH_SENTIMENT +
             FAQS_ENGLISH + FAQS_MANGLISH):
    _key = (_get_question(_faq), _get_answer(_faq))
    if _key not in _seen_qa:
        _seen_qa.add(_key)
        FAQS_SENTIMENT.append(_faq)

FAQS_SHOP: dict[str, list[dict]] = {}

# ── Generic pool embedding index  (FIX I + FIX J) ────────────────────────────
FAQ_EMB_TEXTS: list[str] = []
FAQ_EMB_INDEX: list[int] = []

for _i, _faq in enumerate(FAQS_SENTIMENT):
    for _q in _get_all_questions(_faq):
        if _q:
            FAQ_EMB_TEXTS.append(_q)
            FAQ_EMB_INDEX.append(_i)

_FAQ_EMBEDDINGS: torch.Tensor | None = None


_FAQ_EMB_SIZE: int = 0

def _get_faq_embeddings() -> torch.Tensor:
    """Rebuild if FAQ pool grew (e.g. after generate-shop adds FAQs)."""
    global _FAQ_EMBEDDINGS, _FAQ_EMB_SIZE
    current_size = len(FAQ_EMB_TEXTS)
    if _FAQ_EMBEDDINGS is None or _FAQ_EMB_SIZE != current_size:
        if FAQ_EMB_TEXTS:
            _FAQ_EMBEDDINGS = _get_model().encode(
                FAQ_EMB_TEXTS,
                convert_to_tensor=True,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=64,
            )
            _FAQ_EMB_SIZE = current_size
    return _FAQ_EMBEDDINGS  # type: ignore[return-value]


# ══════════════════════════════════════════════════════════════════════════════
#  SHOP EMBEDDING STORE  (FIX F)
# ══════════════════════════════════════════════════════════════════════════════

# Per-slug store — prevents multi-tenant vector overwrite
_SHOP_EMB_STORE: dict[str, tuple] = {}

# Keep globals for backwards compat with shop_manager imports
SHOP_EMB_VECTORS: torch.Tensor | None = None
SHOP_EMB_META:    list[dict]          = []
SHOP_FLAT:        list[dict]          = []


def reload_placeholders() -> None:
    pass

def register_shop_embeddings(slug: str, vectors, meta: list) -> None:
    """Called by shop_manager after building per-shop FAQ embeddings.
    Stores vectors in per-slug dict for multi-tenant isolation.
    """
    slug_norm = slug.strip().lower().replace(" ", "-")
    _SHOP_EMB_STORE[slug_norm] = (vectors, meta)



# ══════════════════════════════════════════════════════════════════════════════
#  INTENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "hours":      ["open", "close", "timing", "time", "hour", "eppo", "neram", "worktime"],
    "location":   ["where", "address", "location", "evide", "evda", "sthalam", "map", "directions"],
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
#  SEMANTIC MATCH  (FIX D + FIX E + FIX J)
# ══════════════════════════════════════════════════════════════════════════════

def semantic_match(
    query: str,
    faqs: list[dict],
    threshold: float = SEMANTIC_THRESHOLD,
) -> dict | None:
    if not faqs:
        return None

    model = _get_model()
    q_emb = model.encode(
        query, convert_to_tensor=True,
        normalize_embeddings=True, show_progress_bar=False,
    )

    # FIX J: full generic pool → use pre-built cache
    if faqs is FAQS_SENTIMENT and FAQ_EMB_TEXTS:
        c_embs = _get_faq_embeddings()
        scores = util.cos_sim(q_emb, c_embs)[0]

        best_row   = int(scores.argmax())
        best_score = float(scores[best_row])

        if best_score < threshold:
            return None

        # Gap check removed: multilingual model produces small gaps
        # on valid Manglish matches. Threshold above is sufficient.
        faq = dict(FAQS_SENTIMENT[FAQ_EMB_INDEX[best_row]])
        faq["faq_score"] = round(best_score, 4)
        return faq

    # Inline path: sub-pool — FIX E: index all variants
    corpus_texts: list[str] = []
    corpus_index: list[int] = []

    for idx, faq in enumerate(faqs):
        for q_text in _get_all_questions(faq):
            if q_text:
                corpus_texts.append(q_text)
                corpus_index.append(idx)

    if not corpus_texts:
        return None

    c_embs = model.encode(
        corpus_texts, convert_to_tensor=True,
        normalize_embeddings=True, show_progress_bar=False,
    )
    scores = util.cos_sim(q_emb, c_embs)[0]

    best_row   = int(scores.argmax())
    best_score = float(scores[best_row])

    if best_score < threshold:
        return None

    faq = dict(faqs[corpus_index[best_row]])
    faq["faq_score"] = round(best_score, 4)
    return faq


# ══════════════════════════════════════════════════════════════════════════════
#  F1 TOKEN OVERLAP MATCH  (FIX E)
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
    q_tokens   = _tokenise(query)
    best_score = 0.0
    best_faq   = None

    for faq in faqs:
        best_variant_score = max(
            (_f1_score(q_tokens, _tokenise(q)) for q in _get_all_questions(faq)),
            default=0.0,
        )
        if best_variant_score > best_score:
            best_score = best_variant_score
            best_faq   = faq

    if best_score < threshold or best_faq is None:
        return None

    result = dict(best_faq)
    result["faq_score"] = round(best_score, 4)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  FUZZY MATCH  (FIX E)
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
        for q_text in _get_all_questions(faq):
            score = fuzz.token_set_ratio(query.lower(), q_text.lower())
            if score > best_score:
                best_score = score
                best_faq   = faq

    if best_score < threshold or best_faq is None:
        return None

    result = dict(best_faq)
    result["faq_score"] = round(best_score / 100, 4)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  SHOP-SPECIFIC SEMANTIC MATCH  (Pass 0 — FIX A + FIX C)
# ══════════════════════════════════════════════════════════════════════════════

# ── Universal topic guard (shop-agnostic) ────────────────────────────────────
# Stops a FAQ winning when it is about a DIFFERENT product/service than the
# query. Short queries embed noisily and can land nearest a wrong-topic FAQ
# (beauty: "facial undo" -> bridal FAQ; pharmacy: "paracetamol" -> syrup FAQ).
# The shop vocabulary is derived FROM THE SHOP'S OWN ITEMS at runtime, so this
# works for ANY shop type (beauty, restaurant, pharmacy, hardware) with no
# hardcoded word lists.
_TOPIC_STOP = {
    "the", "a", "an", "of", "for", "to", "do", "you", "i", "we", "is", "are",
    "and", "or", "with", "at", "by", "this", "that", "my", "me", "our", "your",
    "what", "which", "how", "much", "have", "has", "offer", "provide", "sell",
    "want", "need", "get", "show", "list", "available", "price", "cost", "rate",
    "service", "services", "item", "items", "types", "kinds", "all", "full",
    "details", "undo", "und", "undu", "indo", "aano", "kittumo", "cheyyumo",
    "ethra", "ethoke", "enthoke", "okke", "ellam", "please", "there",
}


def _content_words(text: str) -> set:
    toks = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return {t for t in toks if len(t) >= 3 and t not in _TOPIC_STOP}


def _build_shop_vocab(items: list) -> set:
    """Derive the shop's product/service vocabulary from its own item names.
    Cached per call site via the items list identity is unnecessary; this is
    cheap (a few hundred short strings)."""
    vocab: set = set()
    for it in (items or []):
        for w in re.sub(r"[^\w\s]", " ", str(it.get("name", "")).lower()).split():
            if len(w) >= 3 and w not in _TOPIC_STOP:
                vocab.add(w)
    return vocab


def _topic_guard_ok(query: str, faq_question: str, shop_vocab: set) -> bool:
    """True if the FAQ may answer this query: they share a shop-vocabulary word,
    or the query names nothing in the shop vocab (general: hours/location/etc.)."""
    if not shop_vocab:
        return True                       # no item data -> can't guard, allow

    # PERMANENT FIX: expand known synonyms/spelling variants (chaya/tea ->
    # chai, vegetarian -> veg, etc.) before checking the query against shop
    # vocab. Without this, "chaya" (a different word for tea, not a typo of
    # it) never overlaps shop_vocab's "chai", qc comes back empty, the guard
    # reads that as "general query -> allow anything", and a completely
    # unrelated FAQ (Chapathi, Dal Tadka, whatever embeds nearest) wins
    # unguarded -- item_lookup, which already handles this correctly via
    # its own _expand_synonyms, never gets a chance to run.
    try:
        from item_matcher import _expand_synonyms
        _query_for_guard = _expand_synonyms(query)
    except Exception:
        _query_for_guard = query
    qc = _content_words(_query_for_guard) & shop_vocab
    if not qc:
        return True                       # general query -> semantic decides
    fc = _content_words(faq_question) & shop_vocab
    if not fc:
        return True                       # FAQ is general -> allowed
    for a in qc:
        for b in fc:
            if a.startswith(b) or b.startswith(a):
                return True
    return False


# Margin within which two candidates are treated as a genuine near-tie.
# Deliberately narrow: this does NOT reject the top match the way the old
# (removed) "gap check" did -- it only re-ranks among candidates that are
# ALREADY close enough that picking purely by embedding score is close to a
# coin flip (e.g. "pharmacy_home_delivery" vs "pharmacy_delivery_charges" for
# a "Delivery charge undoo?" query -- both are topically about delivery, but
# only one actually answers what was asked).
_NEAR_TIE_MARGIN = 0.03


def _keyword_overlap(query: str, faq_question: str) -> float:
    """Lightweight lexical overlap (Jaccard on tokens), used ONLY to break
    near-ties between semantically-similar FAQ candidates -- never used as a
    standalone matcher or a rejection gate."""
    q_tokens = set(re.findall(r"\b\w+\b", query.lower()))
    f_tokens = set(re.findall(r"\b\w+\b", faq_question.lower()))
    if not q_tokens or not f_tokens:
        return 0.0
    return len(q_tokens & f_tokens) / len(q_tokens | f_tokens)


def _best_with_tiebreak(scores, meta_list: list, query: str):
    """Like scores.argmax(), but when multiple candidates land within
    _NEAR_TIE_MARGIN of the top score, re-rank that near-tied group by
    keyword overlap with the query instead of trusting the raw embedding
    score alone. Returns (best_row, best_score) using the ORIGINAL semantic
    score for the winner (keyword overlap only decides WHICH near-tied
    candidate wins, it doesn't replace the confidence score)."""
    k = min(5, scores.shape[0])
    top_scores, top_idx = scores.topk(k)
    top_scores = top_scores.tolist()
    top_idx = top_idx.tolist()

    best_score = top_scores[0]
    tied = [(i, s) for i, s in zip(top_idx, top_scores)
            if best_score - s <= _NEAR_TIE_MARGIN]

    if len(tied) <= 1:
        return top_idx[0], top_scores[0]

    def _q_text(row_meta: dict) -> str:
        return row_meta.get("q") or row_meta.get("question") or ""

    ranked = sorted(
        tied,
        key=lambda pair: _keyword_overlap(query, _q_text(meta_list[pair[0]])),
        reverse=True,
    )
    winner_idx, _ = ranked[0]
    # Report the winner's own semantic score, not the top score, so
    # downstream threshold checks stay honest about actual confidence.
    winner_score = dict(tied)[winner_idx]
    return winner_idx, winner_score


def _shop_semantic_match(query: str, slug: str, lang: str = "english", shop_vocab: set | None = None) -> dict | None:
    # FIX A: use pre-built matrix from shop_manager
    # FIX 1: dual threshold — Manglish short queries need lower floor
    # FIX LANG: filter candidate rows by _qlang to avoid cross-language matches
    threshold = SHOP_FAQ_THRESHOLD_ML if lang == "manglish" else SHOP_FAQ_THRESHOLD

    slug_norm = slug.strip().lower().replace(" ", "-")
    # Check per-slug store first (multi-tenant safe)
    _entry = _SHOP_EMB_STORE.get(slug_norm)
    if _entry is not None:
        _vecs, _meta = _entry
        if _vecs is not None and _meta:
            # Build language-filtered index.
            # Prefer same-language rows; fall back to all rows if none found.
            want_lang = "ml" if lang == "manglish" else "en"
            lang_rows = [i for i, m in enumerate(_meta) if m.get("_qlang") == want_lang]
            if not lang_rows:
                # No language tags — old index, search everything (safe fallback)
                lang_rows = list(range(len(_meta)))

            lang_vecs = _vecs[lang_rows]
            lang_meta = [_meta[i] for i in lang_rows]

            model = _get_model()
            q_emb = model.encode(query, convert_to_tensor=True,
                                  normalize_embeddings=True,
                                  show_progress_bar=False)
            scores = util.cos_sim(q_emb, lang_vecs)[0]
            best_row, best_score = _best_with_tiebreak(scores, lang_meta, query)
            if best_score < threshold:
                return None
            faq = dict(lang_meta[best_row])
            _fq = faq.get("q") or faq.get("question") or ""
            if shop_vocab is not None and not _topic_guard_ok(query, _fq, shop_vocab):
                return None
            faq["faq_score"]  = round(best_score, 4)
            faq["faq_source"] = f"shop:{slug_norm}"
            return faq

    # Legacy global fallback
    if SHOP_EMB_VECTORS is not None and SHOP_EMB_META:
        model = _get_model()
        q_emb  = model.encode(query, convert_to_tensor=True,
                               normalize_embeddings=True, show_progress_bar=False)
        scores = util.cos_sim(q_emb, SHOP_EMB_VECTORS)[0]
        best_row, best_score = _best_with_tiebreak(scores, SHOP_EMB_META, query)
        if best_score < threshold:
            return None
        faq = dict(SHOP_EMB_META[best_row])
        _fq = faq.get("q") or faq.get("question") or ""
        if shop_vocab is not None and not _topic_guard_ok(query, _fq, shop_vocab):
            return None
        faq["faq_score"]  = round(best_score, 4)
        faq["faq_source"] = f"shop:{slug_norm}"
        return faq

    # Fallback: disk load + inline encode
    shop_faqs = FAQS_SHOP.get(slug)
    if shop_faqs is None:
        shop_faqs = load_shop_faqs(slug)  # FIX C: reads shop_faq.json
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


# ── Item-query intents — applies to ALL shop types ───────────────────────────
_ITEM_QUERY_INTENTS = {
    "services", "booking", "menu", "availability", "food", "items", "catalog", "price",
}

# Food/menu intents that should NEVER hit generic pool (FIX 3)
_FOOD_INTENTS = {"menu", "availability", "price", "food", "items", "catalog"}


def detect_intent_v2(message: str) -> str | None:
    """Extended intent detection covering beauty/service/food/retail shops."""
    _EXTENDED_KEYWORDS: dict[str, list[str]] = {
        "hours":      ["open", "close", "timing", "time", "hour", "eppo", "neram"],
        "location":   ["where", "address", "location", "evide", "evda", "sthalam", "map"],
        "contact":    ["contact", "phone", "call", "whatsapp", "email", "reach", "number"],
        "payment":    ["payment", "pay", "upi", "card", "cash", "gpay", "phonepay"],
        "delivery":   ["delivery", "deliver", "shipping", "ship", "parcel"],
        "returns":    ["return", "exchange", "refund", "replace", "back", "cancel"],
        "offer":      ["offer", "discount", "deal", "sale", "coupon", "code", "promo"],
        "complaint":  [
            "complaint", "compliant", "complaining", "complient",
            "problem", "issue", "bad", "worst", "damaged", "not happy",
            "not satisfied", "mosham", "fraud", "cheating",
        ],
        "booking":    ["book", "appointment", "slot", "schedule", "reserve", "session"],
        "services":   [
            "service", "facial", "cleanup", "bleach", "wax", "waxing", "threading",
            "manicure", "pedicure", "massage", "haircut", "trim", "highlights",
            "color", "colour", "straightening", "rebonding", "keratin", "bridal",
            "makeup", "eyebrow", "undo", "und", "undu", "indo", "kittumo", "ethoke",
        ],
        "food":       [
            "menu", "food", "dish", "dishes", "biriyani", "biryani", "chicken",
            "mutton", "fish", "prawn", "seafood", "veg", "items", "undo", "und",
        ],
        "items":      ["product", "item", "brand", "stock", "available", "price", "vila"],
        "price":      ["price", "cost", "rate", "charge", "fee", "how much", "ethra", "vila"],
    }
    msg_lower = message.lower()
    for intent, keywords in _EXTENDED_KEYWORDS.items():
        if any(kw in msg_lower for kw in keywords):
            return intent
    return None


def match_faq(
    message: str,
    sentiment: str,
    slug: str | None = None,
    lang: str | None = None,           # FIX 2: accept lang from pipeline
) -> dict | None:
    shop_type: str | None = None
    shop_items: list[dict] = []
    if slug:
        cfg = _load_shop_config(slug)
        shop_type = cfg.get("shop_type")
        try:
            from shop_manager import get_shop_items as _get_items
            shop_items = _get_items(slug) or []
        except Exception:
            pass

    is_negative = sentiment in ("negative", "sarcastic", "urgent")
    # FIX 2: use pipeline lang; fall back to local detection
    lang_guess = lang if lang in ("english", "manglish") else (
        "manglish" if _looks_manglish(message) else "english"
    )

    if lang_guess == "manglish":
        base_pool = load_manglish_faqs(shop_type)
        sent_pool = load_manglish_sentiment_faqs(shop_type) if is_negative else []
    else:
        base_pool = load_english_faqs(shop_type)
        sent_pool = load_english_sentiment_faqs(shop_type) if is_negative else []

    combined_pool = _dedup(sent_pool + base_pool)

    # ── Pass -1: shop item lookup (runs BEFORE semantic FAQ match) ───────────
    # A direct 'what do you have / how much' query must win over a fuzzy
    # semantic match against aftercare/info FAQs. e.g. 'threading undo'
    # should list items, not return 'pat dry with a clean towel'.
    # ────────────────────────────────────────────
    # Fires for ANY shop type (beauty, restaurant, pharmacy, retail).
    # "facial undo" → lists all facials with prices (beauty shop)
    # "chicken undo" → lists all chicken dishes with prices (restaurant)
    _GREETING_TOKENS = {
        "namaskaram", "hello", "hi", "hey", "hlo", "hoi",
        "vanakkam", "hai", "salam",
    }
    _BROAD_SVC = [
        # Manglish
        "services enthoke", "enthokke service", "enthokee service",
        "enthoke service", "enthoke und service", "enthoke anu service",
        "enthoke service available", "services ivide", "services undo",
        "services und", "enthellam services", "enthellam und",
        # English
        "all services", "full service", "service details",
        "what services", "which services", "what do you offer",
        "what all services", "list of services", "services available",
        "service list", "all service", "what services do you",
        "full menu", "menu list",
    ]
    _msg_toks = set(message.lower().split())
    _is_greeting = bool(_msg_toks & _GREETING_TOKENS) and len(_msg_toks) <= 3
    _is_broad = any(p in message.lower() for p in _BROAD_SVC)

    # Service name signals — "threading undo", "facial cheyanam" etc.
    _SERVICE_SIGNALS = {
        "threading", "facial", "waxing", "manicure", "pedicure",
        "makeup", "bridal", "keratin", "haircut", "cleanup", "hair",
        "bleach", "eyebrow", "highlights", "rebonding", "straightening",
        "massage", "spa", "peel", "scrub", "polish", "colour", "color",
        "biriyani", "biryani", "chicken", "mutton", "fish", "prawn",
        "shawarma", "pizza", "burger", "noodles", "pasta", "rice",
    }
    _has_service = bool(set(message.lower().split()) & _SERVICE_SIGNALS)

    _has_service = bool(set(message.lower().split()) & _SERVICE_SIGNALS)

    # A full grammatical question ("Do you offer anti-aging skin
    # treatments?", "How long does a facial session take?", "Can
    # bridal packages include makeup for family members?") must NOT
    # be hijacked into a price-list dump just because it contains a
    # service-signal word -- these usually have their own specific
    # FAQ answer in Pass 0. Bare item-lookup phrases ("facial undo",
    # "threading price ethra") never start with a question word, so
    # this rule cleanly separates the two without shop-specific logic.
    _QUESTION_STARTERS = {
        "can", "is", "are", "does", "do", "should", "will", "would",
        "could", "why", "when", "what", "how", "where", "who",
    }
    _msg_words = re.sub(r"[^\w\s]", " ", message.lower()).split()
    # Lowered from 4 to 3 words -- "Is threading painful?" is a
    # real, complete question at 3 words and was wrongly missed.
    # Safe at 3: item-lookup phrases never start with a question
    # word ("facial undo" starts with a noun), so there is no
    # overlap risk even at this lower threshold.
    _looks_like_full_question_en = (
        bool(_msg_words) and
        _msg_words[0] in _QUESTION_STARTERS and
        len(_msg_words) >= 3
    )

    # Manglish equivalent of the English check above. Manglish
    # question markers are usually SUFFIX PARTICLES attached to
    # the verb (undakumo, aano, pattumo, kittumo) rather than
    # sentence-initial words like English "is"/"does"/"can". A
    # bare particle alone is NOT safe on its own -- ordinary item
    # lookups also end this way ("facial undo" must stay totally
    # unaffected). The real signal is a PARTICLE combined with a
    # QUALITY/DESCRIPTIVE word (pain, safe, side effect, how
    # long) -- that combination reliably means a real question
    # about safety/duration/experience, not a simple lookup.
    _MANGLISH_QUESTION_PARTICLES = {
        "undakumo", "aakumo", "pattumo", "aano", "ano", "undo",
        "kittumo", "venamo", "cheyyumo", "varumo", "akumo",
    }
    # _QUALITY_WORDS_V2_COVERAGE_FIX -- broadened beyond the
    # original beauty/health-shaped list to cover other shop
    # domains (restaurant, hotel, gym) with the same mechanism.
    # PREFIX-matched stems: safe for longer words where a
    # collision with an unrelated word is extremely unlikely.
    # Catches inflections ("painful" matches "pain", "spicy"
    # matches "spic") without enumerating every variant by hand.
    _MANGLISH_QUALITY_STEMS_PREFIX = {
        "pain", "vedana", "safe", "long", "neram", "ethra",
        "good", "nalla", "better", "best", "effect", "problem",
        "issue", "risk", "danger",
        "spic", "fresh", "pacha", "choodu", "cold",
        "tasty", "rusi", "hygien", "clean", "vrithi", "crowd", "rush",
        "comfort", "sukham", "eluppam", "difficult", "bhutham",
        "thright", "veham", "quality", "genuine",
    }
    # EXACT-matched only: short words where prefix matching would
    # create real collisions ("hotel".startswith("hot"),
    # "karate".startswith("kara")) -- safety verified by testing.
    _MANGLISH_QUALITY_EXACT = {
        "side", "hot", "kara", "easy", "fast", "slow", "quick",
        "after", "before", "during",
    }
    _msg_word_set_ml = set(_msg_words)
    _has_quality_word_ml = bool(_msg_word_set_ml & _MANGLISH_QUALITY_EXACT) or any(
        any(_w.startswith(_s) for _s in _MANGLISH_QUALITY_STEMS_PREFIX)
        for _w in _msg_words
    )
    _looks_like_full_question_ml = (
        len(_msg_words) >= 3 and
        bool(_msg_word_set_ml & _MANGLISH_QUESTION_PARTICLES) and
        _has_quality_word_ml
    )

    _looks_like_full_question = (
        _looks_like_full_question_en or _looks_like_full_question_ml
    )

    # Ambiguous zone: a service word is present but the cheap
    # rules said "not a question". This is exactly where rules
    # have repeatedly been wrong this session. Get a semantic
    # second opinion ONLY here -- clear-cut cases above never
    # reach this code, so there is no added latency for the
    # common case.
    if _has_service and not _looks_like_full_question:
        if _looks_like_full_question_semantic(message):
            _looks_like_full_question = True

    # Breadth query ("all facials", "list of syrups", "ella biriyani")? Enumerate
    # the whole category from items BEFORE any single FAQ can hijack it.
    # Universal: keys on the shop's own item names, any shop type.
    if shop_items and not _is_greeting:
        try:
            from item_matcher import category_list_lookup
            _cat = category_list_lookup(message, shop_items, lang=lang_guess)
            if _cat:
                return {
                    "answer":      _cat,
                    "question":    message,
                    "faq_source":  "category_list",
                    "faq_id":      "category_list",
                    "faq_score":   1.0,
                    "escalate":    False,
                    "answer_lang": lang_guess,
                }
        except Exception as _ce:
            print(f"[category_list] skipped: {_ce}")

    _FAQ_WIN_THRESHOLD = 0.45 if lang_guess == "manglish" else 0.58
    _is_item_query = (
        shop_items and not _is_greeting and not _is_broad and
        (_has_service or is_availability_query(message) or is_price_query(message))
    )

    # Pass 0: FAQ always runs first (topic-guarded with shop's own vocabulary)
    _shop_vocab = _build_shop_vocab(shop_items)
    _faq_hit = None
    if slug:
        _faq_hit = _shop_semantic_match(message, slug, lang=lang_guess, shop_vocab=_shop_vocab)

    if _faq_hit:
        _faq_score = _faq_hit.get("faq_score", 0.0)
        if _is_item_query and _faq_score < _FAQ_WIN_THRESHOLD:
            item_reply = (None if _ABOUT_SERVICE_INTENT.search(message)
                          else item_lookup(message, shop_items, lang=lang_guess))
            if item_reply:
                return {
                    "answer":      item_reply,
                    "question":    message,
                    "faq_source":  "item_lookup",
                    "faq_id":      "item_lookup",
                    "faq_score":   1.0,
                    "escalate":    False,
                    "answer_lang": lang_guess,
                }
        hit = _enrich(_faq_hit, sentiment, slug)
        return hit

    if _is_item_query:
        item_reply = (None if _ABOUT_SERVICE_INTENT.search(message)
                      else item_lookup(message, shop_items, lang=lang_guess))
        if item_reply:
            return {
                "answer":      item_reply,
                "question":    message,
                "faq_source":  "item_lookup",
                "faq_id":      "item_lookup",
                "faq_score":   1.0,
                "escalate":    False,
                "answer_lang": lang_guess,
            }

    # A full-question message that _is_item_query didn't already claim
    # (e.g. it has no literal service-signal word and doesn't match the
    # availability/price regexes, but still reads as a real question) is
    # exactly the case the fallback below exists for. If _is_item_query
    # WAS true, item_lookup already ran above -- retrying it here would
    # just repeat the same deterministic call, so skip in that case.
    _item_lookup_fallback = bool(shop_items) and _looks_like_full_question and not _is_item_query

    # Fallback: full-question item lookup. The message looked like a
    # full question ("Do you offer anti-aging skin treatments?") so
    # Pass -1 deferred to Pass 0 above, hoping for a dedicated FAQ.
    # Pass 0 found nothing -- so this is a genuine item-related
    # question with no specific FAQ entry. Give it a real, shop-
    # grounded answer now instead of falling through to a generic
    # or wrong-category match.
    if locals().get("_item_lookup_fallback"):
        item_reply = (None if _ABOUT_SERVICE_INTENT.search(message)
                      else item_lookup(message, shop_items, lang=lang_guess))
        if item_reply:
            return {
                "answer":      item_reply,
                "question":    message,
                "faq_source":  "item_lookup_fallback",
                "faq_id":      "item_lookup_fallback",
                "faq_score":   0.9,
                "escalate":    False,
                "answer_lang": lang_guess,
            }


    # ── Block generic pool for item/service queries when shop has items ───────
    intent = detect_intent_v2(message)
    if shop_items and intent in _ITEM_QUERY_INTENTS:
        return None  # go to RAG — generic pool has no shop-specific data



    # FIX 3: food/menu/item/price queries must NOT hit generic pool
    # They either hit shop FAQ (Pass 0) or go straight to RAG — never generic
    intent = detect_intent(message)
    if intent in _FOOD_INTENTS and shop_type in ("restaurant", "bakery", "supermarket", "pharmacy"):
        return None  # force RAG — generic pool has no shop-specific food data

    # Pass 1: intent-filtered semantic
    filtered = _filter_by_intent(combined_pool, intent)
    hit = semantic_match(message, filtered, threshold=SEMANTIC_THRESHOLD)
    if hit:
        hit.setdefault("faq_source", lang_guess)
        hit = _enrich(hit, sentiment, slug)
        return hit

    # Pass 1.5: full-pool semantic
    if filtered is not combined_pool:
        hit = semantic_match(message, combined_pool, threshold=SEMANTIC_THRESHOLD)
        if hit:
            hit.setdefault("faq_source", lang_guess)
            hit = _enrich(hit, sentiment, slug)
            return hit

    # Pass 2.5: fuzzy
    hit = fuzzy_match(message, combined_pool)
    if hit:
        hit.setdefault("faq_source", lang_guess + "_fuzzy")
        hit = _enrich(hit, sentiment, slug)
        return hit

    # Pass 3: F1 token overlap
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
    manglish_words = {
        # Core particles
        "aanu", "alle", "aano", "sheri", "njan", "ningal", "njangal",
        "okke", "kollam", "kittum", "venam", "ippo", "ethra", "evide",
        "engane", "undenkil", "parayuka", "cheyyam", "undo", "ithu",
        "athu", "pinne", "enthu", "entha", "ntha",
        # FIX 4: item/menu/availability — critical for restaurant queries
        "indo", "indoo", "indu", "kittumo", "kittuvo",
        "undoo", "undaa", "undu", "und",
        "enthoke", "enthokke",        # "chicken items enthoke" pattern
        "kazhicho", "kazhikkam",
        "vila", "vilayil",
        "athe", "illa", "illya",
        "hlo", "hoi", "sukhamano",
        "enthada", "enthanu", "varum",
        "paripadi",
    }
    tokens = set(text.lower().split())
    return bool(tokens & manglish_words)


def _dedup(faqs: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    out:  list[dict]           = []
    for f in faqs:
        key = (_get_question(f).lower(), _get_answer(f).lower())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _enrich(faq: dict, sentiment: str, slug: str | None) -> dict:
    """
    FIX G: normalises both "q"/"a" and "question"/"answer" schemas
    into a single "answer" key so chat.py always gets a valid reply.
    """
    faq = dict(faq)

    raw_answer = _get_answer(faq)
    faq["answer"] = resolve_for_slug(raw_answer, slug)

    if "question" not in faq:
        faq["question"] = _get_question(faq)

    # generate_shop.py's schema writes "answer_ml", not "a_ml" -- everything
    # downstream (here and in chat.py) only ever checks "a_ml". Without this
    # bridge, any Manglish content generated via /admin/generate-shop was
    # silently invisible at runtime: present in the data, never served.
    if not faq.get("a_ml") and faq.get("answer_ml"):
        faq["a_ml"] = faq["answer_ml"]

    if faq.get("a_ml"):
        faq["a_ml"] = resolve_for_slug(faq["a_ml"], slug)

    src = faq.get("faq_source", "")
    faq["answer_lang"] = "manglish" if "manglish" in src else "english"

    faq.setdefault("escalate", faq.get("escalate_flag", False))
    faq.setdefault("faq_id",   faq.get("id", ""))

    return faq

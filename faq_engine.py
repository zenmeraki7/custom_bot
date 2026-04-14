
"""
faq_engine.py — FAQ loading, embedding index, and matching
===========================================================
Exported symbols used by chat.py:
  - FAQS_SENTIMENT, FAQS_ENGLISH, FAQS_MANGLISH, FAQS_SHOP
  - SHOP_SENT, SHOP_FLAT
  - FAQ_EMB_VECTORS, FAQ_EMB_TEXTS, FAQ_EMB_META
  - match_faq(query, query_sentiment) → dict | None
  - FAQ_THRESHOLD, SEMANTIC_THRESHOLD, MANGLISH_BOOST

Depends on: nlp.py
"""

import json
import os
from glob import glob
from pathlib import Path

from nlp import (
    embedder,
    f1_score,
    is_manglish,
    normalize,
    tokenize,
    MANGLISH_SIGNALS,
)

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

# Paths to FAQ JSON files – now inside the 'faqs/' subfolder
FAQ_PATH       = "faqs/faqs.json"
ENGLISH_PATH   = "faqs/english.json"
MANGLISH_PATH  = "faqs/manglish.json"
SHOP_FAQ_DIR   = "shop_faqs"

FAQ_THRESHOLD      = 0.35   # F1 fallback threshold
SEMANTIC_THRESHOLD = 0.60   # cosine similarity threshold
MANGLISH_BOOST     = 1.15

# ══════════════════════════════════════════════════════════════════════════════
#  INTENT CLASSIFICATION
# ══════════════════════════════════════════════════════════════════════════════

_INTENT_MAP: dict[str, list[str]] = {
    "payment":     ["payment"],
    "delivery":    ["delivery", "shipping"],
    "return":      ["returns", "refund"],
    "order":       ["ordering", "order_contact_support", "reschedule",
                    "order_reschedule", "post_delivery"],
    "tracking":    ["tracking"],
    "offer":       ["offers", "pricing"],
    "quality":     ["quality", "complaint", "warranty", "damaged_product_complaint"],
    "size":        ["size"],
    "appointment": ["appointment", "appointments_booking"],
    "account":     ["account"],
    "store":       ["store"],
    "support":     ["support", "order_contact_support"],
    "review":      ["review", "post_delivery_review"],
}

_INTENT_KEYWORDS: dict[str, list[str]] = {
    "tracking":    ["track", "tracking", "order status", "order location",
                    "parcel status", "parcel evide", "shipment",
                    "evide aanu ippo", "order evide"],
    "return":      ["return", "refund", "exchange", "money back",
                    "paisa thurik", "wrong product", "thettaya product",
                    "cheyyano return", "return cheyy"],
    "quality":     ["quality", "defective", "damaged", "damage", "complaint",
                    "warranty", "guarantee", "fabric", "material",
                    "stitching", "broken", "torn"],
    "appointment": ["appointment", "book a slot", "schedule visit",
                    "trial room", "fitting room", "store visit"],
    "account":     ["account", "login", "password", "profile", "register",
                    "signup", "otp", "forgot password", "delete account"],
    "review":      ["review", "rating", "write review", "post review",
                    "feedback", "submit review"],
    "payment":     ["payment method", "pay", "upi", "gpay", "phonepay",
                    "paytm", "cod", "cash on delivery", "card payment",
                    "emi", "netbanking", "online payment", "payment options",
                    "payment fail", "payment safe"],
    "delivery":    ["delivery time", "delivery charge", "delivery free",
                    "deliver", "shipping", "days il kittum", "divasam",
                    "express delivery", "same day delivery", "fast delivery",
                    "delivery date", "delivery address"],
    "order":       ["cancel order", "modify order", "place order",
                    "how to order", "order cheyy", "vanganam",
                    "idanam", "buy", "purchase", "cancel cheyyam",
                    "order cancel", "order modify"],
    "offer":       ["offer", "discount", "sale", "coupon", "promo code",
                    "price drop", "kooduthal", "vila", "rate enthu",
                    "cost", "first time", "welcome10"],
    "size":        ["size", "fit", "fitting", "measure", "size chart",
                    "size guide", "small aano", "large aano"],
    "store":       ["shop evide", "store evide", "store location",
                    "shop address", "shop timing", "store hours",
                    "shop open", "store open", "ningalude shop",
                    "where is your store", "where is the shop",
                    "your store", "your shop"],
    "support":     ["contact", "phone number", "whatsapp number",
                    "customer care", "email id", "support team",
                    "call cheyyam", "help line"],
}


def detect_intent(query: str) -> str | None:
    t = query.lower()
    for intent, keywords in _INTENT_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return intent
    return None


def _filter_by_intent(faqs: list[dict], sections: list[str]) -> list[dict]:
    return [
        f for f in faqs
        if f.get("section", f.get("category", "")).lower()
        in [s.lower() for s in sections]
    ]

# ══════════════════════════════════════════════════════════════════════════════
#  FAQ LOADERS
# ══════════════════════════════════════════════════════════════════════════════

def load_sentiment_faqs(path: str) -> list[dict]:
    if not Path(path).exists():
        print(f"[faq_engine] ⚠   {path} not found — skipping")
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    for faq in data:
        faq.setdefault("source", "sentiment_aware")
    print(f"[faq_engine] ✅  faqs.json        — {len(data):>4} sentiment-aware FAQs")
    return data


def load_english_faqs(path: str) -> list[dict]:
    if not Path(path).exists():
        print(f"[faq_engine] ⚠   {path} not found — skipping")
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    flat: list[dict] = []
    seen: set = set()

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            variants = [v.strip() for v in item.get("question_variants", [])
                        if isinstance(v, str) and v.strip()]
            answer   = item.get("answer", "").strip()
            if not variants:
                q = (item.get("question_en") or item.get("question") or "").strip()
                if q:
                    variants = [q]
            if not variants or not answer:
                continue
            key = (variants[0].lower(), answer.lower())
            if key in seen:
                continue
            seen.add(key)
            flat.append({
                "id":       item.get("id", ""),
                "q":        variants[0],
                "variants": variants[1:],
                "a":        answer,
                "section":  item.get("category", "general"),
                "source":   "english",
            })
    elif isinstance(data, dict):
        for section, items in data.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                q = (item.get("question_en") or item.get("question") or "").strip()
                a = (item.get("answer_en")   or item.get("answer")   or "").strip()
                if not q or not a:
                    continue
                key = (q.lower(), a.lower())
                if key in seen:
                    continue
                seen.add(key)
                flat.append({
                    "id":       item.get("id", ""),
                    "q":        q,
                    "variants": [],
                    "a":        a,
                    "section":  section,
                    "source":   "english",
                })

    print(f"[faq_engine] ✅  english.json     — {len(flat):>4} English FAQs")
    return flat


def load_manglish_faqs(path: str) -> list[dict]:
    if not Path(path).exists():
        print(f"[faq_engine] ⚠   {path} not found — skipping")
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []

    flat: list[dict] = []
    seen: set = set()

    for element in data:
        if not isinstance(element, dict):
            continue
        if "question_variants" in element:
            variants = [v.strip() for v in element.get("question_variants", [])
                        if isinstance(v, str) and v.strip()]
            answer   = element.get("answer", "").strip()
            if not variants or not answer:
                continue
            key = (variants[0].lower(), answer.lower())
            if key in seen:
                continue
            seen.add(key)
            flat.append({
                "id":       element.get("id", ""),
                "q":        variants[0],
                "variants": variants[1:],
                "a":        answer,
                "section":  element.get("category", "general"),
                "source":   "manglish",
            })
        else:
            for section, items in element.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    q = item.get("question", "").strip()
                    a = item.get("answer",   "").strip()
                    if not q or not a:
                        continue
                    key = (q.lower(), a.lower())
                    if key in seen:
                        continue
                    seen.add(key)
                    flat.append({
                        "id":       item.get("id", ""),
                        "q":        q,
                        "variants": [],
                        "a":        a,
                        "section":  section,
                        "source":   "manglish",
                    })

    print(f"[faq_engine] ✅  manglish.json    — {len(flat):>4} Manglish FAQs")
    return flat


def load_shop_faqs(shop_dir: str) -> list[dict]:
    if not Path(shop_dir).exists():
        return []
    all_shop: list[dict] = []
    for fpath in sorted(glob(os.path.join(shop_dir, "*.json"))):
        shop_name = Path(fpath).stem
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"[faq_engine] ⚠   {fpath}: {exc}")
            continue
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                if "questions" in item and "answers" in item:
                    item.setdefault("source", f"shop_{shop_name}")
                    item.setdefault("category", shop_name)
                    all_shop.append(item)
                else:
                    q = (item.get("question_en") or item.get("question") or "").strip()
                    a = (item.get("answer_en")   or item.get("answer")   or "").strip()
                    if q and a:
                        all_shop.append({
                            "q": q, "a": a,
                            "source": f"shop_{shop_name}",
                            "section": shop_name,
                        })
        print(f"[faq_engine] ✅  shop_faqs/{shop_name}.json — {len(all_shop)} FAQs (cumulative)")
    return all_shop

# ══════════════════════════════════════════════════════════════════════════════
#  LOAD ALL DATA
# ══════════════════════════════════════════════════════════════════════════════

FAQS_SENTIMENT: list[dict] = load_sentiment_faqs(FAQ_PATH)
FAQS_ENGLISH:   list[dict] = load_english_faqs(ENGLISH_PATH)
FAQS_MANGLISH:  list[dict] = load_manglish_faqs(MANGLISH_PATH)
FAQS_SHOP:      list[dict] = load_shop_faqs(SHOP_FAQ_DIR)

print(f"\n[faq_engine] FAQ pool summary:")
print(f"  ├─ sentiment_aware : {len(FAQS_SENTIMENT)}")
print(f"  ├─ manglish flat   : {len(FAQS_MANGLISH)}")
print(f"  ├─ english flat    : {len(FAQS_ENGLISH)}")
print(f"  └─ shop-specific   : {len(FAQS_SHOP)}")

SHOP_SENT = [f for f in FAQS_SHOP if "questions" in f and "answers" in f]
SHOP_FLAT = [f for f in FAQS_SHOP if "q" in f and "a" in f]

# ══════════════════════════════════════════════════════════════════════════════
#  EMBEDDING INDEX
# ══════════════════════════════════════════════════════════════════════════════

FAQ_EMB_VECTORS = None
FAQ_EMB_TEXTS:  list[str]  = []
FAQ_EMB_META:   list[dict] = []


def build_embeddings() -> None:
    """
    Precompute cosine-ready tensors for every FAQ question + variants.
    Safe no-op if sentence-transformers is not installed.
    """
    global FAQ_EMB_VECTORS, FAQ_EMB_TEXTS, FAQ_EMB_META

    if embedder is None:
        print("[faq_engine] ⚠   Embedder not available — skipping index build")
        return

    texts: list[str] = []
    meta:  list[dict] = []

    for faq in FAQS_SENTIMENT + SHOP_SENT:
        for questions in faq.get("questions", {}).values():
            for q in questions:
                if q and q.strip():
                    texts.append(q.strip())
                    meta.append({"type": "sentiment", "faq": faq})

    for item in FAQS_MANGLISH + FAQS_ENGLISH + SHOP_FLAT:
        q = item.get("q", "").strip()
        if not q:
            continue
        texts.append(q)
        meta.append({"type": "flat", "item": item})
        for variant in item.get("variants", []):
            if variant and variant.strip():
                texts.append(variant.strip())
                meta.append({"type": "flat", "item": item})

    if not texts:
        print("[faq_engine] ⚠   No FAQ texts — embedding index empty")
        return

    print(f"[faq_engine] Building embedding index for {len(texts)} entries…")
    FAQ_EMB_VECTORS = embedder.encode(
        texts,
        convert_to_tensor=True,
        show_progress_bar=False,
        batch_size=64,
    )
    FAQ_EMB_TEXTS = texts
    FAQ_EMB_META  = meta
    print(f"[faq_engine] ✅  Index ready — {FAQ_EMB_VECTORS.shape[0]} vectors, dim={FAQ_EMB_VECTORS.shape[1]}")


build_embeddings()

# ══════════════════════════════════════════════════════════════════════════════
#  CORE MATCHING
# ══════════════════════════════════════════════════════════════════════════════

def pick_answer(answers: dict, query_sentiment: str) -> tuple[str, str]:
    for key in (query_sentiment, "neutral"):
        if key in answers:
            return answers[key], key
    first_key = next(iter(answers))
    return answers[first_key], first_key


def semantic_match(query: str, query_sentiment: str) -> dict | None:
    if FAQ_EMB_VECTORS is None or embedder is None:
        return None

    from sentence_transformers import util as st_util

    query_emb    = embedder.encode(query, convert_to_tensor=True)
    scores       = st_util.cos_sim(query_emb, FAQ_EMB_VECTORS)[0]
    sorted_scores = sorted(scores.tolist(), reverse=True)
    best_score   = sorted_scores[0]
    second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0.0

    CONFIDENCE_GAP = 0.08
    if best_score < SEMANTIC_THRESHOLD or (best_score - second_score) < CONFIDENCE_GAP:
        return None

    best_idx = int(scores.argmax())
    entry    = FAQ_EMB_META[best_idx]

    if entry["type"] == "sentiment":
        faq      = entry["faq"]
        answer, _ = pick_answer(faq["answers"], query_sentiment)
        norm      = normalize(query)
        esc_kw    = faq.get("escalate_if", {}).get("keywords", [])
        escalate  = bool(esc_kw and any(kw.lower() in norm for kw in esc_kw))
        return {
            "faq_id":      faq.get("id", ""),
            "category":    faq.get("category", "general"),
            "faq_source":  faq.get("source", "sentiment_aware"),
            "answer":      answer,
            "answer_lang": "english",
            "score":       round(best_score, 3),
            "escalate":    escalate,
        }
    else:
        item = entry["item"]
        return {
            "faq_id":      "",
            "category":    item.get("section", "general"),
            "faq_source":  item.get("source", ""),
            "answer":      item["a"],
            "answer_lang": item.get("source", "english"),
            "score":       round(best_score, 3),
            "escalate":    False,
        }


def match_faq(query: str, query_sentiment: str) -> dict | None:
    """
    FAQ matching pipeline:
      Pass 0 — Intent detection (narrow pool by category)
      Pass 1 — Semantic cosine match (threshold 0.60 + gap 0.08)
      Pass 2 — F1 token overlap fallback (threshold 0.35)
    """
    intent   = detect_intent(query)
    sections = _INTENT_MAP.get(intent, []) if intent else []

    ml_filtered = _filter_by_intent(FAQS_MANGLISH, sections) if sections else []
    en_filtered = _filter_by_intent(FAQS_ENGLISH,  sections) if sections else []

    # Pass 1: semantic
    sem = semantic_match(query, query_sentiment)
    if sem:
        return sem

    # Pass 2: F1 fallback
    norm     = normalize(query)
    q_tokens = tokenize(norm)
    manglish = is_manglish(query)

    best_score      = -1.0
    best_n_variants = 0
    best_result: dict | None = None

    def _update(score: float, candidate: dict, n_variants: int = 1) -> None:
        nonlocal best_score, best_n_variants, best_result
        if score > best_score or (score == best_score and n_variants > best_n_variants):
            best_score      = score
            best_n_variants = n_variants
            best_result     = candidate

    # Sentiment-aware FAQs
    for faq in FAQS_SENTIMENT + SHOP_SENT:
        _faq_n = sum(len(qs) for qs in faq.get("questions", {}).values())
        for sent_key, questions in faq.get("questions", {}).items():
            for q_text in questions:
                score = f1_score(q_tokens, q_text)
                if score > 0:
                    answer, _ = pick_answer(faq["answers"], query_sentiment)
                    esc_kw    = faq.get("escalate_if", {}).get("keywords", [])
                    escalate  = bool(esc_kw and any(kw.lower() in norm for kw in esc_kw))
                    _update(score, {
                        "faq_id":      faq.get("id", ""),
                        "category":    faq.get("category", "general"),
                        "faq_source":  faq.get("source", "sentiment_aware"),
                        "answer":      answer,
                        "answer_lang": "english",
                        "score":       score,
                        "escalate":    escalate,
                    }, n_variants=_faq_n)

    # Manglish FAQs (intent-filtered pool first)
    manglish_pool = ml_filtered + [
        f for f in FAQS_MANGLISH + SHOP_FLAT
        if f not in ml_filtered
        and (f.get("source", "") in ("manglish",) or "shop" in f.get("source", ""))
    ]
    for item in manglish_pool:
        if item.get("source", "") not in ("manglish",) and "shop" not in item.get("source", ""):
            continue
        all_qs = [item["q"]] + item.get("variants", [])
        raw    = max(f1_score(q_tokens, q) for q in all_qs)
        score  = raw * MANGLISH_BOOST if manglish else raw
        _update(score, {
            "faq_id":      item.get("id", ""),
            "category":    item.get("section", "general"),
            "faq_source":  item["source"],
            "answer":      item["a"],
            "answer_lang": "manglish",
            "score":       score,
            "escalate":    False,
        }, n_variants=len(all_qs))

    # English FAQs (intent-filtered pool first)
    english_pool = en_filtered + [f for f in FAQS_ENGLISH if f not in en_filtered]
    for item in english_pool:
        all_qs = [item["q"]] + item.get("variants", [])
        score  = max(f1_score(q_tokens, q) for q in all_qs)
        _update(score, {
            "faq_id":      item.get("id", ""),
            "category":    item.get("section", "general"),
            "faq_source":  "english",
            "answer":      item["a"],
            "answer_lang": "english",
            "score":       score,
            "escalate":    False,
        }, n_variants=len(all_qs))

    if best_score < FAQ_THRESHOLD or best_result is None:
        return None

    best_result["score"] = round(best_score, 3)
    return best_result 
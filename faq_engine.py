# # """
# # faq_engine.py — FAQ loading, embedding index, and matching
# # ===========================================================
# # Exported symbols used by chat.py:
# #   - FAQS_SENTIMENT, FAQS_ENGLISH, FAQS_MANGLISH, FAQS_SHOP
# #   - FAQS_ENGLISH_SENTIMENT, FAQS_MANGLISH_SENTIMENT
# #   - SHOP_SENT, SHOP_FLAT
# #   - FAQ_EMB_VECTORS, FAQ_EMB_TEXTS, FAQ_EMB_META
# #   - match_faq(query, query_sentiment) → dict | None
# #   - FAQ_THRESHOLD, SEMANTIC_THRESHOLD, MANGLISH_BOOST

# # Depends on: nlp.py

# # v5.2 → v5.3 fixes:
# #   1. _INTENT_KEYWORDS["return"]: added Manglish paripadi/niyamam variants
# #      so "nthanu paripadi" → intent="return" → filters to return FAQ pool
# #   2. fuzzy_pass(): answer_lang detection hardened — explicitly checks
# #      item["source"].startswith("manglish") rather than trusting the lang var
# #   3. match_faq(): when fuzzy returns English for a Manglish query, it now
# #      falls ALL the way through to F1 before returning the English fuzzy result.
# #      Previously it returned the English fuzzy result immediately, forcing a
# #      slow Ollama rephrase. F1 may find a native Manglish answer instead.
# #   4. match_faq() final fallback priority:
# #        native Manglish F1 > semantic English > fuzzy English > Ollama
# #      ensures cheapest path that still produces natural Manglish output.
# # """

# # import json
# # import os
# # import pickle
# # from glob import glob
# # from pathlib import Path

# # from nlp import (
# #     embedder,
# #     expand_synonyms,
# #     f1_score,
# #     fuzzy_match,
# #     is_manglish,
# #     normalize,
# #     tokenize,
# #     MANGLISH_SIGNALS,
# # )

# # # ══════════════════════════════════════════════════════════════════════════════
# # #  SHOP CONFIG PLACEHOLDER RESOLVER
# # #  Resolves {whatsapp}, {email}, {location} etc. in FAQ answers at load time.
# # #  Generic FAQs stay generic — the actual values come from shop_config.json.
# # # ══════════════════════════════════════════════════════════════════════════════

# # def _load_placeholder_map() -> dict:
# #     """Build placeholder map from shop_config.json."""
# #     try:
# #         with open("shop_config.json", "r", encoding="utf-8") as f:
# #             cfg = json.load(f)
# #     except FileNotFoundError:
# #         return {}
# #     h     = cfg.get("hours", {})
# #     c     = cfg.get("contact", {})
# #     d     = cfg.get("delivery", {})
# #     r     = cfg.get("returns", {})
# #     offer = cfg.get("first_offer", {})
# #     return {
# #         "whatsapp":         c.get("whatsapp", ""),
# #         "phone":            c.get("phone", ""),
# #         "email":            c.get("email", ""),
# #         "hours_weekdays":   h.get("weekdays", ""),
# #         "hours_sunday":     "" if h.get("sunday","") == h.get("weekdays","") else h.get("sunday",""),
# #         "hours_holiday":    h.get("holiday", ""),
# #         "location":         cfg.get("location", ""),
# #         "city":             cfg.get("city", ""),
# #         "delivery_areas":   d.get("areas", ""),
# #         "delivery_free":    d.get("free_above", ""),
# #         "delivery_days":    d.get("days", ""),
# #         "return_days":      str(r.get("days", 7)),
# #         "return_condition": r.get("condition", ""),
# #         "refund_days":      r.get("refund_days", ""),
# #         "offer_code":       offer.get("code", ""),
# #         "offer_desc":       offer.get("description", ""),
# #         "shop_name":        cfg.get("shop_name", ""),
# #         "bot_name":         cfg.get("bot_name", ""),
# #     }

# # _PLACEHOLDER_MAP: dict = _load_placeholder_map()

# # def resolve(text: str) -> str:
# #     """Replace {placeholders} in FAQ answers with values from shop_config.json."""
# #     if not _PLACEHOLDER_MAP or '{' not in text:
# #         return text
# #     try:
# #         return text.format_map(_PLACEHOLDER_MAP)
# #     except (KeyError, ValueError):
# #         return text  # return as-is if unknown placeholder

# # def reload_placeholders() -> None:
# #     """Hot-reload placeholder map when shop_config.json changes."""
# #     global _PLACEHOLDER_MAP
# #     _PLACEHOLDER_MAP = _load_placeholder_map()
# #     print(f"[faq_engine] ✅  Placeholder map reloaded — shop={_PLACEHOLDER_MAP.get('shop_name','?')}")

# # # ══════════════════════════════════════════════════════════════════════════════
# # #  CONFIG
# # # ══════════════════════════════════════════════════════════════════════════════

# # FAQ_PATH                = "faqs/faq.json"
# # ENGLISH_PATH            = "faqs/english.json"
# # MANGLISH_PATH           = "faqs/manglish.json"
# # SHOP_FAQ_PATH           = "faqs/shop_faq.json"   # single file — shop uploads this
# # ENGLISH_SENTIMENT_PATH  = "faqs/english_sentiment.json"
# # MANGLISH_SENTIMENT_PATH = "faqs/manglish_sentiment.json"

# # FAQ_THRESHOLD      = 0.30   # F1 fallback threshold
# # SEMANTIC_THRESHOLD = 0.52   # cosine similarity threshold
# # MANGLISH_BOOST     = 1.15   # F1 score multiplier for manglish queries on manglish FAQs
# # FUZZY_THRESHOLD    = 0.72   # rapidfuzz token_set_ratio threshold (0–1)

# # _MANGLISH_PARTICLES = {
# #     "kittum", "kittiyilla", "cheyyam", "cheyyano", "cheyyuka", "cheythu",
# #     "aanu", "alle", "aano", "undo", "undu", "okke", "ippo", "ethra",
# #     "evide", "enthu", "engane", "njan", "njangal", "ningal", "avarkku",
# #     "polum", "venam", "venda", "pattumo", "tharaamo", "undenkil",
# #     "allenkil", "nokam", "nokkanam", "sheri", "kollam", "adipoli",
# #     "mosham", "ano", "ithu", "athu", "ente", "eppo", "pinne",
# # }

# # # ══════════════════════════════════════════════════════════════════════════════
# # #  INTENT CLASSIFICATION
# # # ══════════════════════════════════════════════════════════════════════════════

# # _INTENT_MAP: dict[str, list[str]] = {
# #     "menu":        ["menu", "food", "dish", "ordering", "shop"],
# #     "payment":     ["payment"],
# #     "delivery":    ["delivery", "shipping"],
# #     "return":      ["returns", "refund"],
# #     "order":       ["ordering", "order_contact_support", "reschedule",
# #                     "order_reschedule", "post_delivery"],
# #     "tracking":    ["tracking"],
# #     "offer":       ["offers", "pricing"],
# #     "quality":     ["quality", "complaint", "warranty", "damaged_product_complaint"],
# #     "size":        ["size"],
# #     "appointment": ["appointment", "appointments_booking"],
# #     "account":     ["account"],
# #     "store":       ["store"],
# #     "support":     ["support", "order_contact_support"],
# #     "review":      ["review", "post_delivery_review"],
# # }

# # _INTENT_KEYWORDS: dict[str, list[str]] = {
# #     "tracking":    ["track", "tracking", "order status", "order location",
# #                     "parcel status", "parcel evide", "shipment",
# #                     "evide aanu ippo", "order evide"],
# #     "return":      [
# #         # English
# #         "return", "refund", "exchange", "money back",
# #         "return policy", "return rule", "return niyamam",
# #         # Manglish — FIX v5.3: added paripadi/niyamam variants
# #         "paripadi", "niyamam", "return paripadi", "nthanu paripadi",
# #         "enthu paripadi", "return niyamam", "enthu niyamam",
# #         "paisa thurik", "wrong product", "thettaya product",
# #         "cheyyano return", "return cheyy",
# #         "ethra naal", "7 days", "7 naal",
# #     ],
# #     "quality":     ["quality", "defective", "damaged", "damage",
# #                     "complaint", "complient", "complain",
# #                     "warranty", "guarantee", "fabric", "material",
# #                     "stitching", "broken", "torn", "ripped", "faded",
# #                     "shrunk", "smell", "colour", "color"],
# #     "appointment": ["appointment", "book a slot", "schedule visit",
# #                     "trial room", "fitting room", "store visit",
# #                     # FIX: "session", "book" were not matched
# #                     "session", "book", "booking", "book appointment",
# #                     "book session", "slot", "visit", "schedule",
# #                     "book for", "how to book"],
# #     "account":     ["account", "login", "password", "profile", "register",
# #                     "signup", "otp", "forgot password", "delete account"],
# #     "review":      ["review", "rating", "write review", "post review",
# #                     "feedback", "submit review"],
# #     "payment":     ["payment method", "pay", "upi", "gpay", "phonepay", "phonepe",
# #                     "paytm", "cod", "cash on delivery", "card payment",
# #                     "emi", "netbanking", "online payment", "payment options",
# #                     "payment fail", "payment safe", "charged", "billed"],
# #     "delivery":    ["delivery time", "delivery charge", "delivery free",
# #                     "deliver", "shipping", "days il kittum", "divasam",
# #                     "express delivery", "same day delivery", "fast delivery",
# #                     "delivery date", "delivery address", "package", "parcel",
# #                     "kittiyilla", "arrived", "received"],
# #     "order":       ["cancel order", "modify order", "place order",
# #                     "how to order", "order cheyy", "vanganam",
# #                     "idanam", "buy", "purchase", "cancel cheyyam",
# #                     "order cancel", "order modify"],
# #     "offer":       ["offer", "discount", "sale", "coupon", "promo code",
# #                     "price drop", "kooduthal", "vila", "rate enthu",
# #                     "cost", "first time", "welcome10"],
# #     "size":        ["size", "fit", "fitting", "measure", "size chart",
# #                     "size guide", "small aano", "large aano",
# #                     "tight", "loose", "shrunk"],
# #     "menu":        [
# #         "enthoke", "ullath", "kazhikkan", "enthund", "enthoke ind",
# #         "entha ullath", "enthu ullath", "menu", "food", "dish", "dishes",
# #         "items", "meals", "veg", "nonveg", "special", "available",
# #         "what do you have", "what do you serve", "what is available",
# #     ],
# #     "store":       [
# #         # English
# #         "shop location", "store location", "store address",
# #         "shop address", "shop timing", "store hours",
# #         "shop open", "store open", "where is your store",
# #         "where is the shop", "your store", "your shop",
# #         # Holiday / open status — FIX: was routing to delivery
# #         "holiday", "open tomorrow", "open today", "open on",
# #         "open sunday", "open saturday", "closed", "working hours",
# #         "what time", "opening time", "closing time",
# #         # FIX: bare "open hours" and "hours" variants not matching
# #         "open hours", "store open hours", "shop hours",
# #         "opening hours", "business hours", "open now",
# #         "are you open", "when do you open", "when do you close",
# #         "what time do you open", "what time do you close",
# #         "open time", "close time", "hours of operation",
# #         # Manglish variants
# #         "shop evide", "store evide", "ningalude shop",
# #         "evideya shop", "evideya store", "shopinte sthalam",
# #         "store sthalam", "shop sthalam",
# #         "evide aanu shop", "evide aanu store",
# #         "shop address enthu", "store address enthu",
# #         "shop evide aanu", "store evide aanu",
# #         "ningalude store evide", "ningalude shop evide",
# #         "location enthu", "ningal evide",
# #         "shop ethu neram", "shop open aano", "shop close aano",
# #         "holiday il open", "holiday il shop",
# #     ],
# #     "support":     [
# #         "complaint", "complient", "complain",
# #         "complaint kodukkum", "complaint cheyyam",
# #         "issue parayam", "problem parayam", "contact",
# #         "phone number", "whatsapp number",
# #         "customer care", "email id", "support team",
# #         "call cheyyam", "help line",
# #         # Manglish number variants
# #         "number undo", "number enthu", "number aanu",
# #         "number tharamo", "contact number",
# #         "whatsapp number undo", "phone number undo",
# #         "call cheyyaan number",
# #         "ningalude number", "shop number",
# #         "contact cheyyaan", "contact engane",
# #     ],
# # }


# # def detect_intent(query: str) -> str | None:
# #     t = query.lower()
# #     for intent, keywords in _INTENT_KEYWORDS.items():
# #         if any(kw in t for kw in keywords):
# #             return intent
# #     return None


# # def _filter_by_intent(faqs: list[dict], sections: list[str]) -> list[dict]:
# #     return [
# #         f for f in faqs
# #         if f.get("section", f.get("category", "")).lower()
# #         in [s.lower() for s in sections]
# #     ]

# # # ══════════════════════════════════════════════════════════════════════════════
# # #  FAQ LOADERS
# # # ══════════════════════════════════════════════════════════════════════════════

# # def load_sentiment_faqs(path: str) -> list[dict]:
# #     if not Path(path).exists():
# #         print(f"[faq_engine] ⚠   {path} not found — skipping")
# #         return []
# #     with open(path, "r", encoding="utf-8") as f:
# #         data = json.load(f)
# #     if not isinstance(data, list):
# #         return []
# #     for faq in data:
# #         faq.setdefault("source", "sentiment_aware")
# #     print(f"[faq_engine] ✅  faq.json            — {len(data):>4} sentiment-aware FAQs")
# #     return data


# # def load_english_faqs(path: str) -> list[dict]:
# #     if not Path(path).exists():
# #         print(f"[faq_engine] ⚠   {path} not found — skipping")
# #         return []
# #     with open(path, "r", encoding="utf-8") as f:
# #         data = json.load(f)

# #     flat: list[dict] = []
# #     seen: set = set()

# #     if isinstance(data, list):
# #         for item in data:
# #             if not isinstance(item, dict):
# #                 continue
# #             variants = [v.strip() for v in item.get("question_variants", [])
# #                         if isinstance(v, str) and v.strip()]
# #             answer   = item.get("answer", "").strip()
# #             if not variants:
# #                 q = (item.get("question_en") or item.get("question") or "").strip()
# #                 if q:
# #                     variants = [q]
# #             if not variants or not answer:
# #                 continue
# #             key = (variants[0].lower(), answer.lower())
# #             if key in seen:
# #                 continue
# #             seen.add(key)
# #             flat.append({
# #                 "id":       item.get("id", ""),
# #                 "q":        variants[0],
# #                 "variants": variants[1:],
# #                 "a":        resolve(answer),
# #                 "section":  item.get("category", "general"),
# #                 "source":   "english",
# #             })
# #     elif isinstance(data, dict):
# #         for section, items in data.items():
# #             if not isinstance(items, list):
# #                 continue
# #             for item in items:
# #                 if not isinstance(item, dict):
# #                     continue
# #                 q = (item.get("question_en") or item.get("question") or "").strip()
# #                 a = (item.get("answer_en")   or item.get("answer")   or "").strip()
# #                 if not q or not a:
# #                     continue
# #                 key = (q.lower(), a.lower())
# #                 if key in seen:
# #                     continue
# #                 seen.add(key)
# #                 flat.append({
# #                     "id":       item.get("id", ""),
# #                     "q":        q,
# #                     "variants": [],
# #                     "a":        a,
# #                     "section":  section,
# #                     "source":   "english",
# #                 })

# #     print(f"[faq_engine] ✅  english.json        — {len(flat):>4} English FAQs")
# #     return flat


# # def load_manglish_faqs(path: str) -> list[dict]:
# #     if not Path(path).exists():
# #         print(f"[faq_engine] ⚠   {path} not found — skipping")
# #         return []
# #     with open(path, "r", encoding="utf-8") as f:
# #         data = json.load(f)
# #     if not isinstance(data, list):
# #         return []

# #     flat: list[dict] = []
# #     seen: set = set()

# #     for element in data:
# #         if not isinstance(element, dict):
# #             continue
# #         if "question_variants" in element:
# #             variants = [v.strip() for v in element.get("question_variants", [])
# #                         if isinstance(v, str) and v.strip()]
# #             answer   = element.get("answer", "").strip()
# #             if not variants or not answer:
# #                 continue
# #             key = (variants[0].lower(), answer.lower())
# #             if key in seen:
# #                 continue
# #             seen.add(key)
# #             flat.append({
# #                 "id":       element.get("id", ""),
# #                 "q":        variants[0],
# #                 "variants": variants[1:],
# #                 "a":        resolve(answer),
# #                 "section":  element.get("category", "general"),
# #                 "source":   "manglish",
# #             })
# #         else:
# #             for section, items in element.items():
# #                 if not isinstance(items, list):
# #                     continue
# #                 for item in items:
# #                     if not isinstance(item, dict):
# #                         continue
# #                     q = item.get("question", "").strip()
# #                     a = item.get("answer",   "").strip()
# #                     if not q or not a:
# #                         continue
# #                     key = (q.lower(), a.lower())
# #                     if key in seen:
# #                         continue
# #                     seen.add(key)
# #                     flat.append({
# #                         "id":       item.get("id", ""),
# #                         "q":        q,
# #                         "variants": [],
# #                         "a":        a,
# #                         "section":  section,
# #                         "source":   "manglish",
# #                     })

# #     print(f"[faq_engine] ✅  manglish.json       — {len(flat):>4} Manglish FAQs")
# #     return flat


# # def load_english_sentiment_faqs(path: str) -> list[dict]:
# #     if not Path(path).exists():
# #         print(f"[faq_engine] ⚠   {path} not found — skipping")
# #         return []
# #     with open(path, "r", encoding="utf-8") as f:
# #         data = json.load(f)
# #     if not isinstance(data, list):
# #         return []

# #     flat: list[dict] = []
# #     seen: set = set()
# #     skipped = 0

# #     for item in data:
# #         if not isinstance(item, dict):
# #             continue
# #         variants = [v.strip() for v in item.get("question_variants", [])
# #                     if isinstance(v, str) and v.strip()]
# #         answer   = item.get("answer", "").strip()
# #         if not variants or not answer:
# #             skipped += 1
# #             continue
# #         key = (variants[0].lower(), answer.lower())
# #         if key in seen:
# #             continue
# #         seen.add(key)
# #         flat.append({
# #             "id":       item.get("id", ""),
# #             "q":        variants[0],
# #             "variants": variants[1:],
# #             "a":        resolve(answer),
# #             "section":  item.get("category", "general"),
# #             "source":   "english_sentiment",
# #         })

# #     print(f"[faq_engine] ✅  english_sentiment   — {len(flat):>4} FAQs "
# #           f"(skipped {skipped} empty-answer rows)")
# #     return flat


# # def load_manglish_sentiment_faqs(path: str) -> list[dict]:
# #     if not Path(path).exists():
# #         print(f"[faq_engine] ⚠   {path} not found — skipping")
# #         return []
# #     with open(path, "r", encoding="utf-8") as f:
# #         data = json.load(f)
# #     if not isinstance(data, list):
# #         return []

# #     flat: list[dict] = []
# #     seen: set = set()

# #     for item in data:
# #         if not isinstance(item, dict):
# #             continue
# #         variants = [v.strip() for v in item.get("question_variants", [])
# #                     if isinstance(v, str) and v.strip()]
# #         answer   = item.get("answer", "").strip()
# #         if not variants or not answer:
# #             continue
# #         key = (variants[0].lower(), answer.lower())
# #         if key in seen:
# #             continue
# #         seen.add(key)
# #         flat.append({
# #             "id":       item.get("id", ""),
# #             "q":        variants[0],
# #             "variants": variants[1:],
# #             "a":        resolve(answer),
# #             "section":  item.get("category", "general"),
# #             "source":   "manglish_sentiment",
# #         })

# #     print(f"[faq_engine] ✅  manglish_sentiment  — {len(flat):>4} FAQs")
# #     return flat


# # def load_shop_faqs(path: str) -> list[dict]:
# #     """
# #     Load shop-specific FAQs from faqs/shop_faq.json.
# #     This is the ONLY file shops need to upload.
# #     All other FAQs (english.json, manglish.json, sentiments) are generic and stay unchanged.
# #     """
# #     if not Path(path).exists():
# #         print(f"[faq_engine] ℹ   {path} not found — no shop FAQs (OK)")
# #         return []
# #     try:
# #         with open(path, "r", encoding="utf-8") as f:
# #             data = json.load(f)
# #     except Exception as exc:
# #         print(f"[faq_engine] ⚠   {path}: {exc}")
# #         return []
# #     if not isinstance(data, list):
# #         print(f"[faq_engine] ⚠   {path}: must be a JSON array")
# #         return []

# #     flat: list[dict] = []
# #     seen: set = set()
# #     for item in data:
# #         if not isinstance(item, dict):
# #             continue
# #         if "question_variants" in item:
# #             variants = [v.strip() for v in item.get("question_variants", []) if isinstance(v, str) and v.strip()]
# #             answer   = item.get("answer", "").strip()
# #             if not variants or not answer:
# #                 continue
# #             key = (variants[0].lower(), answer.lower())
# #             if key in seen:
# #                 continue
# #             seen.add(key)
# #             flat.append({
# #                 "id":       item.get("id", ""),
# #                 "q":        variants[0],
# #                 "variants": variants[1:],
# #                 "a":        resolve(answer),
# #                 "section":  item.get("category", "shop"),
# #                 "source":   "shop_faq",
# #                 "lang":     item.get("lang", "english"),
# #             })
# #         elif "question" in item or "q" in item:
# #             q = (item.get("question") or item.get("q") or "").strip()
# #             a = (item.get("answer")   or item.get("a")   or "").strip()
# #             if not q or not a:
# #                 continue
# #             key = (q.lower(), a.lower())
# #             if key in seen:
# #                 continue
# #             seen.add(key)
# #             flat.append({
# #                 "id":       item.get("id", ""),
# #                 "q":        q,
# #                 "variants": [],
# #                 "a":        resolve(a),
# #                 "section":  item.get("category", "shop"),
# #                 "source":   "shop_faq",
# #                 "lang":     item.get("lang", "english"),
# #             })

# #     print(f"[faq_engine] ✅  shop_faq.json      — {len(flat):>4} shop FAQs")
# #     return flat

# # # ══════════════════════════════════════════════════════════════════════════════
# # #  LOAD ALL DATA
# # # ══════════════════════════════════════════════════════════════════════════════

# # FAQS_SENTIMENT:          list[dict] = load_sentiment_faqs(FAQ_PATH)
# # FAQS_ENGLISH:            list[dict] = load_english_faqs(ENGLISH_PATH)
# # FAQS_ENGLISH_SENTIMENT:  list[dict] = load_english_sentiment_faqs(ENGLISH_SENTIMENT_PATH)
# # FAQS_MANGLISH:           list[dict] = load_manglish_faqs(MANGLISH_PATH)
# # FAQS_MANGLISH_SENTIMENT: list[dict] = load_manglish_sentiment_faqs(MANGLISH_SENTIMENT_PATH)
# # FAQS_SHOP:               list[dict] = load_shop_faqs(SHOP_FAQ_PATH)

# # print(f"\n[faq_engine] FAQ pool summary:")
# # print(f"  ├─ sentiment_aware      : {len(FAQS_SENTIMENT)}")
# # print(f"  ├─ english flat         : {len(FAQS_ENGLISH)}")
# # print(f"  ├─ english_sentiment    : {len(FAQS_ENGLISH_SENTIMENT)}")
# # print(f"  ├─ manglish flat        : {len(FAQS_MANGLISH)}")
# # print(f"  ├─ manglish_sentiment   : {len(FAQS_MANGLISH_SENTIMENT)}")
# # print(f"  └─ shop-specific        : {len(FAQS_SHOP)}")

# # SHOP_SENT = [f for f in FAQS_SHOP if "questions" in f and "answers" in f]
# # SHOP_FLAT = [f for f in FAQS_SHOP if "q" in f and "a" in f]

# # # ══════════════════════════════════════════════════════════════════════════════
# # #  EMBEDDING INDEX
# # # ══════════════════════════════════════════════════════════════════════════════

# # FAQ_EMB_VECTORS = None
# # FAQ_EMB_TEXTS:  list[str]  = []
# # FAQ_EMB_META:   list[dict] = []
# # FAQ_EMB_INTENT_SLICES: dict[str, list[int]] = {}

# # # Shop FAQ precomputed embeddings (Pass 0 priority check)
# # SHOP_EMB_VECTORS = None
# # SHOP_EMB_META:  list[dict] = []


# # def _item_intent(item: dict) -> str | None:
# #     section = item.get("section", item.get("category", "")).lower()
# #     for intent, sections in _INTENT_MAP.items():
# #         if section in [s.lower() for s in sections]:
# #             return intent
# #     return None


# # CACHE_PATH = "faq_embeddings_cache.pkl"


# # def _cache_checksum() -> str:
# #     """Generate a checksum based on FAQ counts — if counts change, cache is invalid."""
# #     import hashlib
# #     counts = (
# #         len(FAQS_SENTIMENT), len(FAQS_ENGLISH), len(FAQS_ENGLISH_SENTIMENT),
# #         len(FAQS_MANGLISH), len(FAQS_MANGLISH_SENTIMENT), len(SHOP_FLAT), len(SHOP_SENT)
# #     )
# #     return hashlib.md5(str(counts).encode()).hexdigest()


# # def build_embeddings() -> None:
# #     global FAQ_EMB_VECTORS, FAQ_EMB_TEXTS, FAQ_EMB_META, FAQ_EMB_INTENT_SLICES
# #     if embedder is None:
# #         print("[faq_engine] ⚠   Embedder not available — skipping index build")
# #         return

# #     # ── Try loading from cache ──────────────────────────────────────────────
# #     current_checksum = _cache_checksum()
# #     if Path(CACHE_PATH).exists():
# #         try:
# #             with open(CACHE_PATH, "rb") as f:
# #                 cache = pickle.load(f)
# #             if cache.get("checksum") == current_checksum:
# #                 FAQ_EMB_VECTORS        = cache["vectors"]
# #                 FAQ_EMB_TEXTS          = cache["texts"]
# #                 FAQ_EMB_META           = cache["meta"]
# #                 FAQ_EMB_INTENT_SLICES  = cache["intent_slices"]
# #                 print(f"[faq_engine] ✅  Loaded embedding cache — "
# #                       f"{FAQ_EMB_VECTORS.shape[0]} vectors (skipped recompute)")
# #                 print(f"[faq_engine] ✅  Intent slices: "
# #                       + ", ".join(f"{k}={len(v)}" for k, v in FAQ_EMB_INTENT_SLICES.items()))
# #                 return
# #             else:
# #                 print("[faq_engine] ℹ   FAQ data changed — rebuilding embedding cache…")
# #         except Exception as e:
# #             print(f"[faq_engine] ⚠   Cache load failed ({e}) — rebuilding…")

# #     # ── Build from scratch ──────────────────────────────────────────────────
# #     texts: list[str] = []
# #     meta:  list[dict] = []

# #     for faq in FAQS_SENTIMENT + SHOP_SENT:
# #         for questions in faq.get("questions", {}).values():
# #             for q in questions:
# #                 if q and q.strip():
# #                     texts.append(q.strip())
# #                     meta.append({"type": "sentiment", "faq": faq, "intent": None})

# #     for item in (FAQS_MANGLISH + FAQS_MANGLISH_SENTIMENT
# #                  + FAQS_ENGLISH + FAQS_ENGLISH_SENTIMENT
# #                  + SHOP_FLAT):
# #         q = item.get("q", "").strip()
# #         if not q:
# #             continue
# #         intent = _item_intent(item)
# #         idx = len(texts)
# #         texts.append(q)
# #         meta.append({"type": "flat", "item": item, "intent": intent})

# #         if intent:
# #             FAQ_EMB_INTENT_SLICES.setdefault(intent, []).append(idx)

# #         for variant in item.get("variants", []):
# #             if variant and variant.strip():
# #                 vidx = len(texts)
# #                 texts.append(variant.strip())
# #                 meta.append({"type": "flat", "item": item, "intent": intent})
# #                 if intent:
# #                     FAQ_EMB_INTENT_SLICES.setdefault(intent, []).append(vidx)

# #     if not texts:
# #         print("[faq_engine] ⚠   No FAQ texts — embedding index empty")
# #         return

# #     print(f"[faq_engine] Building embedding index for {len(texts)} entries…")
# #     FAQ_EMB_VECTORS = embedder.encode(
# #         texts,
# #         convert_to_tensor=True,
# #         show_progress_bar=False,
# #         batch_size=64,
# #     )
# #     FAQ_EMB_TEXTS = texts
# #     FAQ_EMB_META  = meta
# #     print(f"[faq_engine] ✅  Index ready — {FAQ_EMB_VECTORS.shape[0]} vectors, "
# #           f"dim={FAQ_EMB_VECTORS.shape[1]}")
# #     print(f"[faq_engine] ✅  Intent slices: "
# #           + ", ".join(f"{k}={len(v)}" for k, v in FAQ_EMB_INTENT_SLICES.items()))

# #     # ── Save cache ──────────────────────────────────────────────────────────
# #     try:
# #         with open(CACHE_PATH, "wb") as f:
# #             pickle.dump({
# #                 "checksum":     current_checksum,
# #                 "vectors":      FAQ_EMB_VECTORS,
# #                 "texts":        FAQ_EMB_TEXTS,
# #                 "meta":         FAQ_EMB_META,
# #                 "intent_slices":FAQ_EMB_INTENT_SLICES,
# #             }, f)
# #         print(f"[faq_engine] ✅  Embedding cache saved → {CACHE_PATH}")
# #     except Exception as e:
# #         print(f"[faq_engine] ⚠   Cache save failed: {e}")


# # build_embeddings()


# # def build_shop_embeddings() -> None:
# #     """
# #     Precompute embeddings for shop_faq.json — primary questions + all variants.
# #     Called once at startup and after shop_faq reload.
# #     Stored in SHOP_EMB_VECTORS / SHOP_EMB_META for Pass 0 priority matching.
# #     """
# #     global SHOP_EMB_VECTORS, SHOP_EMB_META
# #     if not SHOP_FLAT or embedder is None:
# #         SHOP_EMB_VECTORS = None
# #         SHOP_EMB_META    = []
# #         return
# #     texts: list[str]  = []
# #     meta:  list[dict] = []
# #     for item in SHOP_FLAT:
# #         q = item.get("q", "").strip()
# #         if q:
# #             texts.append(q)
# #             meta.append(item)
# #         for v in item.get("variants", []):
# #             if v and v.strip():
# #                 texts.append(v.strip())
# #                 meta.append(item)
# #     if not texts:
# #         return
# #     SHOP_EMB_VECTORS = embedder.encode(
# #         texts,
# #         convert_to_tensor=True,
# #         normalize_embeddings=True,
# #         show_progress_bar=False,
# #         batch_size=64,
# #     )
# #     SHOP_EMB_META = meta
# #     print(f"[faq_engine] ✅  Shop FAQ embeddings — {len(texts)} vectors ({len(SHOP_FLAT)} FAQs)")


# # build_shop_embeddings()

# # # ══════════════════════════════════════════════════════════════════════════════
# # #  CORE MATCHING
# # # ══════════════════════════════════════════════════════════════════════════════

# # def pick_answer(answers: dict, query_sentiment: str) -> tuple[str, str]:
# #     for key in (query_sentiment, "neutral"):
# #         if key in answers:
# #             return answers[key], key
# #     first_key = next(iter(answers))
# #     return answers[first_key], first_key


# # def semantic_match(
# #     query: str,
# #     query_sentiment: str,
# #     intent: str | None = None,
# #     is_ml_query: bool = False,
# # ) -> dict | None:
# #     if FAQ_EMB_VECTORS is None or embedder is None:
# #         return None

# #     import torch
# #     from sentence_transformers import util as st_util

# #     query_emb = embedder.encode(query, convert_to_tensor=True)

# #     slice_indices = FAQ_EMB_INTENT_SLICES.get(intent, []) if intent else []
# #     USE_SLICE     = len(slice_indices) >= 5

# #     if USE_SLICE:
# #         slice_tensor = FAQ_EMB_VECTORS[slice_indices]
# #         scores_slice = st_util.cos_sim(query_emb, slice_tensor)[0]
# #         sorted_scores = sorted(scores_slice.tolist(), reverse=True)
# #         best_score    = sorted_scores[0]
# #         second_score  = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
# #         best_local_idx = int(scores_slice.argmax())
# #         best_idx       = slice_indices[best_local_idx]
# #     else:
# #         scores       = st_util.cos_sim(query_emb, FAQ_EMB_VECTORS)[0]
# #         sorted_scores = sorted(scores.tolist(), reverse=True)
# #         best_score   = sorted_scores[0]
# #         second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
# #         best_idx     = int(scores.argmax())

# #     if best_score < SEMANTIC_THRESHOLD:
# #         return None

# #     CONFIDENCE_GAP = 0.05
# #     if not is_ml_query and (best_score - second_score) < CONFIDENCE_GAP:
# #         return None

# #     entry = FAQ_EMB_META[best_idx]

# #     if entry["type"] == "sentiment":
# #         faq      = entry["faq"]
# #         answer, _ = pick_answer(faq["answers"], query_sentiment)
# #         norm      = normalize(query)
# #         esc_kw    = faq.get("escalate_if", {}).get("keywords", [])
# #         escalate  = bool(esc_kw and any(kw.lower() in norm for kw in esc_kw))
# #         return {
# #             "faq_id":      faq.get("id", ""),
# #             "category":    faq.get("category", "general"),
# #             "faq_source":  faq.get("source", "sentiment_aware"),
# #             "answer":      answer,
# #             "answer_lang": "english",
# #             "score":       round(best_score, 3),
# #             "escalate":    escalate,
# #         }
# #     else:
# #         item = entry["item"]
# #         src  = item.get("source", "english")
# #         lang = "manglish" if src.startswith("manglish") else "english"
# #         return {
# #             "faq_id":      item.get("id", ""),
# #             "category":    item.get("section", "general"),
# #             "faq_source":  src,
# #             "answer":      item["a"],
# #             "answer_lang": lang,
# #             "score":       round(best_score, 3),
# #             "escalate":    False,
# #         }


# # def fuzzy_pass(
# #     norm_query: str,
# #     pool: list[dict],
# #     is_ml_query: bool = False,
# # ) -> dict | None:
# #     """
# #     Pass 1.5 — rapidfuzz token_set_ratio match.
# #     Handles typos, phonetic variants, word reordering, partial overlaps.

# #     FIX v5.3: answer_lang is now derived strictly from item["source"].startswith("manglish")
# #     rather than from an outer `lang` variable. This prevents English FAQ answers
# #     from being tagged as "manglish" answer_lang when the query happens to be Manglish.
# #     """
# #     best_score  = -1.0
# #     best_result = None

# #     for item in pool:
# #         all_qs = [item.get("q", "")] + item.get("variants", [])
# #         score  = max(fuzzy_match(norm_query, q) for q in all_qs if q)

# #         src = item.get("source", "english")
# #         if is_ml_query and src.startswith("manglish"):
# #             score = min(score * MANGLISH_BOOST, 1.0)

# #         if score >= FUZZY_THRESHOLD and score > best_score:
# #             best_score  = score
# #             # FIX: derive answer_lang strictly from source, not from query lang
# #             answer_lang = "manglish" if src.startswith("manglish") else "english"
# #             best_result = {
# #                 "faq_id":      item.get("id", ""),
# #                 "category":    item.get("section", "general"),
# #                 "faq_source":  src,
# #                 "answer":      item["a"],
# #                 "answer_lang": answer_lang,
# #                 "score":       round(score, 3),
# #                 "escalate":    False,
# #             }

# #     return best_result


# # def match_faq(query: str, query_sentiment: str) -> dict | None:
# #     """
# #     FAQ matching pipeline:
# #       Pass 0   — Shop FAQ priority check (shop_faq.json always wins if score ≥ 0.45)
# #       Pass 1   — Intent detection (narrows F1 pool + semantic search slice)
# #       Pass 2   — Semantic cosine match (threshold 0.52)
# #       Pass 2.5 — Fuzzy match via rapidfuzz (threshold 0.72)
# #       Pass 3   — F1 token overlap with synonym expansion (threshold 0.30)

# #     Shop FAQ priority:
# #       shop_faq.json answers are shop-specific and always more accurate than generic
# #       FAQs for the same topic. If a shop FAQ matches at ≥ 0.45 cosine similarity,
# #       it wins over any generic FAQ — no matter the score of the generic one.
# #     """
# #     norm_query = normalize(query)
# #     intent     = detect_intent(norm_query)
# #     manglish   = is_manglish(query)

# #     # ── Pass 0: Shop FAQ priority ──────────────────────────────────────────
# #     # Check shop_faq.json FIRST — lower threshold (0.45) but always wins
# #     # over generic FAQs. This ensures dental appointment answer beats
# #     # generic "book a store visit" answer.
# #     # NOTE: shop embeddings are precomputed at load time in SHOP_EMB_VECTORS
# #     if SHOP_EMB_VECTORS is not None and SHOP_FLAT and embedder is not None:
# #         try:
# #             from sentence_transformers import util as st_util
# #             q_vec    = embedder.encode([norm_query], normalize_embeddings=True,
# #                                        convert_to_tensor=True)
# #             scores   = st_util.cos_sim(q_vec, SHOP_EMB_VECTORS)[0]
# #             best_idx = int(scores.argmax())
# #             best_sc  = float(scores[best_idx])
# #             if best_sc >= 0.60:
# #                 item = SHOP_EMB_META[best_idx]
# #                 return {
# #                     "answer":      resolve(item["a"]),
# #                     "answer_lang": item.get("lang", "english"),
# #                     "faq_source":  "shop_faq",
# #                     "faq_id":      item.get("id", ""),
# #                     "faq_score":   round(best_sc, 3),
# #                     "escalate":    False,
# #                 }
# #         except Exception as e:
# #             print(f"[faq_engine] ⚠   Shop FAQ Pass 0 error: {e}")
# #             pass  # fall through to normal matching

# #     # ── Pass 1: Intent detection ──

# #     # ── Pass 1: Intent detection ──
# #     sections  = _INTENT_MAP.get(intent, []) if intent else []

# #     ml_filtered = _filter_by_intent(FAQS_MANGLISH + FAQS_MANGLISH_SENTIMENT, sections) if sections else []
# #     en_filtered = _filter_by_intent(FAQS_ENGLISH  + FAQS_ENGLISH_SENTIMENT,  sections) if sections else []
# #     sem = semantic_match(norm_query, query_sentiment, intent=intent, is_ml_query=manglish)
# #     if sem:
# #         if not manglish:
# #             return sem
# #         # Manglish query: prefer native Manglish answer
# #         if sem["answer_lang"].startswith("manglish"):
# #             return sem
# #         # English semantic result held — continue searching for native Manglish

# #     # ── Pass 1.5: fuzzy match ──
# #     flat_pool = (
# #         FAQS_MANGLISH + FAQS_MANGLISH_SENTIMENT
# #         + FAQS_ENGLISH + FAQS_ENGLISH_SENTIMENT
# #         + SHOP_FLAT
# #     )
# #     fuz = fuzzy_pass(norm_query, flat_pool, is_ml_query=manglish)
# #     if fuz:
# #         if not manglish:
# #             return fuz
# #         # Manglish query: prefer native Manglish fuzzy answer
# #         if fuz["answer_lang"].startswith("manglish"):
# #             return fuz
# #         # English fuzzy result held — continue to F1 for native Manglish

# #     # ── Pass 2: F1 with synonym expansion ──
# #     q_tokens = expand_synonyms(tokenize(norm_query))

# #     best_score      = -1.0
# #     best_n_variants = 0
# #     best_result: dict | None = None

# #     def _update(score: float, candidate: dict, n_variants: int = 1) -> None:
# #         nonlocal best_score, best_n_variants, best_result
# #         if score > best_score or (score == best_score and n_variants > best_n_variants):
# #             best_score      = score
# #             best_n_variants = n_variants
# #             best_result     = candidate

# #     # Sentiment-aware FAQs
# #     for faq in FAQS_SENTIMENT + SHOP_SENT:
# #         _faq_n = sum(len(qs) for qs in faq.get("questions", {}).values())
# #         for sent_key, questions in faq.get("questions", {}).items():
# #             for q_text in questions:
# #                 score = f1_score(q_tokens, q_text)
# #                 if score > 0:
# #                     answer, _ = pick_answer(faq["answers"], query_sentiment)
# #                     esc_kw    = faq.get("escalate_if", {}).get("keywords", [])
# #                     escalate  = bool(esc_kw and any(kw.lower() in norm_query for kw in esc_kw))
# #                     _update(score, {
# #                         "faq_id":      faq.get("id", ""),
# #                         "category":    faq.get("category", "general"),
# #                         "faq_source":  faq.get("source", "sentiment_aware"),
# #                         "answer":      answer,
# #                         "answer_lang": "english",
# #                         "score":       score,
# #                         "escalate":    escalate,
# #                     }, n_variants=_faq_n)

# #     # Manglish FAQs — searched first + boosted
# #     manglish_pool = ml_filtered + [
# #         f for f in FAQS_MANGLISH + FAQS_MANGLISH_SENTIMENT + SHOP_FLAT
# #         if f not in ml_filtered
# #         and (f.get("source", "") in ("manglish", "manglish_sentiment")
# #              or "shop" in f.get("source", ""))
# #     ]
# #     for item in manglish_pool:
# #         src = item.get("source", "")
# #         if src not in ("manglish", "manglish_sentiment") and "shop" not in src:
# #             continue
# #         all_qs = [item["q"]] + item.get("variants", [])
# #         raw    = max(f1_score(q_tokens, q) for q in all_qs)
# #         if manglish and raw > 0:
# #             q_content    = set(q_tokens) - _MANGLISH_PARTICLES
# #             faq_all_text = " ".join(all_qs)
# #             faq_content  = set(tokenize(faq_all_text)) - _MANGLISH_PARTICLES
# #             if q_content and faq_content and not (q_content & faq_content):
# #                 raw = 0.0
# #         score = raw * MANGLISH_BOOST if manglish else raw
# #         _update(score, {
# #             "faq_id":      item.get("id", ""),
# #             "category":    item.get("section", "general"),
# #             "faq_source":  src,
# #             "answer":      item["a"],
# #             "answer_lang": "manglish",
# #             "score":       score,
# #             "escalate":    False,
# #         }, n_variants=len(all_qs))

# #     # English FAQs
# #     english_pool = en_filtered + [f for f in FAQS_ENGLISH + FAQS_ENGLISH_SENTIMENT
# #                                    if f not in en_filtered]
# #     for item in english_pool:
# #         all_qs = [item["q"]] + item.get("variants", [])
# #         score  = max(f1_score(q_tokens, q) for q in all_qs)
# #         _update(score, {
# #             "faq_id":      item.get("id", ""),
# #             "category":    item.get("section", "general"),
# #             "faq_source":  "english",
# #             "answer":      item["a"],
# #             "answer_lang": "english",
# #             "score":       score,
# #             "escalate":    False,
# #         }, n_variants=len(all_qs))

# #     # ── Final priority resolution for Manglish queries ──
# #     if manglish and best_score >= FAQ_THRESHOLD and best_result:
# #         # F1 found a native Manglish answer → always prefer over held English results
# #         if best_result["answer_lang"].startswith("manglish"):
# #             best_result["score"] = round(best_score, 3)
# #             return best_result
# #         # F1 found English — compare against held semantic/fuzzy English results
# #         # Return whichever has the highest score; pipeline will rephrase all of them
# #         candidates = [(best_score, best_result)]
# #         if sem:
# #             candidates.append((sem["score"], sem))
# #         if fuz:
# #             candidates.append((fuz["score"], fuz))
# #         best_candidate = max(candidates, key=lambda x: x[0])
# #         result = best_candidate[1]
# #         result["score"] = round(best_candidate[0], 3)
# #         return result

# #     # Non-Manglish: standard priority
# #     if sem and best_score >= FAQ_THRESHOLD and best_result:
# #         return sem  # semantic beats F1 for English queries

# #     if fuz and (best_result is None or best_score < FAQ_THRESHOLD):
# #         return fuz

# #     if best_score < FAQ_THRESHOLD or best_result is None:
# #         # Last resort: return held semantic/fuzzy English for Manglish query
# #         # (pipeline will rephrase via Ollama)
# #         if manglish:
# #             if sem:
# #                 return sem
# #             if fuz:
# #                 return fuz
# #         return None

# #     best_result["score"] = round(best_score, 3)
# #     return best_result






# """
# faq_engine.py — FAQ loading, embedding index, and matching
# ===========================================================
# Exported symbols used by chat.py:
#   - FAQS_SENTIMENT, FAQS_ENGLISH, FAQS_MANGLISH, FAQS_SHOP
#   - FAQS_ENGLISH_SENTIMENT, FAQS_MANGLISH_SENTIMENT
#   - SHOP_SENT, SHOP_FLAT
#   - FAQ_EMB_VECTORS, FAQ_EMB_TEXTS, FAQ_EMB_META
#   - match_faq(query, query_sentiment, slug=None) → dict | None
#   - FAQ_THRESHOLD, SEMANTIC_THRESHOLD, MANGLISH_BOOST

# Depends on: nlp.py

# v5.2 → v5.3 fixes:
#   1. _INTENT_KEYWORDS["return"]: added Manglish paripadi/niyamam variants
#      so "nthanu paripadi" → intent="return" → filters to return FAQ pool
#   2. fuzzy_pass(): answer_lang detection hardened — explicitly checks
#      item["source"].startswith("manglish") rather than trusting the lang var
#   3. match_faq(): when fuzzy returns English for a Manglish query, it now
#      falls ALL the way through to F1 before returning the English fuzzy result.
#      Previously it returned the English fuzzy result immediately, forcing a
#      slow Ollama rephrase. F1 may find a native Manglish answer instead.
#   4. match_faq() final fallback priority:
#        native Manglish F1 > semantic English > fuzzy English > Ollama
#      ensures cheapest path that still produces natural Manglish output.

# v5.3 → v5.6.1 fixes:
#   BUG 5 — match_faq(): ml_filtered and en_filtered were assigned BEFORE
#      sections was defined, causing a NameError at runtime on every request
#      that went past Pass 0. Fixed by moving sections definition above
#      ml_filtered/en_filtered assignments.

# v5.6.1 → v5.6.2 fixes:
#   FIX 1 — slug-aware placeholder resolution.
#      _load_placeholder_map() now accepts a slug param and loads from
#      shops/{slug}/shop_config.json when available. resolve() is unchanged
#      (still uses global _PLACEHOLDER_MAP for load-time resolve of generic FAQs).
#      New resolve_for_slug(text, slug) resolves using per-slug config — used in
#      match_faq() so every returned answer has the correct shop's contact details.

#   FIX 2 — Raw answer storage at load time.
#      All load_*_faqs() functions now store raw (unresolved) answers in item["a"].
#      resolve() is NO LONGER called at load time. This prevents the root
#      shop_config.json from polluting hey-foodie's FAQ answers with the wrong
#      WhatsApp number / location. Resolution happens at query time in match_faq()
#      using the request's slug.

#   FIX 3 — FAQ_THRESHOLD raised from 0.30 → 0.45.
#      0.30 was too permissive — food queries were matching clothing/warranty FAQs
#      via shared stopwords after F1 normalization. 0.45 requires meaningful
#      token overlap before a match is accepted.

#   FIX 4 — match_faq() accepts slug param.
#      All returned answers are resolved via resolve_for_slug(answer, slug) so
#      {whatsapp}, {location}, etc. always contain the correct shop's values.
#      chat.py must pass slug=slug when calling match_faq().
# """

# import json
# import os
# import pickle
# from glob import glob
# from pathlib import Path

# from nlp import (
#     embedder,
#     expand_synonyms,
#     f1_score,
#     fuzzy_match,
#     is_manglish,
#     normalize,
#     tokenize,
#     MANGLISH_SIGNALS,
# )

# # ══════════════════════════════════════════════════════════════════════════════
# #  SHOP CONFIG PLACEHOLDER RESOLVER
# #  FIX v5.6.2: resolve() no longer called at load time — answers stored raw.
# #  resolve_for_slug() resolves at query time using the correct slug's config.
# # ══════════════════════════════════════════════════════════════════════════════

# def _load_placeholder_map(slug: str | None = None) -> dict:
#     """
#     Build placeholder map from shop_config.json.
#     If slug is given, tries shops/{slug}/shop_config.json first.
#     Falls back to root shop_config.json.
#     """
#     paths_to_try = []
#     if slug:
#         paths_to_try.append(os.path.join("shops", slug.strip().lower().replace(" ", "-"), "shop_config.json"))
#     paths_to_try.append("shop_config.json")

#     cfg = {}
#     for path in paths_to_try:
#         try:
#             with open(path, "r", encoding="utf-8") as f:
#                 content = f.read().strip()
#                 if content:
#                     cfg = json.loads(content)
#                     break
#         except (FileNotFoundError, json.JSONDecodeError):
#             continue

#     if not cfg:
#         return {}

#     h     = cfg.get("hours", {})
#     c     = cfg.get("contact", {})
#     d     = cfg.get("delivery", {})
#     r     = cfg.get("returns", {})
#     offer = cfg.get("first_offer", {})
#     return {
#         "whatsapp":         c.get("whatsapp", ""),
#         "phone":            c.get("phone", ""),
#         "email":            c.get("email", ""),
#         "hours_weekdays":   h.get("weekdays", ""),
#         "hours_sunday":     h.get("sunday", ""),
#         "hours_holiday":    h.get("holiday", ""),
#         "location":         cfg.get("location", ""),
#         "city":             cfg.get("city", ""),
#         "delivery_areas":   d.get("areas", ""),
#         "delivery_free":    d.get("free_above", ""),
#         "delivery_days":    d.get("days", ""),
#         "return_days":      str(r.get("days", 7)),
#         "return_condition": r.get("condition", ""),
#         "refund_days":      r.get("refund_days", ""),
#         "offer_code":       offer.get("code", ""),
#         "offer_desc":       offer.get("description", ""),
#         "shop_name":        cfg.get("shop_name", ""),
#         "bot_name":         cfg.get("bot_name", ""),
#     }

# # Global placeholder map — loaded from root config, used only as a fallback.
# # Per-request resolution uses resolve_for_slug(text, slug) which loads the
# # correct shop's config on demand.
# _PLACEHOLDER_MAP: dict = _load_placeholder_map()


# def resolve(text: str) -> str:
#     """
#     Replace {placeholders} using the global (root) placeholder map.
#     Still used as a fallback — prefer resolve_for_slug() at query time.
#     """
#     if not _PLACEHOLDER_MAP or '{' not in text:
#         return text
#     try:
#         return text.format_map(_PLACEHOLDER_MAP)
#     except (KeyError, ValueError):
#         return text


# def resolve_for_slug(text: str, slug: str | None = None) -> str:
#     """
#     FIX v5.6.2 — Resolve {placeholders} using the slug-specific shop config.
#     This is the correct function to call at query time (inside match_faq).
#     Falls back to global _PLACEHOLDER_MAP if no slug config is found.
#     """
#     if '{' not in text:
#         return text
#     if slug:
#         pm = _load_placeholder_map(slug)
#         if pm:
#             try:
#                 return text.format_map(pm)
#             except (KeyError, ValueError):
#                 pass
#     # Fallback to global map
#     return resolve(text)


# def reload_placeholders() -> None:
#     """Hot-reload placeholder map when shop_config.json changes."""
#     global _PLACEHOLDER_MAP
#     _PLACEHOLDER_MAP = _load_placeholder_map()
#     print(f"[faq_engine] ✅  Placeholder map reloaded — shop={_PLACEHOLDER_MAP.get('shop_name','?')}")


# # ══════════════════════════════════════════════════════════════════════════════
# #  CONFIG
# # ══════════════════════════════════════════════════════════════════════════════

# FAQ_PATH                = "faqs/faq.json"
# ENGLISH_PATH            = "faqs/english.json"
# MANGLISH_PATH           = "faqs/manglish.json"
# SHOP_FAQ_PATH           = "faqs/shop_faq.json"
# ENGLISH_SENTIMENT_PATH  = "faqs/english_sentiment.json"
# MANGLISH_SENTIMENT_PATH = "faqs/manglish_sentiment.json"

# # FIX v5.6.2: raised from 0.30 → 0.45.
# # 0.30 was too permissive — food queries matched clothing/warranty FAQs via
# # shared stopwords after F1 normalization. 0.45 requires genuine token overlap.
# FAQ_THRESHOLD      = 0.45
# SEMANTIC_THRESHOLD = 0.52
# MANGLISH_BOOST     = 1.15
# FUZZY_THRESHOLD    = 0.72

# _MANGLISH_PARTICLES = {
#     "kittum", "kittiyilla", "cheyyam", "cheyyano", "cheyyuka", "cheythu",
#     "aanu", "alle", "aano", "undo", "undu", "okke", "ippo", "ethra",
#     "evide", "enthu", "engane", "njan", "njangal", "ningal", "avarkku",
#     "polum", "venam", "venda", "pattumo", "tharaamo", "undenkil",
#     "allenkil", "nokam", "nokkanam", "sheri", "kollam", "adipoli",
#     "mosham", "ano", "ithu", "athu", "ente", "eppo", "pinne",
# }

# # ══════════════════════════════════════════════════════════════════════════════
# #  INTENT CLASSIFICATION
# # ══════════════════════════════════════════════════════════════════════════════

# _INTENT_MAP: dict[str, list[str]] = {
#     "payment":     ["payment"],
#     "delivery":    ["delivery", "shipping"],
#     "return":      ["returns", "refund"],
#     "order":       ["ordering", "order_contact_support", "reschedule",
#                     "order_reschedule", "post_delivery"],
#     "tracking":    ["tracking"],
#     "offer":       ["offers", "pricing"],
#     "quality":     ["quality", "complaint", "warranty", "damaged_product_complaint"],
#     "size":        ["size"],
#     "appointment": ["appointment", "appointments_booking"],
#     "account":     ["account"],
#     "store":       ["store"],
#     "support":     ["support", "order_contact_support"],
#     "review":      ["review", "post_delivery_review"],
# }

# _INTENT_KEYWORDS: dict[str, list[str]] = {
#     "tracking":    ["track", "tracking", "order status", "order location",
#                     "parcel status", "parcel evide", "shipment",
#                     "evide aanu ippo", "order evide"],
#     "return":      [
#         "return", "refund", "exchange", "money back",
#         "return policy", "return rule", "return niyamam",
#         "paripadi", "niyamam", "return paripadi", "nthanu paripadi",
#         "enthu paripadi", "return niyamam", "enthu niyamam",
#         "paisa thurik", "wrong product", "thettaya product",
#         "cheyyano return", "return cheyy",
#         "ethra naal", "7 days", "7 naal",
#     ],
#     "quality":     ["quality", "defective", "damaged", "damage",
#                     "complaint", "complient", "complain",
#                     "warranty", "guarantee", "fabric", "material",
#                     "stitching", "broken", "torn", "ripped", "faded",
#                     "shrunk", "smell", "colour", "color"],
#     "appointment": ["appointment", "book a slot", "schedule visit",
#                     "trial room", "fitting room", "store visit",
#                     "session", "book", "booking", "book appointment",
#                     "book session", "slot", "visit", "schedule",
#                     "book for", "how to book"],
#     "account":     ["account", "login", "password", "profile", "register",
#                     "signup", "otp", "forgot password", "delete account"],
#     "review":      ["review", "rating", "write review", "post review",
#                     "feedback", "submit review"],
#     "payment":     ["payment method", "pay", "upi", "gpay", "phonepay", "phonepe",
#                     "paytm", "cod", "cash on delivery", "card payment",
#                     "emi", "netbanking", "online payment", "payment options",
#                     "payment fail", "payment safe", "charged", "billed"],
#     "delivery":    ["delivery time", "delivery charge", "delivery free",
#                     "deliver", "shipping", "days il kittum", "divasam",
#                     "express delivery", "same day delivery", "fast delivery",
#                     "delivery date", "delivery address", "package", "parcel",
#                     "kittiyilla", "arrived", "received"],
#     "order":       ["cancel order", "modify order", "place order",
#                     "how to order", "order cheyy", "vanganam",
#                     "idanam", "buy", "purchase", "cancel cheyyam",
#                     "order cancel", "order modify"],
#     "offer":       ["offer", "discount", "sale", "coupon", "promo code",
#                     "price drop", "kooduthal", "vila", "rate enthu",
#                     "cost", "first time", "welcome10"],
#     "size":        ["size", "fit", "fitting", "measure", "size chart",
#                     "size guide", "small aano", "large aano",
#                     "tight", "loose", "shrunk"],
#     "store":       [
#         "shop location", "store location", "store address",
#         "shop address", "shop timing", "store hours",
#         "shop open", "store open", "where is your store",
#         "where is the shop", "your store", "your shop",
#         "holiday", "open tomorrow", "open today", "open on",
#         "open sunday", "open saturday", "closed", "working hours",
#         "what time", "opening time", "closing time",
#         "open hours", "store open hours", "shop hours",
#         "opening hours", "business hours", "open now",
#         "are you open", "when do you open", "when do you close",
#         "what time do you open", "what time do you close",
#         "open time", "close time", "hours of operation",
#         "shop evide", "store evide", "ningalude shop",
#         "evideya shop", "evideya store", "shopinte sthalam",
#         "store sthalam", "shop sthalam",
#         "evide aanu shop", "evide aanu store",
#         "shop address enthu", "store address enthu",
#         "shop evide aanu", "store evide aanu",
#         "ningalude store evide", "ningalude shop evide",
#         "location enthu", "ningal evide",
#         "shop ethu neram", "shop open aano", "shop close aano",
#         "holiday il open", "holiday il shop",
#     ],
#     "support":     [
#         "complaint", "complient", "complain",
#         "complaint kodukkum", "complaint cheyyam",
#         "issue parayam", "problem parayam", "contact",
#         "phone number", "whatsapp number",
#         "customer care", "email id", "support team",
#         "call cheyyam", "help line",
#         "number undo", "number enthu", "number aanu",
#         "number tharamo", "contact number",
#         "whatsapp number undo", "phone number undo",
#         "call cheyyaan number",
#         "ningalude number", "shop number",
#         "contact cheyyaan", "contact engane",
#     ],
# }


# def detect_intent(query: str) -> str | None:
#     t = query.lower()
#     for intent, keywords in _INTENT_KEYWORDS.items():
#         if any(kw in t for kw in keywords):
#             return intent
#     return None


# def _filter_by_intent(faqs: list[dict], sections: list[str]) -> list[dict]:
#     return [
#         f for f in faqs
#         if f.get("section", f.get("category", "")).lower()
#         in [s.lower() for s in sections]
#     ]

# # ══════════════════════════════════════════════════════════════════════════════
# #  FAQ LOADERS
# #  FIX v5.6.2: All loaders store RAW (unresolved) answers — no resolve() at
# #  load time. Resolution happens in match_faq() via resolve_for_slug(slug).
# # ══════════════════════════════════════════════════════════════════════════════

# def load_sentiment_faqs(path: str) -> list[dict]:
#     if not Path(path).exists():
#         print(f"[faq_engine] ⚠   {path} not found — skipping")
#         return []
#     with open(path, "r", encoding="utf-8") as f:
#         data = json.load(f)
#     if not isinstance(data, list):
#         return []
#     for faq in data:
#         faq.setdefault("source", "sentiment_aware")
#         # Answers stored raw — resolve at query time
#     print(f"[faq_engine] ✅  faq.json            — {len(data):>4} sentiment-aware FAQs")
#     return data


# def load_english_faqs(path: str) -> list[dict]:
#     if not Path(path).exists():
#         print(f"[faq_engine] ⚠   {path} not found — skipping")
#         return []
#     with open(path, "r", encoding="utf-8") as f:
#         data = json.load(f)

#     flat: list[dict] = []
#     seen: set = set()

#     if isinstance(data, list):
#         for item in data:
#             if not isinstance(item, dict):
#                 continue
#             variants = [v.strip() for v in item.get("question_variants", [])
#                         if isinstance(v, str) and v.strip()]
#             answer   = item.get("answer", "").strip()
#             if not variants:
#                 q = (item.get("question_en") or item.get("question") or "").strip()
#                 if q:
#                     variants = [q]
#             if not variants or not answer:
#                 continue
#             key = (variants[0].lower(), answer.lower())
#             if key in seen:
#                 continue
#             seen.add(key)
#             flat.append({
#                 "id":       item.get("id", ""),
#                 "q":        variants[0],
#                 "variants": variants[1:],
#                 "a":        answer,          # RAW — no resolve() here
#                 "section":  item.get("category", "general"),
#                 "source":   "english",
#             })
#     elif isinstance(data, dict):
#         for section, items in data.items():
#             if not isinstance(items, list):
#                 continue
#             for item in items:
#                 if not isinstance(item, dict):
#                     continue
#                 q = (item.get("question_en") or item.get("question") or "").strip()
#                 a = (item.get("answer_en")   or item.get("answer")   or "").strip()
#                 if not q or not a:
#                     continue
#                 key = (q.lower(), a.lower())
#                 if key in seen:
#                     continue
#                 seen.add(key)
#                 flat.append({
#                     "id":       item.get("id", ""),
#                     "q":        q,
#                     "variants": [],
#                     "a":        a,           # RAW — no resolve() here
#                     "section":  section,
#                     "source":   "english",
#                 })

#     print(f"[faq_engine] ✅  english.json        — {len(flat):>4} English FAQs")
#     return flat


# def load_manglish_faqs(path: str) -> list[dict]:
#     if not Path(path).exists():
#         print(f"[faq_engine] ⚠   {path} not found — skipping")
#         return []
#     with open(path, "r", encoding="utf-8") as f:
#         data = json.load(f)
#     if not isinstance(data, list):
#         return []

#     flat: list[dict] = []
#     seen: set = set()

#     for element in data:
#         if not isinstance(element, dict):
#             continue
#         if "question_variants" in element:
#             variants = [v.strip() for v in element.get("question_variants", [])
#                         if isinstance(v, str) and v.strip()]
#             answer   = element.get("answer", "").strip()
#             if not variants or not answer:
#                 continue
#             key = (variants[0].lower(), answer.lower())
#             if key in seen:
#                 continue
#             seen.add(key)
#             flat.append({
#                 "id":       element.get("id", ""),
#                 "q":        variants[0],
#                 "variants": variants[1:],
#                 "a":        answer,          # RAW — no resolve() here
#                 "section":  element.get("category", "general"),
#                 "source":   "manglish",
#             })
#         else:
#             for section, items in element.items():
#                 if not isinstance(items, list):
#                     continue
#                 for item in items:
#                     if not isinstance(item, dict):
#                         continue
#                     q = item.get("question", "").strip()
#                     a = item.get("answer",   "").strip()
#                     if not q or not a:
#                         continue
#                     key = (q.lower(), a.lower())
#                     if key in seen:
#                         continue
#                     seen.add(key)
#                     flat.append({
#                         "id":       item.get("id", ""),
#                         "q":        q,
#                         "variants": [],
#                         "a":        a,       # RAW — no resolve() here
#                         "section":  section,
#                         "source":   "manglish",
#                     })

#     print(f"[faq_engine] ✅  manglish.json       — {len(flat):>4} Manglish FAQs")
#     return flat


# def load_english_sentiment_faqs(path: str) -> list[dict]:
#     if not Path(path).exists():
#         print(f"[faq_engine] ⚠   {path} not found — skipping")
#         return []
#     with open(path, "r", encoding="utf-8") as f:
#         data = json.load(f)
#     if not isinstance(data, list):
#         return []

#     flat: list[dict] = []
#     seen: set = set()
#     skipped = 0

#     for item in data:
#         if not isinstance(item, dict):
#             continue
#         variants = [v.strip() for v in item.get("question_variants", [])
#                     if isinstance(v, str) and v.strip()]
#         answer   = item.get("answer", "").strip()
#         if not variants or not answer:
#             skipped += 1
#             continue
#         key = (variants[0].lower(), answer.lower())
#         if key in seen:
#             continue
#         seen.add(key)
#         flat.append({
#             "id":       item.get("id", ""),
#             "q":        variants[0],
#             "variants": variants[1:],
#             "a":        answer,              # RAW — no resolve() here
#             "section":  item.get("category", "general"),
#             "source":   "english_sentiment",
#         })

#     print(f"[faq_engine] ✅  english_sentiment   — {len(flat):>4} FAQs "
#           f"(skipped {skipped} empty-answer rows)")
#     return flat


# def load_manglish_sentiment_faqs(path: str) -> list[dict]:
#     if not Path(path).exists():
#         print(f"[faq_engine] ⚠   {path} not found — skipping")
#         return []
#     with open(path, "r", encoding="utf-8") as f:
#         data = json.load(f)
#     if not isinstance(data, list):
#         return []

#     flat: list[dict] = []
#     seen: set = set()

#     for item in data:
#         if not isinstance(item, dict):
#             continue
#         variants = [v.strip() for v in item.get("question_variants", [])
#                     if isinstance(v, str) and v.strip()]
#         answer   = item.get("answer", "").strip()
#         if not variants or not answer:
#             continue
#         key = (variants[0].lower(), answer.lower())
#         if key in seen:
#             continue
#         seen.add(key)
#         flat.append({
#             "id":       item.get("id", ""),
#             "q":        variants[0],
#             "variants": variants[1:],
#             "a":        answer,              # RAW — no resolve() here
#             "section":  item.get("category", "general"),
#             "source":   "manglish_sentiment",
#         })

#     print(f"[faq_engine] ✅  manglish_sentiment  — {len(flat):>4} FAQs")
#     return flat


# def load_shop_faqs(path: str) -> list[dict]:
#     """
#     Load shop-specific FAQs from faqs/shop_faq.json.
#     Answers stored RAW — resolved at query time via resolve_for_slug().
#     """
#     if not Path(path).exists():
#         print(f"[faq_engine] ℹ   {path} not found — no shop FAQs (OK)")
#         return []
#     try:
#         with open(path, "r", encoding="utf-8") as f:
#             data = json.load(f)
#     except Exception as exc:
#         print(f"[faq_engine] ⚠   {path}: {exc}")
#         return []
#     if not isinstance(data, list):
#         print(f"[faq_engine] ⚠   {path}: must be a JSON array")
#         return []

#     flat: list[dict] = []
#     seen: set = set()
#     for item in data:
#         if not isinstance(item, dict):
#             continue
#         if "question_variants" in item:
#             variants = [v.strip() for v in item.get("question_variants", []) if isinstance(v, str) and v.strip()]
#             answer   = item.get("answer", "").strip()
#             if not variants or not answer:
#                 continue
#             key = (variants[0].lower(), answer.lower())
#             if key in seen:
#                 continue
#             seen.add(key)
#             flat.append({
#                 "id":       item.get("id", ""),
#                 "q":        variants[0],
#                 "variants": variants[1:],
#                 "a":        answer,          # RAW — no resolve() here
#                 "section":  item.get("category", "shop"),
#                 "source":   "shop_faq",
#                 "lang":     item.get("lang", "english"),
#             })
#         elif "question" in item or "q" in item:
#             q = (item.get("question") or item.get("q") or "").strip()
#             a = (item.get("answer")   or item.get("a")   or "").strip()
#             if not q or not a:
#                 continue
#             key = (q.lower(), a.lower())
#             if key in seen:
#                 continue
#             seen.add(key)
#             flat.append({
#                 "id":       item.get("id", ""),
#                 "q":        q,
#                 "variants": [],
#                 "a":        a,               # RAW — no resolve() here
#                 "section":  item.get("category", "shop"),
#                 "source":   "shop_faq",
#                 "lang":     item.get("lang", "english"),
#             })

#     print(f"[faq_engine] ✅  shop_faq.json      — {len(flat):>4} shop FAQs")
#     return flat

# # ══════════════════════════════════════════════════════════════════════════════
# #  LOAD ALL DATA
# # ══════════════════════════════════════════════════════════════════════════════

# FAQS_SENTIMENT:          list[dict] = load_sentiment_faqs(FAQ_PATH)
# FAQS_ENGLISH:            list[dict] = load_english_faqs(ENGLISH_PATH)
# FAQS_ENGLISH_SENTIMENT:  list[dict] = load_english_sentiment_faqs(ENGLISH_SENTIMENT_PATH)
# FAQS_MANGLISH:           list[dict] = load_manglish_faqs(MANGLISH_PATH)
# FAQS_MANGLISH_SENTIMENT: list[dict] = load_manglish_sentiment_faqs(MANGLISH_SENTIMENT_PATH)
# FAQS_SHOP:               list[dict] = load_shop_faqs(SHOP_FAQ_PATH)

# print(f"\n[faq_engine] FAQ pool summary:")
# print(f"  ├─ sentiment_aware      : {len(FAQS_SENTIMENT)}")
# print(f"  ├─ english flat         : {len(FAQS_ENGLISH)}")
# print(f"  ├─ english_sentiment    : {len(FAQS_ENGLISH_SENTIMENT)}")
# print(f"  ├─ manglish flat        : {len(FAQS_MANGLISH)}")
# print(f"  ├─ manglish_sentiment   : {len(FAQS_MANGLISH_SENTIMENT)}")
# print(f"  └─ shop-specific        : {len(FAQS_SHOP)}")

# SHOP_SENT = [f for f in FAQS_SHOP if "questions" in f and "answers" in f]
# SHOP_FLAT = [f for f in FAQS_SHOP if "q" in f and "a" in f]

# # ══════════════════════════════════════════════════════════════════════════════
# #  EMBEDDING INDEX
# # ══════════════════════════════════════════════════════════════════════════════

# FAQ_EMB_VECTORS = None
# FAQ_EMB_TEXTS:  list[str]  = []
# FAQ_EMB_META:   list[dict] = []
# FAQ_EMB_INTENT_SLICES: dict[str, list[int]] = {}

# SHOP_EMB_VECTORS = None
# SHOP_EMB_META:  list[dict] = []


# def _item_intent(item: dict) -> str | None:
#     section = item.get("section", item.get("category", "")).lower()
#     for intent, sections in _INTENT_MAP.items():
#         if section in [s.lower() for s in sections]:
#             return intent
#     return None


# CACHE_PATH = "faq_embeddings_cache.pkl"


# def _cache_checksum() -> str:
#     import hashlib
#     counts = (
#         len(FAQS_SENTIMENT), len(FAQS_ENGLISH), len(FAQS_ENGLISH_SENTIMENT),
#         len(FAQS_MANGLISH), len(FAQS_MANGLISH_SENTIMENT), len(SHOP_FLAT), len(SHOP_SENT)
#     )
#     return hashlib.md5(str(counts).encode()).hexdigest()


# def build_embeddings() -> None:
#     global FAQ_EMB_VECTORS, FAQ_EMB_TEXTS, FAQ_EMB_META, FAQ_EMB_INTENT_SLICES
#     if embedder is None:
#         print("[faq_engine] ⚠   Embedder not available — skipping index build")
#         return

#     current_checksum = _cache_checksum()
#     if Path(CACHE_PATH).exists():
#         try:
#             with open(CACHE_PATH, "rb") as f:
#                 cache = pickle.load(f)
#             if cache.get("checksum") == current_checksum:
#                 FAQ_EMB_VECTORS        = cache["vectors"]
#                 FAQ_EMB_TEXTS          = cache["texts"]
#                 FAQ_EMB_META           = cache["meta"]
#                 FAQ_EMB_INTENT_SLICES  = cache["intent_slices"]
#                 print(f"[faq_engine] ✅  Loaded embedding cache — "
#                       f"{FAQ_EMB_VECTORS.shape[0]} vectors (skipped recompute)")
#                 print(f"[faq_engine] ✅  Intent slices: "
#                       + ", ".join(f"{k}={len(v)}" for k, v in FAQ_EMB_INTENT_SLICES.items()))
#                 return
#             else:
#                 print("[faq_engine] ℹ   FAQ data changed — rebuilding embedding cache…")
#         except Exception as e:
#             print(f"[faq_engine] ⚠   Cache load failed ({e}) — rebuilding…")

#     texts: list[str] = []
#     meta:  list[dict] = []

#     for faq in FAQS_SENTIMENT + SHOP_SENT:
#         for questions in faq.get("questions", {}).values():
#             for q in questions:
#                 if q and q.strip():
#                     texts.append(q.strip())
#                     meta.append({"type": "sentiment", "faq": faq, "intent": None})

#     for item in (FAQS_MANGLISH + FAQS_MANGLISH_SENTIMENT
#                  + FAQS_ENGLISH + FAQS_ENGLISH_SENTIMENT
#                  + SHOP_FLAT):
#         q = item.get("q", "").strip()
#         if not q:
#             continue
#         intent = _item_intent(item)
#         idx = len(texts)
#         texts.append(q)
#         meta.append({"type": "flat", "item": item, "intent": intent})

#         if intent:
#             FAQ_EMB_INTENT_SLICES.setdefault(intent, []).append(idx)

#         for variant in item.get("variants", []):
#             if variant and variant.strip():
#                 vidx = len(texts)
#                 texts.append(variant.strip())
#                 meta.append({"type": "flat", "item": item, "intent": intent})
#                 if intent:
#                     FAQ_EMB_INTENT_SLICES.setdefault(intent, []).append(vidx)

#     if not texts:
#         print("[faq_engine] ⚠   No FAQ texts — embedding index empty")
#         return

#     print(f"[faq_engine] Building embedding index for {len(texts)} entries…")
#     FAQ_EMB_VECTORS = embedder.encode(
#         texts,
#         convert_to_tensor=True,
#         show_progress_bar=False,
#         batch_size=64,
#     )
#     FAQ_EMB_TEXTS = texts
#     FAQ_EMB_META  = meta
#     print(f"[faq_engine] ✅  Index ready — {FAQ_EMB_VECTORS.shape[0]} vectors, "
#           f"dim={FAQ_EMB_VECTORS.shape[1]}")
#     print(f"[faq_engine] ✅  Intent slices: "
#           + ", ".join(f"{k}={len(v)}" for k, v in FAQ_EMB_INTENT_SLICES.items()))

#     try:
#         with open(CACHE_PATH, "wb") as f:
#             pickle.dump({
#                 "checksum":     current_checksum,
#                 "vectors":      FAQ_EMB_VECTORS,
#                 "texts":        FAQ_EMB_TEXTS,
#                 "meta":         FAQ_EMB_META,
#                 "intent_slices":FAQ_EMB_INTENT_SLICES,
#             }, f)
#         print(f"[faq_engine] ✅  Embedding cache saved → {CACHE_PATH}")
#     except Exception as e:
#         print(f"[faq_engine] ⚠   Cache save failed: {e}")


# build_embeddings()


# def build_shop_embeddings() -> None:
#     global SHOP_EMB_VECTORS, SHOP_EMB_META
#     if not SHOP_FLAT or embedder is None:
#         SHOP_EMB_VECTORS = None
#         SHOP_EMB_META    = []
#         return
#     texts: list[str]  = []
#     meta:  list[dict] = []
#     for item in SHOP_FLAT:
#         q = item.get("q", "").strip()
#         if q:
#             texts.append(q)
#             meta.append(item)
#         for v in item.get("variants", []):
#             if v and v.strip():
#                 texts.append(v.strip())
#                 meta.append(item)
#     if not texts:
#         return
#     SHOP_EMB_VECTORS = embedder.encode(
#         texts,
#         convert_to_tensor=True,
#         normalize_embeddings=True,
#         show_progress_bar=False,
#         batch_size=64,
#     )
#     SHOP_EMB_META = meta
#     print(f"[faq_engine] ✅  Shop FAQ embeddings — {len(texts)} vectors ({len(SHOP_FLAT)} FAQs)")


# build_shop_embeddings()

# # ══════════════════════════════════════════════════════════════════════════════
# #  CORE MATCHING
# # ══════════════════════════════════════════════════════════════════════════════

# def pick_answer(answers: dict, query_sentiment: str) -> tuple[str, str]:
#     for key in (query_sentiment, "neutral"):
#         if key in answers:
#             return answers[key], key
#     first_key = next(iter(answers))
#     return answers[first_key], first_key


# def semantic_match(
#     query: str,
#     query_sentiment: str,
#     intent: str | None = None,
#     is_ml_query: bool = False,
# ) -> dict | None:
#     if FAQ_EMB_VECTORS is None or embedder is None:
#         return None

#     import torch
#     from sentence_transformers import util as st_util

#     query_emb = embedder.encode(query, convert_to_tensor=True)

#     slice_indices = FAQ_EMB_INTENT_SLICES.get(intent, []) if intent else []
#     USE_SLICE     = len(slice_indices) >= 5

#     if USE_SLICE:
#         slice_tensor = FAQ_EMB_VECTORS[slice_indices]
#         scores_slice = st_util.cos_sim(query_emb, slice_tensor)[0]
#         sorted_scores = sorted(scores_slice.tolist(), reverse=True)
#         best_score    = sorted_scores[0]
#         second_score  = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
#         best_local_idx = int(scores_slice.argmax())
#         best_idx       = slice_indices[best_local_idx]
#     else:
#         scores       = st_util.cos_sim(query_emb, FAQ_EMB_VECTORS)[0]
#         sorted_scores = sorted(scores.tolist(), reverse=True)
#         best_score   = sorted_scores[0]
#         second_score = sorted_scores[1] if len(sorted_scores) > 1 else 0.0
#         best_idx     = int(scores.argmax())

#     if best_score < SEMANTIC_THRESHOLD:
#         return None

#     CONFIDENCE_GAP = 0.05
#     if not is_ml_query and (best_score - second_score) < CONFIDENCE_GAP:
#         return None

#     entry = FAQ_EMB_META[best_idx]

#     if entry["type"] == "sentiment":
#         faq      = entry["faq"]
#         answer, _ = pick_answer(faq["answers"], query_sentiment)
#         norm      = normalize(query)
#         esc_kw    = faq.get("escalate_if", {}).get("keywords", [])
#         escalate  = bool(esc_kw and any(kw.lower() in norm for kw in esc_kw))
#         return {
#             "faq_id":      faq.get("id", ""),
#             "category":    faq.get("category", "general"),
#             "faq_source":  faq.get("source", "sentiment_aware"),
#             "answer":      answer,   # raw — resolve_for_slug applied in match_faq
#             "answer_lang": "english",
#             "score":       round(best_score, 3),
#             "escalate":    escalate,
#         }
#     else:
#         item = entry["item"]
#         src  = item.get("source", "english")
#         lang = "manglish" if src.startswith("manglish") else "english"
#         return {
#             "faq_id":      item.get("id", ""),
#             "category":    item.get("section", "general"),
#             "faq_source":  src,
#             "answer":      item["a"],   # raw — resolve_for_slug applied in match_faq
#             "answer_lang": lang,
#             "score":       round(best_score, 3),
#             "escalate":    False,
#         }


# def fuzzy_pass(
#     norm_query: str,
#     pool: list[dict],
#     is_ml_query: bool = False,
# ) -> dict | None:
#     best_score  = -1.0
#     best_result = None

#     for item in pool:
#         all_qs = [item.get("q", "")] + item.get("variants", [])
#         score  = max(fuzzy_match(norm_query, q) for q in all_qs if q)

#         src = item.get("source", "english")
#         if is_ml_query and src.startswith("manglish"):
#             score = min(score * MANGLISH_BOOST, 1.0)

#         if score >= FUZZY_THRESHOLD and score > best_score:
#             best_score  = score
#             answer_lang = "manglish" if src.startswith("manglish") else "english"
#             best_result = {
#                 "faq_id":      item.get("id", ""),
#                 "category":    item.get("section", "general"),
#                 "faq_source":  src,
#                 "answer":      item["a"],   # raw — resolve_for_slug applied in match_faq
#                 "answer_lang": answer_lang,
#                 "score":       round(score, 3),
#                 "escalate":    False,
#             }

#     return best_result


# def match_faq(query: str, query_sentiment: str, slug: str | None = None) -> dict | None:
#     """
#     FAQ matching pipeline:
#       Pass 0   — Shop FAQ priority check (shop_faq.json always wins if score ≥ 0.45)
#       Pass 1   — Intent detection (narrows F1 pool + semantic search slice)
#       Pass 2   — Semantic cosine match (threshold 0.52)
#       Pass 2.5 — Fuzzy match via rapidfuzz (threshold 0.72)
#       Pass 3   — F1 token overlap with synonym expansion (threshold 0.45)

#     FIX v5.6.2: accepts slug param. All returned answers are resolved via
#     resolve_for_slug(answer, slug) so {whatsapp}, {location} etc. always
#     contain the correct shop's values — NOT the root config's values.
#     """
#     norm_query = normalize(query)
#     intent     = detect_intent(norm_query)
#     manglish   = is_manglish(query)

#     def _resolve(text: str) -> str:
#         """Resolve a raw answer using the slug-specific config."""
#         return resolve_for_slug(text, slug)

#     def _resolve_result(result: dict | None) -> dict | None:
#         """Apply slug-aware resolution to the answer field of a result dict."""
#         if result is None:
#             return None
#         result = dict(result)
#         result["answer"] = _resolve(result["answer"])
#         return result

#     # ── Pass 0: Shop FAQ priority ──────────────────────────────────────────
#     if SHOP_EMB_VECTORS is not None and SHOP_FLAT and embedder is not None:
#         try:
#             from sentence_transformers import util as st_util
#             q_vec    = embedder.encode([norm_query], normalize_embeddings=True,
#                                        convert_to_tensor=True)
#             scores   = st_util.cos_sim(q_vec, SHOP_EMB_VECTORS)[0]
#             best_idx = int(scores.argmax())
#             best_sc  = float(scores[best_idx])
#             if best_sc >= 0.45:
#                 item = SHOP_EMB_META[best_idx]
#                 return {
#                     "answer":      _resolve(item["a"]),
#                     "answer_lang": item.get("lang", "english"),
#                     "faq_source":  "shop_faq",
#                     "faq_id":      item.get("id", ""),
#                     "faq_score":   round(best_sc, 3),
#                     "escalate":    False,
#                 }
#         except Exception as e:
#             print(f"[faq_engine] ⚠   Shop FAQ Pass 0 error: {e}")

#     # ── Pass 1: Intent detection ──────────────────────────────────────────
#     # FIX v5.6.1 BUG 5: sections MUST be defined before ml_filtered/en_filtered
#     sections    = _INTENT_MAP.get(intent, []) if intent else []
#     ml_filtered = _filter_by_intent(FAQS_MANGLISH + FAQS_MANGLISH_SENTIMENT, sections) if sections else []
#     en_filtered = _filter_by_intent(FAQS_ENGLISH  + FAQS_ENGLISH_SENTIMENT,  sections) if sections else []

#     sem = semantic_match(norm_query, query_sentiment, intent=intent, is_ml_query=manglish)
#     if sem:
#         if not manglish:
#             return _resolve_result(sem)
#         if sem["answer_lang"].startswith("manglish"):
#             return _resolve_result(sem)
#         # English semantic result held — continue searching for native Manglish

#     # ── Pass 1.5: fuzzy match ──────────────────────────────────────────────
#     flat_pool = (
#         FAQS_MANGLISH + FAQS_MANGLISH_SENTIMENT
#         + FAQS_ENGLISH + FAQS_ENGLISH_SENTIMENT
#         + SHOP_FLAT
#     )
#     fuz = fuzzy_pass(norm_query, flat_pool, is_ml_query=manglish)
#     if fuz:
#         if not manglish:
#             return _resolve_result(fuz)
#         if fuz["answer_lang"].startswith("manglish"):
#             return _resolve_result(fuz)
#         # English fuzzy result held — continue to F1 for native Manglish

#     # ── Pass 2: F1 with synonym expansion ─────────────────────────────────
#     q_tokens = expand_synonyms(tokenize(norm_query))

#     best_score      = -1.0
#     best_n_variants = 0
#     best_result: dict | None = None

#     def _update(score: float, candidate: dict, n_variants: int = 1) -> None:
#         nonlocal best_score, best_n_variants, best_result
#         if score > best_score or (score == best_score and n_variants > best_n_variants):
#             best_score      = score
#             best_n_variants = n_variants
#             best_result     = candidate

#     # Sentiment-aware FAQs
#     for faq in FAQS_SENTIMENT + SHOP_SENT:
#         _faq_n = sum(len(qs) for qs in faq.get("questions", {}).values())
#         for sent_key, questions in faq.get("questions", {}).items():
#             for q_text in questions:
#                 score = f1_score(q_tokens, q_text)
#                 if score > 0:
#                     answer, _ = pick_answer(faq["answers"], query_sentiment)
#                     esc_kw    = faq.get("escalate_if", {}).get("keywords", [])
#                     escalate  = bool(esc_kw and any(kw.lower() in norm_query for kw in esc_kw))
#                     _update(score, {
#                         "faq_id":      faq.get("id", ""),
#                         "category":    faq.get("category", "general"),
#                         "faq_source":  faq.get("source", "sentiment_aware"),
#                         "answer":      answer,   # raw
#                         "answer_lang": "english",
#                         "score":       score,
#                         "escalate":    escalate,
#                     }, n_variants=_faq_n)

#     # Manglish FAQs — searched first + boosted
#     manglish_pool = ml_filtered + [
#         f for f in FAQS_MANGLISH + FAQS_MANGLISH_SENTIMENT + SHOP_FLAT
#         if f not in ml_filtered
#         and (f.get("source", "") in ("manglish", "manglish_sentiment")
#              or "shop" in f.get("source", ""))
#     ]
#     for item in manglish_pool:
#         src = item.get("source", "")
#         if src not in ("manglish", "manglish_sentiment") and "shop" not in src:
#             continue
#         all_qs = [item["q"]] + item.get("variants", [])
#         raw    = max(f1_score(q_tokens, q) for q in all_qs)
#         if manglish and raw > 0:
#             q_content    = set(q_tokens) - _MANGLISH_PARTICLES
#             faq_all_text = " ".join(all_qs)
#             faq_content  = set(tokenize(faq_all_text)) - _MANGLISH_PARTICLES
#             if q_content and faq_content and not (q_content & faq_content):
#                 raw = 0.0
#         score = raw * MANGLISH_BOOST if manglish else raw
#         _update(score, {
#             "faq_id":      item.get("id", ""),
#             "category":    item.get("section", "general"),
#             "faq_source":  src,
#             "answer":      item["a"],   # raw
#             "answer_lang": "manglish",
#             "score":       score,
#             "escalate":    False,
#         }, n_variants=len(all_qs))

#     # English FAQs
#     english_pool = en_filtered + [f for f in FAQS_ENGLISH + FAQS_ENGLISH_SENTIMENT
#                                    if f not in en_filtered]
#     for item in english_pool:
#         all_qs = [item["q"]] + item.get("variants", [])
#         score  = max(f1_score(q_tokens, q) for q in all_qs)
#         _update(score, {
#             "faq_id":      item.get("id", ""),
#             "category":    item.get("section", "general"),
#             "faq_source":  "english",
#             "answer":      item["a"],   # raw
#             "answer_lang": "english",
#             "score":       score,
#             "escalate":    False,
#         }, n_variants=len(all_qs))

#     # ── Final priority resolution for Manglish queries ──
#     if manglish and best_score >= FAQ_THRESHOLD and best_result:
#         if best_result["answer_lang"].startswith("manglish"):
#             best_result["score"] = round(best_score, 3)
#             return _resolve_result(best_result)
#         candidates = [(best_score, best_result)]
#         if sem:
#             candidates.append((sem["score"], sem))
#         if fuz:
#             candidates.append((fuz["score"], fuz))
#         best_candidate = max(candidates, key=lambda x: x[0])
#         result = best_candidate[1]
#         result["score"] = round(best_candidate[0], 3)
#         return _resolve_result(result)

#     # Non-Manglish: standard priority
#     if sem and best_score >= FAQ_THRESHOLD and best_result:
#         return _resolve_result(sem)

#     if fuz and (best_result is None or best_score < FAQ_THRESHOLD):
#         return _resolve_result(fuz)

#     if best_score < FAQ_THRESHOLD or best_result is None:
#         if manglish:
#             if sem:
#                 return _resolve_result(sem)
#             if fuz:
#                 return _resolve_result(fuz)
#         return None

#     best_result["score"] = round(best_score, 3)
#     return _resolve_result(best_result)












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
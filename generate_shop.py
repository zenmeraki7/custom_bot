
"""
generate_shop.py — v8.1  (GPU-enforced, production-ready)
Universal shop config + FAQ generator from extracted items.
 
What changed in v8.1
─────────────────────
  FIX GPU  call_ollama() now passes num_gpu=999, num_ctx=2048, keep_alive=-1
           on EVERY Ollama call — covers infer_shop_type, detect_veg,
           detect_shop_gender, detect_specialisation, infer_hours_location,
           infer_shop_name, infer_signature_items, infer_item_gender,
           infer_category.  Previously all timed out on RTX 3050 4GB because
           they had no GPU options and a 30-second hard timeout.
 
  FIX TIMEOUT  Raised from 30s → 60s.  First Ollama call after cold start
               on a 4GB GPU can take 15–25s to load the model into VRAM.
 
  FIX OLLAMA_AVAILABLE  Single availability check at module load time.
           If Ollama is down, all infer_* functions return keyword-based
           fallbacks instantly instead of hanging for 60s each.
 
FAQ MERGE STRATEGY (unchanged from v8.0):
  Layer 1 — data/english.json + data/manglish.json
  Layer 2 — data/english_sentiment.json + data/manglish_sentiment.json
  Layer 3 — faq_templates/{shop_type}_english.json + _manglish.json
  Layer 4 — core_faqs (contact, hours, location, payment)
  Layer 5 — item_faqs (catalogue + pricing)
"""
 
import json
import os
import re
import sys
import argparse
from collections import defaultdict
from pathlib import Path
import requests
 
from dynamic_shop_profile import get_shop_profile_with_cache, ShopProfile  # pyright: ignore
 
# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
 
import ollama_client

# ── PDF-GROUNDED FAQ POLICY ──────────────────────────────────────────────
# Every shop's FAQ pool is built ONLY from its own extracted PDF:
#   core (extracted shop info) + type templates (answers RAG-grounded from
#   the PDF by populate_faq_from_pdf) + items (extracted price list).
# The generic 441-entry "common" pack is EXCLUDED — it injected parcel/
# courier/checkout answers into service shops ("evide anu" → order
# tracking). Flip to True only if you knowingly want generic FAQs.
INCLUDE_COMMON_FAQS = False
 
# Ollama config now lives in ollama_client.py

DEFAULTS = {
    "shop_name":        "Our Shop",
    "shop_type":        "general",
    "hours_weekdays":   "Mon–Sat 9AM–8PM",
    "hours_sunday":     "Sunday 10AM–6PM",
    "hours_holiday":    "Check WhatsApp for holiday hours",
    "location":         "Kerala, India",
    "whatsapp":         "+91 00000 00000",
    "email":            "support@example.com",
    "payment":          ["UPI", "Cards", "Cash"],
    "delivery_areas":   "Local area",
    "delivery_free":    "₹500",
    "delivery_days":    "2–3 working days",
    "return_days":      7,
    "return_condition": "unused with original packaging",
    "refund_days":      "5–7 business days",
    "offer_code":       "WELCOME10",
    "offer_desc":       "10% off for new customers",
}
 
# Filename → shop_type mapping (handles typos in existing template files)
TEMPLATE_FILENAME_MAP: dict[str, str] = {
    "restaurant":          "restaurant",
    "resaturent":          "restaurant",
    "restaurent":          "restaurant",
    "bakery":              "bakery",
    "beauty_parlour":      "beauty_parlour",
    "beautyparlour":       "beauty_parlour",
    "gym":                 "gym",
    "pharmacy":            "pharmacy",
    "clothing":            "clothing",
    "electronics":         "electronics",
    "electronic_products": "electronics",
    "electronic_product":  "electronics",
    "jewellery":           "jewellery",
    "jewelry":             "jewellery",
    "optical":             "optical",
    "opticals":            "optical",
    "hotel":               "hotel",
    "supermarket":         "supermarket",
    "school":              "school",
    "scool":               "school",
    "travel_agency":       "travel_agency",
    "real_estate":         "real_estate",
    "law_firm":            "law_firm",
    "ca_firm":             "ca_firm",
    "dental_clinic":       "dental_clinic",
    "salon":               "salon",
    "cafe":                "cafe",
    "pet_shop":            "pet_shop",
    "driving_school":      "driving_school",
    "drvingschool":        "driving_school",
    "furniture_shop":      "furniture_shop",
    "mobile_shop":         "mobile_shop",
    "laundry_service":     "laundry_service",
    "tailoring_shop":      "tailoring_shop",
    "coaching_center":     "coaching_center",
    "spa":                 "spa",
    "hardware_store":      "hardware_store",
    "diagnostic_center":   "diagnostic_center",
    "photography":         "photography",
    "photography_studio":  "photography",
    "courier_service":     "courier_service",
    "event_management":    "event_management",
    "footwear_shop":       "footwear_shop",
    "hr_consultant":       "hr_consultant",
    "immigration":         "immigration",
    "hospital":            "hospital",
}
 
VEG_NAME_SIGNALS: list[str] = [
    "veg", "pure veg", "satvic", "satvik", "brahmin", "jain",
    "shudh", "shuddh", "sattvik",
]
 
NON_VEG_ITEM_SIGNALS: list[str] = [
    "chicken", "mutton", "beef", "pork", "fish", "prawn", "shrimp",
    "crab", "lobster", "egg", "meat", "lamb", "turkey", "tuna",
    "salmon", "sardine", "anchovy", "bacon", "sausage", "keema",
]
 
SHOP_GENDER_NAME_SIGNALS: dict[str, list[str]] = {
    "babies": ["baby", "infant", "toddler", "newborn", "kids wear", "baby store", "baby shop"],
    "boys":   ["boys", "boy", "junior boys", "gents boy"],
    "girls":  ["girls", "girl", "junior girls"],
    "kids":   ["kids", "children", "child", "junior"],
    "men":    ["mens", "men's", "gents", "male", "man"],
    "women":  ["womens", "women's", "ladies", "female", "woman", "girl"],
    "unisex": ["unisex", "all gender", "everyone"],
}
 
SPECIALISATION_SIGNALS: dict[str, tuple[str, list[str]]] = {
    "cake":     ("bakery",         ["Cakes", "Pastries"]),
    "cakes":    ("bakery",         ["Cakes", "Pastries"]),
    "pastry":   ("bakery",         ["Cakes", "Pastries"]),
    "bread":    ("bakery",         ["Breads", "Snacks"]),
    "biryani":  ("restaurant",     ["Biryani", "Rice", "Curries"]),
    "seafood":  ("restaurant",     ["Seafood", "Starters", "Rice", "Curries"]),
    "shawarma": ("restaurant",     ["Starters", "Snacks", "Beverages"]),
    "pizza":    ("restaurant",     ["Starters", "Snacks", "Beverages", "Desserts"]),
    "chinese":  ("restaurant",     ["Noodles", "Rice", "Starters", "Soups", "Beverages"]),
    "coffee":   ("restaurant",     ["Beverages", "Snacks", "Desserts"]),
    "saree":    ("clothing",       ["Sarees", "Accessories"]),
    "kurta":    ("clothing",       ["Kurtas", "Ethnic Wear", "Accessories"]),
    "bridal":   ("beauty_parlour", ["Bridal Makeup", "Hair Spa", "Facial", "Skin Care"]),
    "yoga":     ("gym",            ["Yoga", "Group Classes", "Diet Plans"]),
    "zumba":    ("gym",            ["Group Classes", "Cardio"]),
}
 
GENDER_KEYWORDS: dict[str, list[str]] = {
    "babies": ["baby", "infant", "toddler", "newborn"],
    "boys":   ["boys", "boy", "junior boys", "kids boys"],
    "girls":  ["girls", "girl", "junior girls", "kids girls"],
    "kids":   ["kids", "children", "child", "junior"],
    "men":    ["men", "male", "gents", "man", "mens"],
    "women":  ["women", "female", "ladies", "woman", "womens"],
    "unisex": ["unisex", "universal", "all gender", "both"],
    "all":    ["all", "everyone"],
}
 
# Keyword-based shop type fallback — used when Ollama is unavailable
_KEYWORD_SHOP_TYPE: dict[str, list[str]] = {
    "beauty_parlour": [
        "facial", "wax", "threading", "makeup", "bridal", "hair colour",
        "manicure", "pedicure", "salon", "parlour", "balayage", "highlights",
        "hair spa", "keratin", "nail", "skin care", "bleach",
    ],
    "restaurant": [
        "biryani", "chicken", "mutton", "fish", "dosa", "idli", "curry",
        "rice", "noodles", "soup", "starter", "dessert", "pizza", "burger",
        "shawarma", "parotta", "appam", "roti", "meal", "lunch", "dinner",
    ],
    "bakery": [
        "cake", "pastry", "bread", "cookie", "muffin", "croissant",
        "brownie", "cupcake", "tart", "donut", "bun", "puff",
    ],
    "gym": [
        "membership", "trainer", "workout", "cardio", "yoga", "zumba",
        "weights", "treadmill", "crossfit", "fitness",
    ],
    "pharmacy": [
        "tablet", "syrup", "medicine", "capsule", "injection", "cream",
        "ointment", "vitamin", "supplement", "prescription",
    ],
    "jewellery": [
        "gold", "silver", "diamond", "ring", "necklace", "earring",
        "bracelet", "bangle", "chain", "pendant", "hallmark",
    ],
    "electronics": [
        "mobile", "laptop", "tv", "refrigerator", "washing machine",
        "speaker", "headphone", "charger", "cable", "tablet",
    ],
    "clothing": [
        "shirt", "dress", "kurta", "saree", "jeans", "trouser",
        "leggings", "top", "kurti", "suit", "blouse",
    ],
    "dental_clinic": [
        "tooth", "dental", "braces", "filling", "root canal",
        "extraction", "whitening", "crown", "implant",
    ],
    "hospital": [
        "doctor", "consultation", "ward", "surgery", "x-ray",
        "scan", "blood test", "icu", "emergency", "opd",
    ],
    "hotel": [
        "room", "suite", "checkin", "checkout", "ac room",
        "deluxe", "breakfast", "buffet", "banquet",
    ],
    "optical": [
        "spectacles", "lens", "frame", "glasses", "contact lens",
        "eye test", "power", "sunglasses",
    ],
}
 
 
def _keyword_infer_shop_type(items: list) -> str:
    """Fast keyword-based shop type detection — used as Ollama fallback."""
    names = " ".join(it.get("name", "").lower() for it in items[:30])
    scores: dict[str, int] = defaultdict(int)
    for stype, keywords in _KEYWORD_SHOP_TYPE.items():
        for kw in keywords:
            if kw in names:
                scores[stype] += 1
    if scores:
        best = max(scores, key=lambda k: scores[k])
        if scores[best] >= 2:
            return best
    return "general"
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  OLLAMA AVAILABILITY CHECK
#  Single 3-second ping at module import time.
#  If Ollama is down, all infer_* functions use keyword/regex fallbacks.
#  This prevents 5 × 60s timeouts during generate-shop requests.
# ══════════════════════════════════════════════════════════════════════════════
 
def _check_ollama_available() -> bool:
    import ollama_client
    return ollama_client.is_up()

def _load_json_file(path: str | Path) -> list | dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []
 
 
def _faq_key(q: str, a: str) -> tuple:
    return (q.strip().lower(), a.strip().lower()[:80])
 
 
def load_common_faqs(data_dir: str = "data") -> list[dict]:
    files = [
        "english.json", "manglish.json",
        "english_sentiment.json", "manglish_sentiment.json",
    ]
    combined: list[dict] = []
    seen: set = set()
 
    for fname in files:
        path = Path(data_dir) / fname
        if not path.exists():
            continue
        raw = _load_json_file(path)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            variants = item.get("question_variants", [])
            answer   = item.get("answer", "").strip()
            if not variants or not answer:
                continue
            key = _faq_key(variants[0], answer)
            if key in seen:
                continue
            seen.add(key)
            combined.append({
                "id":                item.get("id", ""),
                "category":          item.get("category", "general"),
                "question_variants": variants,
                "answer":            answer,
                "source":            "common",
            })
 
    print(f"[faq_loader] common FAQs loaded: {len(combined)} entries")
    return combined
 
 
def _find_template_file(shop_type: str, lang: str, templates_dir: str = "faq_templates") -> Path | None:
    reverse: dict[str, list[str]] = defaultdict(list)
    for stem, stype in TEMPLATE_FILENAME_MAP.items():
        reverse[stype].append(stem)
 
    base       = Path(templates_dir)
    candidates = reverse.get(shop_type, [shop_type])
 
    for stem in candidates:
        p = base / f"{stem}_{lang}.json"
        if p.exists():
            return p
    return None
 
 
def load_template_faqs(shop_type: str, templates_dir: str = "faq_templates") -> list[dict]:
    en_path = _find_template_file(shop_type, "english",  templates_dir)
    ml_path = _find_template_file(shop_type, "manglish", templates_dir)
 
    if not en_path and not ml_path:
        print(f"[faq_loader] no template file found for shop_type='{shop_type}'")
        return []
 
    def _parse_template(path: Path) -> dict[str, dict]:
        raw  = _load_json_file(path)
        faqs = raw.get("faqs", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
        result = {}
        for item in faqs:
            cat = item.get("category", "general")
            q   = item.get("question", "").strip()
            a   = item.get("answer", "").strip()
            if q and a:
                result[cat] = {"question": q, "answer": a}
        return result
 
    en_map   = _parse_template(en_path) if en_path else {}
    ml_map   = _parse_template(ml_path) if ml_path else {}
    all_cats = set(en_map.keys()) | set(ml_map.keys())
 
    combined: list[dict] = []
    seen: set = set()
 
    for cat in all_cats:
        en        = en_map.get(cat, {})
        ml        = ml_map.get(cat, {})
        answer    = en.get("answer") or ml.get("answer", "")
        answer_ml = ml.get("answer", "")
        variants  = []
        if en.get("question"):
            variants.append(en["question"])
        if ml.get("question") and ml["question"] != en.get("question"):
            variants.append(ml["question"])
        if not variants or not answer:
            continue
        key = _faq_key(variants[0], answer)
        if key in seen:
            continue
        seen.add(key)
        entry: dict = {
            "id":                f"{shop_type}_{cat}",
            "category":          cat,
            "question_variants": variants,
            "answer":            answer,
            "source":            "template",
        }
        if answer_ml and answer_ml != answer:
            entry["answer_ml"] = answer_ml
        combined.append(entry)
 
    print(f"[faq_loader] template FAQs loaded for '{shop_type}': {len(combined)} entries "
          f"(en={len(en_map)}, ml={len(ml_map)})")
    return combined
 
 
def merge_faq_layers(*layers: list[dict]) -> list[dict]:
    seen: set    = set()
    merged: list = []
    for layer in layers:
        for item in layer:
            variants = item.get("question_variants", [])
            answer   = item.get("answer", "")
            if not variants or not answer:
                continue
            key = _faq_key(variants[0], answer)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  OLLAMA CALL — GPU OPTIONS ON EVERY CALL
# ══════════════════════════════════════════════════════════════════════════════
 
def call_ollama(prompt: str, system: str = "") -> str:
    reply, ok = ollama_client.generate(
        prompt, system=system or None, temperature=0.1, num_predict=400,
    )
    return reply if ok else ""

def infer_shop_type(items: list) -> str:
    if not _check_ollama_available():
        result = _keyword_infer_shop_type(items)
        print(f"[infer_shop_type] keyword fallback → {result}")
        return result
 
    sample = [it.get("name", "") for it in items[:20]]
    valid  = [
        "clothing", "gym", "beauty_parlour", "restaurant", "bakery",
        "electronics", "pharmacy", "jewellery", "optical", "school",
        "dental_clinic", "hospital", "hotel", "supermarket", "travel_agency",
        "real_estate", "law_firm", "ca_firm", "driving_school",
        "photography", "courier_service", "event_management",
        "footwear_shop", "furniture_shop", "hr_consultant", "immigration",
        "general",
    ]
    prompt = (
        f"Given these product/service names, what is the most likely shop type? "
        f"Choose ONLY one word from: {', '.join(valid)}.\n"
        f"Return only that single word.\n\nProducts: {', '.join(sample)}"
    )
    reply = call_ollama(prompt).lower().strip()
    for t in valid:
        if t in reply:
            return t
 
    # Ollama responded but didn't match — use keyword fallback
    result = _keyword_infer_shop_type(items)
    print(f"[infer_shop_type] Ollama reply '{reply}' unrecognised → keyword fallback → {result}")
    return result
 
 
def detect_veg(items: list, shop_name: str, shop_type: str, use_ollama: bool = True) -> bool:
    if shop_type not in ("restaurant", "bakery"):
        return False
    if any(sig in shop_name.lower() for sig in VEG_NAME_SIGNALS):
        return True
    for item in items:
        if any(sig in item.get("name", "").lower() for sig in NON_VEG_ITEM_SIGNALS):
            return False
    if use_ollama and _check_ollama_available() and items:
        sample = [it.get("name", "") for it in items[:20]]
        reply  = call_ollama(
            f"Is this a pure vegetarian restaurant?\nShop: {shop_name}\n"
            f"Menu: {', '.join(sample)}\nAnswer only: yes or no"
        ).lower().strip()
        return reply.startswith("yes")
    return False
 
 
def detect_shop_gender(items: list, shop_name: str, shop_type: str, use_ollama: bool = True) -> str:
    if shop_type in {
        "restaurant", "bakery", "electronics", "pharmacy", "general",
        "beauty_parlour", "spa", "salon", "dental_clinic", "hospital",
        "law_firm", "ca_firm", "school", "travel_agency", "hotel",
        "supermarket", "courier_service", "event_management",
        "hr_consultant", "immigration", "ca_firm", "photography",
    }:
        return "all"
 
    lower_name = shop_name.lower()
    valid      = list(GENDER_KEYWORDS.keys())
 
    for gender, keywords in SHOP_GENDER_NAME_SIGNALS.items():
        if gender not in valid:
            continue
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', lower_name):
                return gender
 
    gender_counts: dict[str, int] = defaultdict(int)
    for it in items:
        g = it.get("gender", "")
        if g and g != "all":
            gender_counts[g] += 1
    total = sum(gender_counts.values())
    if total > 0:
        top_g, top_c = max(gender_counts.items(), key=lambda x: x[1])
        if top_c / total >= 0.90 and top_g in valid:
            return top_g
 
    if use_ollama and _check_ollama_available():
        sample = [it.get("name", "") for it in items[:15]]
        reply  = call_ollama(
            f"Is this shop for one gender? Shop: {shop_name}\n"
            f"Items: {', '.join(sample)}\nChoose ONE from: {', '.join(valid)}, all\n"
            f"Return only the single word."
        ).lower().strip()
        for g in valid:
            if g in reply:
                return g
 
    return "all"
 
 
def detect_specialisation(
    items: list, shop_name: str, shop_type: str,
    use_ollama: bool = True, _profile_cats: list | None = None,
) -> tuple[str | None, list[str]]:
    lower_name = shop_name.lower()
    full_cats  = _profile_cats or ["General"]
 
    for signal, (target_type, cats) in SPECIALISATION_SIGNALS.items():
        if target_type != shop_type:
            continue
        if re.search(r'\b' + re.escape(signal) + r'\b', lower_name):
            valid_cats = [c for c in cats if c in full_cats]
            if valid_cats:
                return signal, valid_cats
 
    cat_counts: dict[str, int] = defaultdict(int)
    for it in items:
        c = it.get("category", "")
        if c:
            cat_counts[c] += 1
    if cat_counts:
        total    = sum(cat_counts.values())
        top_cats = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
        acc, chosen = 0, []
        for cat, cnt in top_cats:
            acc += cnt
            chosen.append(cat)
            if acc / total >= 0.80:
                break
        if len(chosen) <= 2 and acc / total >= 0.80:
            return "+".join(c.lower() for c in chosen), chosen
 
    if use_ollama and _check_ollama_available() and len(full_cats) > 4:
        sample = [it.get("name", "") for it in items[:20]]
        reply  = call_ollama(
            f"Does this shop specialise in only a few from {full_cats}?\n"
            f"Shop: {shop_name}\nItems: {', '.join(sample)}\n"
            f"List matching categories as comma-separated names, or 'all'.",
            system="Return only category names from the list, or 'all'."
        )
        if reply.lower().strip() != "all":
            matched = [c for c in full_cats if c.lower() in reply.lower()]
            if matched:
                return "ollama_inferred", matched
 
    return None, full_cats
 
 
def infer_shop_name(items: list, fallback: str) -> str:
    if not _check_ollama_available():
        return fallback
    sample = [it.get("name", "") for it in items[:10]]
    reply  = call_ollama(
        f"Based on these products, suggest a short shop name (max 3 words). "
        f"Products: {', '.join(sample)}"
    )
    return reply if reply and len(reply.split()) <= 5 else fallback
 
 
def infer_hours_location(shop_type: str) -> dict:
    if not _check_ollama_available():
        return {k: DEFAULTS[k] for k in ("hours_weekdays", "hours_sunday", "location")}
    reply = call_ollama(
        f"For a typical {shop_type} in Kerala, suggest opening hours and location. "
        f'Return JSON: {{"hours_weekdays":"...","hours_sunday":"...","location":"..."}}',
        system="Return only valid JSON, no explanation."
    )
    try:
        data = json.loads(reply)
        return {
            "hours_weekdays": data.get("hours_weekdays", DEFAULTS["hours_weekdays"]),
            "hours_sunday":   data.get("hours_sunday",   DEFAULTS["hours_sunday"]),
            "location":       data.get("location",       DEFAULTS["location"]),
        }
    except Exception:
        return {k: DEFAULTS[k] for k in ("hours_weekdays", "hours_sunday", "location")}
 
 
def infer_item_gender(item_name: str, shop_type: str) -> str:
    if shop_type in {
        "restaurant", "bakery", "electronics", "pharmacy", "general",
        "beauty_parlour", "spa", "salon", "dental_clinic", "hospital",
        "law_firm", "ca_firm", "school", "travel_agency",
    }:
        return "all"
    lower = item_name.lower()
    for gender, keywords in GENDER_KEYWORDS.items():
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', lower):
                return gender
    if not _check_ollama_available():
        return "all"
    reply = call_ollama(
        f"What gender is this product for? Choose from: {', '.join(GENDER_KEYWORDS)}. "
        f"Product: {item_name}\nReturn only the single word."
    ).lower().strip()
    for g in GENDER_KEYWORDS:
        if g in reply:
            return g
    return "all"
 
 
def infer_category(item_name: str, shop_type: str, allowed_cats: list | None = None) -> str:
    cats = allowed_cats or ["General"]
    if not _check_ollama_available():
        return cats[0]
    reply = call_ollama(
        f"Which category from {cats} best fits '{item_name}'? "
        f"Return ONLY the category name."
    )
    for cat in cats:
        if cat.lower() in reply.lower():
            return cat
    return cats[0]
 
 
def infer_signature_items(items: list, shop_type: str) -> str:
    priced = sorted(
        [it for it in items if it.get("price")],
        key=lambda x: x.get("price", 0), reverse=True,
    )
    if len(priced) >= 2:
        return ", ".join(it["name"] for it in priced[:3])
    if not _check_ollama_available():
        return ", ".join(it.get("name", "") for it in items[:3])
    sample = [it.get("name", "") for it in items[:15]]
    reply  = call_ollama(
        f"From these {shop_type} items: {', '.join(sample)}, "
        f"list 3 signature ones as comma-separated names."
    )
    return reply or ""
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  ENRICH ITEMS
# ══════════════════════════════════════════════════════════════════════════════
 
def enrich_items(
    items: list, shop_type: str, use_ollama: bool = True,
    shop_gender: str = "all", allowed_categories: list | None = None,
) -> list:
    enriched      = []
    valid_genders = list(GENDER_KEYWORDS.keys())
    allowed_cats  = allowed_categories or ["General"]
    single_gender = shop_gender != "all"
 
    for item in items:
        item = item.copy()
        if single_gender:
            item["gender"] = shop_gender
        elif not item.get("gender"):
            item["gender"] = (
                infer_item_gender(item.get("name", ""), shop_type)
                if use_ollama else "all"
            )
        else:
            provided       = item["gender"].lower().strip()
            item["gender"] = next(
                (g for g in valid_genders if g in provided or provided in g), "all"
            )
 
        if not item.get("category"):
            item["category"] = (
                infer_category(item.get("name", ""), shop_type, allowed_cats)
                if use_ollama else (allowed_cats[0] if allowed_cats else "General")
            )
        else:
            if item["category"].strip() not in allowed_cats:
                item["category"] = (
                    infer_category(item.get("name", ""), shop_type, allowed_cats)
                    if use_ollama else (allowed_cats[0] if allowed_cats else item["category"])
                )
        enriched.append(item)
    return enriched
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  FORMAT PRICE
# ══════════════════════════════════════════════════════════════════════════════
 
def format_price(item: dict) -> str:
    if "price" in item:
        return f"₹{item['price']:,}"
    if "price_min" in item and "price_max" in item:
        return f"₹{item['price_min']:,} – ₹{item['price_max']:,}"
    return "price on request"
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  ITEM-BASED FAQs (Layer 5)
# ══════════════════════════════════════════════════════════════════════════════
 
def build_item_faqs(
    items: list, shop_type: str, is_veg: bool = False,
    shop_gender: str = "all", specialisation: str | None = None,
    profile: "ShopProfile | None" = None,
) -> list:
    if not items:
        return []
 
    faqs:     list = []
    seen_ids: set  = set()
 
    item_label  = profile.item_label if profile else "items"
    q_templates = profile.faq_templates if profile else [
        "{gender_cat} undo?", "{gender_cat} available aano?",
        "{gender_cat} kittumo?", "Do you have {gender_cat}?",
        "What {gender_cat} do you offer?",
    ]
    veg_badge   = " 🌿" if is_veg and shop_type in ("restaurant", "bakery") else ""
    # Check the sentinel BEFORE replacing underscores — the old order turned
    # "ollama_inferred" into "ollama inferred", the check never matched, and
    # the internal flag leaked into customer-facing FAQ questions
    # ("ollama inferred haircuts available aano?").
    spec_prefix = (specialisation or "").strip()
    if spec_prefix in ("ollama_inferred", "all", "-", ""):
        spec_prefix = ""
    else:
        spec_prefix = spec_prefix.replace("+", "/").replace("_", " ")
 
    by_cat_gender: dict = defaultdict(list)
    for it in items:
        by_cat_gender[
            (it.get("category", "General").strip(), it.get("gender", "all").strip())
        ].append(it)
 
    for (cat, gen), cat_items in by_cat_gender.items():
        if shop_gender != "all" and gen not in (shop_gender, "all"):
            continue
        slug_key = re.sub(r'[^a-z0-9_]', '_', f"{gen}_{cat}".lower())[:40]
        faq_id   = f"cat_{slug_key}"
        if faq_id in seen_ids:
            continue
        seen_ids.add(faq_id)
 
        prefix = (
            cat if (shop_gender != "all" and gen == shop_gender)
            else f"{gen.capitalize()} {cat}" if gen != "all"
            else cat
        )
 
        lines  = [f"• {it['name']} — {format_price(it)}" for it in cat_items[:10]]
        answer = f"{prefix} {item_label}{veg_badge}:\n" + "\n".join(lines)
        if len(cat_items) > 10:
            answer += f"\n...and {len(cat_items) - 10} more. WhatsApp {{whatsapp}} for full list."
 
        parts = []
        if is_veg and shop_type in ("restaurant", "bakery"):
            parts = ["veg"]
        if spec_prefix:
            parts.append(spec_prefix)
        if shop_gender == "all" and gen != "all":
            parts.append(gen)
        parts.append(cat.lower())
 
        variants = [t.format(gender_cat=" ".join(parts)) for t in q_templates]
        faq: dict = {
            "id": faq_id, "category": "catalog",
            "question_variants": variants, "answer": answer,
        }
        if shop_type in ("restaurant", "bakery"):
            faq["dietary"] = "veg_only" if is_veg else "veg_nonveg"
        faqs.append(faq)
 
    for it in items:
        name = it.get("name", "")
        if not name or len(name) < 3:
            continue
        faq_id = "item_" + re.sub(r'[^a-z0-9]', '_', name.lower())[:30]
        if faq_id in seen_ids:
            continue
        seen_ids.add(faq_id)
 
        variants = [
            f"How much is {name}?",
            f"Price of {name}?",
            f"{name} vila enthu?",
            f"{name} rate?",
            f"Is {name} available?",
            f"{name} undo?",
        ]
        desc = it.get("description", "").strip()
        if desc:
            variants += [f"What is {name}?", f"{name} enthu aanu?"]
 
        price_str = format_price(it)
        answer    = (
            f"{name} — {price_str} ({desc}). WhatsApp {{whatsapp}} for details."
            if desc else
            f"{name} — {price_str}. WhatsApp {{whatsapp}} for details."
        )
 
        faqs.append({
            "id": faq_id, "category": "pricing",
            "question_variants": variants,
            "answer": answer,
        })
 
    return faqs
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  CORE FAQs (Layer 4)
# ══════════════════════════════════════════════════════════════════════════════
 
def build_core_faqs(is_veg: bool, shop_type: str, signature: str) -> list:
    faqs = [
        {
            "id": "core_contact", "category": "support",
            "question_variants": [
                "Contact number?", "WhatsApp number?", "number enthu?", "contact info?",
            ],
            "answer": "WhatsApp: {whatsapp} | Email: {email} | Open {hours_weekdays}.",
        },
        {
            "id": "core_hours", "category": "store",
            "question_variants": [
                "What are your hours?", "timings entha?", "open aano?", "eppol thurakum?",
            ],
            "answer": "Open {hours_weekdays} and {hours_sunday}. {hours_holiday}.",
        },
        {
            "id": "core_location", "category": "store",
            "question_variants": [
                "Where are you?", "shop evide?", "address?", "location enthu?",
            ],
            "answer": "We are at {location}. WhatsApp {whatsapp} for directions!",
        },
        {
            "id": "core_payment", "category": "payment",
            "question_variants": [
                "Payment methods?", "enthu payment undo?", "UPI undo?", "card undo?",
            ],
            "answer": "We accept UPI, Cards, Cash, GPay, PhonePe, Paytm.",
        },
    ]
    if signature:
        faqs.append({
            "id": "core_signature", "category": "catalog",
            "question_variants": [
                "signature items enthu?", "special items undo?",
                "best items enthu?",      "top picks?",
            ],
            "answer": f"Njangal best picks: {signature}. WhatsApp {{whatsapp}} to enquire!",
        })
    if is_veg and shop_type in ("restaurant", "bakery"):
        faqs.append({
            "id": "core_veg", "category": "dietary",
            "question_variants": [
                "pure veg aano?", "non-veg undo?", "egg use cheyyumo?",
                "veg only aano?", "is this vegetarian?",
            ],
            "answer": (
                "Athe! Njangal 100% pure veg aanu 🌿 "
                "Meat, fish, egg onnum use cheyyunnilla."
            ),
        })
    return faqs
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  MAIN GENERATOR
# ══════════════════════════════════════════════════════════════════════════════
 
def generate_shop_from_items(
    items: list,
    use_ollama: bool = True,
    data_dir: str = "data",
    templates_dir: str = "faq_templates",
    preferred_type: str | None = None,
) -> tuple:
    if not items:
        print("No items provided.")
        sys.exit(1)
 
    use_ollama = use_ollama and _check_ollama_available()
 
    # AUTHORITATIVE type first: pdf.py already detected the shop type from the
    # FULL PDF text (tested correct across beauty/dental/restaurant/jewellery/
    # pharmacy). Ollama inference from item NAMES alone hallucinated
    # dental_clinic for a beauty parlour ("Cleanup" items) and poisoned the
    # shop with 319 dental FAQs. Only infer when no detected type exists.
    if preferred_type and preferred_type != "general":
        shop_type = preferred_type
        print(f"[shop_type] using detected type: {shop_type} (inference skipped)")
    else:
        shop_type = infer_shop_type(items) if use_ollama else _keyword_infer_shop_type(items)
        print(f"[Inferred shop_type] {shop_type}")
 
    shop_name   = infer_shop_name(items, DEFAULTS["shop_name"]) if use_ollama else DEFAULTS["shop_name"]
    shop_gender = detect_shop_gender(items, shop_name, shop_type, use_ollama)
    print(f"[shop_gender] {shop_gender}")
 
    profile = get_shop_profile_with_cache(shop_name, shop_type, items, use_ollama)
    print(f"[profile] source={profile.source} cats={profile.categories} label='{profile.item_label}'")
 
    specialisation, allowed_categories = detect_specialisation(
        items, shop_name, shop_type, use_ollama, _profile_cats=profile.categories,
    )
    print(f"[specialisation] {specialisation or 'none'} → {allowed_categories}")
 
    items     = enrich_items(items, shop_type, use_ollama, shop_gender, allowed_categories)
    hours_loc = infer_hours_location(shop_type) if use_ollama else {
        k: DEFAULTS[k] for k in ("hours_weekdays", "hours_sunday", "location")
    }
    signature    = infer_signature_items(items, shop_type)
    is_veg       = detect_veg(items, shop_name, shop_type, use_ollama)
    dietary_mode = "veg_only" if is_veg else ("veg_nonveg" if shop_type in ("restaurant", "bakery") else None)
    if shop_type in ("restaurant", "bakery"):
        print(f"[Dietary mode] {'veg_only' if is_veg else 'veg_nonveg'}")
 
    config = {
        "bot_name":           shop_name.split()[0][:10] if shop_name else "Bot",
        "shop_name":          shop_name,
        "shop_type":          shop_type,
        "tagline":            "English & Manglish",
        "description":        f"{shop_name} – auto-generated from items",
        "location":           hours_loc.get("location",       DEFAULTS["location"]),
        "city":               "Kerala",
        "state":              "Kerala",
        "hours": {
            "weekdays": hours_loc.get("hours_weekdays", DEFAULTS["hours_weekdays"]),
            "sunday":   hours_loc.get("hours_sunday",   DEFAULTS["hours_sunday"]),
            "holiday":  DEFAULTS["hours_holiday"],
        },
        "contact": {
            "whatsapp": DEFAULTS["whatsapp"],
            "phone":    DEFAULTS["whatsapp"],
            "email":    DEFAULTS["email"],
        },
        "payment":  DEFAULTS["payment"],
        "services": [],
        "delivery": {
            "areas":      "",
            "free_above": "",
            "days":       "",
        },
        "returns": {
            "days":        0,
            "condition":   "",
            "refund_days": "",
        },
        "first_offer":        {"code": "", "description": ""},
        "escalate":           {"whatsapp": DEFAULTS["whatsapp"], "email": DEFAULTS["email"]},
        "language":           "english_manglish",
        "currency":           "INR",
        "shop_gender":        shop_gender,
        "specialisation":     specialisation,
        "allowed_categories": allowed_categories,
        "item_label":         profile.item_label,
        "profile_source":     profile.source,
        "is_veg":             is_veg,
        "dietary_mode":       dietary_mode,
        "escalate_topics":    ["fraud", "refund", "complaint"],
        "blocked_topics":     [],
        "blocked_reply": {
            "manglish": "Athu njangalude shop-il applicable alla 😊 Enthelum help cheyyamo?",
            "english":  "That's not applicable here. Can I help with something else?",
        },
        "quick_chips":     [],
        "welcome_cards":   [],
        "item_count":      len(items),
        "signature_items": signature,
    }
 
    common_faqs   = load_common_faqs(data_dir) if INCLUDE_COMMON_FAQS else []
    template_faqs = load_template_faqs(shop_type, templates_dir)
    core_faqs     = build_core_faqs(is_veg, shop_type, signature)
    item_faqs     = build_item_faqs(
        items, shop_type, is_veg=is_veg,
        shop_gender=shop_gender, specialisation=specialisation, profile=profile,
    )
    all_faqs = merge_faq_layers(core_faqs, template_faqs, common_faqs, item_faqs)
 
    print(
        f"[generate_shop] FAQ summary — "
        f"core={len(core_faqs)} template={len(template_faqs)} "
        f"common={len(common_faqs)} items={len(item_faqs)} "
        f"merged_total={len(all_faqs)}"
    )
    return config, all_faqs, items
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  BRIDGE FUNCTION (called by api.py)
# ══════════════════════════════════════════════════════════════════════════════
 
def generate_shop_files(
    info: dict,
    use_ollama: bool = True,
    data_dir: str = "data",
    templates_dir: str = "faq_templates",
) -> tuple:
    raw_items = info.get("shop_items") or []
    if not raw_items:
        raw_items = [{
            "name":     info.get("shop_name", "Item"),
            "category": info.get("shop_type", "general"),
            "price":    0,
        }]
 
    config, faqs, items = generate_shop_from_items(
        raw_items, use_ollama=use_ollama,
        data_dir=data_dir, templates_dir=templates_dir,
        preferred_type=info.get("shop_type"),
    )
 
    shop_name = info.get("shop_name") or config["shop_name"]
    bot_name  = info.get("bot_name")  or (shop_name.split()[0][:10] if shop_name else "Bot")
 
    config.update({
        "bot_name":    bot_name,
        "shop_name":   shop_name,
        "shop_type":   info.get("shop_type",    config["shop_type"]),
        "tagline":     info.get("tagline",      config.get("tagline", "English & Manglish")),
        "description": info.get("description",  config.get("description", "")),
        "location":    info.get("location",     config.get("location", "")),
        "city":        info.get("city",         config.get("city", "Kerala")),
        "state":       info.get("state",        config.get("state", "Kerala")),
    })
 
    h = config.setdefault("hours", {})
    if info.get("hours_weekdays"): h["weekdays"] = info["hours_weekdays"]
    if info.get("hours_sunday"):   h["sunday"]   = info["hours_sunday"]
    if info.get("hours_holiday"):  h["holiday"]  = info["hours_holiday"]
 
    c = config.setdefault("contact", {})
    if info.get("whatsapp"):
        c["whatsapp"] = info["whatsapp"]
        c["phone"]    = info.get("phone") or info["whatsapp"]
    if info.get("email"):   c["email"]   = info["email"]
    if info.get("website"): c["website"] = info["website"]
 
    if info.get("payment"):  config["payment"]  = info["payment"]
    if info.get("services"): config["services"] = info["services"]
 
    d = config.setdefault("delivery", {})
    if info.get("delivery_areas") and info["delivery_areas"] != "N/A": d["areas"]      = info["delivery_areas"]
    if info.get("delivery_free")  and info["delivery_free"]  != "N/A": d["free_above"] = info["delivery_free"]
    if info.get("delivery_days")  and info["delivery_days"]  != "N/A": d["days"]       = info["delivery_days"]
 
    r = config.setdefault("returns", {})
    if info.get("return_days"):                                              r["days"]        = info["return_days"]
    if info.get("return_condition") and info["return_condition"] != "N/A":  r["condition"]   = info["return_condition"]
    if info.get("refund_days")      and info["refund_days"]      != "N/A":  r["refund_days"] = info["refund_days"]
 
    o = config.setdefault("first_offer", {})
    if info.get("offer_code"): o["code"]        = info["offer_code"]
    if info.get("offer_desc"): o["description"] = info["offer_desc"]
 
    e = config.setdefault("escalate", {})
    ew = info.get("escalate_whatsapp") or info.get("whatsapp")
    ee = info.get("escalate_email")    or info.get("email")
    if ew: e["whatsapp"] = ew
    if ee: e["email"]    = ee
    if info.get("escalate_topics"): config["escalate_topics"] = info["escalate_topics"]
    if info.get("blocked_topics"):  config["blocked_topics"]  = info["blocked_topics"]
 
    # Re-load template FAQs using the CONFIRMED shop_type from info
    real_type = config["shop_type"]
    if real_type != (info.get("shop_type") or real_type):
        new_template_faqs = load_template_faqs(real_type, templates_dir)
        common_faqs       = load_common_faqs(data_dir) if INCLUDE_COMMON_FAQS else []
        core_faqs         = build_core_faqs(
            config.get("is_veg", False), real_type,
            config.get("signature_items", "")
        )
        item_faqs = [f for f in faqs if f.get("category") in ("catalog", "pricing")]
        faqs      = merge_faq_layers(core_faqs, new_template_faqs, common_faqs, item_faqs)
        print(f"[generate_shop_files] re-merged FAQs for real type='{real_type}': {len(faqs)} total")
 
    # Resolve {whatsapp} placeholder in item FAQs before saving
    real_whatsapp = config.get("contact", {}).get("whatsapp", "")
    if real_whatsapp:
        for faq in faqs:
            if "{whatsapp}" in faq.get("answer", ""):
                faq["answer"] = faq["answer"].replace("{whatsapp}", real_whatsapp)
            if "{whatsapp}" in faq.get("answer_ml", ""):
                faq["answer_ml"] = faq["answer_ml"].replace("{whatsapp}", real_whatsapp)
 
    return config, faqs, items
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  SAVE FILES (CLI helper)
# ══════════════════════════════════════════════════════════════════════════════
 
def save_files(
    config, faqs, items,
    output_config="shop_config.json",
    output_faqs="faqs/shop_faq.json",
    output_items="faqs/shop_items.json",
):
    with open(output_config, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"✅ Saved {output_config}")
 
    os.makedirs(os.path.dirname(output_faqs) or ".", exist_ok=True)
    with open(output_faqs, "w", encoding="utf-8") as f:
        json.dump(faqs, f, ensure_ascii=False, indent=2)
    print(f"✅ Saved {output_faqs} ({len(faqs)} FAQs)")
 
    if items:
        os.makedirs(os.path.dirname(output_items) or ".", exist_ok=True)
        with open(output_items, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"✅ Saved {output_items} ({len(items)} items)")
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate shop config and FAQs from extracted items."
    )
    parser.add_argument("--input",         "-i", required=True,
        help="JSON file with items: [{name, price, category?, gender?}]")
    parser.add_argument("--output-config", default="shop_config.json")
    parser.add_argument("--output-faqs",   default="faqs/shop_faq.json")
    parser.add_argument("--output-items",  default="faqs/shop_items.json")
    parser.add_argument("--data-dir",      default="data")
    parser.add_argument("--templates-dir", default="faq_templates")
    parser.add_argument("--no-ollama",     action="store_true")
    args = parser.parse_args()
 
    with open(args.input, "r", encoding="utf-8") as f:
        raw_items = json.load(f)
 
    print(f"Loaded {len(raw_items)} items from {args.input}")
    config, faqs, enriched = generate_shop_from_items(
        raw_items,
        use_ollama=not args.no_ollama,
        data_dir=args.data_dir,
        templates_dir=args.templates_dir,
    )
    save_files(config, faqs, enriched, args.output_config, args.output_faqs, args.output_items)
 
    print(f"\n=== Summary ===")
    print(f"Shop          : {config['shop_name']} ({config['shop_type']})")
    print(f"Gender        : {config['shop_gender']}")
    print(f"Specialisation: {config['specialisation'] or 'none'}")
    print(f"Categories    : {config['allowed_categories']}")
    if config.get("dietary_mode"):
        print(f"Dietary       : {config['dietary_mode']}")
    print(f"FAQs          : {len(faqs)} total")
    print(f"Items         : {len(enriched)} enriched")

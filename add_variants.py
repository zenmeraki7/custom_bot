# """
# add_variants.py — Auto-expand question_variants in shop_faq.json
# ================================================================
# Run once (or after any shop_faq.json update):

#     python add_variants.py --slug hey-foodie

# What it does
# ────────────
# For every FAQ in shops/{slug}/shop_faq.json it:
#   1. Detects the FAQ category (menu, availability, price, hours, location,
#      payment, delivery, returns, contact, offer)
#   2. Generates Manglish variant questions using per-category templates
#   3. Merges new variants in — existing ones are preserved, duplicates skipped
#   4. Writes back to shop_faq.json in-place (backup first)

# This is the #2 highest-impact fix: more variants → higher Pass 0 cosine
# hit rate → fewer Ollama fallbacks.

# Item-specific templates
# ───────────────────────
# For shop_items.json items, variants like "biriyani indo?",
# "biriyani kittumo?", "biriyani price ethra?" are generated automatically
# so every new item gets coverage without manual editing.
# """

# from __future__ import annotations
# import argparse
# import json
# import re
# import shutil
# from pathlib import Path

# SHOPS_DIR = Path("shops")

# # ── Per-category Manglish variant templates ───────────────────────────────────
# # {q} = original question text (lowercased)
# # These cover the exact failure patterns seen in chat_logs.csv

# _CATEGORY_VARIANTS: dict[str, list[str]] = {
#     "hours": [
#         "Ethra mani open aanu?",
#         "Eppo open aanu?",
#         "Opening time enthu?",
#         "Timing enthu aanu?",
#         "Worktime ethranu?",
#         "Eppozhanu open?",
#         "Ethra mani vare open und?",
#         "Shop eppo open cheyyum?",
#         "Sunday open aano?",
#         "Holiday il open aano?",
#     ],
#     "location": [
#         "Evide aanu shop?",
#         "Address paranju tharamo?",
#         "Shop evide aanu?",
#         "Evideyanu ningalude shop?",
#         "Location enthu?",
#         "Evideya ningalude store?",
#         "Map link tharamo?",
#         "Directions tharamo?",
#     ],
#     "contact": [
#         "Number enthu aanu?",
#         "WhatsApp number paranju tharamo?",
#         "Contact cheyyendath engane?",
#         "Phone number enthu?",
#         "Ningalku call cheyyam?",
#         "Reach cheyyendath engane?",
#     ],
#     "payment": [
#         "GPay cheyyaamo?",
#         "Payment engane cheyyam?",
#         "Online payment accept cheyyunnundo?",
#         "PhonePe cheyyaamo?",
#         "Cash payment okay aano?",
#         "Card payment undo?",
#         "Paytm cheyyaamo?",
#         "UPI accept cheyyunnundo?",
#     ],
#     "delivery": [
#         "Delivery undaakumo?",
#         "Deliver cheyyunnundo?",
#         "Home delivery undo?",
#         "Delivery kittumo?",
#         "Delivery charge ethranu?",
#         "Free delivery undo?",
#         "Delivery ethra divasam edukum?",
#         "Evide vare delivery und?",
#     ],
#     "returns": [
#         "Return cheyyaamo?",
#         "Return policy enthu?",
#         "Paripadi enthu aanu?",
#         "Exchange cheyyaamo?",
#         "Refund kittumoo?",
#         "Return ethra divasam und?",
#         "Product return cheyyam?",
#         "Maattaan pattumo?",
#     ],
#     "offer": [
#         "Offer undo?",
#         "Discount und?",
#         "New customer offer undo?",
#         "Coupon code undo?",
#         "Promo code paranju tharamo?",
#         "First order offer undo?",
#         "Sale und?",
#     ],
#     "menu": [
#         "Menu enthu und?",
#         "Enthu okke und?",
#         "Enthu dishes und?",
#         "Food items enthu okke und?",
#         "Full menu paranju tharamo?",
#         "Enthu kazhikkan und?",
#         "Menu list tharamo?",
#         "Enthellaanu und?",
#         "Items enthu und?",
#         "What do you serve?",
#     ],
#     "availability": [
#         "{item} indo?",
#         "{item} undo?",
#         "{item} kittumo?",
#         "{item} available aano?",
#         "{item} und?",
#         "Do you have {item}?",
#         "{item} stock undo?",
#     ],
#     "price": [
#         "{item} price ethra?",
#         "{item} ethranu?",
#         "{item} vila ethra?",
#         "{item} cost enthu?",
#         "{item} rate ethra aanu?",
#         "How much is {item}?",
#         "{item} charge ethranu?",
#     ],
#     "services": [
#         "Enthu services offer cheyyunnu?",
#         "Enthu okke cheyyunnu?",
#         "Services enthu und?",
#     ],
#     "booking": [
#         "Appointment edukkan pattumo?",
#         "Booking cheyyaamo?",
#         "Slot available aano?",
#         "Appointment schedule cheyyam?",
#         "Book cheyyendath engane?",
#     ],
#     "greeting": [],   # no extra variants needed — regex handles these
#     "social": [],
#     "complaint": [],
#     "neutral": [],
# }

# # ── Item-name extraction helpers ──────────────────────────────────────────────

# def _extract_item_name(faq: dict) -> str | None:
#     """Try to extract a product/item name from a FAQ entry."""
#     q = (faq.get("q") or faq.get("question") or "").strip()
#     # Patterns: "Crab Masala price ethra?", "Mutton Fry undo?", "Biryani kittumo?"
#     m = re.match(r"^([A-Z][A-Za-z\s]+?)\s+(price|ethra|undo|indo|kittumo|available)", q)
#     if m:
#         return m.group(1).strip()
#     return None


# def _infer_category(faq: dict) -> str:
#     """Infer category from faq fields."""
#     cat = (faq.get("category") or faq.get("section") or "").lower()
#     if cat:
#         for key in _CATEGORY_VARIANTS:
#             if key in cat:
#                 return key
#     # Fallback: scan question text
#     q = (faq.get("q") or faq.get("question") or "").lower()
#     if any(w in q for w in ["open", "close", "timing", "eppo", "mani", "hour"]):
#         return "hours"
#     if any(w in q for w in ["evide", "address", "location", "map", "where"]):
#         return "location"
#     if any(w in q for w in ["menu", "food", "dishes", "items", "kazhikkan", "what do you"]):
#         return "menu"
#     if any(w in q for w in ["undo", "indo", "available", "kittumo", "have"]):
#         return "availability"
#     if any(w in q for w in ["price", "ethra", "vila", "cost", "rate", "how much"]):
#         return "price"
#     if any(w in q for w in ["payment", "pay", "gpay", "upi", "cash", "card"]):
#         return "payment"
#     if any(w in q for w in ["delivery", "deliver", "shipping", "home delivery"]):
#         return "delivery"
#     if any(w in q for w in ["return", "refund", "exchange", "paripadi", "replace"]):
#         return "returns"
#     if any(w in q for w in ["offer", "discount", "coupon", "promo", "sale"]):
#         return "offer"
#     if any(w in q for w in ["contact", "phone", "call", "whatsapp", "number", "email"]):
#         return "contact"
#     return "neutral"


# def _generate_variants(faq: dict, category: str, existing: set[str]) -> list[str]:
#     """Generate new variant questions not already in existing set."""
#     templates = _CATEGORY_VARIANTS.get(category, [])
#     if not templates:
#         return []

#     item_name = _extract_item_name(faq)
#     new_variants: list[str] = []

#     for tmpl in templates:
#         if "{item}" in tmpl:
#             if not item_name:
#                 continue
#             v = tmpl.replace("{item}", item_name)
#         else:
#             v = tmpl
#         if v.lower() not in existing:
#             new_variants.append(v)

#     return new_variants


# # ── Item FAQ auto-generation from shop_items.json ─────────────────────────────

# def _generate_item_faqs(items: list[dict], existing_questions: set[str]) -> list[dict]:
#     """
#     For each item in shop_items.json, generate availability + price FAQs
#     if not already covered in shop_faq.json.
#     """
#     new_faqs: list[dict] = []
#     seen_items: set[str] = set()

#     for item in items:
#         name = (item.get("name") or "").strip()
#         if not name or name.lower() in seen_items:
#             continue
#         seen_items.add(name.lower())

#         price = item.get("price") or item.get("price_min") or ""
#         category = item.get("category") or "general"

#         # Skip if already covered
#         avail_check = f"{name.lower()} undo"
#         price_check = f"{name.lower()} price"
#         if avail_check in existing_questions and price_check in existing_questions:
#             continue

#         avail_variants = [
#             f"{name} indo?", f"{name} undo?", f"{name} kittumo?",
#             f"{name} available aano?", f"{name} und?",
#             f"Do you have {name}?", f"Is {name} available?",
#         ]
#         price_variants = [
#             f"{name} price ethra?", f"{name} ethranu?",
#             f"{name} vila ethra?", f"How much is {name}?",
#             f"{name} cost enthu?",
#         ]

#         # Availability FAQ
#         avail_answer = f"Athe, {name} und! " + (
#             f"Price ₹{price}. " if price else ""
#         ) + "Kooduthal ariyaan WhatsApp cheyyuka {whatsapp} 😊"

#         new_faqs.append({
#             "id": f"item_{re.sub(r'[^a-z0-9]', '_', name.lower())}_avail",
#             "category": category,
#             "question_variants": avail_variants,
#             "answer": f"Yes, {name} is available!" + (f" Price: ₹{price}." if price else "") +
#                       " For more details, WhatsApp us at {whatsapp} 😊",
#             "answer_ml": avail_answer,
#             "lang": "english_manglish",
#             "source": "auto_generated",
#         })

#         # Price FAQ (only if price is known)
#         if price:
#             new_faqs.append({
#                 "id": f"item_{re.sub(r'[^a-z0-9]', '_', name.lower())}_price",
#                 "category": category,
#                 "question_variants": price_variants,
#                 "answer": f"{name} costs ₹{price}. WhatsApp us for the full menu: {{whatsapp}} 😊",
#                 "answer_ml": f"{name} ₹{price} aanu! Full menu venam enkil WhatsApp cheyyuka {{whatsapp}} 😊",
#                 "lang": "english_manglish",
#                 "source": "auto_generated",
#             })

#     return new_faqs


# # ── Main ──────────────────────────────────────────────────────────────────────

# def run(slug: str, dry_run: bool = False) -> None:
#     slug_dir  = SHOPS_DIR / slug
#     faq_path  = slug_dir / "shop_faq.json"
#     item_path = slug_dir / "shop_items.json"

#     if not faq_path.exists():
#         print(f"❌  {faq_path} not found")
#         return

#     faqs = json.loads(faq_path.read_text(encoding="utf-8"))
#     items = json.loads(item_path.read_text(encoding="utf-8")) if item_path.exists() else []

#     print(f"\n📂  {slug}: {len(faqs)} FAQs, {len(items)} items\n")

#     # Build existing question set for dedup
#     existing_qs: set[str] = set()
#     for faq in faqs:
#         q = (faq.get("q") or faq.get("question") or "").lower()
#         if q:
#             existing_qs.add(q)
#         for v in (faq.get("variants") or faq.get("question_variants") or []):
#             existing_qs.add(v.lower())

#     # Pass 1: expand variants on existing FAQs
#     total_added = 0
#     for faq in faqs:
#         category = _infer_category(faq)
#         new_vars  = _generate_variants(faq, category, existing_qs)
#         if new_vars:
#             key = "variants" if "variants" in faq else "question_variants"
#             faq.setdefault(key, [])
#             faq[key].extend(new_vars)
#             for v in new_vars:
#                 existing_qs.add(v.lower())
#             total_added += len(new_vars)
#             print(f"  ✅ [{category}] +{len(new_vars)} variants → \"{faq.get('q') or faq.get('question', '')}\"")

#     # Pass 2: auto-generate item FAQs
#     new_item_faqs = _generate_item_faqs(items, existing_qs)
#     if new_item_faqs:
#         faqs = new_item_faqs + faqs   # prepend so Pass 0 sees them first
#         print(f"\n  ✅ Auto-generated {len(new_item_faqs)} item FAQs from shop_items.json")

#     print(f"\n  Total: +{total_added} variants added, {len(new_item_faqs)} new item FAQs")

#     if dry_run:
#         print("\n  [DRY RUN] — nothing written")
#         return

#     # Backup then write
#     backup = faq_path.with_suffix(".json.bak")
#     shutil.copy(faq_path, backup)
#     faq_path.write_text(json.dumps(faqs, ensure_ascii=False, indent=2), encoding="utf-8")
#     print(f"\n  ✅  Written to {faq_path}  (backup: {backup})")
#     print(f"\n  Next steps:")
#     print(f"  1. Restart uvicorn — shop_manager will rebuild embeddings automatically")
#     print(f"  2. Check terminal for 'X shop embeddings built'")
#     print(f"  3. Test: 'biriyani indo?', 'menu enthu und?', 'price ethra?'\n")


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Auto-expand shop_faq.json variants")
#     parser.add_argument("--slug",    required=True, help="Shop slug (e.g. hey-foodie)")
#     parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
#     args = parser.parse_args()
#     run(args.slug, dry_run=args.dry_run)










"""
add_variants.py — Auto-expand question_variants in shop_faq.json
================================================================
Run once (or after any shop_faq.json update):

    python add_variants.py --slug hey-foodie

What it does
────────────
For every FAQ in shops/{slug}/shop_faq.json it:
  1. Detects the FAQ category (menu, availability, price, hours, location,
     payment, delivery, returns, contact, offer)
  2. Generates Manglish variant questions using per-category templates
  3. Merges new variants in — existing ones are preserved, duplicates skipped
  4. Writes back to shop_faq.json in-place (backup first)

This is the #2 highest-impact fix: more variants → higher Pass 0 cosine
hit rate → fewer Ollama fallbacks.

Item-specific templates
───────────────────────
For shop_items.json items, variants like "biriyani indo?",
"biriyani kittumo?", "biriyani price ethra?" are generated automatically
so every new item gets coverage without manual editing.
"""

from __future__ import annotations
import argparse
import json
import re
import shutil
from pathlib import Path

SHOPS_DIR = Path("shops")

# ── UNVERIFIED AMENITY CLAIM GUARD ───────────────────────────────────────────
# The generic type-pack templates (restaurent_english.json etc.) assert
# amenities like WiFi, valet/parking specifics, international card support,
# and student discounts as confident fact -- written for a hypothetical
# generic/chain business, not verified against any specific shop's actual
# PDF. Since these are exact-match template answers (not weak LLM guesses),
# they win every confidence check in the runtime pipeline, so a fabricated
# claim like "Yes, free WiFi is available" ships with full confidence. This
# runs automatically on every shop's FAQ generation, not just one shop, since
# the root cause is in the shared template, not any single shop's data.
_AMENITY_TOPIC_SAFE_ANSWERS: dict[str, str] = {
    "wifi": "We don't have WiFi details confirmed — please ask our staff on-site.",
    "valet": "We don't currently list valet parking — please confirm with our staff or WhatsApp {whatsapp}.",
    "parking": "Please contact us on WhatsApp {whatsapp} to check current parking availability.",
    "contactless": "We accept card and UPI payments — for contactless/tap-to-pay support, please confirm with our staff.",
    "international_card": "We accept major cards — please confirm international card support on WhatsApp {whatsapp} before your visit.",
    "student_discount": "We don't have a student discount listed currently — please check with us on WhatsApp {whatsapp} for any current offers.",
}

# Order matters: check more specific topics before generic ones so e.g.
# "international_card" wins over a hypothetical bare "card" entry.
_AMENITY_TOPIC_ORDER = [
    "wifi", "valet", "parking", "international_card", "contactless", "student_discount",
]


def _sanitize_unverified_amenity_claims(faqs: list[dict], whatsapp: str = "") -> int:
    """Replace any FAQ whose category/section/question touches an
    unverifiable amenity topic with an honest, topic-scoped answer instead
    of the template's confident (and unverified) claim. Returns count changed."""
    changed = 0
    for faq in faqs:
        haystack = " ".join(str(faq.get(k, "")) for k in ("category", "section", "q")).lower()
        for topic in _AMENITY_TOPIC_ORDER:
            topic_word = topic.replace("_", "[ _-]?")
            if re.search(topic_word, haystack):
                faq["a"] = _AMENITY_TOPIC_SAFE_ANSWERS[topic].format(whatsapp=whatsapp or "us")
                faq["source"] = "template_corrected_unverified_claim"
                changed += 1
                break
    return changed


# ── Per-category Manglish variant templates ───────────────────────────────────
# {q} = original question text (lowercased)
# These cover the exact failure patterns seen in chat_logs.csv

_CATEGORY_VARIANTS: dict[str, list[str]] = {
    "hours": [
        "Ethra mani open aanu?",
        "Eppo open aanu?",
        "Opening time enthu?",
        "Timing enthu aanu?",
        "Worktime ethranu?",
        "Eppozhanu open?",
        "Ethra mani vare open und?",
        "Shop eppo open cheyyum?",
        "Sunday open aano?",
        "Holiday il open aano?",
    ],
    "location": [
        "Evide aanu shop?",
        "Address paranju tharamo?",
        "Shop evide aanu?",
        "Evideyanu ningalude shop?",
        "Location enthu?",
        "Evideya ningalude store?",
        "Map link tharamo?",
        "Directions tharamo?",
    ],
    "contact": [
        "Number enthu aanu?",
        "WhatsApp number paranju tharamo?",
        "Contact cheyyendath engane?",
        "Phone number enthu?",
        "Ningalku call cheyyam?",
        "Reach cheyyendath engane?",
    ],
    "payment": [
        "GPay cheyyaamo?",
        "Payment engane cheyyam?",
        "Online payment accept cheyyunnundo?",
        "PhonePe cheyyaamo?",
        "Cash payment okay aano?",
        "Card payment undo?",
        "Paytm cheyyaamo?",
        "UPI accept cheyyunnundo?",
    ],
    "delivery": [
        "Delivery undaakumo?",
        "Deliver cheyyunnundo?",
        "Home delivery undo?",
        "Delivery kittumo?",
        "Delivery charge ethranu?",
        "Free delivery undo?",
        "Delivery ethra divasam edukum?",
        "Evide vare delivery und?",
    ],
    "returns": [
        "Return cheyyaamo?",
        "Return policy enthu?",
        "Paripadi enthu aanu?",
        "Exchange cheyyaamo?",
        "Refund kittumoo?",
        "Return ethra divasam und?",
        "Product return cheyyam?",
        "Maattaan pattumo?",
    ],
    "offer": [
        "Offer undo?",
        "Discount und?",
        "New customer offer undo?",
        "Coupon code undo?",
        "Promo code paranju tharamo?",
        "First order offer undo?",
        "Sale und?",
    ],
    "menu": [
        "Menu enthu und?",
        "Enthu okke und?",
        "Enthu dishes und?",
        "Food items enthu okke und?",
        "Full menu paranju tharamo?",
        "Enthu kazhikkan und?",
        "Menu list tharamo?",
        "Enthellaanu und?",
        "Items enthu und?",
        "What do you serve?",
    ],
    "availability": [
        "{item} indo?",
        "{item} undo?",
        "{item} kittumo?",
        "{item} available aano?",
        "{item} und?",
        "Do you have {item}?",
        "{item} stock undo?",
    ],
    "price": [
        "{item} price ethra?",
        "{item} ethranu?",
        "{item} vila ethra?",
        "{item} cost enthu?",
        "{item} rate ethra aanu?",
        "How much is {item}?",
        "{item} charge ethranu?",
    ],
    "services": [
        "Enthu services offer cheyyunnu?",
        "Enthu okke cheyyunnu?",
        "Services enthu und?",
    ],
    "booking": [
        "Appointment edukkan pattumo?",
        "Booking cheyyaamo?",
        "Slot available aano?",
        "Appointment schedule cheyyam?",
        "Book cheyyendath engane?",
    ],
    "greeting": [],   # no extra variants needed — regex handles these
    "social": [],
    "complaint": [],
    "neutral": [],
}

# ── Shop-type-aware catalogue framing (replaces food-biased "menu") ──────────
# The original "menu" variants assumed a food shop ("dishes", "kazhikkan").
# For a dental clinic, jewellery shop, or pharmacy those are nonsense. This
# map gives each shop type the right word for "the list of what we offer",
# so question-variant coverage is sensible for EVERY shop type, not just food.
_CATALOGUE_TERMS: dict[str, tuple] = {
    "restaurant":     ("menu", "dishes", "kazhikkan"),
    "fast_food":      ("menu", "items", "kazhikkan"),
    "bakery":         ("menu", "baked items", "kazhikkan"),
    "coffee_shop":    ("menu", "drinks", "kudikkan"),
    "cafe":           ("menu", "items", "kudikkan"),
    "catering_service":("menu", "packages", "kazhikkan"),
    "dental_clinic":  ("treatments", "procedures", "treatments"),
    "hospital":       ("services", "departments", "services"),
    "eye_clinic":     ("treatments", "services", "treatments"),
    "skin_clinic":    ("treatments", "services", "treatments"),
    "ayurvedic_clinic":("treatments", "therapies", "treatments"),
    "physiotherapy":  ("treatments", "therapies", "treatments"),
    "pharmacy":       ("medicines", "products", "medicines"),
    "jewellery":      ("collections", "designs", "designs"),
    "beauty_parlour": ("services", "treatments", "services"),
    "salon":          ("services", "treatments", "services"),
    "spa":            ("services", "therapies", "services"),
    "gym":            ("programs", "plans", "plans"),
    "fitness_supplement_store":("products", "supplements", "products"),
    "electronics":    ("products", "models", "products"),
    "mobile_shop":    ("products", "phones", "products"),
    "supermarket":    ("products", "items", "products"),
    "footwear_shop":  ("collection", "designs", "items"),
    "book_store":     ("collection", "titles", "books"),
    "pet_shop":       ("products", "pets", "items"),
    "general":        ("services", "products", "items"),
}


def _catalogue_variants(shop_type: str) -> list[str]:
    """Catalogue ('what do you have') variants adapted to the shop type."""
    primary, secondary, ml = _CATALOGUE_TERMS.get(
        shop_type, _CATALOGUE_TERMS["general"])
    return [
        f"{primary.capitalize()} enthu und?",
        f"{primary.capitalize()} list tharamo?",
        f"Enthokke {primary} und?",
        f"What {primary} do you have?",
        f"{secondary.capitalize()} enthu okke und?",
        f"Full {primary} paranju tharamo?",
        f"{primary.capitalize()} ariyaan pattumo?",
    ]


# ── Item-name extraction helpers ──────────────────────────────────────────────

def _extract_item_name(faq: dict) -> str | None:
    """Try to extract a product/item name from a FAQ entry."""
    q = (faq.get("q") or faq.get("question") or "").strip()
    # Patterns: "Crab Masala price ethra?", "Mutton Fry undo?", "Biryani kittumo?"
    m = re.match(r"^([A-Z][A-Za-z\s]+?)\s+(price|ethra|undo|indo|kittumo|available)", q)
    if m:
        return m.group(1).strip()
    return None


def _infer_category(faq: dict) -> str:
    """Infer category from faq fields."""
    cat = (faq.get("category") or faq.get("section") or "").lower()
    if cat:
        for key in _CATEGORY_VARIANTS:
            if key in cat:
                return key
    # Fallback: scan question text
    q = (faq.get("q") or faq.get("question") or "").lower()
    if any(w in q for w in ["open", "close", "timing", "eppo", "mani", "hour"]):
        return "hours"
    if any(w in q for w in ["evide", "address", "location", "map", "where"]):
        return "location"
    if any(w in q for w in ["menu", "food", "dishes", "items", "kazhikkan", "what do you"]):
        return "menu"
    if any(w in q for w in ["undo", "indo", "available", "kittumo", "have"]):
        return "availability"
    if any(w in q for w in ["price", "ethra", "vila", "cost", "rate", "how much"]):
        return "price"
    if any(w in q for w in ["payment", "pay", "gpay", "upi", "cash", "card"]):
        return "payment"
    if any(w in q for w in ["delivery", "deliver", "shipping", "home delivery"]):
        return "delivery"
    if any(w in q for w in ["return", "refund", "exchange", "paripadi", "replace"]):
        return "returns"
    if any(w in q for w in ["offer", "discount", "coupon", "promo", "sale"]):
        return "offer"
    if any(w in q for w in ["contact", "phone", "call", "whatsapp", "number", "email"]):
        return "contact"
    return "neutral"


def _generate_variants(faq: dict, category: str, existing: set[str]) -> list[str]:
    """Generate new variant questions not already in existing set."""
    templates = _CATEGORY_VARIANTS.get(category, [])
    if not templates:
        return []

    item_name = _extract_item_name(faq)
    new_variants: list[str] = []

    for tmpl in templates:
        if "{item}" in tmpl:
            if not item_name:
                continue
            v = tmpl.replace("{item}", item_name)
        else:
            v = tmpl
        if v.lower() not in existing:
            new_variants.append(v)

    return new_variants


# ── Item FAQ auto-generation from shop_items.json ─────────────────────────────

def _generate_item_faqs(items: list[dict], existing_questions: set[str]) -> list[dict]:
    """
    For each item in shop_items.json, generate availability + price FAQs
    if not already covered in shop_faq.json.
    """
    new_faqs: list[dict] = []
    seen_items: set[str] = set()

    for item in items:
        name = (item.get("name") or "").strip()
        if not name or name.lower() in seen_items:
            continue
        seen_items.add(name.lower())

        price = item.get("price") or item.get("price_min") or ""
        category = item.get("category") or "general"

        # Skip if already covered
        avail_check = f"{name.lower()} undo"
        price_check = f"{name.lower()} price"
        if avail_check in existing_questions and price_check in existing_questions:
            continue

        avail_variants = [
            f"{name} indo?", f"{name} undo?", f"{name} kittumo?",
            f"{name} available aano?", f"{name} und?",
            f"Do you have {name}?", f"Is {name} available?",
        ]
        price_variants = [
            f"{name} price ethra?", f"{name} ethranu?",
            f"{name} vila ethra?", f"How much is {name}?",
            f"{name} cost enthu?",
        ]

        # Availability FAQ
        avail_answer = f"Athe, {name} und! " + (
            f"Price ₹{price}. " if price else ""
        ) + "Kooduthal ariyaan WhatsApp cheyyuka {whatsapp} 😊"

        new_faqs.append({
            "id": f"item_{re.sub(r'[^a-z0-9]', '_', name.lower())}_avail",
            "category": category,
            "question_variants": avail_variants,
            "answer": f"Yes, {name} is available!" + (f" Price: ₹{price}." if price else "") +
                      " For more details, WhatsApp us at {whatsapp} 😊",
            "answer_ml": avail_answer,
            "lang": "english_manglish",
            "source": "auto_generated",
        })

        # Price FAQ (only if price is known)
        if price:
            new_faqs.append({
                "id": f"item_{re.sub(r'[^a-z0-9]', '_', name.lower())}_price",
                "category": category,
                "question_variants": price_variants,
                "answer": f"{name} costs ₹{price}. WhatsApp us for the full menu: {{whatsapp}} 😊",
                "answer_ml": f"{name} ₹{price} aanu! Full menu venam enkil WhatsApp cheyyuka {{whatsapp}} 😊",
                "lang": "english_manglish",
                "source": "auto_generated",
            })

    return new_faqs


# ── Main ──────────────────────────────────────────────────────────────────────

def _detect_shop_type(slug: str) -> str:
    cfg_path = SHOPS_DIR / slug / "shop_config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            return cfg.get("shop_type", "general")
        except Exception:
            pass
    return "general"


def run(slug: str, dry_run: bool = False) -> None:
    slug_dir  = SHOPS_DIR / slug
    faq_path  = slug_dir / "shop_faq.json"
    item_path = slug_dir / "shop_items.json"

    if not faq_path.exists():
        print(f"❌  {faq_path} not found")
        return

    shop_type = _detect_shop_type(slug)

    faqs = json.loads(faq_path.read_text(encoding="utf-8"))
    items = json.loads(item_path.read_text(encoding="utf-8")) if item_path.exists() else []

    print(f"\n📂  {slug}: {len(faqs)} FAQs, {len(items)} items\n")

    # Build existing question set for dedup
    existing_qs: set[str] = set()
    for faq in faqs:
        q = (faq.get("q") or faq.get("question") or "").lower()
        if q:
            existing_qs.add(q)
        for v in (faq.get("variants") or faq.get("question_variants") or []):
            existing_qs.add(v.lower())

    # Pass 1: expand variants on existing FAQs
    total_added = 0
    for faq in faqs:
        category = _infer_category(faq)
        if category == "menu":
            # shop-type-aware catalogue framing instead of food-biased "menu"
            new_vars = [v for v in _catalogue_variants(shop_type)
                        if v.lower() not in existing_qs]
        else:
            new_vars = _generate_variants(faq, category, existing_qs)
        if new_vars:
            key = "variants" if "variants" in faq else "question_variants"
            faq.setdefault(key, [])
            faq[key].extend(new_vars)
            for v in new_vars:
                existing_qs.add(v.lower())
            total_added += len(new_vars)
            print(f"  ✅ [{category}] +{len(new_vars)} variants → \"{faq.get('q') or faq.get('question', '')}\"")

    # Pass 2: auto-generate item FAQs
    new_item_faqs = _generate_item_faqs(items, existing_qs)
    if new_item_faqs:
        faqs = new_item_faqs + faqs   # prepend so Pass 0 sees them first
        print(f"\n  ✅ Auto-generated {len(new_item_faqs)} item FAQs from shop_items.json")

    print(f"\n  Total: +{total_added} variants added, {len(new_item_faqs)} new item FAQs")

    # Permanent fix, not a one-off patch: sanitize unverified amenity claims
    # (WiFi, parking, valet, etc.) for THIS shop every time FAQs are
    # (re)generated, so re-uploading a PDF or re-running this script doesn't
    # bring the fabricated claims back.
    _whatsapp = ""
    _cfg_path = slug_dir / "shop_config.json"
    if _cfg_path.exists():
        try:
            _whatsapp = json.loads(_cfg_path.read_text(encoding="utf-8")).get("contact", {}).get("whatsapp", "")
        except Exception:
            pass
    _amenity_fixed = _sanitize_unverified_amenity_claims(faqs, _whatsapp)
    if _amenity_fixed:
        print(f"  🛡️  Corrected {_amenity_fixed} unverified amenity-claim FAQ(s) (WiFi/parking/etc.)")

    if dry_run:
        print("\n  [DRY RUN] — nothing written")
        return

    # Backup then write
    backup = faq_path.with_suffix(".json.bak")
    shutil.copy(faq_path, backup)
    faq_path.write_text(json.dumps(faqs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  ✅  Written to {faq_path}  (backup: {backup})")
    print(f"\n  Next steps:")
    print(f"  1. Restart uvicorn — shop_manager will rebuild embeddings automatically")
    print(f"  2. Check terminal for 'X shop embeddings built'")
    print(f"  3. Test: 'biriyani indo?', 'menu enthu und?', 'price ethra?'\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-expand shop_faq.json variants")
    parser.add_argument("--slug",    required=True, help="Shop slug (e.g. hey-foodie)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    run(args.slug, dry_run=args.dry_run)
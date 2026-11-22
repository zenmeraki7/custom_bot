# """
# full_menu.py — "show me the full menu / price list / services" intent
# detector + formatter, generalized across ALL shop types
# ========================================================================
# Drop this file next to chat.py / api.py.

# Problem this solves
# --------------------
# The old "3.6. Full menu / catalog query" block inside chat.py's pipeline()
# was hardcoded around the WORD "menu" — great for a restaurant, meaningless
# for the other ~90 shop types this platform already has FAQ templates for
# (faq_templates/: dental_clinic, gym, pharmacy, jwellery, law_firm,
# tution, hospital, immigration, ...). A dental patient typing "treatment
# list undo?" or a gym member typing "full services list" or a jeweller's
# customer typing "full price list please" never matched "menu" at all and
# fell through to Ollama free-generation, which has NO real item data in
# its prompt and will happily invent a plausible-but-fake list.

# Two things had to change, not just one:

#   1. DETECTION must not be menu-only. It now matches ANY of the generic
#      nouns a customer would use for "show me everything you sell/do":
#      menu, price list, rate list/chart, catalog(ue), service(s) list,
#      treatment(s) list, package(s) list, course(s)/class(es) list,
#      item(s)/product(s) list — in English and Manglish, plus qualifier-
#      free forms like "what all do you have", "everything you offer",
#      "ellam undo".

#   2. WORDING in the reply must match the shop type. A dental clinic
#      shouldn't say "Here's our full menu" — it should say "Here's our
#      full treatment list". This is driven off `cfg["shop_type"]` via
#      _NOUN_BY_SHOP_TYPE below, with a sensible generic fallback for any
#      shop_type not explicitly listed (so a brand-new vertical never
#      breaks, it just gets the generic wording).

# This module is self-contained: no Ollama call, no hallucination risk,
# grounded 100% in shops/{slug}/shop_items.json. Import it from chat.py
# and call `get_full_menu_reply(...)` as an early pipeline step (see
# INTEGRATION NOTES at the bottom of this file).
# """

# from __future__ import annotations

# import json
# import os
# import re


# # ══════════════════════════════════════════════════════════════════════════
# #  WORDING PER SHOP TYPE
# # ══════════════════════════════════════════════════════════════════════════
# #
# # Keyed off the SAME shop_type strings your PDF-extraction / chat.py code
# # already uses (see chat.py's _BROAD_SVC_DEFAULTS and pdf.py's TYPE_KW).
# # Anything not listed here falls back to _DEFAULT_NOUN — new shop types
# # never crash, they just get generic-but-correct wording until someone
# # adds a specific entry.

# _NOUN_BY_SHOP_TYPE: dict[str, str] = {
#     # Food & drink → "menu"
#     "restaurant": "menu", "bakery": "menu", "coffee_shop": "menu",
#     "fast_food": "menu", "catering_service": "menu", "hotel": "menu",
#     "resorts": "menu",

#     # Service-based businesses → "service list"
#     "beauty_parlour": "service list", "salon": "service list",
#     "spa": "service list", "gym": "service list",
#     "tatto_studio": "service list", "laundry": "service list",
#     "cleaning_service": "service list", "photography": "service list",
#     "interior_design": "service list", "dance_academy": "service list",
#     "driving_school": "service list", "ac_service_center": "service list",
#     "car_rental": "service list", "taxi_service": "service list",
#     "packers_and_movers": "service list", "logistic": "service list",
#     "event_management": "service list", "hr_consultant": "service list",
#     "immigration": "service list", "law_firm": "service list",
#     "ca_firm": "service list", "architecture": "service list",
#     "advertising_company": "service list", "construction": "service list",
#     "printing_shop": "service list",

#     # Clinical / treatment-based → "treatment list"
#     "dental_clinic": "treatment list", "skin_clinic": "treatment list",
#     "ayurvedic_clinic": "treatment list",
#     "physiotherapy_clinic": "treatment list", "eye_clinic": "treatment list",
#     "hospital": "treatment list", "medical_lab": "treatment list",

#     # Retail / product-based → "price list"
#     "pharmacy": "price list", "jewellery": "price list",
#     "electronics": "price list", "electronic_products": "price list",
#     "mobile_shop": "price list", "supermarket": "price list",
#     "book_store": "price list", "stationary_shop": "price list",
#     "hardware_store": "price list", "footwear_shop": "price list",
#     "furniture_shop": "price list", "watch_shop": "price list",
#     "sports_shop": "price list", "fish_shop": "price list",
#     "computer_shop": "price list", "home_appliances_store": "price list",
#     "bike_showroom": "price list", "pet_shop": "price list",
#     "fitness_supplement_store": "price list", "opticals": "price list",
#     "optical": "price list",

#     # Travel / booking-based → "package list"
#     "travel_agency": "package list", "adventure_tourism": "package list",
#     "hostel": "package list", "overseas_education_consultancy": "package list",

#     # Education → "course list"
#     "tution": "course list", "tuition": "course list",
#     "kindergarden": "course list", "school": "course list",
#     "college": "course list", "yoga_center": "course list",
#     "day_care": "course list",
# }
# _DEFAULT_NOUN = "price list"


# def _catalog_noun(shop_type: str | None) -> str:
#     return _NOUN_BY_SHOP_TYPE.get((shop_type or "").strip().lower(), _DEFAULT_NOUN)


# # ══════════════════════════════════════════════════════════════════════════
# #  INTENT DETECTION — English + Manglish, regex-based (not plain substring),
# #  and NOT tied to any one shop type
# # ══════════════════════════════════════════════════════════════════════════
# #
# # Word-boundary regex, not `phrase in message.lower()` substring checks —
# # substring checks over-match (e.g. "menu" alone would match inside "is
# # there a kids menu option") and under-match word-order variants ("menu
# # full undo" vs "full menu undo"). Detection deliberately covers ALL the
# # generic nouns (menu/price list/service list/treatment list/package
# # list/course list/catalog) rather than filtering by the current shop's
# # type — a customer might say "menu" loosely even at a salon, and that
# # should still trigger the catalog reply, just worded correctly by
# # _catalog_noun() above.

# _NOUN_ALT = (
#     r"(?:menu|price\s*list|rate\s*list|rate\s*chart|catalog(?:ue)?|"
#     r"service(?:s)?\s*list|treatment(?:s)?\s*list|package(?:s)?\s*list|"
#     r"course(?:s)?\s*list|class(?:es)?\s*list|item(?:s)?\s*list|"
#     r"product(?:s)?\s*list|full\s*details)"
# )

# _FULL_MENU_RE = re.compile(
#     r"("
#     # ── English: qualifier + noun ───────────────────────────────────
#     rf"\b(?:full|whole|complete|entire)\s+{_NOUN_ALT}\b"
#     rf"|\bwhat'?s?\s+on\s+the\s+menu\b"
#     rf"|\bwhat\s+is\s+on\s+the\s+menu\b"
#     rf"|\bshow\s+(?:me\s+)?(?:the\s+|your\s+)?(?:full\s+)?{_NOUN_ALT}\b"
#     rf"|\bsee\s+(?:the\s+|your\s+)?{_NOUN_ALT}\b"
#     rf"|\b{_NOUN_ALT}\s+(?:card\s+)?please\b"
#     rf"|\bsend\s+(?:me\s+)?(?:the\s+|your\s+)?{_NOUN_ALT}\b"
#     rf"|\bcan\s+i\s+see\s+(?:the\s+|your\s+)?{_NOUN_ALT}\b"
#     rf"|\bmenu\s+card\b"
#     r"|\bwhat\s+all\s+(?:do\s+you\s+have|items?|do\s+you\s+offer|"
#     r"do\s+you\s+sell|services?\s+do\s+you\s+(?:have|offer|provide)|"
#     r"treatments?\s+do\s+you\s+(?:have|offer|provide)|"
#     r"products?\s+do\s+you\s+(?:have|sell))\b"
#     r"|\beverything\s+you\s+(?:have|offer|sell|provide|do)\b"
#     r"|\ball\s+(?:the\s+)?(?:items?|services?|treatments?|products?|"
#     r"packages?|courses?)\s+(?:you\s+have|available|list)\b"
#     r"|\blist\s+of\s+(?:services?|items?|treatments?|products?|"
#     r"packages?|courses?)\b"
#     # ── Manglish ─────────────────────────────────────────────────────
#     rf"|\b{_NOUN_ALT}\s+(?:und|undo|venam|kittumo|kaanikko|kanikku)\b"
#     rf"|\bmuzhu(?:va)?n\s+{_NOUN_ALT}\b"
#     rf"|\b{_NOUN_ALT}\s+muzhuvan\b"
#     rf"|\b{_NOUN_ALT}\s+onnu\s+kan(?:ikk|ick)\w*\b"
#     rf"|\b{_NOUN_ALT}\s+kaanikko\b"
#     rf"|\b{_NOUN_ALT}\s+kanikku\w*\b"
#     r"|\bfull\s+list\s+venam\b"
#     r"|\bellam\s+(?:enthu\s+)?und[oe]?\b"
#     r"|\bella(?:m)?\s+(?:items?|services?|treatments?)\s+(?:und|venam|kanikku)\b"
#     rf"|\b{_NOUN_ALT}\s+enthu\s+(?:und|undu)\b"
#     rf"|\b{_NOUN_ALT}\s+ariyano\b"
#     rf"|\b{_NOUN_ALT}\s+tharumo\b"
#     rf"|\b{_NOUN_ALT}\s+ayaykku?m?o\b"
#     rf"|\b{_NOUN_ALT}\s+onnu\s+ayakku?\w*\b"
#     rf"|\bfull\s+{_NOUN_ALT}\s+ayakk\w*\b"
#     rf"|\b{_NOUN_ALT}\s+full\s+aayi\b"
#     r"|\bwhat\s+all\s+(?:undu|und)\b"
#     r"|\benthokke\s+und\b"
#     r"|\benthellam\s+und\b"
#     r")",
#     re.IGNORECASE,
# )


# def is_full_menu_query(message: str) -> bool:
#     """True if the message is asking for the FULL catalog (menu / price
#     list / service list / treatment list / package list / course list —
#     whatever noun fits, in any shop type), not a specific item. Callers
#     should check this BEFORE any specific-item lookup, since a "full
#     list" question itself contains no single item name to match on."""
#     return bool(_FULL_MENU_RE.search(message or ""))


# # ══════════════════════════════════════════════════════════════════════════
# #  DATA LOADING
# # ══════════════════════════════════════════════════════════════════════════

# def _normalize_slug(slug: str) -> str:
#     return slug.strip().lower().replace(" ", "-")


# def _load_items(slug: str | None) -> list[dict]:
#     if not slug:
#         return []
#     path = os.path.join("shops", _normalize_slug(slug), "shop_items.json")
#     try:
#         with open(path, "r", encoding="utf-8-sig") as f:
#             data = json.load(f) or []
#             return data if isinstance(data, list) else []
#     except (FileNotFoundError, json.JSONDecodeError, OSError):
#         return []


# def _price_label(it: dict) -> str:
#     if "price" in it and it["price"] is not None:
#         return f"Rs. {it['price']:,}"
#     if it.get("price_min") is not None and it.get("price_max") is not None:
#         return f"Rs. {it['price_min']:,}-{it['price_max']:,}"
#     return "on request"


# # ══════════════════════════════════════════════════════════════════════════
# #  FORMATTING
# # ══════════════════════════════════════════════════════════════════════════
# #
# # Kept deliberately non-LLM: the list below is built directly from
# # shop_items.json, so there is zero hallucination risk. This mirrors how
# # item_lookup()/category_list() already work elsewhere in this codebase
# # (see chat.py's _needs_rephrase(), which explicitly keeps those OUT of
# # the Ollama rephrase step for the same reason).

# # Hard cap so one giant catalog doesn't blow past chat-UI/WhatsApp message
# # limits. Past this many items, switch to a category-count summary instead
# # of listing every single item.
# _MAX_ITEMS_TO_LIST = 60
# _MAX_ITEMS_PER_CATEGORY = 12


# def _group_by_category(items: list[dict]) -> dict[str, list[dict]]:
#     grouped: dict[str, list[dict]] = {}
#     for it in items:
#         cat = (it.get("category") or "Other").strip() or "Other"
#         grouped.setdefault(cat, []).append(it)
#     return grouped


# def format_full_menu(
#     items: list[dict],
#     lang: str,
#     whatsapp: str = "",
#     shop_type: str | None = None,
# ) -> str:
#     if not items:
#         return ""

#     grouped = _group_by_category(items)
#     total = len(items)
#     noun = _catalog_noun(shop_type)          # e.g. "menu" / "service list" / "treatment list"

#     lines: list[str] = []
#     if lang == "manglish":
#         lines.append(f"Njangalude full {noun} ithaanu \U0001F447")
#     else:
#         lines.append(f"Here's our full {noun} \U0001F447")
#     lines.append("")

#     if total > _MAX_ITEMS_TO_LIST:
#         # Too big to dump in one chat bubble — category breakdown + counts
#         # instead of a wall of text, still 100% grounded (real category
#         # names, real counts), plus a couple of examples per category so
#         # it doesn't read as empty.
#         for cat, cat_items in grouped.items():
#             examples = ", ".join(i.get("name", "") for i in cat_items[:3])
#             lines.append(f"*{cat}* ({len(cat_items)} items) — e.g. {examples}")
#         lines.append("")
#         if lang == "manglish":
#             lines.append(
#                 f"Full {noun} ({total} items) valuthaanu — WhatsApp cheyyuka "
#                 f"{whatsapp} enkil complete {noun} ayachu tharaam! \U0001F60A"
#                 if whatsapp else
#                 f"Full {noun} has {total} items — ask about a category or "
#                 f"specific item and I'll give you the price! \U0001F60A"
#             )
#         else:
#             lines.append(
#                 f"That's {total} items total — WhatsApp us at {whatsapp} "
#                 f"for the complete {noun}, or ask about a specific "
#                 f"category/item and I'll answer right here! \U0001F60A"
#                 if whatsapp else
#                 f"That's {total} items total — ask about a specific "
#                 f"category or item and I'll give you the price! \U0001F60A"
#             )
#         return "\n".join(lines)

#     # Normal case: list everything, grouped by category
#     for cat, cat_items in grouped.items():
#         lines.append(f"*{cat}*")
#         shown = cat_items[:_MAX_ITEMS_PER_CATEGORY]
#         for it in shown:
#             name = it.get("name", "").strip()
#             if not name:
#                 continue
#             lines.append(f"  - {name} — {_price_label(it)}")
#         leftover = len(cat_items) - len(shown)
#         if leftover > 0:
#             lines.append(f"  ...and {leftover} more")
#         lines.append("")

#     if lang == "manglish":
#         lines.append("Enthelum help venam? \U0001F60A")
#     else:
#         lines.append("Anything else I can help with? \U0001F60A")

#     return "\n".join(lines).strip()


# # ══════════════════════════════════════════════════════════════════════════
# #  PIPELINE-CALLABLE ENTRY POINT
# # ══════════════════════════════════════════════════════════════════════════

# def get_full_menu_reply(
#     message: str,
#     cfg: dict,
#     lang: str,
#     slug: str | None = None,
# ) -> dict | None:
#     """Returns a pipeline-shaped result dict if `message` is a full-menu
#     query and the shop has items on file, else None (so the caller falls
#     through to the rest of the pipeline unchanged). Never calls Ollama —
#     the reply is built directly from shop_items.json, so it can never
#     invent an item or price that doesn't exist."""
#     if not is_full_menu_query(message):
#         return None

#     items = _load_items(slug)
#     whatsapp = (cfg or {}).get("contact", {}).get("whatsapp", "")
#     shop_type = (cfg or {}).get("shop_type")
#     noun = _catalog_noun(shop_type)

#     if not items:
#         # No catalog on file for this shop yet — be honest, don't fake one.
#         reply = (
#             f"{noun.capitalize()} details ippo ready alla — WhatsApp cheyyuka "
#             f"{whatsapp} enkil njangal full {noun} ayachu tharaam! \U0001F60A"
#             if lang == "manglish" else
#             f"I don't have the {noun} loaded yet — WhatsApp us at {whatsapp} "
#             f"and we'll send it right over! \U0001F60A"
#         )
#     else:
#         reply = format_full_menu(items, lang, whatsapp, shop_type)

#     return {
#         "reply": reply,
#         "source": "full_menu",
#         "bypass": "full_menu",
#         "sent_source": "full_menu",
#         "sentiment": "neutral",
#         "confidence": 0.99,
#         "faq_source": "shop_items",
#         "faq_id": "full_menu",
#         "faq_score": 1.0,
#         "escalate": False,
#     }




"""
full_menu.py — "show me the full menu / price list / services" intent
detector + formatter, generalized across ALL shop types
========================================================================
Drop this file next to chat.py / api.py.

Problem this solves
--------------------
The old "3.6. Full menu / catalog query" block inside chat.py's pipeline()
was hardcoded around the WORD "menu" — great for a restaurant, meaningless
for the other ~90 shop types this platform already has FAQ templates for
(faq_templates/: dental_clinic, gym, pharmacy, jwellery, law_firm,
tution, hospital, immigration, ...). A dental patient typing "treatment
list undo?" or a gym member typing "full services list" or a jeweller's
customer typing "full price list please" never matched "menu" at all and
fell through to Ollama free-generation, which has NO real item data in
its prompt and will happily invent a plausible-but-fake list.

Two things had to change, not just one:

  1. DETECTION must not be menu-only. It now matches ANY of the generic
     nouns a customer would use for "show me everything you sell/do":
     menu, price list, rate list/chart, catalog(ue), service(s) list,
     treatment(s) list, package(s) list, course(s)/class(es) list,
     item(s)/product(s) list — in English and Manglish, plus qualifier-
     free forms like "what all do you have", "everything you offer",
     "ellam undo".

  2. WORDING in the reply must match the shop type. A dental clinic
     shouldn't say "Here's our full menu" — it should say "Here's our
     full treatment list". This is driven off `cfg["shop_type"]` via
     _NOUN_BY_SHOP_TYPE below, with a sensible generic fallback for any
     shop_type not explicitly listed (so a brand-new vertical never
     breaks, it just gets the generic wording).

This module is self-contained: no Ollama call, no hallucination risk,
grounded 100% in shops/{slug}/shop_items.json. Import it from chat.py
and call `get_full_menu_reply(...)` as an early pipeline step (see
INTEGRATION NOTES at the bottom of this file).
"""

from __future__ import annotations

import json
import os
import re


# ══════════════════════════════════════════════════════════════════════════
#  WORDING PER SHOP TYPE
# ══════════════════════════════════════════════════════════════════════════
#
# Keyed off the SAME shop_type strings your PDF-extraction / chat.py code
# already uses (see chat.py's _BROAD_SVC_DEFAULTS and pdf.py's TYPE_KW).
# Anything not listed here falls back to _DEFAULT_NOUN — new shop types
# never crash, they just get generic-but-correct wording until someone
# adds a specific entry.

_NOUN_BY_SHOP_TYPE: dict[str, str] = {
    # Food & drink → "menu"
    "restaurant": "menu", "bakery": "menu", "coffee_shop": "menu",
    "fast_food": "menu", "catering_service": "menu", "hotel": "menu",
    "resorts": "menu",

    # Service-based businesses → "service list"
    "beauty_parlour": "service list", "salon": "service list",
    "spa": "service list", "gym": "service list",
    "tatto_studio": "service list", "laundry": "service list",
    "cleaning_service": "service list", "photography": "service list",
    "interior_design": "service list", "dance_academy": "service list",
    "driving_school": "service list", "ac_service_center": "service list",
    "car_rental": "service list", "taxi_service": "service list",
    "packers_and_movers": "service list", "logistic": "service list",
    "event_management": "service list", "hr_consultant": "service list",
    "immigration": "service list", "law_firm": "service list",
    "ca_firm": "service list", "architecture": "service list",
    "advertising_company": "service list", "construction": "service list",
    "printing_shop": "service list",

    # Clinical / treatment-based → "treatment list"
    "dental_clinic": "treatment list", "skin_clinic": "treatment list",
    "ayurvedic_clinic": "treatment list",
    "physiotherapy_clinic": "treatment list", "eye_clinic": "treatment list",
    "hospital": "treatment list", "medical_lab": "treatment list",

    # Retail / product-based → "price list"
    "pharmacy": "price list", "jewellery": "price list",
    "electronics": "price list", "electronic_products": "price list",
    "mobile_shop": "price list", "supermarket": "price list",
    "book_store": "price list", "stationary_shop": "price list",
    "hardware_store": "price list", "footwear_shop": "price list",
    "furniture_shop": "price list", "watch_shop": "price list",
    "sports_shop": "price list", "fish_shop": "price list",
    "computer_shop": "price list", "home_appliances_store": "price list",
    "bike_showroom": "price list", "pet_shop": "price list",
    "fitness_supplement_store": "price list", "opticals": "price list",
    "optical": "price list",

    # Travel / booking-based → "package list"
    "travel_agency": "package list", "adventure_tourism": "package list",
    "hostel": "package list", "overseas_education_consultancy": "package list",

    # Education → "course list"
    "tution": "course list", "tuition": "course list",
    "kindergarden": "course list", "school": "course list",
    "college": "course list", "yoga_center": "course list",
    "day_care": "course list",
}
_DEFAULT_NOUN = "price list"


def _catalog_noun(shop_type: str | None) -> str:
    return _NOUN_BY_SHOP_TYPE.get((shop_type or "").strip().lower(), _DEFAULT_NOUN)


# ══════════════════════════════════════════════════════════════════════════
#  INTENT DETECTION — English + Manglish, regex-based (not plain substring),
#  and NOT tied to any one shop type
# ══════════════════════════════════════════════════════════════════════════
#
# Word-boundary regex, not `phrase in message.lower()` substring checks —
# substring checks over-match (e.g. "menu" alone would match inside "is
# there a kids menu option") and under-match word-order variants ("menu
# full undo" vs "full menu undo"). Detection deliberately covers ALL the
# generic nouns (menu/price list/service list/treatment list/package
# list/course list/catalog) rather than filtering by the current shop's
# type — a customer might say "menu" loosely even at a salon, and that
# should still trigger the catalog reply, just worded correctly by
# _catalog_noun() above.

_NOUN_ALT = (
    r"(?:menu|price\s*list|rate\s*list|rate\s*chart|catalog(?:ue)?|"
    r"service(?:s)?\s*list|treatment(?:s)?\s*list|package(?:s)?\s*list|"
    r"course(?:s)?\s*list|class(?:es)?\s*list|item(?:s)?\s*list|"
    r"product(?:s)?\s*list|medicine(?:s)?\s*list|stock\s*list|"
    r"details)"
)

_FULL_MENU_RE = re.compile(
    r"("
    # ── English: qualifier + noun, allowing up to 2 filler words in
    # between ("full medicine details", "full product list", "need
    # full items and price"). Real customers rarely say "full price
    # list" cleanly.
    rf"\b(?:full|whole|complete|entire)\s+(?:\w+\s+){{0,2}}{_NOUN_ALT}\b"
    rf"|\bwhat'?s?\s+on\s+the\s+menu\b"
    rf"|\bwhat\s+is\s+on\s+the\s+menu\b"
    rf"|\bshow\s+(?:me\s+)?(?:the\s+|your\s+)?(?:full\s+)?{_NOUN_ALT}\b"
    rf"|\bsee\s+(?:the\s+|your\s+)?{_NOUN_ALT}\b"
    rf"|\b{_NOUN_ALT}\s+(?:card\s+)?please\b"
    rf"|\bsend\s+(?:me\s+)?(?:the\s+|your\s+)?{_NOUN_ALT}\b"
    rf"|\bcan\s+i\s+see\s+(?:the\s+|your\s+)?{_NOUN_ALT}\b"
    rf"|\bmenu\s+card\b"
    r"|\bwhat\s+all\s+(?:do\s+you\s+have|items?|do\s+you\s+offer|"
    r"do\s+you\s+sell|services?\s+do\s+you\s+(?:have|offer|provide)|"
    r"treatments?\s+do\s+you\s+(?:have|offer|provide)|"
    r"products?\s+do\s+you\s+(?:have|sell))\b"
    r"|\beverything\s+you\s+(?:have|offer|sell|provide|do)\b"
    r"|\ball\s+(?:the\s+)?(?:items?|services?|treatments?|products?|"
    r"packages?|courses?)\s+(?:you\s+have|available|list)\b"
    r"|\blist\s+of\s+(?:services?|items?|treatments?|products?|"
    r"packages?|courses?)\b"
    # ── Manglish: qualifier-noun forms ──────────────────────────────
    rf"|\b{_NOUN_ALT}\s+(?:und|undo|venam|kittumo|kaanikko|kanikku)\b"
    rf"|\bmuzhu(?:va)?n\s+{_NOUN_ALT}\b"
    rf"|\b{_NOUN_ALT}\s+muzhuvan\b"
    rf"|\b{_NOUN_ALT}\s+onnu\s+kan(?:ikk|ick)\w*\b"
    rf"|\b{_NOUN_ALT}\s+kaanikko\b"
    rf"|\b{_NOUN_ALT}\s+kanikku\w*\b"
    r"|\bfull\s+list\s+venam\b"
    rf"|\b{_NOUN_ALT}\s+enthu\s+(?:und|undu)\b"
    rf"|\b{_NOUN_ALT}\s+ariyano\b"
    rf"|\b{_NOUN_ALT}\s+tharumo\b"
    rf"|\b{_NOUN_ALT}\s+ayaykku?m?o\b"
    rf"|\b{_NOUN_ALT}\s+onnu\s+ayakku?\w*\b"
    rf"|\bfull\s+{_NOUN_ALT}\s+ayakk\w*\b"
    rf"|\b{_NOUN_ALT}\s+full\s+aayi\b"
    # ── Manglish: bare "what all / everything" forms — allow up to 2
    # filler words before "und/undo/etc" ("enthokke items und?",
    # "ellam enthu items venam"). Also accepts "enthoke" (missing the
    # "n" — a very common spelling, confirmed in production logs).
    r"|\bwhat\s+all\s+(?:\w+\s+){0,2}(?:undu|und)\b"
    r"|\benthok?ke\s+(?:\w+\s+){0,2}und[oe]?\b"
    r"|\benthellam\s+(?:\w+\s+){0,2}und[oe]?\b"
    r"|\bellam\s+(?:\w+\s+){0,2}und[oe]?\b"
    r"|\bella(?:m)?\s+(?:\w+\s+){0,2}(?:items?|services?|treatments?)\s+"
    r"(?:und|venam|kanikku)\b"
    r")",
    re.IGNORECASE,
)


def is_full_menu_query(message: str) -> bool:
    """True if the message is asking for the FULL catalog (menu / price
    list / service list / treatment list / package list / course list —
    whatever noun fits, in any shop type), not a specific item. Callers
    should check this BEFORE any specific-item lookup, since a "full
    list" question itself contains no single item name to match on."""
    return bool(_FULL_MENU_RE.search(message or ""))


# ══════════════════════════════════════════════════════════════════════════
#  DATA LOADING
# ══════════════════════════════════════════════════════════════════════════

def _normalize_slug(slug: str) -> str:
    return slug.strip().lower().replace(" ", "-")


def _load_items(slug: str | None) -> list[dict]:
    if not slug:
        return []
    path = os.path.join("shops", _normalize_slug(slug), "shop_items.json")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f) or []
            return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _price_label(it: dict) -> str:
    if "price" in it and it["price"] is not None:
        return f"Rs. {it['price']:,}"
    if it.get("price_min") is not None and it.get("price_max") is not None:
        return f"Rs. {it['price_min']:,}-{it['price_max']:,}"
    return "on request"


# ══════════════════════════════════════════════════════════════════════════
#  FORMATTING
# ══════════════════════════════════════════════════════════════════════════
#
# Kept deliberately non-LLM: the list below is built directly from
# shop_items.json, so there is zero hallucination risk. This mirrors how
# item_lookup()/category_list() already work elsewhere in this codebase
# (see chat.py's _needs_rephrase(), which explicitly keeps those OUT of
# the Ollama rephrase step for the same reason).

# Hard cap so one giant catalog doesn't blow past chat-UI/WhatsApp message
# limits. Past this many items, switch to a category-count summary instead
# of listing every single item.
_MAX_ITEMS_TO_LIST = 60
_MAX_ITEMS_PER_CATEGORY = 12


def _group_by_category(items: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for it in items:
        cat = (it.get("category") or "Other").strip() or "Other"
        grouped.setdefault(cat, []).append(it)
    return grouped


def format_full_menu(
    items: list[dict],
    lang: str,
    whatsapp: str = "",
    shop_type: str | None = None,
) -> str:
    if not items:
        return ""

    grouped = _group_by_category(items)
    total = len(items)
    noun = _catalog_noun(shop_type)          # e.g. "menu" / "service list" / "treatment list"

    lines: list[str] = []
    if lang == "manglish":
        lines.append(f"Njangalude full {noun} ithaanu \U0001F447")
    else:
        lines.append(f"Here's our full {noun} \U0001F447")
    lines.append("")

    if total > _MAX_ITEMS_TO_LIST:
        # Too big to dump in one chat bubble — category breakdown + counts
        # instead of a wall of text, still 100% grounded (real category
        # names, real counts), plus a couple of examples per category so
        # it doesn't read as empty.
        for cat, cat_items in grouped.items():
            examples = ", ".join(i.get("name", "") for i in cat_items[:3])
            lines.append(f"*{cat}* ({len(cat_items)} items) — e.g. {examples}")
        lines.append("")
        if lang == "manglish":
            lines.append(
                f"Full {noun} ({total} items) valuthaanu — WhatsApp cheyyuka "
                f"{whatsapp} enkil complete {noun} ayachu tharaam! \U0001F60A"
                if whatsapp else
                f"Full {noun} has {total} items — ask about a category or "
                f"specific item and I'll give you the price! \U0001F60A"
            )
        else:
            lines.append(
                f"That's {total} items total — WhatsApp us at {whatsapp} "
                f"for the complete {noun}, or ask about a specific "
                f"category/item and I'll answer right here! \U0001F60A"
                if whatsapp else
                f"That's {total} items total — ask about a specific "
                f"category or item and I'll give you the price! \U0001F60A"
            )
        return "\n".join(lines)

    # Normal case: list everything, grouped by category
    for cat, cat_items in grouped.items():
        lines.append(f"*{cat}*")
        shown = cat_items[:_MAX_ITEMS_PER_CATEGORY]
        for it in shown:
            name = it.get("name", "").strip()
            if not name:
                continue
            lines.append(f"  - {name} — {_price_label(it)}")
        leftover = len(cat_items) - len(shown)
        if leftover > 0:
            lines.append(f"  ...and {leftover} more")
        lines.append("")

    if lang == "manglish":
        lines.append("Enthelum help venam? \U0001F60A")
    else:
        lines.append("Anything else I can help with? \U0001F60A")

    return "\n".join(lines).strip()


# ══════════════════════════════════════════════════════════════════════════
#  PIPELINE-CALLABLE ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

def get_full_menu_reply(
    message: str,
    cfg: dict,
    lang: str,
    slug: str | None = None,
) -> dict | None:
    """Returns a pipeline-shaped result dict if `message` is a full-menu
    query and the shop has items on file, else None (so the caller falls
    through to the rest of the pipeline unchanged). Never calls Ollama —
    the reply is built directly from shop_items.json, so it can never
    invent an item or price that doesn't exist."""
    if not is_full_menu_query(message):
        return None

    items = _load_items(slug)
    whatsapp = (cfg or {}).get("contact", {}).get("whatsapp", "")
    shop_type = (cfg or {}).get("shop_type")
    noun = _catalog_noun(shop_type)

    if not items:
        # No catalog on file for this shop yet — be honest, don't fake one.
        reply = (
            f"{noun.capitalize()} details ippo ready alla — WhatsApp cheyyuka "
            f"{whatsapp} enkil njangal full {noun} ayachu tharaam! \U0001F60A"
            if lang == "manglish" else
            f"I don't have the {noun} loaded yet — WhatsApp us at {whatsapp} "
            f"and we'll send it right over! \U0001F60A"
        )
    else:
        reply = format_full_menu(items, lang, whatsapp, shop_type)

    return {
        "reply": reply,
        "source": "full_menu",
        "bypass": "full_menu",
        "sent_source": "full_menu",
        "sentiment": "neutral",
        "confidence": 0.99,
        "faq_source": "shop_items",
        "faq_id": "full_menu",
        "faq_score": 1.0,
        "escalate": False,
    }
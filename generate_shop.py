
# """
# generate_shop.py — v7.1
# Universal shop config + FAQ generator from extracted items.

# FIXES in v7.1:
#   - Added generate_shop_files(info: dict) bridge function.
#     api.py calls gs.generate_shop_files(info) — this now works correctly.
#     It extracts shop_items from the info dict, calls generate_shop_from_items,
#     then patches the config with all real metadata so nothing is lost.
#   - generate_shop_from_items() is unchanged — still the canonical entry point
#     when called from CLI or directly.
# """

# import json
# import os
# import re
# import sys
# import argparse
# from collections import defaultdict
# import requests

# from dynamic_shop_profile import get_shop_profile_with_cache, ShopProfile  # pyright: ignore[reportMissingImports]

# # ============================================================
# #  CONFIGURATION
# # ============================================================
# OLLAMA_URL   = "http://localhost:11434/api/generate"
# OLLAMA_MODEL = "gemma3:4b"

# DEFAULTS = {
#     "shop_name":       "Our Shop",
#     "shop_type":       "general",
#     "hours_weekdays":  "Mon–Sat 9AM–8PM",
#     "hours_sunday":    "Sunday 10AM–6PM",
#     "hours_holiday":   "Check WhatsApp for holiday hours",
#     "location":        "Kerala, India",
#     "whatsapp":        "+91 00000 00000",
#     "email":           "support@example.com",
#     "payment":         ["UPI", "Cards", "Cash"],
#     "delivery_areas":  "Local area",
#     "delivery_free":   "₹500",
#     "delivery_days":   "2–3 working days",
#     "return_days":     7,
#     "return_condition":"unused with original packaging",
#     "refund_days":     "5–7 business days",
#     "offer_code":      "WELCOME10",
#     "offer_desc":      "10% off for new customers",
# }

# VEG_NAME_SIGNALS: list[str] = [
#     "veg", "pure veg", "satvic", "satvik", "brahmin", "jain",
#     "shudh", "shuddh", "sattvik",
# ]

# NON_VEG_ITEM_SIGNALS: list[str] = [
#     "chicken", "mutton", "beef", "pork", "fish", "prawn", "shrimp",
#     "crab", "lobster", "egg", "meat", "lamb", "turkey", "tuna",
#     "salmon", "sardine", "anchovy", "bacon", "sausage", "keema",
# ]

# SHOP_GENDER_NAME_SIGNALS: dict[str, list[str]] = {
#     "babies":  ["baby", "infant", "toddler", "newborn", "kids wear", "baby store",
#                 "baby shop", "little ones"],
#     "boys":    ["boys", "boy", "junior boys", "gents boy"],
#     "girls":   ["girls", "girl", "junior girls"],
#     "kids":    ["kids", "children", "child", "junior"],
#     "men":     ["mens", "men's", "gents", "male", "man"],
#     "women":   ["womens", "women's", "ladies", "female", "woman", "girl"],
#     "unisex":  ["unisex", "all gender", "everyone"],
# }

# SPECIALISATION_SIGNALS: dict[str, tuple[str, list[str]]] = {
#     "cake":        ("bakery",         ["Cakes", "Pastries"]),
#     "cakes":       ("bakery",         ["Cakes", "Pastries"]),
#     "pastry":      ("bakery",         ["Cakes", "Pastries"]),
#     "bread":       ("bakery",         ["Breads", "Snacks"]),
#     "cookie":      ("bakery",         ["Cookies", "Snacks"]),
#     "biscuit":     ("bakery",         ["Cookies", "Snacks"]),
#     "juice":       ("restaurant",     ["Beverages"]),
#     "ice cream":   ("restaurant",     ["Desserts", "Beverages"]),
#     "icecream":    ("restaurant",     ["Desserts", "Beverages"]),
#     "mandi":       ("restaurant",     ["Chicken", "Mutton", "Rice", "Breads"]),
#     "mandhi":      ("restaurant",     ["Chicken", "Mutton", "Rice", "Breads"]),
#     "biryani":     ("restaurant",     ["Biryani", "Rice", "Curries"]),
#     "shawarma":    ("restaurant",     ["Starters", "Snacks", "Beverages"]),
#     "pizza":       ("restaurant",     ["Starters", "Snacks", "Beverages", "Desserts"]),
#     "chinese":     ("restaurant",     ["Noodles", "Rice", "Starters", "Soups", "Beverages"]),
#     "seafood":     ("restaurant",     ["Seafood", "Starters", "Rice", "Curries"]),
#     "tea":         ("restaurant",     ["Beverages", "Snacks"]),
#     "chai":        ("restaurant",     ["Beverages", "Snacks"]),
#     "coffee":      ("restaurant",     ["Beverages", "Snacks", "Desserts"]),
#     "saree":       ("clothing",       ["Sarees", "Accessories"]),
#     "sari":        ("clothing",       ["Sarees", "Accessories"]),
#     "kurta":       ("clothing",       ["Kurtas", "Ethnic Wear", "Accessories"]),
#     "suit":        ("clothing",       ["Ethnic Wear", "Western Wear", "Accessories"]),
#     "uniform":     ("clothing",       ["Uniforms"]),
#     "sportswear":  ("clothing",       ["Sportswear", "Accessories"]),
#     "innerwear":   ("clothing",       ["Innerwear"]),
#     "bridal":      ("beauty_parlour", ["Bridal Makeup", "Hair Spa", "Facial", "Skin Care",
#                                        "Manicure", "Pedicure"]),
#     "hair":        ("beauty_parlour", ["Haircuts", "Hair Color", "Hair Spa"]),
#     "skin":        ("beauty_parlour", ["Facial", "Skin Care", "Waxing", "Threading"]),
#     "nail":        ("beauty_parlour", ["Manicure", "Pedicure"]),
#     "yoga":        ("gym",            ["Yoga", "Group Classes", "Diet Plans"]),
#     "crossfit":    ("gym",            ["CrossFit", "Strength", "Cardio"]),
#     "zumba":       ("gym",            ["Group Classes", "Cardio"]),
# }

# GENDER_KEYWORDS: dict[str, list[str]] = {
#     "babies": ["baby", "infant", "toddler", "newborn"],
#     "boys":   ["boys", "boy", "junior boys", "kids boys"],
#     "girls":  ["girls", "girl", "junior girls", "kids girls"],
#     "kids":   ["kids", "children", "child", "junior"],
#     "men":    ["men", "male", "gents", "man", "mens"],
#     "women":  ["women", "female", "ladies", "woman", "womens"],
#     "unisex": ["unisex", "universal", "all gender", "both"],
#     "all":    ["all", "everyone"],
# }


# # ============================================================
# #  OLLAMA HELPERS
# # ============================================================
# def call_ollama(prompt: str, system: str = "") -> str:
#     try:
#         resp = requests.post(
#             OLLAMA_URL,
#             json={
#                 "model":   OLLAMA_MODEL,
#                 "system":  system,
#                 "prompt":  prompt,
#                 "stream":  False,
#                 "options": {"temperature": 0.2, "num_predict": 200},
#             },
#             timeout=30,
#         )
#         resp.raise_for_status()
#         return resp.json().get("response", "").strip()
#     except Exception as e:
#         print(f"[Ollama error] {e}")
#         return ""


# def infer_shop_type(items: list) -> str:
#     sample = [it.get("name", "") for it in items[:20]]
#     valid  = ["clothing", "gym", "beauty_parlour", "restaurant", "bakery",
#               "electronics", "pharmacy", "jewellery", "optical", "school", "general"]
#     prompt = (
#         f"Given these product/service names, what is the most likely shop type? "
#         f"Choose ONLY one word from: {', '.join(valid)}.\n"
#         f"Return only that single word.\n\nProducts: {', '.join(sample)}"
#     )
#     reply = call_ollama(prompt).lower().strip()
#     for t in valid:
#         if t in reply:
#             return t
#     return "general"


# def detect_veg(items: list, shop_name: str, shop_type: str, use_ollama: bool = True) -> bool:
#     if shop_type not in ("restaurant", "bakery"):
#         return False
#     lower_name = shop_name.lower()
#     if any(sig in lower_name for sig in VEG_NAME_SIGNALS):
#         return True
#     for item in items:
#         lower_item = item.get("name", "").lower()
#         if any(sig in lower_item for sig in NON_VEG_ITEM_SIGNALS):
#             return False
#     if use_ollama and items:
#         sample = [it.get("name", "") for it in items[:20]]
#         prompt = (
#             f"Is this a pure vegetarian (no meat, fish, or eggs) restaurant?\n"
#             f"Shop name: {shop_name}\n"
#             f"Menu sample: {', '.join(sample)}\n"
#             f"Answer only: yes or no"
#         )
#         reply = call_ollama(prompt).lower().strip()
#         if reply.startswith("yes"):
#             return True
#     return True


# def detect_shop_gender(
#     items: list, shop_name: str, shop_type: str, use_ollama: bool = True
# ) -> str:
#     SHOP_GENDER_THRESHOLD = 0.90
#     lower_name = shop_name.lower()
#     food_types = {"restaurant", "bakery", "electronics", "pharmacy", "general"}
#     if shop_type in food_types:
#         return "all"
#     valid = list(GENDER_KEYWORDS.keys())

#     for gender, keywords in SHOP_GENDER_NAME_SIGNALS.items():
#         if gender not in valid:
#             continue
#         for kw in keywords:
#             if re.search(r'\b' + re.escape(kw) + r'\b', lower_name):
#                 print(f"[shop_gender] '{kw}' in name → {gender}")
#                 return gender

#     gender_counts: dict[str, int] = defaultdict(int)
#     for it in items:
#         g = it.get("gender", "")
#         if g and g != "all":
#             gender_counts[g] += 1
#     total_with_gender = sum(gender_counts.values())
#     if total_with_gender > 0:
#         top_gender, top_count = max(gender_counts.items(), key=lambda x: x[1])
#         if top_count / total_with_gender >= SHOP_GENDER_THRESHOLD and top_gender in valid:
#             print(f"[shop_gender] item vote ({top_count}/{total_with_gender}) → {top_gender}")
#             return top_gender

#     if use_ollama:
#         sample    = [it.get("name", "") for it in items[:15]]
#         valid_str = ", ".join(valid)
#         prompt    = (
#             f"Is this shop exclusively for one gender group?\n"
#             f"Shop name: {shop_name}\n"
#             f"Sample items: {', '.join(sample)}\n"
#             f"Choose ONE from: {valid_str}, all\n"
#             f"Return only the single word."
#         )
#         reply = call_ollama(prompt).lower().strip()
#         for g in valid:
#             if g in reply:
#                 print(f"[shop_gender] Ollama → {g}")
#                 return g

#     return "all"


# def detect_specialisation(
#     items: list, shop_name: str, shop_type: str, use_ollama: bool = True,
#     _profile_cats: list | None = None,
# ) -> tuple[str | None, list[str]]:
#     lower_name = shop_name.lower()
#     full_cats  = _profile_cats if _profile_cats else ["General"]

#     for signal, (target_type, cats) in SPECIALISATION_SIGNALS.items():
#         if target_type != shop_type:
#             continue
#         if re.search(r'\b' + re.escape(signal) + r'\b', lower_name):
#             valid_cats = [c for c in cats if c in full_cats]
#             if valid_cats:
#                 print(f"[specialisation] '{signal}' in name → {valid_cats}")
#                 return signal, valid_cats

#     SPEC_THRESHOLD = 0.80
#     cat_counts: dict[str, int] = defaultdict(int)
#     for it in items:
#         c = it.get("category", "")
#         if c:
#             cat_counts[c] += 1
#     if cat_counts:
#         total    = sum(cat_counts.values())
#         top_cats = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)
#         accumulated, chosen = 0, []
#         for cat, cnt in top_cats:
#             accumulated += cnt
#             chosen.append(cat)
#             if accumulated / total >= SPEC_THRESHOLD:
#                 break
#         if len(chosen) <= 2 and accumulated / total >= SPEC_THRESHOLD:
#             label = "+".join(c.lower() for c in chosen)
#             print(f"[specialisation] item vote → {chosen}")
#             return label, chosen

#     if use_ollama and len(full_cats) > 4:
#         sample = [it.get("name", "") for it in items[:20]]
#         prompt = (
#             f"Does this shop specialise in only a few categories from {full_cats}?\n"
#             f"Shop name: {shop_name}\n"
#             f"Items: {', '.join(sample)}\n"
#             f"If yes, list the matching categories as comma-separated names from the list. "
#             f"If no specialisation, return 'all'."
#         )
#         reply = call_ollama(prompt, system="Return only category names from the list, or 'all'.")
#         if reply.lower().strip() != "all":
#             matched = [c for c in full_cats if c.lower() in reply.lower()]
#             if matched:
#                 print(f"[specialisation] Ollama → {matched}")
#                 return "ollama_inferred", matched

#     return None, full_cats


# def infer_shop_name(items: list, fallback: str) -> str:
#     sample = [it.get("name", "") for it in items[:10]]
#     prompt = (
#         f"Based on these products/services, suggest a short shop name (max 3 words). "
#         f"Products: {', '.join(sample)}"
#     )
#     reply = call_ollama(prompt)
#     return reply if reply and len(reply.split()) <= 5 else fallback


# def infer_hours_location(shop_type: str) -> dict:
#     prompt = (
#         f"For a typical {shop_type} shop in Kerala, suggest opening hours and location. "
#         f'Return JSON: {{"hours_weekdays": "...", "hours_sunday": "...", "location": "..."}}'
#     )
#     reply = call_ollama(prompt, system="Return only valid JSON, no explanation.")
#     try:
#         data = json.loads(reply)
#         return {
#             "hours_weekdays": data.get("hours_weekdays", DEFAULTS["hours_weekdays"]),
#             "hours_sunday":   data.get("hours_sunday",   DEFAULTS["hours_sunday"]),
#             "location":       data.get("location",       DEFAULTS["location"]),
#         }
#     except Exception:
#         return {
#             "hours_weekdays": DEFAULTS["hours_weekdays"],
#             "hours_sunday":   DEFAULTS["hours_sunday"],
#             "location":       DEFAULTS["location"],
#         }


# def infer_item_gender(item_name: str, shop_type: str) -> str:
#     lower_name = item_name.lower()
#     food_types = {"restaurant", "bakery", "electronics", "pharmacy", "general"}
#     if shop_type in food_types:
#         return "all"
#     valid_genders = list(GENDER_KEYWORDS.keys())

#     for gender, keywords in GENDER_KEYWORDS.items():
#         if gender not in valid_genders:
#             continue
#         for kw in keywords:
#             if re.search(r'\b' + re.escape(kw) + r'\b', lower_name):
#                 return gender

#     valid_str = ", ".join(valid_genders)
#     prompt    = (
#         f"What gender is this product/service for? "
#         f"Choose ONLY from: {valid_str}. "
#         f"Product: {item_name}\n"
#         f"Return only the single word."
#     )
#     reply = call_ollama(prompt).lower().strip()
#     for g in valid_genders:
#         if g in reply:
#             return g
#     return "all"


# def infer_category(item_name: str, shop_type: str, allowed_cats: list | None = None) -> str:
#     categories = allowed_cats or ["General"]
#     prompt     = (
#         f"Which category from {categories} best fits '{item_name}'? "
#         f"Return ONLY the category name, nothing else."
#     )
#     reply = call_ollama(prompt)
#     for cat in categories:
#         if cat.lower() in reply.lower():
#             return cat
#     return categories[0] if categories else "General"


# def infer_signature_items(items: list, shop_type: str) -> str:
#     priced = [it for it in items if it.get("price")]
#     if priced:
#         priced.sort(key=lambda x: x.get("price", 0), reverse=True)
#         tops = [it["name"] for it in priced[:3]]
#         if len(tops) >= 2:
#             return ", ".join(tops)
#     sample = [it.get("name", "") for it in items[:15]]
#     prompt = (
#         f"From these {shop_type} items/services: {', '.join(sample)}, "
#         f"list 3 signature ones as comma-separated names. Return only the names."
#     )
#     reply = call_ollama(prompt)
#     return reply if reply else ""


# # ============================================================
# #  ENRICH ITEMS
# # ============================================================
# def enrich_items(
#     items: list,
#     shop_type: str,
#     use_ollama: bool = True,
#     shop_gender: str = "all",
#     allowed_categories: list | None = None,
# ) -> list:
#     enriched      = []
#     valid_genders = list(GENDER_KEYWORDS.keys())
#     allowed_cats  = allowed_categories or ["General"]
#     single_gender = shop_gender != "all"

#     for item in items:
#         item = item.copy()

#         if single_gender:
#             item["gender"] = shop_gender
#         elif not item.get("gender"):
#             item["gender"] = infer_item_gender(item.get("name", ""), shop_type) if use_ollama else "all"
#         else:
#             provided = item["gender"].lower().strip()
#             matched  = next((g for g in valid_genders if g in provided or provided in g), None)
#             item["gender"] = matched if matched else "all"

#         if not item.get("category"):
#             item["category"] = (
#                 infer_category(item.get("name", ""), shop_type, allowed_cats)
#                 if use_ollama else (allowed_cats[0] if allowed_cats else "General")
#             )
#         else:
#             provided_cat = item["category"].strip()
#             if provided_cat not in allowed_cats:
#                 item["category"] = (
#                     infer_category(item.get("name", ""), shop_type, allowed_cats)
#                     if use_ollama else (allowed_cats[0] if allowed_cats else provided_cat)
#                 )

#         enriched.append(item)
#     return enriched


# # ============================================================
# #  FORMAT PRICE
# # ============================================================
# def format_price(item: dict) -> str:
#     if "price" in item:
#         return f"₹{item['price']:,}"
#     if "price_min" in item and "price_max" in item:
#         return f"₹{item['price_min']:,} – ₹{item['price_max']:,}"
#     return "price on request"


# # ============================================================
# #  AUTO-GENERATE FAQs
# # ============================================================
# def build_item_faqs(
#     items: list,
#     shop_type: str,
#     is_veg: bool = False,
#     shop_gender: str = "all",
#     specialisation: str | None = None,
#     profile: "ShopProfile | None" = None,
# ) -> list:
#     if not items:
#         return []

#     faqs:     list = []
#     seen_ids: set  = set()

#     item_label  = profile.item_label if profile else "items"
#     q_templates = profile.faq_templates if profile else [
#         "{gender_cat} undo?", "{gender_cat} available aano?",
#         "{gender_cat} kittumo?", "Do you have {gender_cat}?",
#         "What {gender_cat} do you offer?",
#     ]
#     veg_badge   = " 🌿" if is_veg and shop_type in ("restaurant", "bakery") else ""

#     spec_prefix = (specialisation or "").replace("+", "/").replace("_", " ").strip()
#     if spec_prefix in ("ollama_inferred", "all") or not spec_prefix:
#         spec_prefix = ""

#     by_cat_gender: dict = defaultdict(list)
#     for it in items:
#         cat = it.get("category", "General").strip()
#         gen = it.get("gender",   "all").strip()
#         by_cat_gender[(cat, gen)].append(it)

#     for (cat, gen), cat_items in by_cat_gender.items():
#         if shop_gender != "all" and gen not in (shop_gender, "all"):
#             continue

#         slug_key = re.sub(r'[^a-z0-9_]', '_', f"{gen}_{cat}".lower())[:40]
#         faq_id   = f"cat_{slug_key}"
#         if faq_id in seen_ids:
#             continue
#         seen_ids.add(faq_id)

#         if shop_gender != "all" and gen == shop_gender:
#             prefix = cat
#         elif gen != "all":
#             prefix = f"{gen.capitalize()} {cat}"
#         else:
#             prefix = cat

#         lines  = [f"• {it['name']} — {format_price(it)}" for it in cat_items[:10]]
#         answer = f"{prefix} {item_label}{veg_badge}:\n" + "\n".join(lines)
#         if len(cat_items) > 10:
#             answer += f"\n...and {len(cat_items) - 10} more. WhatsApp {{whatsapp}} for full list."

#         parts = []
#         if is_veg and shop_type in ("restaurant", "bakery"):
#             parts = ["veg"]
#         if spec_prefix:
#             parts.append(spec_prefix)
#         if shop_gender == "all" and gen != "all":
#             parts.append(gen)
#         parts.append(cat.lower())
#         gender_cat = " ".join(parts)

#         variants = [t.format(gender_cat=gender_cat) for t in q_templates]

#         faq: dict = {
#             "id":                faq_id,
#             "category":          "catalog",
#             "question_variants": variants,
#             "answer":            answer,
#         }
#         if shop_type in ("restaurant", "bakery"):
#             faq["dietary"] = "veg_only" if is_veg else "veg_nonveg"
#         faqs.append(faq)

#     for it in items:
#         name = it.get("name", "")
#         if not name or len(name) < 3:
#             continue
#         faq_id = "item_" + re.sub(r'[^a-z0-9]', '_', name.lower())[:30]
#         if faq_id in seen_ids:
#             continue
#         seen_ids.add(faq_id)

#         variants = [
#             f"How much is {name}?",
#             f"Price of {name}?",
#             f"{name} vila enthu?",
#             f"{name} rate?",
#         ]
#         faqs.append({
#             "id":                faq_id,
#             "category":          "pricing",
#             "question_variants": variants,
#             "answer":            f"{name} — {format_price(it)}. WhatsApp {{whatsapp}} for details.",
#         })

#     return faqs


# # ============================================================
# #  MAIN GENERATOR
# # ============================================================
# def generate_shop_from_items(items: list, use_ollama: bool = True) -> tuple:
#     """
#     Primary entry point.
#     Returns (config, faqs, enriched_items).
#     config is populated with DEFAULTS — caller should patch real metadata on top.
#     """
#     if not items:
#         print("No items provided.")
#         sys.exit(1)

#     shop_type = infer_shop_type(items) if use_ollama else "general"
#     print(f"[Inferred shop_type] {shop_type}")

#     shop_name = infer_shop_name(items, DEFAULTS["shop_name"]) if use_ollama else DEFAULTS["shop_name"]

#     shop_gender = detect_shop_gender(items, shop_name, shop_type, use_ollama)
#     print(f"[shop_gender] {shop_gender}")

#     profile = get_shop_profile_with_cache(shop_name, shop_type, items, use_ollama)
#     print(f"[profile] source={profile.source} cats={profile.categories} label='{profile.item_label}'")

#     specialisation, allowed_categories = detect_specialisation(
#         items, shop_name, shop_type, use_ollama,
#         _profile_cats=profile.categories,
#     )
#     print(f"[specialisation] {specialisation or 'none'} → {allowed_categories}")

#     items = enrich_items(
#         items, shop_type, use_ollama,
#         shop_gender=shop_gender,
#         allowed_categories=allowed_categories,
#     )

#     hours_loc = infer_hours_location(shop_type) if use_ollama else {
#         "hours_weekdays": DEFAULTS["hours_weekdays"],
#         "hours_sunday":   DEFAULTS["hours_sunday"],
#         "location":       DEFAULTS["location"],
#     }
#     signature = infer_signature_items(items, shop_type) if use_ollama else ""

#     is_veg       = detect_veg(items, shop_name, shop_type, use_ollama)
#     dietary_mode = "veg_only" if is_veg else ("veg_nonveg" if shop_type in ("restaurant", "bakery") else None)
#     if shop_type in ("restaurant", "bakery"):
#         print(f"[Dietary mode] {'veg_only (pure veg)' if is_veg else 'veg_nonveg'}")

#     config = {
#         "bot_name":           shop_name.split()[0][:10] if shop_name else "Bot",
#         "shop_name":          shop_name,
#         "shop_type":          shop_type,
#         "tagline":            "English & Manglish",
#         "description":        f"{shop_name} – auto-generated from items",
#         "location":           hours_loc.get("location",       DEFAULTS["location"]),
#         "city":               "Kerala",
#         "state":              "Kerala",
#         "hours": {
#             "weekdays": hours_loc.get("hours_weekdays", DEFAULTS["hours_weekdays"]),
#             "sunday":   hours_loc.get("hours_sunday",   DEFAULTS["hours_sunday"]),
#             "holiday":  DEFAULTS["hours_holiday"],
#         },
#         "contact": {
#             "whatsapp": DEFAULTS["whatsapp"],
#             "phone":    DEFAULTS["whatsapp"],
#             "email":    DEFAULTS["email"],
#         },
#         "payment":  DEFAULTS["payment"],
#         "services": [],
#         "delivery": {
#             "areas":      DEFAULTS["delivery_areas"],
#             "free_above": DEFAULTS["delivery_free"],
#             "days":       DEFAULTS["delivery_days"],
#         },
#         "returns": {
#             "days":        DEFAULTS["return_days"],
#             "condition":   DEFAULTS["return_condition"],
#             "refund_days": DEFAULTS["refund_days"],
#         },
#         "first_offer": {
#             "code":        DEFAULTS["offer_code"],
#             "description": DEFAULTS["offer_desc"],
#         },
#         "escalate": {
#             "whatsapp": DEFAULTS["whatsapp"],
#             "email":    DEFAULTS["email"],
#         },
#         "language":           "english_manglish",
#         "currency":           "INR",
#         "shop_gender":        shop_gender,
#         "specialisation":     specialisation,
#         "allowed_categories": allowed_categories,
#         "item_label":         profile.item_label,
#         "profile_source":     profile.source,
#         "is_veg":             is_veg,
#         "dietary_mode":       dietary_mode,
#         "escalate_topics":    ["fraud", "refund", "complaint"],
#         "blocked_topics":     [],
#         "blocked_reply": {
#             "manglish": "Athu njangalude shop-il applicable alla 😊 Enthelum help cheyyamo?",
#             "english":  "That's not applicable here. Can I help with something else?",
#         },
#         "quick_chips":    [],
#         "welcome_cards":  [],
#         "item_count":     len(items),
#         "signature_items": signature,
#     }

#     core_faqs = [
#         {
#             "id": "core_contact",
#             "category": "support",
#             "question_variants": [
#                 "Contact number?", "WhatsApp number?", "number enthu?", "contact info?",
#             ],
#             "answer": "WhatsApp: {whatsapp} | Email: {email} | Open {hours_weekdays}.",
#         },
#         {
#             "id": "core_hours",
#             "category": "store",
#             "question_variants": [
#                 "What are your hours?", "timings entha?", "open aano?", "eppol thurakum?",
#             ],
#             "answer": "Open {hours_weekdays} and {hours_sunday}. {hours_holiday}.",
#         },
#         {
#             "id": "core_location",
#             "category": "store",
#             "question_variants": [
#                 "Where are you?", "shop evide?", "address?", "location enthu?",
#             ],
#             "answer": "We are at {location}. WhatsApp {whatsapp} for directions!",
#         },
#         {
#             "id": "core_payment",
#             "category": "payment",
#             "question_variants": [
#                 "Payment methods?", "enthu payment undo?", "UPI undо?", "card undо?",
#             ],
#             "answer": "We accept UPI, Cards, Cash, GPay, PhonePe, Paytm.",
#         },
#     ]

#     if signature:
#         core_faqs.append({
#             "id":       "core_signature",
#             "category": "catalog",
#             "question_variants": [
#                 "signature items enthu?", "special items undo?",
#                 "best items enthu?",      "top picks?",
#             ],
#             "answer": f"Njangal best picks: {signature}. WhatsApp {{whatsapp}} to enquire!",
#         })

#     if is_veg and shop_type in ("restaurant", "bakery"):
#         core_faqs.append({
#             "id":       "core_veg",
#             "category": "dietary",
#             "question_variants": [
#                 "pure veg aano?", "non-veg undo?", "egg use cheyyumo?",
#                 "veg only restaurant aano?", "meat undо?",
#                 "is this vegetarian?", "100% veg aano?",
#             ],
#             "answer": (
#                 "Athe! Njangal 100% pure veg ആണ് 🌿 "
#                 "Meat, fish, egg onnum use cheyyunnilla. "
#                 "Njangal satvic food serve cheyyunnu."
#             ),
#         })

#     item_faqs = build_item_faqs(
#         items, shop_type,
#         is_veg=is_veg,
#         shop_gender=shop_gender,
#         specialisation=specialisation,
#         profile=profile,
#     )
#     all_faqs = core_faqs + item_faqs

#     try:
#         from generate_faqs import load_type_faqs as _load_type_faqs
#         type_faqs = _load_type_faqs(shop_type, types_dir="faqs/types")
#         if type_faqs:
#             existing_ids  = {f.get("id", "") for f in all_faqs}
#             type_filtered = [
#                 f for f in type_faqs
#                 if f.get("id", "") not in existing_ids
#                 and f.get("category", "") not in ("catalog", "pricing")
#                 and f.get("tier", "type") != "base"
#             ]
#             all_faqs = core_faqs + type_filtered + item_faqs
#             print(f"[generate_shop] type pack +{len(type_filtered)} FAQs for '{shop_type}'")
#     except Exception as e:
#         print(f"[generate_shop] type pack skipped: {e}")

#     return config, all_faqs, items


# # ============================================================
# #  BRIDGE FUNCTION  (v7.1 — NEW)
# #  Called by api.py:  config, faqs, items = gs.generate_shop_files(info)
# # ============================================================
# def generate_shop_files(info: dict, use_ollama: bool = True) -> tuple:
#     """
#     Bridge between api.py's info-dict calling convention and
#     generate_shop_from_items(items_list, use_ollama).

#     Steps:
#       1. Extract shop_items from info (or create a stub if empty).
#       2. Run generate_shop_from_items to get AI-inferred config/FAQs.
#       3. Patch every config field with the real values from info.
#       4. Return (config, faqs, items) — same tuple shape.
#     """
#     raw_items = info.get("shop_items") or []
#     if not raw_items:
#         raw_items = [{
#             "name":     info.get("shop_name", "Item"),
#             "category": info.get("shop_type", "general"),
#             "price":    0,
#         }]

#     config, faqs, items = generate_shop_from_items(raw_items, use_ollama=use_ollama)

#     # ── Patch config with real metadata from info ─────────────────────────
#     shop_name = info.get("shop_name") or config["shop_name"]
#     bot_name  = info.get("bot_name")  or (shop_name.split()[0][:10] if shop_name else "Bot")

#     config["bot_name"]    = bot_name
#     config["shop_name"]   = shop_name
#     config["shop_type"]   = info.get("shop_type",   config["shop_type"])
#     config["tagline"]     = info.get("tagline",     config.get("tagline", "English & Manglish"))
#     config["description"] = info.get("description", config.get("description", ""))
#     config["location"]    = info.get("location",    config.get("location", ""))
#     config["city"]        = info.get("city",        config.get("city", "Kerala"))
#     config["state"]       = info.get("state",       config.get("state", "Kerala"))

#     if "hours" not in config:
#         config["hours"] = {}
#     if info.get("hours_weekdays"):
#         config["hours"]["weekdays"] = info["hours_weekdays"]
#     if info.get("hours_sunday"):
#         config["hours"]["sunday"]   = info["hours_sunday"]
#     if info.get("hours_holiday"):
#         config["hours"]["holiday"]  = info["hours_holiday"]

#     if "contact" not in config:
#         config["contact"] = {}
#     if info.get("whatsapp"):
#         config["contact"]["whatsapp"] = info["whatsapp"]
#         config["contact"]["phone"]    = info.get("phone") or info["whatsapp"]
#     if info.get("email"):
#         config["contact"]["email"]    = info["email"]
#     if info.get("website"):
#         config["contact"]["website"]  = info["website"]

#     if info.get("payment"):
#         config["payment"] = info["payment"]
#     if info.get("services"):
#         config["services"] = info["services"]

#     if "delivery" not in config:
#         config["delivery"] = {}
#     if info.get("delivery_areas") and info["delivery_areas"] != "N/A":
#         config["delivery"]["areas"]      = info["delivery_areas"]
#     if info.get("delivery_free") and info["delivery_free"] != "N/A":
#         config["delivery"]["free_above"] = info["delivery_free"]
#     if info.get("delivery_days") and info["delivery_days"] != "N/A":
#         config["delivery"]["days"]       = info["delivery_days"]

#     if "returns" not in config:
#         config["returns"] = {}
#     if info.get("return_days"):
#         config["returns"]["days"]        = info["return_days"]
#     if info.get("return_condition") and info["return_condition"] != "N/A":
#         config["returns"]["condition"]   = info["return_condition"]
#     if info.get("refund_days") and info["refund_days"] != "N/A":
#         config["returns"]["refund_days"] = info["refund_days"]

#     if "first_offer" not in config:
#         config["first_offer"] = {}
#     if info.get("offer_code"):
#         config["first_offer"]["code"]        = info["offer_code"]
#     if info.get("offer_desc"):
#         config["first_offer"]["description"] = info["offer_desc"]

#     if "escalate" not in config:
#         config["escalate"] = {}
#     escalate_wa = info.get("escalate_whatsapp") or info.get("whatsapp")
#     escalate_em = info.get("escalate_email")    or info.get("email")
#     if escalate_wa:
#         config["escalate"]["whatsapp"] = escalate_wa
#     if escalate_em:
#         config["escalate"]["email"]    = escalate_em
#     if info.get("escalate_topics"):
#         config["escalate_topics"] = info["escalate_topics"]
#     if info.get("blocked_topics"):
#         config["blocked_topics"]  = info["blocked_topics"]

#     return config, faqs, items


# # ============================================================
# #  SAVE FILES  (CLI helper)
# # ============================================================
# def save_files(
#     config, faqs, items,
#     output_config="shop_config.json",
#     output_faqs="faqs/shop_faq.json",
#     output_items="faqs/shop_items.json",
# ):
#     with open(output_config, "w", encoding="utf-8") as f:
#         json.dump(config, f, ensure_ascii=False, indent=2)
#     print(f"✅ Saved {output_config}")

#     os.makedirs(os.path.dirname(output_faqs) or ".", exist_ok=True)
#     with open(output_faqs, "w", encoding="utf-8") as f:
#         json.dump(faqs, f, ensure_ascii=False, indent=2)
#     print(f"✅ Saved {output_faqs}")

#     if items:
#         os.makedirs(os.path.dirname(output_items) or ".", exist_ok=True)
#         with open(output_items, "w", encoding="utf-8") as f:
#             json.dump(items, f, ensure_ascii=False, indent=2)
#         print(f"✅ Saved {output_items}")


# # ============================================================
# #  CLI ENTRY POINT
# # ============================================================
# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(
#         description="Generate shop config and FAQs from extracted items."
#     )
#     parser.add_argument("--input", "-i", required=True,
#         help="JSON file with extracted items (list of {name, price, category?, gender?})")
#     parser.add_argument("--output-config", default="shop_config.json")
#     parser.add_argument("--output-faqs",   default="faqs/shop_faq.json")
#     parser.add_argument("--output-items",  default="faqs/shop_items.json")
#     parser.add_argument("--no-ollama", action="store_true",
#         help="Skip Ollama inference (use defaults/keywords only)")
#     args = parser.parse_args()

#     with open(args.input, "r", encoding="utf-8") as f:
#         raw_items = json.load(f)

#     print(f"Loaded {len(raw_items)} items from {args.input}")
#     config, faqs, enriched = generate_shop_from_items(raw_items, use_ollama=not args.no_ollama)
#     save_files(config, faqs, enriched, args.output_config, args.output_faqs, args.output_items)

#     print("\n=== Summary ===")
#     print(f"Shop          : {config['shop_name']} ({config['shop_type']})")
#     print(f"Gender scope  : {config['shop_gender']}")
#     print(f"Specialisation: {config['specialisation'] or 'none'}")
#     print(f"Categories    : {config['allowed_categories']}")
#     if config.get("dietary_mode"):
#         print(f"Dietary       : {config['dietary_mode']}")
#     print(f"FAQs          : {len(faqs)} entries")
#     print(f"Items         : {len(enriched)} enriched")






"""
generate_shop.py — v8.0
Universal shop config + FAQ generator from extracted items.

FAQ MERGE STRATEGY (v8.0):
  Layer 1 — data/english.json + data/manglish.json
              Common FAQs for ALL shops (ordering, returns, payment, etc.)
              Format: list of {id, category, question_variants, answer}

  Layer 2 — data/english_sentiment.json + data/manglish_sentiment.json
              Sentiment-aware FAQs for ALL shops
              Format: same as above

  Layer 3 — faq_templates/{shop_type}_english.json + {shop_type}_manglish.json
              Shop-type specific FAQs loaded AFTER shop type is identified
              Format: {"faqs": [{category, question, answer}]}
              Filename mapping handles typos (resaturent, scool, opticals, etc.)

  Layer 4 — core_faqs (contact, hours, location, payment) — generated from real config
  Layer 5 — item_faqs — generated from extracted shop items (catalogue + pricing)

All layers are deduplicated by (question.lower(), answer[:80].lower()) before saving.
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

# ============================================================
#  CONFIGURATION
# ============================================================
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"

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

# ── Filename → shop_type mapping (handles typos in existing files) ──────────
# Key   = filename stem (without _english/_manglish suffix)
# Value = canonical shop_type used in config
TEMPLATE_FILENAME_MAP: dict[str, str] = {
    "restaurant":       "restaurant",
    "resaturent":       "restaurant",   # typo in existing file
    "restaurent":       "restaurant",   # typo in existing file
    "bakery":           "bakery",
    "beauty_parlour":   "beauty_parlour",
    "beautyparlour":    "beauty_parlour",
    "gym":              "gym",
    "pharmacy":         "pharmacy",
    "clothing":         "clothing",
    "electronics":      "electronics",
    "electronic_products": "electronics",
    "electronic_product": "electronics",
    "jewellery":        "jewellery",
    "jewelry":          "jewellery",
    "optical":          "optical",
    "opticals":         "optical",      # plural in existing file
    "hotel":            "hotel",
    "supermarket":      "supermarket",
    "school":           "school",
    "scool":            "school",       # typo in existing file
    "travel_agency":    "travel_agency",
    "real_estate":      "real_estate",
    "law_firm":         "law_firm",
    "ca_firm":          "ca_firm",
    "dental_clinic":    "dental_clinic",
    "salon":            "salon",
    "cafe":             "cafe",
    "pet_shop":         "pet_shop",
    "driving_school":   "driving_school",
    "drvingschool":     "driving_school",  # typo in existing file
    "furniture_shop":   "furniture_shop",
    "mobile_shop":      "mobile_shop",
    "laundry_service":  "laundry_service",
    "tailoring_shop":   "tailoring_shop",
    "coaching_center":  "coaching_center",
    "spa":              "spa",
    "hardware_store":   "hardware_store",
    "diagnostic_center":"diagnostic_center",
    "photography":      "photography",
    "photography_studio":"photography",
    "courier_service":  "courier_service",
    "event_management": "event_management",
    "footwear_shop":    "footwear_shop",
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
    "cake":      ("bakery",         ["Cakes", "Pastries"]),
    "cakes":     ("bakery",         ["Cakes", "Pastries"]),
    "pastry":    ("bakery",         ["Cakes", "Pastries"]),
    "bread":     ("bakery",         ["Breads", "Snacks"]),
    "biryani":   ("restaurant",     ["Biryani", "Rice", "Curries"]),
    "seafood":   ("restaurant",     ["Seafood", "Starters", "Rice", "Curries"]),
    "shawarma":  ("restaurant",     ["Starters", "Snacks", "Beverages"]),
    "pizza":     ("restaurant",     ["Starters", "Snacks", "Beverages", "Desserts"]),
    "chinese":   ("restaurant",     ["Noodles", "Rice", "Starters", "Soups", "Beverages"]),
    "coffee":    ("restaurant",     ["Beverages", "Snacks", "Desserts"]),
    "saree":     ("clothing",       ["Sarees", "Accessories"]),
    "kurta":     ("clothing",       ["Kurtas", "Ethnic Wear", "Accessories"]),
    "bridal":    ("beauty_parlour", ["Bridal Makeup", "Hair Spa", "Facial", "Skin Care"]),
    "yoga":      ("gym",            ["Yoga", "Group Classes", "Diet Plans"]),
    "zumba":     ("gym",            ["Group Classes", "Cardio"]),
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


# ============================================================
#  FAQ LOADER HELPERS
# ============================================================

def _load_json_file(path: str | Path) -> list | dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _faq_key(q: str, a: str) -> tuple:
    """Dedup key: normalised question + first 80 chars of answer."""
    return (q.strip().lower(), a.strip().lower()[:80])


def load_common_faqs(data_dir: str = "data") -> list[dict]:
    """
    Layer 1 + 2: Load data/english.json, data/manglish.json,
    data/english_sentiment.json, data/manglish_sentiment.json.

    These are common for ALL shops.
    Format: list of {id, category, question_variants, answer}
    Returns unified list — each entry already has question_variants.
    """
    files = [
        "english.json",
        "manglish.json",
        "english_sentiment.json",
        "manglish_sentiment.json",
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
    """
    Find the right faq_templates file for a shop_type + lang combo.
    Handles typos and plurals via TEMPLATE_FILENAME_MAP (reverse lookup).
    lang: 'english' or 'manglish'
    """
    # Build reverse map: shop_type → list of possible filename stems
    reverse: dict[str, list[str]] = defaultdict(list)
    for stem, stype in TEMPLATE_FILENAME_MAP.items():
        reverse[stype].append(stem)

    base = Path(templates_dir)
    candidates = reverse.get(shop_type, [shop_type])

    for stem in candidates:
        p = base / f"{stem}_{lang}.json"
        if p.exists():
            return p

    return None


def load_template_faqs(shop_type: str, templates_dir: str = "faq_templates") -> list[dict]:
    """
    Layer 3: Load faq_templates/{shop_type}_english.json and _manglish.json.
    Loaded AFTER shop type is identified from extracted items.

    Format in files: {"faqs": [{category, question, answer}]}
    Returns unified list with question_variants built from English + Manglish questions.
    """
    en_path = _find_template_file(shop_type, "english",  templates_dir)
    ml_path = _find_template_file(shop_type, "manglish", templates_dir)

    if not en_path and not ml_path:
        print(f"[faq_loader] no template file found for shop_type='{shop_type}'")
        return []

    def _parse_template(path: Path) -> dict[str, dict]:
        """Returns {category: {question, answer}} keyed by category."""
        raw = _load_json_file(path)
        faqs = raw.get("faqs", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
        result = {}
        for item in faqs:
            cat = item.get("category", "general")
            q   = item.get("question", "").strip()
            a   = item.get("answer", "").strip()
            if q and a:
                result[cat] = {"question": q, "answer": a}
        return result

    en_map = _parse_template(en_path) if en_path else {}
    ml_map = _parse_template(ml_path) if ml_path else {}

    # Merge: combine English + Manglish question as question_variants
    all_cats = set(en_map.keys()) | set(ml_map.keys())
    combined: list[dict] = []
    seen: set = set()

    for cat in all_cats:
        en = en_map.get(cat, {})
        ml = ml_map.get(cat, {})

        answer   = en.get("answer") or ml.get("answer", "")
        answer_ml = ml.get("answer", "")

        variants = []
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
    """
    Merge multiple FAQ layers, deduplicating by (first_question, answer[:80]).
    Later layers are skipped if an earlier layer already has the same Q+A.
    """
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


# ============================================================
#  OLLAMA HELPERS
# ============================================================

def call_ollama(prompt: str, system: str = "") -> str:
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model":   OLLAMA_MODEL,
                "system":  system,
                "prompt":  prompt,
                "stream":  False,
                "options": {"temperature": 0.2, "num_predict": 200},
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        print(f"[Ollama error] {e}")
        return ""


def infer_shop_type(items: list) -> str:
    sample = [it.get("name", "") for it in items[:20]]
    valid  = ["clothing", "gym", "beauty_parlour", "restaurant", "bakery",
              "electronics", "pharmacy", "jewellery", "optical", "school", "general"]
    prompt = (
        f"Given these product/service names, what is the most likely shop type? "
        f"Choose ONLY one word from: {', '.join(valid)}.\n"
        f"Return only that single word.\n\nProducts: {', '.join(sample)}"
    )
    reply = call_ollama(prompt).lower().strip()
    for t in valid:
        if t in reply:
            return t
    return "general"


def detect_veg(items: list, shop_name: str, shop_type: str, use_ollama: bool = True) -> bool:
    if shop_type not in ("restaurant", "bakery"):
        return False
    if any(sig in shop_name.lower() for sig in VEG_NAME_SIGNALS):
        return True
    for item in items:
        if any(sig in item.get("name", "").lower() for sig in NON_VEG_ITEM_SIGNALS):
            return False
    if use_ollama and items:
        sample = [it.get("name", "") for it in items[:20]]
        reply  = call_ollama(
            f"Is this a pure vegetarian restaurant?\nShop: {shop_name}\n"
            f"Menu: {', '.join(sample)}\nAnswer only: yes or no"
        ).lower().strip()
        if reply.startswith("yes"):
            return True
    return True


def detect_shop_gender(items: list, shop_name: str, shop_type: str, use_ollama: bool = True) -> str:
    if shop_type in {"restaurant", "bakery", "electronics", "pharmacy", "general"}:
        return "all"
    lower_name = shop_name.lower()
    valid = list(GENDER_KEYWORDS.keys())

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

    if use_ollama:
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

    if use_ollama and len(full_cats) > 4:
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
    sample = [it.get("name", "") for it in items[:10]]
    reply  = call_ollama(
        f"Based on these products, suggest a short shop name (max 3 words). "
        f"Products: {', '.join(sample)}"
    )
    return reply if reply and len(reply.split()) <= 5 else fallback


def infer_hours_location(shop_type: str) -> dict:
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
    if shop_type in {"restaurant", "bakery", "electronics", "pharmacy", "general"}:
        return "all"
    lower = item_name.lower()
    for gender, keywords in GENDER_KEYWORDS.items():
        for kw in keywords:
            if re.search(r'\b' + re.escape(kw) + r'\b', lower):
                return gender
    reply = call_ollama(
        f"What gender is this product for? Choose from: {', '.join(GENDER_KEYWORDS)}. "
        f"Product: {item_name}\nReturn only the single word."
    ).lower().strip()
    for g in GENDER_KEYWORDS:
        if g in reply:
            return g
    return "all"


def infer_category(item_name: str, shop_type: str, allowed_cats: list | None = None) -> str:
    cats  = allowed_cats or ["General"]
    reply = call_ollama(
        f"Which category from {cats} best fits '{item_name}'? "
        f"Return ONLY the category name."
    )
    for cat in cats:
        if cat.lower() in reply.lower():
            return cat
    return cats[0]


def infer_signature_items(items: list, shop_type: str) -> str:
    priced = sorted([it for it in items if it.get("price")],
                    key=lambda x: x.get("price", 0), reverse=True)
    if len(priced) >= 2:
        return ", ".join(it["name"] for it in priced[:3])
    sample = [it.get("name", "") for it in items[:15]]
    reply  = call_ollama(
        f"From these {shop_type} items: {', '.join(sample)}, "
        f"list 3 signature ones as comma-separated names."
    )
    return reply or ""


# ============================================================
#  ENRICH ITEMS
# ============================================================

def enrich_items(
    items: list, shop_type: str, use_ollama: bool = True,
    shop_gender: str = "all", allowed_categories: list | None = None,
) -> list:
    enriched     = []
    valid_genders = list(GENDER_KEYWORDS.keys())
    allowed_cats  = allowed_categories or ["General"]
    single_gender = shop_gender != "all"

    for item in items:
        item = item.copy()

        if single_gender:
            item["gender"] = shop_gender
        elif not item.get("gender"):
            item["gender"] = infer_item_gender(item.get("name", ""), shop_type) if use_ollama else "all"
        else:
            provided       = item["gender"].lower().strip()
            item["gender"] = next((g for g in valid_genders if g in provided or provided in g), "all")

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


# ============================================================
#  FORMAT PRICE
# ============================================================

def format_price(item: dict) -> str:
    if "price" in item:
        return f"₹{item['price']:,}"
    if "price_min" in item and "price_max" in item:
        return f"₹{item['price_min']:,} – ₹{item['price_max']:,}"
    return "price on request"


# ============================================================
#  ITEM-BASED FAQs (Layer 5)
# ============================================================

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
    spec_prefix = (specialisation or "").replace("+", "/").replace("_", " ").strip()
    if spec_prefix in ("ollama_inferred", "all") or not spec_prefix:
        spec_prefix = ""

    by_cat_gender: dict = defaultdict(list)
    for it in items:
        by_cat_gender[(it.get("category", "General").strip(), it.get("gender", "all").strip())].append(it)

    for (cat, gen), cat_items in by_cat_gender.items():
        if shop_gender != "all" and gen not in (shop_gender, "all"):
            continue
        slug_key = re.sub(r'[^a-z0-9_]', '_', f"{gen}_{cat}".lower())[:40]
        faq_id   = f"cat_{slug_key}"
        if faq_id in seen_ids:
            continue
        seen_ids.add(faq_id)

        prefix = (cat if (shop_gender != "all" and gen == shop_gender)
                  else f"{gen.capitalize()} {cat}" if gen != "all" else cat)

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
        faqs.append({
            "id": faq_id, "category": "pricing",
            "question_variants": [
                f"How much is {name}?", f"Price of {name}?",
                f"{name} vila enthu?", f"{name} rate?",
            ],
            "answer": f"{name} — {format_price(it)}. WhatsApp {{whatsapp}} for details.",
        })

    return faqs


# ============================================================
#  CORE FAQs (Layer 4) — generated from real config values
# ============================================================

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
                "Athe! Njangal 100% pure veg ആണ് 🌿 "
                "Meat, fish, egg onnum use cheyyunnilla."
            ),
        })
    return faqs


# ============================================================
#  MAIN GENERATOR
# ============================================================

def generate_shop_from_items(
    items: list,
    use_ollama: bool = True,
    data_dir: str = "data",
    templates_dir: str = "faq_templates",
) -> tuple:
    """
    Primary entry point.
    Returns (config, faqs, enriched_items).

    FAQ layers (in merge order, earlier wins on dedup):
      1. data/common FAQs (all shops)
      2. faq_templates/{shop_type} FAQs (type-specific, loaded after type detection)
      3. core_faqs (contact/hours/location from real config)
      4. item_faqs (catalogue + pricing from extracted items)
    """
    if not items:
        print("No items provided.")
        sys.exit(1)

    # ── Detect shop properties ───────────────────────────────────────────
    shop_type   = infer_shop_type(items) if use_ollama else "general"
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
        "hours_weekdays": DEFAULTS["hours_weekdays"],
        "hours_sunday":   DEFAULTS["hours_sunday"],
        "location":       DEFAULTS["location"],
    }
    signature    = infer_signature_items(items, shop_type) if use_ollama else ""
    is_veg       = detect_veg(items, shop_name, shop_type, use_ollama)
    dietary_mode = "veg_only" if is_veg else ("veg_nonveg" if shop_type in ("restaurant", "bakery") else None)
    if shop_type in ("restaurant", "bakery"):
        print(f"[Dietary mode] {'veg_only' if is_veg else 'veg_nonveg'}")

    # ── Build config ─────────────────────────────────────────────────────
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
            "areas":      DEFAULTS["delivery_areas"],
            "free_above": DEFAULTS["delivery_free"],
            "days":       DEFAULTS["delivery_days"],
        },
        "returns": {
            "days":        DEFAULTS["return_days"],
            "condition":   DEFAULTS["return_condition"],
            "refund_days": DEFAULTS["refund_days"],
        },
        "first_offer":        {"code": DEFAULTS["offer_code"], "description": DEFAULTS["offer_desc"]},
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
        "quick_chips":    [],
        "welcome_cards":  [],
        "item_count":     len(items),
        "signature_items": signature,
    }

    # ── Build FAQ layers ──────────────────────────────────────────────────
    # Layer 1+2: common FAQs from data/ (all shops)
    common_faqs = load_common_faqs(data_dir)

    # Layer 3: shop-type specific FAQs from faq_templates/
    template_faqs = load_template_faqs(shop_type, templates_dir)

    # Layer 4: core FAQs (contact/hours/location — real values)
    core_faqs = build_core_faqs(is_veg, shop_type, signature)

    # Layer 5: item catalogue + pricing FAQs
    item_faqs = build_item_faqs(
        items, shop_type, is_veg=is_veg,
        shop_gender=shop_gender, specialisation=specialisation, profile=profile,
    )

    # Merge: core + template → deduplicated, then common + items appended
    # Priority: core_faqs > template_faqs > common_faqs > item_faqs
    all_faqs = merge_faq_layers(core_faqs, template_faqs, common_faqs, item_faqs)

    print(
        f"[generate_shop] FAQ summary — "
        f"core={len(core_faqs)} template={len(template_faqs)} "
        f"common={len(common_faqs)} items={len(item_faqs)} "
        f"merged_total={len(all_faqs)}"
    )

    return config, all_faqs, items


# ============================================================
#  BRIDGE FUNCTION  (called by api.py)
# ============================================================

def generate_shop_files(
    info: dict,
    use_ollama: bool = True,
    data_dir: str = "data",
    templates_dir: str = "faq_templates",
) -> tuple:
    """
    Bridge between api.py's info-dict calling convention and
    generate_shop_from_items(items_list).

    Steps:
      1. Extract shop_items from info (or stub if empty).
      2. Run generate_shop_from_items — detects shop type, loads correct FAQ layers.
      3. Patch every config field with real values from info dict.
      4. Return (config, faqs, items).
    """
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
    )

    # ── Patch config with real metadata from info ─────────────────────────
    shop_name = info.get("shop_name") or config["shop_name"]
    bot_name  = info.get("bot_name")  or (shop_name.split()[0][:10] if shop_name else "Bot")

    config.update({
        "bot_name":   bot_name,
        "shop_name":  shop_name,
        "shop_type":  info.get("shop_type",   config["shop_type"]),
        "tagline":    info.get("tagline",     config.get("tagline", "English & Manglish")),
        "description":info.get("description", config.get("description", "")),
        "location":   info.get("location",    config.get("location", "")),
        "city":       info.get("city",        config.get("city", "Kerala")),
        "state":      info.get("state",       config.get("state", "Kerala")),
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
    if info.get("return_days"):                                    r["days"]        = info["return_days"]
    if info.get("return_condition") and info["return_condition"] != "N/A": r["condition"]   = info["return_condition"]
    if info.get("refund_days")      and info["refund_days"]      != "N/A": r["refund_days"] = info["refund_days"]

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

    # ── Re-load template FAQs using the REAL shop_type from info ─────────
    # (generate_shop_from_items infers type from items; info has the confirmed type)
    real_type = config["shop_type"]
    if real_type != (info.get("shop_type") or real_type):
        # Shop type was overridden — reload template FAQs for correct type
        new_template_faqs = load_template_faqs(real_type, templates_dir)
        common_faqs       = load_common_faqs(data_dir)
        core_faqs         = build_core_faqs(
            config.get("is_veg", False), real_type,
            config.get("signature_items", "")
        )
        item_faqs = [f for f in faqs if f.get("category") in ("catalog", "pricing")]
        faqs = merge_faq_layers(core_faqs, new_template_faqs, common_faqs, item_faqs)
        print(f"[generate_shop_files] re-merged FAQs for real type='{real_type}': {len(faqs)} total")

    return config, faqs, items


# ============================================================
#  SAVE FILES  (CLI helper)
# ============================================================

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


# ============================================================
#  CLI ENTRY POINT
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate shop config and FAQs from extracted items."
    )
    parser.add_argument("--input",         "-i", required=True,
        help="JSON file with items: [{name, price, category?, gender?}]")
    parser.add_argument("--output-config", default="shop_config.json")
    parser.add_argument("--output-faqs",   default="faqs/shop_faq.json")
    parser.add_argument("--output-items",  default="faqs/shop_items.json")
    parser.add_argument("--data-dir",      default="data",
        help="Directory containing english.json, manglish.json etc.")
    parser.add_argument("--templates-dir", default="faq_templates",
        help="Directory containing {shop_type}_english.json etc.")
    parser.add_argument("--no-ollama", action="store_true")
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
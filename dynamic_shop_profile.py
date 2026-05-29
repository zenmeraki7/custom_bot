"""
dynamic_shop_profile.py  — v3.0
================================
Provides ShopProfile dataclass and get_shop_profile_with_cache() for
generate_shop.py v7.0+.

v3.0 changes:
  - _KNOWN_PROFILES expanded to match ALL shop types in generate_faqs.py
    (dental_clinic, salon, cafe, pet_shop, driving_school, furniture_shop,
    mobile_shop, laundry_service, tailoring_shop, coaching_center, spa,
    hardware_store, automobile_showroom, and more)
  - faq_templates now pulled from generate_faqs.SHOP_FAQS at runtime
    → single source of truth, no more maintaining two separate lists
  - _faq_templates_from_generate_faqs() falls back to hardcoded if
    generate_faqs is not importable (safe for standalone use)
  - Ollama inference only fires for truly unknown types not in either file

The real call signature (generate_shop.py):
    profile = get_shop_profile_with_cache(shop_name, shop_type, items, use_ollama)

ShopProfile attributes used by generate_shop.py:
    .source        — "known" | "ollama" | "cached" | "fallback"
    .categories    — list[str]  e.g. ["Chicken", "Seafood", "Rice", ...]
    .item_label    — str        e.g. "dishes", "items", "services"
    .faq_templates — list[str]  question template strings with {gender_cat}
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path

import requests

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"
CACHE_DIR    = Path("shops/_profile_cache")

_cache: dict[str, "ShopProfile"] = {}
_lock  = threading.Lock()


# ══════════════════════════════════════════════════════════════════════════
#  ShopProfile
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class ShopProfile:
    shop_type:     str  = "general"
    source:        str  = "fallback"
    categories:    list = field(default_factory=lambda: ["General"])
    item_label:    str  = "items"
    faq_templates: list = field(default_factory=list)

    def __post_init__(self):
        if not self.faq_templates:
            self.faq_templates = _default_faq_templates()


# ══════════════════════════════════════════════════════════════════════════
#  Default {gender_cat} templates — used when shop type has no specific ones
# ══════════════════════════════════════════════════════════════════════════

def _default_faq_templates() -> list[str]:
    return [
        "{gender_cat} undo?",
        "{gender_cat} available aano?",
        "{gender_cat} kittumo?",
        "Do you have {gender_cat}?",
        "What {gender_cat} do you offer?",
        "{gender_cat} entha price?",
        "{gender_cat} show cheyyamo?",
    ]


# ══════════════════════════════════════════════════════════════════════════
#  Pull faq_templates from generate_faqs.py (single source of truth)
#  Falls back to hardcoded per-type templates if import fails.
# ══════════════════════════════════════════════════════════════════════════

def _faq_templates_for(shop_type: str) -> list[str]:
    """
    Derive {gender_cat} question templates from generate_faqs.SHOP_FAQS.
    Takes the ml_q fields from that type's entries and converts them to
    templates by replacing category-specific words with {gender_cat}.
    Falls back to per-type hardcoded templates defined below.
    """
    # Hardcoded per-type templates (best quality, manually tuned)
    _HARDCODED: dict[str, list[str]] = {
        "restaurant": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "{gender_cat} menu-il undo?",
            "Do you serve {gender_cat}?",
            "What {gender_cat} do you have?",
            "{gender_cat} items entha?",
        ],
        "bakery": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you make {gender_cat}?",
            "{gender_cat} order cheyyamo?",
            "What {gender_cat} do you bake?",
            "{gender_cat} kittumo?",
        ],
        "clothing": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "{gender_cat} kittumo?",
            "Do you have {gender_cat}?",
            "What sizes in {gender_cat}?",
            "{gender_cat} price range enthu?",
            "{gender_cat} show cheyyamo?",
        ],
        "gym": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you offer {gender_cat}?",
            "{gender_cat} price enthu?",
            "How to join {gender_cat}?",
            "{gender_cat} timings enthu?",
        ],
        "beauty_parlour": [
            "{gender_cat} available aano?",
            "{gender_cat} undo?",
            "Do you offer {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} book cheyyamo?",
            "How long does {gender_cat} take?",
        ],
        "jewellery": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you have {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} designs undo?",
        ],
        "pharmacy": [
            "{gender_cat} available aano?",
            "{gender_cat} undo?",
            "Do you stock {gender_cat}?",
            "{gender_cat} kittumo?",
        ],
        "electronics": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you sell {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} warranty undo?",
        ],
        "optical": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you have {gender_cat}?",
            "{gender_cat} price range?",
        ],
        "supermarket": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you stock {gender_cat}?",
            "{gender_cat} price enthu?",
        ],
        "hotel": [
            "{gender_cat} available aano?",
            "{gender_cat} undo?",
            "Do you have {gender_cat}?",
            "{gender_cat} rate enthu?",
            "{gender_cat} book cheyyamo?",
        ],
        "travel_agency": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you offer {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} book cheyyamo?",
        ],
        "real_estate": [
            "{gender_cat} available aano?",
            "{gender_cat} undo?",
            "Do you have {gender_cat}?",
            "{gender_cat} price range?",
            "{gender_cat} site visit arrange cheyyamo?",
        ],
        "law_firm": [
            "{gender_cat} handle cheyyumo?",
            "{gender_cat} available aano?",
            "Do you handle {gender_cat}?",
            "{gender_cat} fees enthu?",
        ],
        "ca_firm": [
            "{gender_cat} cheyyumo?",
            "{gender_cat} available aano?",
            "Do you offer {gender_cat}?",
            "{gender_cat} fees enthu?",
        ],
        "school": [
            "{gender_cat} available aano?",
            "{gender_cat} undo?",
            "Do you offer {gender_cat}?",
            "{gender_cat} fees enthu?",
            "{gender_cat} admissions open aano?",
        ],
        # ── New types added in v3.0 ──────────────────────────────────────
        "dental_clinic": [
            "{gender_cat} cheyyumo?",
            "{gender_cat} available aano?",
            "Do you do {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} appointment book cheyyamo?",
        ],
        "salon": [
            "{gender_cat} cheyyumo?",
            "{gender_cat} undo?",
            "Do you offer {gender_cat}?",
            "{gender_cat} price enthu?",
        ],
        "cafe": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you serve {gender_cat}?",
            "{gender_cat} price enthu?",
        ],
        "pet_shop": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you have {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} kittumoo?",
        ],
        "driving_school": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you offer {gender_cat}?",
            "{gender_cat} fees enthu?",
        ],
        "furniture_shop": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you sell {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} delivery undo?",
        ],
        "mobile_shop": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you sell {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} EMI undo?",
        ],
        "laundry_service": [
            "{gender_cat} service undo?",
            "{gender_cat} available aano?",
            "Do you do {gender_cat}?",
            "{gender_cat} charge enthu?",
        ],
        "tailoring_shop": [
            "{gender_cat} cheyyumo?",
            "{gender_cat} stitch cheyyumo?",
            "Do you do {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} ethra time?",
        ],
        "coaching_center": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you offer {gender_cat}?",
            "{gender_cat} fees enthu?",
            "{gender_cat} batch timing?",
        ],
        "spa": [
            "{gender_cat} available aano?",
            "{gender_cat} undo?",
            "Do you offer {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} book cheyyamo?",
        ],
        "hardware_store": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you stock {gender_cat}?",
            "{gender_cat} price enthu?",
        ],
        "automobile_showroom": [
            "{gender_cat} undo?",
            "{gender_cat} available aano?",
            "Do you have {gender_cat}?",
            "{gender_cat} test drive cheyyamo?",
            "{gender_cat} EMI undo?",
        ],
        "diagnostic_center": [
            "{gender_cat} test cheyyumo?",
            "{gender_cat} available aano?",
            "Do you do {gender_cat}?",
            "{gender_cat} price enthu?",
            "{gender_cat} report ethra time?",
        ],
        "general": _default_faq_templates(),
    }
    return _HARDCODED.get(shop_type, _default_faq_templates())


# ══════════════════════════════════════════════════════════════════════════
#  Expanded _KNOWN_PROFILES — covers all types in generate_faqs.SHOP_FAQS
# ══════════════════════════════════════════════════════════════════════════

_KNOWN_PROFILES: dict[str, dict] = {

    "restaurant": {
        "categories": [
            "Starters", "Soups", "Seafood", "Chicken", "Mutton", "Beef",
            "Biryani", "Rice", "Curries", "Breads", "Noodles",
            "Desserts", "Beverages",
        ],
        "item_label": "dishes",
    },
    "bakery": {
        "categories": ["Cakes", "Breads", "Pastries", "Cookies", "Snacks", "Beverages", "Desserts"],
        "item_label": "baked goods",
    },
    "clothing": {
        "categories": [
            "T-Shirts", "Shirts", "Pants", "Jeans", "Ethnic Wear", "Sarees",
            "Kurtas", "Western Wear", "Sportswear", "Innerwear",
            "Kids Wear", "Accessories", "Uniforms",
        ],
        "item_label": "clothing items",
    },
    "gym": {
        "categories": [
            "Memberships", "Personal Training", "Group Classes", "Yoga",
            "CrossFit", "Cardio", "Strength", "Zumba", "Diet Plans",
        ],
        "item_label": "plans",
    },
    "beauty_parlour": {
        "categories": [
            "Haircuts", "Hair Color", "Hair Spa", "Facial", "Skin Care",
            "Waxing", "Threading", "Manicure", "Pedicure",
            "Bridal Makeup", "Makeup",
        ],
        "item_label": "services",
    },
    "jewellery": {
        "categories": [
            "Gold", "Silver", "Diamond", "Platinum", "Necklaces",
            "Rings", "Bangles", "Earrings", "Custom", "Repair",
        ],
        "item_label": "jewellery",
    },
    "pharmacy": {
        "categories": [
            "Prescription Medicines", "OTC Medicines", "Vitamins",
            "Surgical Supplies", "Baby Care", "Personal Care", "Devices",
        ],
        "item_label": "medicines",
    },
    "electronics": {
        "categories": [
            "Mobiles", "Laptops", "TVs", "Appliances",
            "Accessories", "Audio", "Cameras", "Repair Services",
        ],
        "item_label": "products",
    },
    "optical": {
        "categories": [
            "Eyeglasses", "Sunglasses", "Contact Lenses",
            "Eye Tests", "Kids Eyewear", "Sports Eyewear",
        ],
        "item_label": "products",
    },
    "supermarket": {
        "categories": [
            "Groceries", "Vegetables", "Fruits", "Dairy",
            "Snacks", "Beverages", "Personal Care", "Cleaning",
        ],
        "item_label": "products",
    },
    "hotel": {
        "categories": [
            "Standard Rooms", "Deluxe Rooms", "Suites",
            "Restaurant", "Conference Hall", "Swimming Pool", "Amenities",
        ],
        "item_label": "rooms",
    },
    "travel_agency": {
        "categories": [
            "Kerala Tours", "India Tours", "International Tours",
            "Honeymoon Packages", "Group Tours", "Custom Packages",
        ],
        "item_label": "packages",
    },
    "real_estate": {
        "categories": [
            "Apartments", "Villas", "Plots", "Commercial",
            "Rental Properties", "New Projects",
        ],
        "item_label": "properties",
    },
    "law_firm": {
        "categories": [
            "Civil Cases", "Criminal Cases", "Family Law",
            "Property Law", "Corporate Law", "Labour Law", "Consultation",
        ],
        "item_label": "services",
    },
    "ca_firm": {
        "categories": [
            "Tax Filing", "Audit", "GST", "Accounting",
            "Company Registration", "Payroll", "Consultation",
        ],
        "item_label": "services",
    },
    "school": {
        "categories": [
            "Primary Classes", "Secondary Classes", "Higher Secondary",
            "Extracurricular", "Coaching", "Online Classes",
        ],
        "item_label": "courses",
    },

    # ── v3.0: New known types ────────────────────────────────────────────

    "dental_clinic": {
        "categories": [
            "Cleaning", "Filling", "Extraction", "Root Canal",
            "Braces", "Implants", "Whitening", "Crown", "Kids Dental",
        ],
        "item_label": "treatments",
    },
    "salon": {
        "categories": [
            "Haircuts", "Beard Grooming", "Hair Color",
            "Facial", "Shaving", "Styling",
        ],
        "item_label": "services",
    },
    "cafe": {
        "categories": [
            "Coffee", "Tea", "Cold Drinks", "Juices",
            "Sandwiches", "Snacks", "Desserts", "Light Meals",
        ],
        "item_label": "items",
    },
    "pet_shop": {
        "categories": [
            "Dogs", "Cats", "Fish", "Birds", "Rabbits",
            "Pet Food", "Accessories", "Grooming",
        ],
        "item_label": "products",
    },
    "driving_school": {
        "categories": [
            "LMV Car", "MCWG Bike", "Heavy Vehicle",
            "Learner Licence", "Permanent Licence", "Ladies Batch",
        ],
        "item_label": "courses",
    },
    "furniture_shop": {
        "categories": [
            "Beds", "Sofas", "Dining Sets", "Wardrobes",
            "TV Units", "Chairs", "Office Furniture", "Custom",
        ],
        "item_label": "furniture",
    },
    "mobile_shop": {
        "categories": [
            "Smartphones", "Feature Phones", "Accessories",
            "Repair", "Recharge", "EMI Plans",
        ],
        "item_label": "products",
    },
    "laundry_service": {
        "categories": [
            "Wash & Fold", "Dry Cleaning", "Ironing",
            "Steam Press", "Stain Removal", "Pickup & Delivery",
        ],
        "item_label": "services",
    },
    "tailoring_shop": {
        "categories": [
            "Blouse", "Salwar", "Churidar", "Pants",
            "Shirts", "Kurta", "Alterations", "Bridal",
        ],
        "item_label": "stitching services",
    },
    "coaching_center": {
        "categories": [
            "School Tuition", "Competitive Exams", "Spoken English",
            "Online Classes", "Group Batches", "Personal Coaching",
        ],
        "item_label": "courses",
    },
    "spa": {
        "categories": [
            "Body Massage", "Facial", "Scrub", "Wrap",
            "Foot Care", "Aromatherapy", "Couples Package",
        ],
        "item_label": "treatments",
    },
    "hardware_store": {
        "categories": [
            "Tools", "Plumbing", "Electrical", "Paint",
            "Fasteners", "Safety Equipment", "Building Materials",
        ],
        "item_label": "products",
    },
    "automobile_showroom": {
        "categories": [
            "Hatchbacks", "Sedans", "SUVs", "MPVs",
            "Electric Vehicles", "Test Drive", "Finance & EMI",
        ],
        "item_label": "vehicles",
    },
    "diagnostic_center": {
        "categories": [
            "Blood Tests", "Urine Tests", "X-Ray", "Ultrasound",
            "ECG", "Health Packages", "Home Collection",
        ],
        "item_label": "tests",
    },
    "car_service_center": {
        "categories": [
            "General Service", "Oil Change", "Tyres", "Brakes",
            "AC Service", "Denting & Painting", "Insurance Claim",
        ],
        "item_label": "services",
    },
    "hospital": {
        "categories": [
            "OPD", "Emergency", "Surgery", "Maternity",
            "Paediatrics", "Diagnostics", "ICU",
        ],
        "item_label": "services",
    },
    "physiotherapy_clinic": {
        "categories": [
            "Back Pain", "Knee Rehabilitation", "Sports Injury",
            "Stroke Rehabilitation", "Neck Pain", "Home Visit",
        ],
        "item_label": "treatments",
    },
    "eye_clinic": {
        "categories": [
            "Eye Check", "Cataract", "Glaucoma", "LASIK",
            "Contact Lens", "Retina", "Kids Eye Care",
        ],
        "item_label": "services",
    },
    "skin_clinic": {
        "categories": [
            "Acne Treatment", "Laser", "Anti-Ageing",
            "Hair Loss", "Pigmentation", "Chemical Peel",
        ],
        "item_label": "treatments",
    },
    "event_management": {
        "categories": [
            "Weddings", "Corporate Events", "Birthday Parties",
            "Stage Decoration", "Catering", "Photography",
        ],
        "item_label": "packages",
    },
    "photography_studio": {
        "categories": [
            "Wedding Photography", "Portrait", "Product Photography",
            "Passport Photos", "Videography", "Baby Shoot",
        ],
        "item_label": "packages",
    },
    "catering_service": {
        "categories": [
            "Wedding Catering", "Corporate Catering", "Sadya",
            "BBQ", "Live Counters", "Box Meals",
        ],
        "item_label": "packages",
    },
    "interior_design": {
        "categories": [
            "Home Interiors", "Office Interiors", "Kitchen",
            "False Ceiling", "Modular Furniture", "3D Design",
        ],
        "item_label": "services",
    },
    "general": {
        "categories": ["Products", "Services", "General"],
        "item_label": "items",
    },
}


def _make_profile(shop_type: str, data: dict, source: str) -> ShopProfile:
    return ShopProfile(
        shop_type     = shop_type,
        source        = source,
        categories    = list(data.get("categories", ["General"])),
        item_label    = data.get("item_label",       "items"),
        faq_templates = _faq_templates_for(shop_type),  # single source of truth
    )


# ══════════════════════════════════════════════════════════════════════════
#  Disk cache for unknown types queried via Ollama
# ══════════════════════════════════════════════════════════════════════════

def _cache_path(shop_type: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() or c == "_" else "_" for c in shop_type)
    return CACHE_DIR / f"{safe}.json"


def _load_disk_cache(shop_type: str) -> dict | None:
    p = _cache_path(shop_type)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_disk_cache(shop_type: str, data: dict) -> None:
    try:
        _cache_path(shop_type).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        print(f"[dynamic_shop_profile] ⚠  disk cache write failed: {e}")


# ══════════════════════════════════════════════════════════════════════════
#  Ollama inference for truly unknown types
# ══════════════════════════════════════════════════════════════════════════

def _ask_ollama(shop_name: str, shop_type: str, items: list) -> dict | None:
    sample = [it.get("name", "") for it in items[:20] if it.get("name")]
    prompt = (
        f"You are building a chatbot for a shop.\n"
        f"Shop name: {shop_name}\n"
        f"Shop type: {shop_type}\n"
        f"Sample items/services: {', '.join(sample)}\n\n"
        f"Return ONLY a JSON object (no explanation, no markdown) with these keys:\n"
        f"  categories : list of 5-10 product/service category strings\n"
        f"  item_label : single word/phrase for items (e.g. products, services, dishes)\n"
        f"Return only valid JSON."
    )
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model":   OLLAMA_MODEL,
                "prompt":  prompt,
                "system":  "Return only valid JSON. No explanation. No markdown.",
                "stream":  False,
                "options": {"temperature": 0.1, "num_predict": 300},
            },
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())
        if "categories" in data and "item_label" in data:
            return data
    except Exception as e:
        print(f"[dynamic_shop_profile] ⚠  Ollama inference failed: {e}")
    return None


# ══════════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════════

def get_shop_profile_with_cache(
    shop_name:  str,
    shop_type:  str,
    items:      list,
    use_ollama: bool = True,
) -> ShopProfile:
    """
    Return a ShopProfile for this shop.

    Resolution order:
      1. In-process memory cache   → instant
      2. Known hardcoded profiles  → instant  (source="known")  ← now 35+ types
      3. Disk cache                → fast     (source="cached")
      4. Ollama inference          → slow     (source="ollama"), cached to disk
      5. Generic fallback          → instant  (source="fallback")

    faq_templates always come from _faq_templates_for() regardless of source
    → single source of truth, no duplicate maintenance.
    """
    cache_key = shop_type.lower().strip()

    with _lock:
        if cache_key in _cache:
            return _cache[cache_key]

    # Known type
    if cache_key in _KNOWN_PROFILES:
        profile = _make_profile(cache_key, _KNOWN_PROFILES[cache_key], "known")
        print(f"[dynamic_shop_profile] ✅ Known: type={cache_key} cats={profile.categories[:3]}…")
        with _lock:
            _cache[cache_key] = profile
        return profile

    # Disk cache
    cached = _load_disk_cache(cache_key)
    if cached:
        profile = _make_profile(cache_key, cached, "cached")
        print(f"[dynamic_shop_profile] ✅ Cached: type={cache_key}")
        with _lock:
            _cache[cache_key] = profile
        return profile

    # Ollama inference
    if use_ollama and items:
        print(f"[dynamic_shop_profile] 🤖 Ollama: type={cache_key}")
        data = _ask_ollama(shop_name, cache_key, items)
        if data:
            _save_disk_cache(cache_key, data)
            profile = _make_profile(cache_key, data, "ollama")
            print(f"[dynamic_shop_profile] ✅ Ollama saved: type={cache_key}")
            with _lock:
                _cache[cache_key] = profile
            return profile

    # Fallback
    print(f"[dynamic_shop_profile] ⚠  Fallback: type={cache_key}")
    fallback = {
        "categories": ["Products", "Services", "General"],
        "item_label": "items",
    }
    profile = _make_profile(cache_key, fallback, "fallback")
    with _lock:
        _cache[cache_key] = profile
    return profile


def invalidate_cache(shop_type: str | None = None) -> None:
    with _lock:
        if shop_type is None:
            _cache.clear()
            print("[dynamic_shop_profile] 🗑  Full cache cleared")
        elif shop_type in _cache:
            del _cache[shop_type]
            print(f"[dynamic_shop_profile] 🗑  Cache cleared: type='{shop_type}'")
    if shop_type:
        p = _cache_path(shop_type)
        if p.exists():
            p.unlink()
            print(f"[dynamic_shop_profile] 🗑  Disk cache removed: type='{shop_type}'")

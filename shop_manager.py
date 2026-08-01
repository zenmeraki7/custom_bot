"""
shop_manager.py — Per-slug shop context (file-based, no DB)  v4.0
==================================================================
"""

from __future__ import annotations
import re

import json
import threading
from pathlib import Path
from typing import Optional

import chat as _chat_module
import faq_engine as _faq_module
from chat import (
    _build_system_prompt,
    _build_social_prompt,
    pipeline as _global_pipeline,
)

SHOPS_DIR = Path("shops")
SHOPS_DIR.mkdir(exist_ok=True)

_GLOBAL_LOCK = threading.Lock()
_cache: dict[str, "ShopContext"] = {}
_cache_lock = threading.Lock()


def _normalize_slug(slug: str) -> str:
    """Trim, lowercase, collapse whitespace/underscores/dashes into one dash.
    ' beaty - beat ', 'beaty---beat', 'beaty_beat' all map to 'beaty-beat'.
    Shop-agnostic; UUIDs pass through unchanged."""
    s = (slug or "").strip().lower()
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _looksml(text: str) -> bool:
    """Quick heuristic: does this look like a Manglish question?
    Checks for common Manglish particles/suffixes."""
    if not text:
        return False
    t = text.lower()
    ML_PARTICLES = {
        "undo", "und", "indo", "aano", "undu", "aanu",
        "kittumo", "cheyyumo", "cheyyaamo", "kittumano",
        "aano", "entha", "enthu", "ethu", "evide",
        "undaakumo", "paranjutharamo", "nokam",
    }
    words = set(re.sub(r"[^\w\s]", " ", t).split())
    return bool(words & ML_PARTICLES)


_is_manglish_fn = None


def _is_manglish_text(text: str) -> bool:
    """
    Per-variant language check used when building embeddings. Prefers
    nlp.is_manglish() (the ~150+ signal detector used everywhere else in
    the codebase); falls back to the much weaker local _looksml() only if
    nlp.py can't be imported for some reason, so this never hard-fails.
    """
    global _is_manglish_fn
    if _is_manglish_fn is None:
        try:
            from nlp import is_manglish as _fn
            _is_manglish_fn = _fn
        except Exception:
            _is_manglish_fn = _looksml
    return _is_manglish_fn(text)


class ShopContext:
    def __init__(self, slug: str):
        self.slug = _normalize_slug(slug)
        self.cfg: dict = {}
        self.shop_faqs: list = []
        self.shop_items: list = []
        self.shop_emb_vectors = None
        self.shop_emb_meta: list = []
        self._load()

    def _load(self):
        slug_dir = SHOPS_DIR / self.slug
        slug_dir.mkdir(parents=True, exist_ok=True)

        cfg_path = slug_dir / "shop_config.json"
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                self.cfg = json.load(f)
        else:
            # FIX: never inherit another shop's identity. The root-
            # level shop_config.json is whatever shop was last being
            # worked on -- it is NOT a generic template, and loading
            # it here means a brand-new slug briefly shows up with
            # someone else's bot_name/shop_type/etc. until PDF
            # extraction or generate-shop later overwrites it. A
            # slug with no config of its own always gets the clean
            # generic default instead.
            self.cfg = {
                "bot_name": "Assistant", "shop_name": "Our Shop",
                "shop_type": "general", "contact": {}, "hours": {},
                "escalate": {}, "escalate_topics": ["fraud", "refund", "complaint"],
                "blocked_topics": [], "quick_chips": [], "welcome_cards": [],
                "item_count": 0,
                "shop_gender": "all", "specialisation": None,
                "allowed_categories": [], "is_veg": False, "dietary_mode": None,
            }

        pm = self._placeholder_map()

        faq_path = slug_dir / "shop_faq.json"
        if faq_path.exists():
            self.shop_faqs = self._parse_faqs(_load_json(faq_path), pm)
        else:
            root_faq = Path("faqs/shop_faq.json")
            self.shop_faqs = self._parse_faqs(_load_json(root_faq), pm) if root_faq.exists() else []

        try:
            shop_type = self.cfg.get("shop_type", "general")
            type_path = Path(f"faqs/types/{shop_type}_faq.json")
            if not type_path.exists():
                type_path = Path("faqs/types/general_faq.json")
            if type_path.exists():
                type_raw     = _load_json(type_path)
                parsed_type  = self._parse_faqs(type_raw, pm)
                existing_ids = {f.get("id", "") for f in self.shop_faqs}
                unique_type  = [f for f in parsed_type if f.get("id", "") not in existing_ids]
                self.shop_faqs = unique_type + self.shop_faqs
                print(f"[shop:{self.slug}] type pack +{len(unique_type)} FAQs (type='{shop_type}')")
        except Exception as e:
            print(f"[shop:{self.slug}] type pack skipped: {e}")

        items_path = slug_dir / "shop_items.json"
        if items_path.exists():
            self.shop_items = _load_json(items_path) or []
        else:
            root_items = Path("faqs/shop_items.json")
            self.shop_items = _load_json(root_items) if root_items.exists() else []

        self._build_embeddings()

        shop_type      = self.cfg.get("shop_type", "general")
        shop_gender    = self.cfg.get("shop_gender", "all")
        specialisation = self.cfg.get("specialisation") or "-"
        is_veg         = self.cfg.get("is_veg", False)
        print(
            f"[shop:{self.slug}] OK Loaded -- "
            f"bot={self.cfg.get('bot_name')} "
            f"type={shop_type} "
            f"gender={shop_gender} "
            f"spec={specialisation} "
            f"veg={is_veg} "
            f"faqs={len(self.shop_faqs)} "
            f"items={len(self.shop_items)}"
        )

    def _placeholder_map(self) -> dict:
        c = self.cfg.get("contact", {})
        h = self.cfg.get("hours", {})
        d = self.cfg.get("delivery", {})
        r = self.cfg.get("returns", {})
        o = self.cfg.get("first_offer", {})
        h_sun = h.get("sunday", "")
        h_wkd = h.get("weekdays", "")
        return {
            "whatsapp":           c.get("whatsapp", ""),
            "phone":              c.get("phone", ""),
            "email":              c.get("email", ""),
            "hours_weekdays":     h_wkd,
            "hours_sunday":       "" if h_sun == h_wkd else h_sun,
            "hours_holiday":      h.get("holiday", ""),
            "location":           self.cfg.get("location", ""),
            "city":               self.cfg.get("city", ""),
            "delivery_areas":     d.get("areas", "N/A"),
            "delivery_free":      d.get("free_above", "N/A"),
            "delivery_days":      d.get("days", "N/A"),
            "return_days":        str(r.get("days", 0)),
            "return_condition":   r.get("condition", "N/A"),
            "refund_days":        r.get("refund_days", "N/A"),
            "offer_code":         o.get("code", ""),
            "offer_desc":         o.get("description", ""),
            "shop_name":          self.cfg.get("shop_name", ""),
            "bot_name":           self.cfg.get("bot_name", "Assistant"),
            "shop_gender":        self.cfg.get("shop_gender", "all"),
            "specialisation":     self.cfg.get("specialisation") or "",
            "is_veg":             str(self.cfg.get("is_veg", False)).lower(),
            "dietary_mode":       self.cfg.get("dietary_mode") or "",
            "allowed_categories": ", ".join(self.cfg.get("allowed_categories", [])),
        }

    def _parse_faqs(self, raw: list, pm: dict) -> list:
        flat: list = []
        seen: set  = set()

        for item in raw:
            if not isinstance(item, dict):
                continue

            variants = [v.strip() for v in item.get("question_variants", []) if v.strip()]
            answer   = item.get("answer", "").strip()

            if not variants:
                q = (item.get("question") or item.get("q") or "").strip()
                if q:
                    variants = [q]
                if not answer:
                    answer = (item.get("a") or "").strip()

            if not variants or not answer:
                continue

            key = (variants[0].lower(), answer.lower()[:80])
            if key in seen:
                continue
            seen.add(key)

            try:
                answer = answer.format_map(pm)
            except (KeyError, ValueError):
                pass

            # also grab answer_ml for Manglish FAQ packs
            answer_ml = item.get("answer_ml", "").strip()
            if answer_ml:
                try:
                    answer_ml = answer_ml.format_map(pm)
                except (KeyError, ValueError):
                    pass

            # Detect if the primary question is Manglish.
            _item_lang = item.get("lang", "english")
            _q_is_manglish = (
                _item_lang == "manglish"
                or (
                    _item_lang == "english_manglish"
                    and _looksml(variants[0])
                )
            )

            entry = {
                "id":             item.get("id", ""),
                "q":              variants[0],
                "variants":       variants[1:],
                "a":              answer,
                "section":        item.get("category", "shop"),
                "source":         "shop_faq",
                "lang":           _item_lang,
                "_q_is_manglish": _q_is_manglish,
            }
            if answer_ml:
                entry["a_ml"] = answer_ml
            # If this entry already has a paired Manglish question stored
            # explicitly, carry it through for embedding.
            if item.get("q_ml"):
                entry["q_ml"] = item["q_ml"].strip()

            flat.append(entry)

        return flat

    def _build_embeddings(self):
        """
        Build sentence-transformer embeddings for this shop's FAQs.
        Uses faq_engine._get_model() instead of a non-existent 'embedder' export.
        """
        if not self.shop_faqs:
            self.shop_emb_vectors = None
            return
        try:
            model = _faq_module._get_model()
            if model is None:
                return

            texts: list = []
            meta:  list = []

            for item in self.shop_faqs:
                q = item.get("q", "").strip()
                if q:
                    texts.append(q)
                    meta.append({**item, "_qlang": "ml" if item.get("_q_is_manglish") else "en"})
                for v in item.get("variants", []):
                    if v and v.strip():
                        v = v.strip()
                        texts.append(v)
                        # FIX: tag per-variant, not per-entry. question_variants
                        # from generate_shop.py mixes English and Manglish
                        # phrasings in one list -- the old code tagged every
                        # variant with the WHOLE entry's _q_is_manglish flag
                        # (computed only from the primary/first question),
                        # so a genuinely Manglish phrasing sitting at
                        # variants[1] got tagged "en" and became unreachable
                        # for Manglish-filtered search (see faq_engine.py's
                        # _shop_semantic_match, which filters candidate rows
                        # by _qlang before scoring). Uses nlp.is_manglish(),
                        # NOT the file-local _looksml() -- tested and found
                        # _looksml's ~17-particle set misses realistic
                        # Manglish sentences that nlp.py's ~150+ signal list
                        # correctly catches.
                        meta.append({**item, "_qlang": "ml" if _is_manglish_text(v) else "en"})
                # Index Manglish question separately so Manglish queries
                # only match against Manglish questions.
                q_ml = item.get("q_ml", "").strip()
                if q_ml and q_ml != q:
                    texts.append(q_ml)
                    meta.append({**item, "_qlang": "ml"})
                for v in item.get("variants_ml", []):
                    if v and v.strip():
                        texts.append(v.strip())
                        meta.append({**item, "_qlang": "ml"})

            if not texts:
                self.shop_emb_vectors = None
                return

            self.shop_emb_vectors = model.encode(
                texts,
                convert_to_tensor=True,
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=64,
            )
            self.shop_emb_meta = meta
            # Register in per-slug store for multi-tenant isolation
            try:
                if hasattr(_faq_module, "register_shop_embeddings"):
                    _faq_module.register_shop_embeddings(
                        self.slug, self.shop_emb_vectors, self.shop_emb_meta
                    )
            except Exception:
                pass
            print(f"[shop:{self.slug}] OK {len(texts)} shop embeddings built")
        except Exception as e:
            print(f"[shop:{self.slug}] embedding error: {e}")
            self.shop_emb_vectors = None

    def save_config(self, cfg: dict):
        slug_dir = SHOPS_DIR / self.slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        _save_json(slug_dir / "shop_config.json", cfg)
        self.cfg = cfg

    def save_faqs(self, faqs: list):
        slug_dir = SHOPS_DIR / self.slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        _save_json(slug_dir / "shop_faq.json", faqs)
        pm = self._placeholder_map()
        self.shop_faqs = self._parse_faqs(faqs, pm)
        self._build_embeddings()

    def save_items(self, items: list):
        slug_dir = SHOPS_DIR / self.slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        clean = [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]
        _save_json(slug_dir / "shop_items.json", clean)
        self.shop_items = clean
        self.cfg["item_count"] = len(clean)
        _save_json(slug_dir / "shop_config.json", self.cfg)
        self._build_embeddings()

    def pipeline(self, message: str) -> dict:
        with _GLOBAL_LOCK:
            _chat_module._CFG                 = self.cfg
            _chat_module.BOT_NAME             = self.cfg.get("bot_name", "Assistant")
            _chat_module.SHOP_NAME            = self.cfg.get("shop_name", "Our Shop")
            _chat_module.OLLAMA_SYSTEM        = _build_system_prompt(self.cfg)
            _chat_module.OLLAMA_SOCIAL_SYSTEM = _build_social_prompt(self.cfg)

            if hasattr(_chat_module, "_greeting_replies"):
                _chat_module.GREETING_REPLIES = _chat_module._greeting_replies()

            _chat_module.SHOP_GENDER    = self.cfg.get("shop_gender", "all")
            _chat_module.IS_VEG         = self.cfg.get("is_veg", False)
            _chat_module.DIETARY_MODE   = self.cfg.get("dietary_mode")
            _chat_module.SPECIALISATION = self.cfg.get("specialisation")

            # FIX: FAQS_SHOP must be dict[str, list] — api.py /health and /faqs
            # call .values() on it. Setting to bare list caused AttributeError.
            _faq_module.FAQS_SHOP        = {self.slug: self.shop_faqs}
            _faq_module._PLACEHOLDER_MAP = self._placeholder_map()

            if self.shop_emb_vectors is not None:
                _faq_module.SHOP_EMB_VECTORS = self.shop_emb_vectors
                _faq_module.SHOP_EMB_META    = self.shop_emb_meta
                _faq_module.SHOP_FLAT        = self.shop_faqs

            result = _global_pipeline(message, slug=self.slug)

        return result

    def summary(self) -> dict:
        return {
            "slug":           self.slug,
            "bot_name":       self.cfg.get("bot_name", "?"),
            "shop_name":      self.cfg.get("shop_name", "?"),
            "shop_type":      self.cfg.get("shop_type", "general"),
            "shop_gender":    self.cfg.get("shop_gender", "all"),
            "specialisation": self.cfg.get("specialisation"),
            "is_veg":         self.cfg.get("is_veg", False),
            "dietary_mode":   self.cfg.get("dietary_mode"),
            "faq_count":      len(self.shop_faqs),
            "item_count":     len(self.shop_items),
            "emb_count":      len(self.shop_emb_meta),
        }


def _load_json(path) -> list | dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_shop_context(slug: str) -> ShopContext:
    slug = _normalize_slug(slug)
    with _cache_lock:
        if slug not in _cache:
            _cache[slug] = ShopContext(slug)
        return _cache[slug]


def reload_shop(slug: str) -> ShopContext:
    slug = _normalize_slug(slug)
    with _cache_lock:
        ctx = ShopContext(slug)
        _cache[slug] = ctx
        return ctx


def list_shops() -> list[dict]:
    shops: list = []
    if not SHOPS_DIR.exists():
        return shops
    for d in sorted(SHOPS_DIR.iterdir()):
        if not d.is_dir():
            continue
        cfg_path = d / "shop_config.json"
        if not cfg_path.exists():
            shops.append({"slug": d.name, "error": "missing shop_config.json"})
            continue
        try:
            cfg        = json.loads(cfg_path.read_text(encoding="utf-8"))
            faq_count  = len(json.loads((d / "shop_faq.json").read_text()))   if (d / "shop_faq.json").exists()   else 0
            item_count = len(json.loads((d / "shop_items.json").read_text())) if (d / "shop_items.json").exists() else 0
            shops.append({
                "slug":           d.name,
                "bot_name":       cfg.get("bot_name", "?"),
                "shop_name":      cfg.get("shop_name", "?"),
                "shop_type":      cfg.get("shop_type", "general"),
                "shop_gender":    cfg.get("shop_gender", "all"),
                "specialisation": cfg.get("specialisation"),
                "is_veg":         cfg.get("is_veg", False),
                "dietary_mode":   cfg.get("dietary_mode"),
                "faq_count":      faq_count,
                "item_count":     item_count,
            })
        except Exception as e:
            shops.append({"slug": d.name, "error": str(e)})
    return shops


def get_shop_items(slug: str) -> list:
    return get_shop_context(slug).shop_items
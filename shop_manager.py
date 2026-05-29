
# """
# shop_manager.py — Per-slug shop context (file-based, no DB)  v3.0
# ==================================================================
# v3.0 changes (aligned with pdf.py + generate_shop.py v3.0):
#   - Loads shops/{slug}/shop_items.json (item catalogue from pdf.py)
#   - Exposes ctx.shop_items  so api.py can serve /items/{slug}
#   - save_items() persists extracted items and triggers FAQ rebuild
#   - list_shops() now includes item_count
#   - _parse_faqs() resolves {placeholder} in answer strings at load
#     time using the shop's own config — no runtime substitution needed
#   - _build_embeddings() indexes both question_variants AND category
#     group FAQ answers for richer semantic search

# Directory structure:
#   shops/
#     {slug}/
#       shop_config.json   ← generate_shop.py config output
#       shop_faq.json      ← generate_shop.py FAQ output
#       shop_items.json    ← pdf.py extracted item catalogue
# """

# from __future__ import annotations

# import json
# import threading
# from pathlib import Path
# from typing import Optional

# import chat as _chat_module
# import faq_engine as _faq_module
# from chat import (
#     _build_system_prompt,
#     _build_social_prompt,
#     pipeline as _global_pipeline,
# )

# SHOPS_DIR = Path("shops")
# SHOPS_DIR.mkdir(exist_ok=True)

# _GLOBAL_LOCK = threading.Lock()
# _cache: dict[str, "ShopContext"] = {}
# _cache_lock = threading.Lock()


# # ══════════════════════════════════════════════════════════════════════════════
# #  ShopContext
# # ══════════════════════════════════════════════════════════════════════════════

# class ShopContext:
#     def __init__(self, slug: str):
#         self.slug = slug
#         self.cfg: dict = {}
#         self.shop_faqs: list = []       # parsed FAQ dicts for pipeline
#         self.shop_items: list = []      # raw item catalogue (price list)
#         self.shop_emb_vectors = None    # sentence-transformer tensor
#         self.shop_emb_meta: list = []   # parallel metadata list
#         self._load()

#     # ── Load ────────────────────────────────────────────────────────────────

#     def _load(self):
#         slug_dir = SHOPS_DIR / self.slug
#         slug_dir.mkdir(parents=True, exist_ok=True)

#         # ── Config ──────────────────────────────────────────────────────────
#         cfg_path = slug_dir / "shop_config.json"
#         if cfg_path.exists():
#             with open(cfg_path, "r", encoding="utf-8") as f:
#                 self.cfg = json.load(f)
#         else:
#             # Fallback to root shop_config.json (single-tenant mode)
#             root = Path("shop_config.json")
#             if root.exists():
#                 with open(root, "r", encoding="utf-8") as f:
#                     self.cfg = json.load(f)
#             else:
#                 self.cfg = {
#                     "bot_name": "Assistant", "shop_name": "Our Shop",
#                     "shop_type": "general", "contact": {}, "hours": {},
#                     "escalate": {}, "escalate_topics": ["fraud", "refund", "complaint"],
#                     "blocked_topics": [], "quick_chips": [], "welcome_cards": [],
#                     "item_count": 0,
#                 }

#         pm = self._placeholder_map()

#         # ── Shop FAQs ────────────────────────────────────────────────────────
#         faq_path = slug_dir / "shop_faq.json"
#         if faq_path.exists():
#             self.shop_faqs = self._parse_faqs(_load_json(faq_path), pm)
#         else:
#             root_faq = Path("faqs/shop_faq.json")
#             self.shop_faqs = self._parse_faqs(_load_json(root_faq), pm) if root_faq.exists() else []

#         # ── Item catalogue (v3.0) ────────────────────────────────────────────
#         items_path = slug_dir / "shop_items.json"
#         if items_path.exists():
#             self.shop_items = _load_json(items_path) or []
#         else:
#             # Try root faqs/shop_items.json (legacy single-tenant layout)
#             root_items = Path("faqs/shop_items.json")
#             self.shop_items = _load_json(root_items) if root_items.exists() else []

#         self._build_embeddings()
#         print(
#             f"[shop:{self.slug}] ✅ Loaded — "
#             f"bot={self.cfg.get('bot_name')} "
#             f"faqs={len(self.shop_faqs)} "
#             f"items={len(self.shop_items)}"
#         )

#     # ── Placeholder map ─────────────────────────────────────────────────────

#     def _placeholder_map(self) -> dict:
#         c = self.cfg.get("contact", {})
#         h = self.cfg.get("hours", {})
#         d = self.cfg.get("delivery", {})
#         r = self.cfg.get("returns", {})
#         o = self.cfg.get("first_offer", {})
#         h_sun = h.get("sunday", "")
#         h_wkd = h.get("weekdays", "")
#         return {
#             "whatsapp":         c.get("whatsapp", ""),
#             "phone":            c.get("phone", ""),
#             "email":            c.get("email", ""),
#             "hours_weekdays":   h_wkd,
#             "hours_sunday":     "" if h_sun == h_wkd else h_sun,
#             "hours_holiday":    h.get("holiday", ""),
#             "location":         self.cfg.get("location", ""),
#             "city":             self.cfg.get("city", ""),
#             "delivery_areas":   d.get("areas", "N/A"),
#             "delivery_free":    d.get("free_above", "N/A"),
#             "delivery_days":    d.get("days", "N/A"),
#             "return_days":      str(r.get("days", 0)),
#             "return_condition": r.get("condition", "N/A"),
#             "refund_days":      r.get("refund_days", "N/A"),
#             "offer_code":       o.get("code", ""),
#             "offer_desc":       o.get("description", ""),
#             "shop_name":        self.cfg.get("shop_name", ""),
#             "bot_name":         self.cfg.get("bot_name", "Assistant"),
#         }

#     # ── Parse FAQs ──────────────────────────────────────────────────────────

#     def _parse_faqs(self, raw: list, pm: dict) -> list:
#         """
#         Normalise raw FAQ list into the flat format expected by faq_engine.
#         Resolves {placeholder} in answer strings at load time.
#         Accepts both:
#           - generate_shop.py format  {id, question_variants, answer, category}
#           - simple format            {question/q, answer/a}
#         """
#         flat: list = []
#         seen: set = set()

#         for item in raw:
#             if not isinstance(item, dict):
#                 continue

#             variants = [v.strip() for v in item.get("question_variants", []) if v.strip()]
#             answer   = item.get("answer", "").strip()

#             # Simple-format fallback
#             if not variants:
#                 q = (item.get("question") or item.get("q") or "").strip()
#                 if q:
#                     variants = [q]
#                 if not answer:
#                     answer = (item.get("a") or "").strip()

#             if not variants or not answer:
#                 continue

#             key = (variants[0].lower(), answer.lower()[:80])
#             if key in seen:
#                 continue
#             seen.add(key)

#             # Resolve placeholders
#             try:
#                 answer = answer.format_map(pm)
#             except (KeyError, ValueError):
#                 pass  # leave unresolved placeholders as-is

#             flat.append({
#                 "id":       item.get("id", ""),
#                 "q":        variants[0],
#                 "variants": variants[1:],
#                 "a":        answer,
#                 "section":  item.get("category", "shop"),
#                 "source":   "shop_faq",
#                 "lang":     item.get("lang", "english"),
#             })

#         return flat

#     # ── Build embeddings ────────────────────────────────────────────────────

#     def _build_embeddings(self):
#         """
#         Build sentence-transformer embeddings for this shop's FAQs.
#         Indexes all question_variants (primary + alternates) for maximum
#         semantic recall.
#         """
#         if not self.shop_faqs:
#             self.shop_emb_vectors = None
#             return
#         try:
#             from faq_engine import embedder
#             if embedder is None:
#                 return

#             texts: list = []
#             meta:  list = []

#             for item in self.shop_faqs:
#                 q = item.get("q", "").strip()
#                 if q:
#                     texts.append(q)
#                     meta.append(item)
#                 for v in item.get("variants", []):
#                     if v and v.strip():
#                         texts.append(v.strip())
#                         meta.append(item)

#             if not texts:
#                 self.shop_emb_vectors = None
#                 return

#             self.shop_emb_vectors = embedder.encode(
#                 texts,
#                 convert_to_tensor=True,
#                 normalize_embeddings=True,
#                 show_progress_bar=False,
#                 batch_size=64,
#             )
#             self.shop_emb_meta = meta
#             print(f"[shop:{self.slug}] ✅ {len(texts)} shop embeddings built")
#         except Exception as e:
#             print(f"[shop:{self.slug}] ⚠  embedding error: {e}")
#             self.shop_emb_vectors = None

#     # ── Save helpers ────────────────────────────────────────────────────────

#     def save_config(self, cfg: dict):
#         slug_dir = SHOPS_DIR / self.slug
#         slug_dir.mkdir(parents=True, exist_ok=True)
#         _save_json(slug_dir / "shop_config.json", cfg)
#         self.cfg = cfg

#     def save_faqs(self, faqs: list):
#         slug_dir = SHOPS_DIR / self.slug
#         slug_dir.mkdir(parents=True, exist_ok=True)
#         _save_json(slug_dir / "shop_faq.json", faqs)
#         pm = self._placeholder_map()
#         self.shop_faqs = self._parse_faqs(faqs, pm)
#         self._build_embeddings()

#     def save_items(self, items: list):
#         """
#         v3.0 — persist the pdf.py item catalogue and rebuild embeddings
#         so item-price FAQs are immediately searchable.
#         """
#         slug_dir = SHOPS_DIR / self.slug
#         slug_dir.mkdir(parents=True, exist_ok=True)
#         # Strip internal keys before persisting
#         clean = [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]
#         _save_json(slug_dir / "shop_items.json", clean)
#         self.shop_items = clean
#         # Update item_count in config
#         self.cfg["item_count"] = len(clean)
#         _save_json(slug_dir / "shop_config.json", self.cfg)

#     # ── Pipeline ────────────────────────────────────────────────────────────

#     def pipeline(self, message: str) -> dict:
#         """
#         Run chat.pipeline() with this shop's config active.
#         Uses _GLOBAL_LOCK to prevent concurrent slug config swaps.
#         """
#         with _GLOBAL_LOCK:
#             # Swap global chat state to this shop
#             _chat_module._CFG                 = self.cfg
#             _chat_module.BOT_NAME             = self.cfg.get("bot_name", "Assistant")
#             _chat_module.SHOP_NAME            = self.cfg.get("shop_name", "Our Shop")
#             _chat_module.OLLAMA_SYSTEM        = _build_system_prompt(self.cfg)
#             _chat_module.OLLAMA_SOCIAL_SYSTEM = _build_social_prompt(self.cfg)

#             if hasattr(_chat_module, "_greeting_replies"):
#                 _chat_module.GREETING_REPLIES = _chat_module._greeting_replies()

#             # Swap shop FAQ pool
#             _faq_module.FAQS_SHOP         = self.shop_faqs
#             _faq_module._PLACEHOLDER_MAP  = self._placeholder_map()

#             # Swap shop embeddings
#             if self.shop_emb_vectors is not None:
#                 _faq_module.SHOP_EMB_VECTORS = self.shop_emb_vectors
#                 _faq_module.SHOP_EMB_META    = self.shop_emb_meta
#                 _faq_module.SHOP_FLAT        = self.shop_faqs

#             result = _global_pipeline(message)

#         return result

#     # ── Serialisable summary ─────────────────────────────────────────────────

#     def summary(self) -> dict:
#         """Return a lightweight dict for list_shops() / health checks."""
#         return {
#             "slug":       self.slug,
#             "bot_name":   self.cfg.get("bot_name", "?"),
#             "shop_name":  self.cfg.get("shop_name", "?"),
#             "shop_type":  self.cfg.get("shop_type", "general"),
#             "faq_count":  len(self.shop_faqs),
#             "item_count": len(self.shop_items),
#             "emb_count":  len(self.shop_emb_meta),
#         }


# # ══════════════════════════════════════════════════════════════════════════════
# #  File helpers
# # ══════════════════════════════════════════════════════════════════════════════

# def _load_json(path) -> list | dict:
#     try:
#         with open(path, "r", encoding="utf-8") as f:
#             return json.load(f)
#     except Exception:
#         return []


# def _save_json(path, data):
#     with open(path, "w", encoding="utf-8") as f:
#         json.dump(data, f, ensure_ascii=False, indent=2)


# # ══════════════════════════════════════════════════════════════════════════════
# #  Public API
# # ══════════════════════════════════════════════════════════════════════════════

# def get_shop_context(slug: str) -> ShopContext:
#     """Return cached ShopContext for slug, creating it on first access."""
#     with _cache_lock:
#         if slug not in _cache:
#             _cache[slug] = ShopContext(slug)
#         return _cache[slug]


# def reload_shop(slug: str) -> ShopContext:
#     """Force-reload config + FAQs + items from disk, update cache."""
#     with _cache_lock:
#         ctx = ShopContext(slug)
#         _cache[slug] = ctx
#         return ctx


# def list_shops() -> list[dict]:
#     """Return summary dicts for all shops found in shops/ directory."""
#     shops: list = []
#     if not SHOPS_DIR.exists():
#         return shops
#     for d in sorted(SHOPS_DIR.iterdir()):
#         if not d.is_dir():
#             continue
#         cfg_path = d / "shop_config.json"
#         if not cfg_path.exists():
#             shops.append({"slug": d.name, "error": "missing shop_config.json"})
#             continue
#         try:
#             cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
#             faq_count  = len(json.loads((d / "shop_faq.json").read_text()))  if (d / "shop_faq.json").exists()  else 0
#             item_count = len(json.loads((d / "shop_items.json").read_text())) if (d / "shop_items.json").exists() else 0
#             shops.append({
#                 "slug":       d.name,
#                 "bot_name":   cfg.get("bot_name", "?"),
#                 "shop_name":  cfg.get("shop_name", "?"),
#                 "shop_type":  cfg.get("shop_type", "general"),
#                 "faq_count":  faq_count,
#                 "item_count": item_count,
#             })
#         except Exception as e:
#             shops.append({"slug": d.name, "error": str(e)})
#     return shops


# def get_shop_items(slug: str) -> list:
#     """Return the item catalogue for a slug (does not hit disk if cached)."""
#     return get_shop_context(slug).shop_items




# """
# shop_manager.py — Per-slug shop context (file-based, no DB)  v3.0
# ==================================================================
# v3.0 changes (aligned with pdf.py + generate_shop.py v3.0):
#   - Loads shops/{slug}/shop_items.json (item catalogue from pdf.py)
#   - Exposes ctx.shop_items  so api.py can serve /items/{slug}
#   - save_items() persists extracted items and triggers FAQ rebuild
#   - list_shops() now includes item_count
#   - _parse_faqs() resolves {placeholder} in answer strings at load
#     time using the shop's own config — no runtime substitution needed
#   - _build_embeddings() indexes both question_variants AND category
#     group FAQ answers for richer semantic search

# Directory structure:
#   shops/
#     {slug}/
#       shop_config.json   ← generate_shop.py config output
#       shop_faq.json      ← generate_shop.py FAQ output
#       shop_items.json    ← pdf.py extracted item catalogue
# """

# from __future__ import annotations

# import json
# import threading
# from pathlib import Path
# from typing import Optional

# import chat as _chat_module
# import faq_engine as _faq_module
# from chat import (
#     _build_system_prompt,
#     _build_social_prompt,
#     pipeline as _global_pipeline,
# )

# SHOPS_DIR = Path("shops")
# SHOPS_DIR.mkdir(exist_ok=True)

# _GLOBAL_LOCK = threading.Lock()
# _cache: dict[str, "ShopContext"] = {}
# _cache_lock = threading.Lock()


# # ══════════════════════════════════════════════════════════════════════════════
# #  ShopContext
# # ══════════════════════════════════════════════════════════════════════════════

# class ShopContext:
#     def __init__(self, slug: str):
#         self.slug = slug
#         self.cfg: dict = {}
#         self.shop_faqs: list = []       # parsed FAQ dicts for pipeline
#         self.shop_items: list = []      # raw item catalogue (price list)
#         self.shop_emb_vectors = None    # sentence-transformer tensor
#         self.shop_emb_meta: list = []   # parallel metadata list
#         self._load()

#     # ── Load ────────────────────────────────────────────────────────────────

#     def _load(self):
#         slug_dir = SHOPS_DIR / self.slug
#         slug_dir.mkdir(parents=True, exist_ok=True)

#         # ── Config ──────────────────────────────────────────────────────────
#         cfg_path = slug_dir / "shop_config.json"
#         if cfg_path.exists():
#             with open(cfg_path, "r", encoding="utf-8") as f:
#                 self.cfg = json.load(f)
#         else:
#             # Fallback to root shop_config.json (single-tenant mode)
#             root = Path("shop_config.json")
#             if root.exists():
#                 with open(root, "r", encoding="utf-8") as f:
#                     self.cfg = json.load(f)
#             else:
#                 self.cfg = {
#                     "bot_name": "Assistant", "shop_name": "Our Shop",
#                     "shop_type": "general", "contact": {}, "hours": {},
#                     "escalate": {}, "escalate_topics": ["fraud", "refund", "complaint"],
#                     "blocked_topics": [], "quick_chips": [], "welcome_cards": [],
#                     "item_count": 0,
#                 }

#         pm = self._placeholder_map()

#         # ── Shop FAQs ────────────────────────────────────────────────────────
#         faq_path = slug_dir / "shop_faq.json"
#         if faq_path.exists():
#             self.shop_faqs = self._parse_faqs(_load_json(faq_path), pm)
#         else:
#             root_faq = Path("faqs/shop_faq.json")
#             self.shop_faqs = self._parse_faqs(_load_json(root_faq), pm) if root_faq.exists() else []

#         # ── Item catalogue (v3.0) ────────────────────────────────────────────
#         items_path = slug_dir / "shop_items.json"
#         if items_path.exists():
#             self.shop_items = _load_json(items_path) or []
#         else:
#             # Try root faqs/shop_items.json (legacy single-tenant layout)
#             root_items = Path("faqs/shop_items.json")
#             self.shop_items = _load_json(root_items) if root_items.exists() else []

#         self._build_embeddings()
#         print(
#             f"[shop:{self.slug}] ✅ Loaded — "
#             f"bot={self.cfg.get('bot_name')} "
#             f"faqs={len(self.shop_faqs)} "
#             f"items={len(self.shop_items)}"
#         )

#     # ── Placeholder map ─────────────────────────────────────────────────────

#     def _placeholder_map(self) -> dict:
#         c = self.cfg.get("contact", {})
#         h = self.cfg.get("hours", {})
#         d = self.cfg.get("delivery", {})
#         r = self.cfg.get("returns", {})
#         o = self.cfg.get("first_offer", {})
#         h_sun = h.get("sunday", "")
#         h_wkd = h.get("weekdays", "")
#         return {
#             "whatsapp":         c.get("whatsapp", ""),
#             "phone":            c.get("phone", ""),
#             "email":            c.get("email", ""),
#             "hours_weekdays":   h_wkd,
#             "hours_sunday":     "" if h_sun == h_wkd else h_sun,
#             "hours_holiday":    h.get("holiday", ""),
#             "location":         self.cfg.get("location", ""),
#             "city":             self.cfg.get("city", ""),
#             "delivery_areas":   d.get("areas", "N/A"),
#             "delivery_free":    d.get("free_above", "N/A"),
#             "delivery_days":    d.get("days", "N/A"),
#             "return_days":      str(r.get("days", 0)),
#             "return_condition": r.get("condition", "N/A"),
#             "refund_days":      r.get("refund_days", "N/A"),
#             "offer_code":       o.get("code", ""),
#             "offer_desc":       o.get("description", ""),
#             "shop_name":        self.cfg.get("shop_name", ""),
#             "bot_name":         self.cfg.get("bot_name", "Assistant"),
#         }

#     # ── Parse FAQs ──────────────────────────────────────────────────────────

#     def _parse_faqs(self, raw: list, pm: dict) -> list:
#         """
#         Normalise raw FAQ list into the flat format expected by faq_engine.
#         Resolves {placeholder} in answer strings at load time.
#         Accepts both:
#           - generate_shop.py format  {id, question_variants, answer, category}
#           - simple format            {question/q, answer/a}
#         """
#         flat: list = []
#         seen: set = set()

#         for item in raw:
#             if not isinstance(item, dict):
#                 continue

#             variants = [v.strip() for v in item.get("question_variants", []) if v.strip()]
#             answer   = item.get("answer", "").strip()

#             # Simple-format fallback
#             if not variants:
#                 q = (item.get("question") or item.get("q") or "").strip()
#                 if q:
#                     variants = [q]
#                 if not answer:
#                     answer = (item.get("a") or "").strip()

#             if not variants or not answer:
#                 continue

#             key = (variants[0].lower(), answer.lower()[:80])
#             if key in seen:
#                 continue
#             seen.add(key)

#             # Resolve placeholders
#             try:
#                 answer = answer.format_map(pm)
#             except (KeyError, ValueError):
#                 pass  # leave unresolved placeholders as-is

#             flat.append({
#                 "id":       item.get("id", ""),
#                 "q":        variants[0],
#                 "variants": variants[1:],
#                 "a":        answer,
#                 "section":  item.get("category", "shop"),
#                 "source":   "shop_faq",
#                 "lang":     item.get("lang", "english"),
#             })

#         return flat

#     # ── Build embeddings ────────────────────────────────────────────────────

#     def _build_embeddings(self):
#         """
#         Build sentence-transformer embeddings for this shop's FAQs.
#         Indexes all question_variants (primary + alternates) for maximum
#         semantic recall.
#         """
#         if not self.shop_faqs:
#             self.shop_emb_vectors = None
#             return
#         try:
#             from faq_engine import embedder
#             if embedder is None:
#                 return

#             texts: list = []
#             meta:  list = []

#             for item in self.shop_faqs:
#                 q = item.get("q", "").strip()
#                 if q:
#                     texts.append(q)
#                     meta.append(item)
#                 for v in item.get("variants", []):
#                     if v and v.strip():
#                         texts.append(v.strip())
#                         meta.append(item)

#             if not texts:
#                 self.shop_emb_vectors = None
#                 return

#             self.shop_emb_vectors = embedder.encode(
#                 texts,
#                 convert_to_tensor=True,
#                 normalize_embeddings=True,
#                 show_progress_bar=False,
#                 batch_size=64,
#             )
#             self.shop_emb_meta = meta
#             print(f"[shop:{self.slug}] ✅ {len(texts)} shop embeddings built")
#         except Exception as e:
#             print(f"[shop:{self.slug}] ⚠  embedding error: {e}")
#             self.shop_emb_vectors = None

#     # ── Save helpers ────────────────────────────────────────────────────────

#     def save_config(self, cfg: dict):
#         slug_dir = SHOPS_DIR / self.slug
#         slug_dir.mkdir(parents=True, exist_ok=True)
#         _save_json(slug_dir / "shop_config.json", cfg)
#         self.cfg = cfg

#     def save_faqs(self, faqs: list):
#         slug_dir = SHOPS_DIR / self.slug
#         slug_dir.mkdir(parents=True, exist_ok=True)
#         _save_json(slug_dir / "shop_faq.json", faqs)
#         pm = self._placeholder_map()
#         self.shop_faqs = self._parse_faqs(faqs, pm)
#         self._build_embeddings()

#     def save_items(self, items: list):
#         """
#         v3.0 — persist the pdf.py item catalogue and rebuild embeddings
#         so item-price FAQs are immediately searchable.
#         """
#         slug_dir = SHOPS_DIR / self.slug
#         slug_dir.mkdir(parents=True, exist_ok=True)
#         # Strip internal keys before persisting
#         clean = [{k: v for k, v in it.items() if not k.startswith("_")} for it in items]
#         _save_json(slug_dir / "shop_items.json", clean)
#         self.shop_items = clean
#         # Update item_count in config
#         self.cfg["item_count"] = len(clean)
#         _save_json(slug_dir / "shop_config.json", self.cfg)

#     # ── Pipeline ────────────────────────────────────────────────────────────

#     def pipeline(self, message: str) -> dict:
#         """
#         Run chat.pipeline() with this shop's config active.
#         Uses _GLOBAL_LOCK to prevent concurrent slug config swaps.
#         """
#         with _GLOBAL_LOCK:
#             # Swap global chat state to this shop
#             _chat_module._CFG                 = self.cfg
#             _chat_module.BOT_NAME             = self.cfg.get("bot_name", "Assistant")
#             _chat_module.SHOP_NAME            = self.cfg.get("shop_name", "Our Shop")
#             _chat_module.OLLAMA_SYSTEM        = _build_system_prompt(self.cfg)
#             _chat_module.OLLAMA_SOCIAL_SYSTEM = _build_social_prompt(self.cfg)

#             if hasattr(_chat_module, "_greeting_replies"):
#                 _chat_module.GREETING_REPLIES = _chat_module._greeting_replies()

#             # Swap shop FAQ pool
#             _faq_module.FAQS_SHOP         = self.shop_faqs
#             _faq_module._PLACEHOLDER_MAP  = self._placeholder_map()

#             # Swap shop embeddings
#             if self.shop_emb_vectors is not None:
#                 _faq_module.SHOP_EMB_VECTORS = self.shop_emb_vectors
#                 _faq_module.SHOP_EMB_META    = self.shop_emb_meta
#                 _faq_module.SHOP_FLAT        = self.shop_faqs

#             result = _global_pipeline(message)

#         return result

#     # ── Serialisable summary ─────────────────────────────────────────────────

#     def summary(self) -> dict:
#         """Return a lightweight dict for list_shops() / health checks."""
#         return {
#             "slug":       self.slug,
#             "bot_name":   self.cfg.get("bot_name", "?"),
#             "shop_name":  self.cfg.get("shop_name", "?"),
#             "shop_type":  self.cfg.get("shop_type", "general"),
#             "faq_count":  len(self.shop_faqs),
#             "item_count": len(self.shop_items),
#             "emb_count":  len(self.shop_emb_meta),
#         }


# # ══════════════════════════════════════════════════════════════════════════════
# #  File helpers
# # ══════════════════════════════════════════════════════════════════════════════

# def _load_json(path) -> list | dict:
#     try:
#         with open(path, "r", encoding="utf-8") as f:
#             return json.load(f)
#     except Exception:
#         return []


# def _save_json(path, data):
#     with open(path, "w", encoding="utf-8") as f:
#         json.dump(data, f, ensure_ascii=False, indent=2)


# # ══════════════════════════════════════════════════════════════════════════════
# #  Public API
# # ══════════════════════════════════════════════════════════════════════════════

# def get_shop_context(slug: str) -> ShopContext:
#     """Return cached ShopContext for slug, creating it on first access."""
#     with _cache_lock:
#         if slug not in _cache:
#             _cache[slug] = ShopContext(slug)
#         return _cache[slug]


# def reload_shop(slug: str) -> ShopContext:
#     """Force-reload config + FAQs + items from disk, update cache."""
#     with _cache_lock:
#         ctx = ShopContext(slug)
#         _cache[slug] = ctx
#         return ctx


# def list_shops() -> list[dict]:
#     """Return summary dicts for all shops found in shops/ directory."""
#     shops: list = []
#     if not SHOPS_DIR.exists():
#         return shops
#     for d in sorted(SHOPS_DIR.iterdir()):
#         if not d.is_dir():
#             continue
#         cfg_path = d / "shop_config.json"
#         if not cfg_path.exists():
#             shops.append({"slug": d.name, "error": "missing shop_config.json"})
#             continue
#         try:
#             cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
#             faq_count  = len(json.loads((d / "shop_faq.json").read_text()))  if (d / "shop_faq.json").exists()  else 0
#             item_count = len(json.loads((d / "shop_items.json").read_text())) if (d / "shop_items.json").exists() else 0
#             shops.append({
#                 "slug":       d.name,
#                 "bot_name":   cfg.get("bot_name", "?"),
#                 "shop_name":  cfg.get("shop_name", "?"),
#                 "shop_type":  cfg.get("shop_type", "general"),
#                 "faq_count":  faq_count,
#                 "item_count": item_count,
#             })
#         except Exception as e:
#             shops.append({"slug": d.name, "error": str(e)})
#     return shops


# def get_shop_items(slug: str) -> list:
#     """Return the item catalogue for a slug (does not hit disk if cached)."""
#     return get_shop_context(slug).shop_items








"""
shop_manager.py — Per-slug shop context (file-based, no DB)  v4.0
==================================================================
"""

from __future__ import annotations

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


class ShopContext:
    def __init__(self, slug: str):
        self.slug = slug
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
            root = Path("shop_config.json")
            if root.exists():
                with open(root, "r", encoding="utf-8") as f:
                    self.cfg = json.load(f)
            else:
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
            f"[shop:{self.slug}] ✅ Loaded — "
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

            # ── also grab answer_ml for Manglish FAQ packs ──
            answer_ml = item.get("answer_ml", "").strip()
            if answer_ml:
                try:
                    answer_ml = answer_ml.format_map(pm)
                except (KeyError, ValueError):
                    pass

            entry = {
                "id":       item.get("id", ""),
                "q":        variants[0],
                "variants": variants[1:],
                "a":        answer,
                "section":  item.get("category", "shop"),
                "source":   "shop_faq",
                "lang":     item.get("lang", "english"),
            }
            if answer_ml:
                entry["a_ml"] = answer_ml

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
            # ✅ FIX: use _get_model() from faq_engine — 'embedder' does not exist
            model = _faq_module._get_model()
            if model is None:
                return

            texts: list = []
            meta:  list = []

            for item in self.shop_faqs:
                q = item.get("q", "").strip()
                if q:
                    texts.append(q)
                    meta.append(item)
                for v in item.get("variants", []):
                    if v and v.strip():
                        texts.append(v.strip())
                        meta.append(item)

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
            print(f"[shop:{self.slug}] ✅ {len(texts)} shop embeddings built")
        except Exception as e:
            print(f"[shop:{self.slug}] ⚠  embedding error: {e}")
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

            _faq_module.FAQS_SHOP        = self.shop_faqs
            _faq_module._PLACEHOLDER_MAP = self._placeholder_map()

            if self.shop_emb_vectors is not None:
                _faq_module.SHOP_EMB_VECTORS = self.shop_emb_vectors
                _faq_module.SHOP_EMB_META    = self.shop_emb_meta
                _faq_module.SHOP_FLAT        = self.shop_faqs

            result = _global_pipeline(message)

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
    with _cache_lock:
        if slug not in _cache:
            _cache[slug] = ShopContext(slug)
        return _cache[slug]


def reload_shop(slug: str) -> ShopContext:
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
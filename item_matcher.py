# """
# item_matcher.py — Shop item lookup for any shop type  v2.0
# ==========================================================
# Used by faq_engine.py (Pass 0.5) and shop_rag.py.

# Given a customer query and a shop's item list, returns a formatted
# answer listing matching items with prices — in English or Manglish.

# Works for ALL shop types:
#   - Beauty studio: "facial undo"   → lists ALL facial treatments + prices
#   - Restaurant:    "chicken undo"  → lists ALL chicken dishes + prices
#   - Pharmacy:      "paracetamol"   → lists matching medicines + prices
#   - Supermarket:   "rice brands"   → lists matching products + prices

# Key behaviours:
#   - "facial undo"         → ALL facials (not just one)
#   - "is there facials"    → ALL facials
#   - "home service undo"   → Home Service Charge (compound phrase match)
#   - "keratin service undo"→ only keratin items (not Home Service)
#   - "services enthoke"    → [] (broad query — routed to FAQ/WhatsApp)
# """

# from __future__ import annotations

# import re
# from typing import Optional

# # ── Scoring weights ────────────────────────────────────────────────────────────
# _EXACT_NAME_SCORE    = 3.0   # token exactly in item name
# _WORD_MATCH_SCORE    = 1.0   # substring match in name
# _CATEGORY_SCORE      = 0.4   # category-only match (low — not enough to win alone)
# _DESCRIPTION_SCORE   = 0.3
# _MIN_SCORE_THRESHOLD = 0.9   # requires at least one name-level token match

# # ── Max items shown in a single reply ─────────────────────────────────────────
# _MAX_ITEMS_SHOWN = 20

# # ── Manglish availability particles ───────────────────────────────────────────
# _AVAILABILITY_PARTICLES = {
#     "undo", "und", "undu", "undoo", "aano", "ano",
#     "indo", "indu", "indoo", "kittumo", "kittuvo",
#     "undaakumo", "kittumano", "cheyyaamo", "pattumo",
#     "ethoke", "enthoke", "ethokke", "enthokke",
#     "ellam", "okke", "ulla",
#     # typo variants from real messages
#     "availavle", "availble", "avialable", "avlable",
# }

# # ── English availability phrases ───────────────────────────────────────────────
# _AVAILABILITY_PHRASES = [
#     r"\bI (need|want|would like|am looking for)\b",
#     r"\bget me\b",
#     r"\bdo you (have|offer|provide|sell)\b",
#     r"\bis there\b",
#     r"\bare there\b",
#     r"\bwhat .{0,20}(do you have|available|offer)\b",
#     r"\bshow me\b",
#     r"\blist\b",
#     r"\btypes of\b",
#     r"\bkinds of\b",
#     r"\bwhat .{0,20}available\b",
#     r"\bavailable\b",
#     r"\bwhich .{0,20}(have|offer|available)\b",
# ]
# _AVAILABILITY_RE = re.compile("|".join(_AVAILABILITY_PHRASES), re.IGNORECASE)

# # ── Price question patterns ────────────────────────────────────────────────────
# _PRICE_RE = re.compile(
#     r"\b(price|cost|rate|charge|fee|vila|vilayil|ethra|how much|kithr)\b",
#     re.IGNORECASE,
# )

# # ── Broad query patterns → return [] so FAQ/RAG handles them ──────────────────
# _BROAD_QUERY_PATTERNS = [
#     "services enthoke", "enthokke service", "enthokee service",
#     "enthoke service", "all services", "full service",
#     "service details", "enthellam services",
#     "what services", "which services", "full details",
#     "services list", "list of services", "services available",
#     "what all services", "what do you offer",
# ]

# # ── Spelling normalisations ────────────────────────────────────────────────────
# _QUERY_NORMALIZATIONS = [
#     (re.compile(r"\bbiriyani\b", re.I), "biryani"),
#     (re.compile(r"\bbriyani\b",  re.I), "biryani"),
#     (re.compile(r"\bbiriani\b",  re.I), "biryani"),
#     (re.compile(r"\bbyriany\b",  re.I), "biryani"),
#     (re.compile(r"\bcolour\b",   re.I), "color"),
#     (re.compile(r"\bmanicure\b", re.I), "manicure"),
#     (re.compile(r"\bserrvice\b", re.I), "service"),
#     (re.compile(r"\bserivce\b",  re.I), "service"),
#     (re.compile(r"\bhomr\b",     re.I), "home"),
# ]

# _CATEGORY_SYNONYMS: dict[str, set[str]] = {
#     "hair removal": {"waxing", "threading", "wax", "thread"},
#     "nail care":     {"manicure", "pedicure", "nail", "nails"},
#     "skin care":     {"facial", "cleanup", "peel", "treatment"},
#     "hair care":     {"haircut", "color", "spa", "keratin", "rebonding", "smoothing"},
#     "bridal":        {"bridal", "makeup", "mehendi", "groom"},
#     "starters":      {"appetizer", "starter", "snack"},
#     "main course":   {"curry", "rice", "biryani", "gravy"},
#     "vegetarian":    {"veg"},
#     "veggie":        {"veg"},
#     "veggies":       {"veg"},
#     "pure veg":      {"veg"},
#     "tea":           {"chai"},
#     "chaya":         {"chai"},
#     "chayya":        {"chai"},
# }

# # category_list_lookup() works on the item NAME text directly (see the
# # Non-Veg exclusion guard below) rather than through _expand_synonyms(),
# # so "vegetarian"/"veggie" need their own normalization pass to the exact
# # word ("veg") that actually appears in item names like "Veg Biryani".
# # Longest phrases first so "non vegetarian"/"non-vegetarian" get replaced
# # whole before the bare "vegetarian" -> "veg" rule would partially clobber
# # them into a mismatched "non veg" / "non-veg" form.
# _DIETARY_SYNONYMS: list[tuple[str, str]] = sorted(
#     [
#         ("non vegetarian", "non-veg"),
#         ("non-vegetarian", "non-veg"),
#         ("nonveg", "non-veg"),
#         ("non veg", "non-veg"),
#         ("vegetarian", "veg"),
#         ("veggies", "veg"),
#         ("veggie", "veg"),
#         ("pure veg", "veg"),
#     ],
#     key=lambda pair: -len(pair[0]),
# )


# def _normalize_dietary_terms(query: str) -> str:
#     q = query
#     for phrase, canonical in _DIETARY_SYNONYMS:
#         q = re.sub(re.escape(phrase), canonical, q, flags=re.IGNORECASE)
#     return q


# def _expand_synonyms(query: str) -> str:
#     """If the query contains an umbrella term, append its mapped
#     specific words so they participate in tokenization/matching."""
#     ql = query.lower()
#     extra: list[str] = []
#     for phrase, words in _CATEGORY_SYNONYMS.items():
#         if phrase in ql:
#             extra.extend(words)
#     if extra:
#         return query + " " + " ".join(extra)
#     return query



# def _normalize_query(text: str) -> str:
#     for pattern, replacement in _QUERY_NORMALIZATIONS:
#         text = pattern.sub(replacement, text)
#     return text


# def _stem(word: str) -> str:
#     """Minimal suffix-strip stemmer — no nltk needed."""
#     for suffix in ("ings", "ing", "tion", "sion", "als", "ies", "es", "s"):
#         if word.endswith(suffix) and len(word) - len(suffix) >= 3:
#             return word[: -len(suffix)]
#     return word


# def _tokenize(text: str) -> set[str]:
#     """Tokenize, remove stop words, apply stemming."""
#     stop = _AVAILABILITY_PARTICLES | {
#         "i", "a", "an", "the", "is", "it", "in", "of", "to", "do",
#         "my", "me", "we", "you", "am", "are", "be", "for", "on",
#         "with", "at", "by", "this", "that", "please", "want", "need",
#         "have", "has", "what", "which", "show", "list", "types", "kinds",
#         # "home" and "service" are too generic — compound phrase check
#         # above handles "home service undo" before tokenisation
#         "home", "service",
#     }
#     tokens = set(re.findall(r"\b\w+\b", text.lower()))
#     cleaned = tokens - stop
#     stemmed = {_stem(t) for t in cleaned}
#     return cleaned | stemmed


# def _price_label(item: dict) -> str:
#     if item.get("price"):
#         return f"₹{item['price']:,}"
#     if item.get("price_min") and item.get("price_max"):
#         return f"₹{item['price_min']:,}–₹{item['price_max']:,}"
#     return ""


# def _score_item(query_tokens: set[str], item: dict) -> float:
#     score = 0.0
#     name  = item.get("name", "").lower()
#     cat   = item.get("category", "").lower()
#     desc  = item.get("description", "").lower()

#     name_tokens = {_stem(t) for t in name.split()} | set(name.split())
#     cat_tokens  = {_stem(t) for t in cat.split()}  | set(cat.split())
#     desc_tokens = {_stem(t) for t in re.findall(r"\b\w+\b", desc)}

#     for qt in query_tokens:
#         if qt in name_tokens:
#             score += _EXACT_NAME_SCORE
#         elif qt in name:
#             score += _WORD_MATCH_SCORE
#         if qt in cat_tokens:
#             score += _CATEGORY_SCORE
#         if qt in desc_tokens:
#             score += _DESCRIPTION_SCORE

#     # Category-EXACT bonus: if every (non-generic) query token is
#     # found in the category name itself, this is a pure category
#     # query ("starters undo" → category "Starters") and should match
#     # on its own merit, even without a separate name-level hit.
#     _CATEGORY_EXACT_BOOST = 1.0
#     _q_for_cat = query_tokens
#     if _q_for_cat and cat:
#         _cat_word_set = set(cat.split())
#         if _q_for_cat <= (_cat_word_set | cat_tokens):
#             score += _CATEGORY_EXACT_BOOST

#     return score
# def find_matching_items(
#     query: str,
#     items: list[dict],
#     min_score: float = _MIN_SCORE_THRESHOLD,
#     max_results: int = _MAX_ITEMS_SHOWN,
# ) -> list[dict]:
#     """
#     Return items matching the query, sorted by relevance.
#     Returns empty list for broad service queries.
#     """
#     if not items:
#         return []

#     # Block broad queries — route to FAQ/WhatsApp instead
#     q_low = query.lower()
#     if any(p in q_low for p in _BROAD_QUERY_PATTERNS):
#         return []

#     query = _normalize_query(query)
#     query = _expand_synonyms(query)

#     # ── Compound phrase check (BEFORE tokenisation) ────────────────────────────
#     # Ensures "home service undo" matches "Home Service Charge" even though
#     # "home" and "service" are stop words in the tokeniser.
#     _cmpd = []
#     _ql   = query.lower()
#     for _it in items:
#         _nm = _it.get("name", "").lower()
#         _ws = _nm.split()
#         for _wi in range(len(_ws) - 1):
#             _ph = _ws[_wi] + " " + _ws[_wi + 1]
#             if len(_ph) > 6 and _ph in _ql:
#                 _cmpd.append(_it)
#                 break
#     if _cmpd:
#         return _cmpd[:max_results]

#     # ── Token scoring ──────────────────────────────────────────────────────────
#     query_tokens = _tokenize(query)
#     if not query_tokens:
#         return []

#     scored = [
#         (score, item)
#         for item in items
#         if (score := _score_item(query_tokens, item)) >= min_score
#     ]
#     scored.sort(key=lambda x: x[0], reverse=True)
#     return [item for _, item in scored[:max_results]]


# def is_availability_query(query: str) -> bool:
#     """True if query asks 'do you have X' / 'what X do you offer'."""
#     tokens = set(query.lower().split())
#     return bool(tokens & _AVAILABILITY_PARTICLES) or bool(_AVAILABILITY_RE.search(query))


# def is_price_query(query: str) -> bool:
#     """True if query asks about price."""
#     return bool(_PRICE_RE.search(query))


# def format_items_english(
#     items: list[dict],
#     query_noun: str = "",
#     show_price: bool = True,
# ) -> str:
#     if not items:
#         return ""
#     lines = []
#     for item in items:
#         name  = item.get("name", "")
#         price = _price_label(item)
#         desc  = item.get("description", "")
#         line  = f"• {name} — {price}" if (show_price and price) else f"• {name}"
#         if desc and len(desc) < 60:
#             line += f" ({desc})"
#         lines.append(line)
#     header = f"Here's what we have for {query_noun}:" if query_noun else "Here's what we have:"
#     return f"{header}\n" + "\n".join(lines) + "\nLet me know if you need anything else! 😊"


# def format_items_manglish(
#     items: list[dict],
#     query_noun: str = "",
#     show_price: bool = True,
# ) -> str:
#     if not items:
#         return ""
#     lines = []
#     for item in items:
#         name  = item.get("name", "")
#         price = _price_label(item)
#         desc  = item.get("description", "")
#         line  = f"• {name} — {price}" if (show_price and price) else f"• {name}"
#         if desc and len(desc) < 60:
#             line += f" ({desc})"
#         lines.append(line)
#     header = (
#         f"Athe! Njangalkku {query_noun} options okke und:"
#         if query_noun else
#         "Athe! Ithokke available aanu:"
#     )
#     return f"{header}\n" + "\n".join(lines) + "\nEnthelum help venam? 😊"


# def format_items_reply(
#     items: list[dict],
#     lang: str,
#     query_noun: str = "",
#     show_price: bool = True,
# ) -> str:
#     if lang == "manglish":
#         return format_items_manglish(items, query_noun, show_price)
#     return format_items_english(items, query_noun, show_price)


# def extract_query_noun(query: str, matched_items: list[dict] | None = None) -> str:
#     """Extract the main subject noun from a query for use in reply headers."""
#     normalized = _normalize_query(query)
#     raw_tokens = re.findall(r"\b\w+\b", normalized.lower())
#     stem_to_orig: dict[str, str] = {_stem(r): r for r in raw_tokens}

#     tokens = _tokenize(normalized)
#     _skip = {
#         "available", "price", "cost", "rate", "service", "item",
#         "items", "option", "options", "type", "types", "kind", "kinds",
#         "show", "list", "there",
#     }
#     meaningful = [t for t in tokens if len(t) > 3 and t not in _skip]
#     if not meaningful:
#         return ""

#     def _disp(stem: str) -> str:
#         return stem_to_orig.get(stem, stem)

#     if matched_items:
#         # Try compound phrases first (2-word sequences in query)
#         _raw_words = normalized.lower().split()
#         _stop_set  = _AVAILABILITY_PARTICLES | {
#             "i", "a", "an", "the", "is", "do", "you", "have",
#             "what", "which", "show", "list", "there", "are",
#         }
#         for i in range(len(_raw_words) - 1):
#             w1, w2 = _raw_words[i], _raw_words[i + 1]
#             if w1 in _stop_set or w2 in _stop_set:
#                 continue
#             phrase = w1 + " " + w2
#             for item in matched_items:
#                 name = item.get("name", "").lower()
#                 cat  = item.get("category", "").lower()
#                 if phrase in name or phrase in cat:
#                     return phrase  # compound phrase wins

#         # Fall back to single token with best match
#         best, best_score = "", 0
#         for stem in meaningful:
#             disp = _disp(stem)
#             for item in matched_items:
#                 name = item.get("name", "").lower()
#                 cat  = item.get("category", "").lower()
#                 if stem in name or stem in cat or disp in name or disp in cat:
#                     if len(disp) > best_score:
#                         best_score = len(disp)
#                         best = disp
#         if best:
#             return best

#     by_len = sorted(meaningful, key=len, reverse=True)
#     return _disp(by_len[0]) if by_len else ""


# # ─────────────────────────────────────────────────────────────────────────────
# # Category enumeration — "all facials", "full threading details", "wax ethoke und"
# # Lists EVERY item whose NAME contains the service keyword, in the query language.
# # Keys on item NAME (the 'category' field is unreliable — items may all share one
# # category like "Hair Spa"). Shop-agnostic. Bypasses the result cap.
# # ─────────────────────────────────────────────────────────────────────────────

# _BREADTH_SIGNALS = {
#     "all", "full", "list", "every", "complete", "entire", "details",
#     "varieties", "types", "kinds", "options", "menu", "everything",
#     "ellaam", "ellam", "okke", "ethoke", "enthoke", "ethokke",
#     "enthokke", "ella", "ethellam", "mothham", "muzhuvan", "muzhuvanum",
# }

# _CAT_STOPWORDS = {
#     "i", "we", "you", "do", "have", "the", "a", "an", "of", "for", "me",
#     "need", "want", "show", "give", "tell", "what", "which", "your", "that",
#     "and", "or", "is", "are", "with", "about", "njan", "enikku", "venam",
#     "und", "undo", "undu", "indo", "kittumo", "cheyyumo", "cheyyaamo",
#     "aano", "paranju", "tharamo", "please",
# } | _BREADTH_SIGNALS


# # A query can contain a category word AND a breadth word yet still NOT be a
# # request to LIST items — e.g. "threading pain undakumo?" (does it hurt),
# # "after facial enth cheyanam?" (aftercare). These ask ABOUT a service, so
# # enumerating the whole category is wrong. Block enumeration when this fires.
# _NON_LIST_INTENT = re.compile(
#     r"\b(pain|hurt|undakumo|undaakumo|safe|side\s*effect|after|before|"
#     r"during|while|how\s*long|how\s*often|can\s*i|should\s*i|"
#     r"cheyaam|cheyyamo|cheyyanam|cheyyano|venamo|"
#     r"enth\s*chey|enthu\s*chey|nallath|better|good\s*for|"
#     r"recommend|suggest|advice|tip)\b",
#     re.IGNORECASE,
# )


# def _query_has_breadth(query: str) -> bool:
#     if _NON_LIST_INTENT.search(query):
#         return False
#     toks = set(re.sub(r"[^\w\s]", " ", query.lower()).split())
#     singularized = {t[:-1] if t.endswith("s") and len(t) > 3 else t for t in toks}
#     return bool((toks | singularized) & _BREADTH_SIGNALS)


# def _extract_category_keyword(query: str, items: list) -> str:
#     q_toks = [t for t in re.sub(r"[^\w\s]", " ", query.lower()).split()
#               if t not in _CAT_STOPWORDS and len(t) > 2]
#     if not q_toks:
#         return ""
#     name_words: set = set()
#     for it in items:
#         for w in re.sub(r"[^\w\s]", " ", it.get("name", "").lower()).split():
#             if len(w) > 2:
#                 name_words.add(w)
#     for t in q_toks:
#         for c in ([t, t[:-1]] if t.endswith("s") else [t]):
#             if c in name_words:
#                 return c
#     return ""


# _AVAIL_PARTICLES = {
#     "undo", "indo", "und", "unde", "undoo", "available", "aano", "ano",
#     "aanu", "kittumo", "kitumo", "kittum", "cheyyumo", "cheyumo", "cheyunnundo", "cheyunundo",
#     "ille", "illa", "do", "you", "have", "any", "is", "there", "the",
#     "a", "an", "what", "about", "ningalude", "njangalude", "ivide",
# }


# def _bare_category_keyword(query: str) -> str | None:
#     """'facial undo' / 'threading?' -> 'facial'/'threading'. Returns the lone
#     content token when the query is just one keyword + availability particles;
#     None otherwise (so specific multi-word items stay single-answer)."""
#     if _NON_LIST_INTENT.search(query):
#         return None
#     toks = [w for w in re.sub(r"[^\w\s]", " ", query.lower()).split()
#             if w not in _AVAIL_PARTICLES and len(w) >= 3]
#     return toks[0] if len(toks) == 1 else None


# def category_list_lookup(query: str, items: list, lang: str = "english"):
#     """If the query asks for ALL of a category, return the full formatted list.
#     Returns reply string, or None if not a breadth/category query."""
#     if not items or not query.strip():
#         return None
#     query = _normalize_dietary_terms(query)
#     _bare = None
#     if not _query_has_breadth(query):
#         _bare = _bare_category_keyword(query)
#         if not _bare:
#             return None
#     keyword = _bare or _extract_category_keyword(query, items)
#     if not keyword:
#         return None
#     # "Non-Veg" contains "Veg" right after the hyphen, and a hyphen IS a
#     # regex word boundary -- so a bare \bveg\b falsely matches inside
#     # "Non-Veg" and pollutes a vegetarian customer's "veg" list. Exclude
#     # any match immediately preceded by "non-"/"non " (case-insensitive).
#     _kw_re = re.compile(r"(?<!non[- ])\b" + re.escape(keyword), re.IGNORECASE)
#     matched = [it for it in items if _kw_re.search(it.get("name", ""))]
#     if _bare and len(matched) < 2:
#         return None   # single/zero match: let normal item_lookup answer it
#     if len(matched) < 2:
#         return None
#     return format_items_reply(matched, lang, query_noun=keyword, show_price=True)


# def item_lookup(
#     query: str,
#     items: list[dict],
#     lang: str = "english",
#     min_score: float = _MIN_SCORE_THRESHOLD,
# ) -> Optional[str]:
#     # Yes/no inclusion questions ("Is hairstyling included in bridal
#     # packages?", "Does it include X?") should answer from the
#     # matched item's description, not dump the full price list.
#     _is_inclusion_q = bool(re.search(
#         r"\b(?:is|are|does|do)\b.{0,40}\b(?:include|included|includes|"
#         r"comes? with|got)\b", query, re.IGNORECASE
#     ))
#     if _is_inclusion_q:
#         _matches = find_matching_items(query, items)
#         if _matches:
#             _lines = []
#             for it in _matches[:5]:
#                 _desc = (it.get("description") or "").strip()
#                 if _desc:
#                     _lines.append(f"{it['name']}: {_desc}")
#             if _lines:
#                 _body = " | ".join(_lines)
#                 if lang == "manglish":
#                     return f"Athe! {_body}. Enthelum help venam? \U0001F60A"
#                 return f"Yes — {_body}. Let me know if you need anything else! \U0001F60A"

#     """
#     Main entry point.
#     Returns formatted reply string (English or Manglish) or None if no match.
#     """
#     if not items or not query.strip():
#         return None

#     # Breadth query ("all facials", "wax ethoke und")? List the whole category.
#     _cat = category_list_lookup(query, items, lang=lang)
#     if _cat:
#         return _cat

#     matched = find_matching_items(query, items, min_score=min_score)
#     if not matched:
#         return None
#     noun = extract_query_noun(query, matched_items=matched)
#     return format_items_reply(matched, lang, query_noun=noun, show_price=True)










"""
item_matcher.py — Shop item lookup for any shop type  v2.0
==========================================================
Used by faq_engine.py (Pass 0.5) and shop_rag.py.

Given a customer query and a shop's item list, returns a formatted
answer listing matching items with prices — in English or Manglish.

Works for ALL shop types:
  - Beauty studio: "facial undo"   → lists ALL facial treatments + prices
  - Restaurant:    "chicken undo"  → lists ALL chicken dishes + prices
  - Pharmacy:      "paracetamol"   → lists matching medicines + prices
  - Supermarket:   "rice brands"   → lists matching products + prices

Key behaviours:
  - "facial undo"         → ALL facials (not just one)
  - "is there facials"    → ALL facials
  - "home service undo"   → Home Service Charge (compound phrase match)
  - "keratin service undo"→ only keratin items (not Home Service)
  - "services enthoke"    → [] (broad query — routed to FAQ/WhatsApp)
"""

from __future__ import annotations

import re
from typing import Optional

# ── Scoring weights ────────────────────────────────────────────────────────────
_EXACT_NAME_SCORE    = 3.0   # token exactly in item name
_WORD_MATCH_SCORE    = 1.0   # substring match in name
_CATEGORY_SCORE      = 0.4   # category-only match (low — not enough to win alone)
_DESCRIPTION_SCORE   = 0.3
_MIN_SCORE_THRESHOLD = 0.9   # requires at least one name-level token match

# ── Max items shown in a single reply ─────────────────────────────────────────
_MAX_ITEMS_SHOWN = 20

# ── Manglish availability particles ───────────────────────────────────────────
_AVAILABILITY_PARTICLES = {
    "undo", "und", "undu", "undoo", "aano", "ano",
    "indo", "indu", "indoo", "kittumo", "kittuvo",
    "undaakumo", "kittumano", "cheyyaamo", "pattumo",
    "ethoke", "enthoke", "ethokke", "enthokke",
    "ellam", "okke", "oke", "ulla",
    # typo variants from real messages
    "availavle", "availble", "avialable", "avlable",
}

# ── English availability phrases ───────────────────────────────────────────────
_AVAILABILITY_PHRASES = [
    r"\bI (need|want|would like|am looking for)\b",
    r"\bget me\b",
    r"\bdo you (have|offer|provide|sell)\b",
    r"\bis there\b",
    r"\bare there\b",
    r"\bwhat .{0,20}(do you have|available|offer)\b",
    r"\bshow me\b",
    r"\blist\b",
    r"\btypes of\b",
    r"\bkinds of\b",
    r"\bwhat .{0,20}available\b",
    r"\bavailable\b",
    r"\bwhich .{0,20}(have|offer|available)\b",
]
_AVAILABILITY_RE = re.compile("|".join(_AVAILABILITY_PHRASES), re.IGNORECASE)

# ── Price question patterns ────────────────────────────────────────────────────
_PRICE_RE = re.compile(
    r"\b(price|cost|rate|charge|fee|vila|vilayil|ethra|how much|kithr)\b",
    re.IGNORECASE,
)

# ── Broad query patterns → return [] so FAQ/RAG handles them ──────────────────
_BROAD_QUERY_PATTERNS = [
    "services enthoke", "enthokke service", "enthokee service",
    "enthoke service", "all services", "full service",
    "service details", "enthellam services",
    "what services", "which services", "full details",
    "services list", "list of services", "services available",
    "what all services", "what do you offer",
]

# ── Spelling normalisations ────────────────────────────────────────────────────
_QUERY_NORMALIZATIONS = [
    (re.compile(r"\bbiriyani\b", re.I), "biryani"),
    (re.compile(r"\bbriyani\b",  re.I), "biryani"),
    (re.compile(r"\bbiriani\b",  re.I), "biryani"),
    (re.compile(r"\bbyriany\b",  re.I), "biryani"),
    (re.compile(r"\bcolour\b",   re.I), "color"),
    (re.compile(r"\bmanicure\b", re.I), "manicure"),
    (re.compile(r"\bserrvice\b", re.I), "service"),
    (re.compile(r"\bserivce\b",  re.I), "service"),
    (re.compile(r"\bhomr\b",     re.I), "home"),
    (re.compile(r"\bpoori\b",    re.I), "puri"),
    (re.compile(r"\bpuris\b",    re.I), "puri"),
    (re.compile(r"\bnan\b",      re.I), "naan"),
]

_CATEGORY_SYNONYMS: dict[str, set[str]] = {
    "hair removal": {"waxing", "threading", "wax", "thread"},
    "nail care":     {"manicure", "pedicure", "nail", "nails"},
    "skin care":     {"facial", "cleanup", "peel", "treatment"},
    "hair care":     {"haircut", "color", "spa", "keratin", "rebonding", "smoothing"},
    "bridal":        {"bridal", "makeup", "mehendi", "groom"},
    "starters":      {"appetizer", "starter", "snack"},
    "main course":   {"curry", "rice", "biryani", "gravy"},
    "vegetarian":    {"veg"},
    "veggie":        {"veg"},
    "veggies":       {"veg"},
    "pure veg":      {"veg"},
    "tea":           {"chai"},
    "chaya":         {"chai"},
    "chayya":        {"chai"},
}

# category_list_lookup() works on the item NAME text directly (see the
# Non-Veg exclusion guard below) rather than through _expand_synonyms(),
# so "vegetarian"/"veggie" need their own normalization pass to the exact
# word ("veg") that actually appears in item names like "Veg Biryani".
# Longest phrases first so "non vegetarian"/"non-vegetarian" get replaced
# whole before the bare "vegetarian" -> "veg" rule would partially clobber
# them into a mismatched "non veg" / "non-veg" form.
_DIETARY_SYNONYMS: list[tuple[str, str]] = sorted(
    [
        ("non vegetarian", "non-veg"),
        ("non-vegetarian", "non-veg"),
        ("nonveg", "non-veg"),
        ("non veg", "non-veg"),
        ("vegetarian", "veg"),
        ("veggies", "veg"),
        ("veggie", "veg"),
        ("pure veg", "veg"),
    ],
    key=lambda pair: -len(pair[0]),
)


def _normalize_dietary_terms(query: str) -> str:
    q = query
    for phrase, canonical in _DIETARY_SYNONYMS:
        q = re.sub(re.escape(phrase), canonical, q, flags=re.IGNORECASE)
    return q


def _expand_synonyms(query: str) -> str:
    """If the query contains an umbrella term, append its mapped
    specific words so they participate in tokenization/matching."""
    ql = query.lower()
    extra: list[str] = []
    for phrase, words in _CATEGORY_SYNONYMS.items():
        if phrase in ql:
            extra.extend(words)
    if extra:
        return query + " " + " ".join(extra)
    return query



def _normalize_query(text: str) -> str:
    for pattern, replacement in _QUERY_NORMALIZATIONS:
        text = pattern.sub(replacement, text)
    return text


def _stem(word: str) -> str:
    """Minimal suffix-strip stemmer — no nltk needed."""
    for suffix in ("ings", "ing", "tion", "sion", "als", "ies", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _tokenize(text: str) -> set[str]:
    """Tokenize, remove stop words, apply stemming."""
    stop = _AVAILABILITY_PARTICLES | {
        "i", "a", "an", "the", "is", "it", "in", "of", "to", "do",
        "my", "me", "we", "you", "am", "are", "be", "for", "on",
        "with", "at", "by", "this", "that", "please", "want", "need",
        "have", "has", "what", "which", "show", "list", "types", "kinds",
        # "home" and "service" are too generic — compound phrase check
        # above handles "home service undo" before tokenisation
        "home", "service",
    }
    tokens = set(re.findall(r"\b\w+\b", text.lower()))
    cleaned = tokens - stop
    stemmed = {_stem(t) for t in cleaned}
    return cleaned | stemmed


def _price_label(item: dict) -> str:
    if item.get("price"):
        return f"₹{item['price']:,}"
    if item.get("price_min") and item.get("price_max"):
        return f"₹{item['price_min']:,}–₹{item['price_max']:,}"
    return ""


_GENERIC_TOKEN_ITEM_THRESHOLD = 5  # a word in this many+ item names isn't a useful discriminator alone


def _compute_generic_tokens(items: list) -> set[str]:
    from collections import Counter
    counts: Counter = Counter()
    for it in items:
        name_toks = set(re.findall(r"\b\w+\b", it.get("name", "").lower()))
        for t in name_toks:
            counts[t] += 1
    return {t for t, c in counts.items() if c >= _GENERIC_TOKEN_ITEM_THRESHOLD}


def _score_item(query_tokens: set[str], item: dict, generic_tokens: frozenset = frozenset()) -> float:
    score = 0.0
    name  = item.get("name", "").lower()
    cat   = item.get("category", "").lower()
    desc  = item.get("description", "").lower()

    name_tokens = {_stem(t) for t in name.split()} | set(name.split())
    cat_tokens  = {_stem(t) for t in cat.split()}  | set(cat.split())
    desc_tokens = {_stem(t) for t in re.findall(r"\b\w+\b", desc)}

    # A generic word (e.g. "masala" -- appears in Chicken Masala, Mutton
    # Masala, Paneer Tikka Masala, Masala Chai...) only gets full credit
    # when it's the query's ONLY content token ("masala undo" is a
    # legitimate "show me masala dishes" category ask). Alongside a more
    # specific token ("masala poori"), it shouldn't independently qualify
    # unrelated items -- otherwise "poori" (which uniquely names Puri)
    # gets drowned out by nine unrelated masala-dishes tying on score.
    _downweight_generic = len(query_tokens) > 1

    for qt in query_tokens:
        _is_generic = _downweight_generic and qt in generic_tokens
        if qt in name_tokens:
            score += _CATEGORY_SCORE if _is_generic else _EXACT_NAME_SCORE
        elif any(w.startswith(qt) for w in name.split()):
            # Word-boundary-aware prefix match, NOT raw substring -- `qt in
            # name` previously matched 'nan' against 'banana milkshake'
            # purely because those letters appear consecutively mid-word.
            # Requiring qt to be a PREFIX of an actual word in the name
            # keeps that fixed while this generic-word-downweighting logic
            # (for the masala/poori case) is layered on top of it.
            score += (_CATEGORY_SCORE * 0.5) if _is_generic else _WORD_MATCH_SCORE
        if qt in cat_tokens:
            score += _CATEGORY_SCORE
        if qt in desc_tokens:
            score += _DESCRIPTION_SCORE

    # Category-EXACT bonus: if every (non-generic) query token is
    # found in the category name itself, this is a pure category
    # query ("starters undo" → category "Starters") and should match
    # on its own merit, even without a separate name-level hit.
    _CATEGORY_EXACT_BOOST = 1.0
    _q_for_cat = query_tokens
    if _q_for_cat and cat:
        _cat_word_set = set(cat.split())
        if _q_for_cat <= (_cat_word_set | cat_tokens):
            score += _CATEGORY_EXACT_BOOST

    return score
def find_matching_items(
    query: str,
    items: list[dict],
    min_score: float = _MIN_SCORE_THRESHOLD,
    max_results: int = _MAX_ITEMS_SHOWN,
) -> list[dict]:
    """
    Return items matching the query, sorted by relevance.
    Returns empty list for broad service queries.
    """
    if not items:
        return []

    # Block broad queries — route to FAQ/WhatsApp instead
    q_low = query.lower()
    if any(p in q_low for p in _BROAD_QUERY_PATTERNS):
        return []

    query = _normalize_query(query)
    query = _expand_synonyms(query)

    # ── Compound phrase check (BEFORE tokenisation) ────────────────────────────
    # Ensures "home service undo" matches "Home Service Charge" even though
    # "home" and "service" are stop words in the tokeniser.
    _cmpd = []
    _ql   = query.lower()
    for _it in items:
        _nm = _it.get("name", "").lower()
        _ws = _nm.split()
        for _wi in range(len(_ws) - 1):
            _ph = _ws[_wi] + " " + _ws[_wi + 1]
            if len(_ph) > 6 and _ph in _ql:
                _cmpd.append(_it)
                break
    if _cmpd:
        return _cmpd[:max_results]

    # ── Token scoring ──────────────────────────────────────────────────────────
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    generic_tokens = frozenset(_compute_generic_tokens(items))
    scored = [
        (score, item)
        for item in items
        if (score := _score_item(query_tokens, item, generic_tokens=generic_tokens)) >= min_score
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_results]]


def is_availability_query(query: str) -> bool:
    """True if query asks 'do you have X' / 'what X do you offer'."""
    tokens = set(query.lower().split())
    return bool(tokens & _AVAILABILITY_PARTICLES) or bool(_AVAILABILITY_RE.search(query))


def is_price_query(query: str) -> bool:
    """True if query asks about price."""
    return bool(_PRICE_RE.search(query))


def format_items_english(
    items: list[dict],
    query_noun: str = "",
    show_price: bool = True,
) -> str:
    if not items:
        return ""
    lines = []
    for item in items:
        name  = item.get("name", "")
        price = _price_label(item)
        desc  = item.get("description", "")
        line  = f"• {name} — {price}" if (show_price and price) else f"• {name}"
        if desc and len(desc) < 60:
            line += f" ({desc})"
        lines.append(line)
    header = f"Here's what we have for {query_noun}:" if query_noun else "Here's what we have:"
    return f"{header}\n" + "\n".join(lines) + "\nLet me know if you need anything else! 😊"


def format_items_manglish(
    items: list[dict],
    query_noun: str = "",
    show_price: bool = True,
) -> str:
    if not items:
        return ""
    lines = []
    for item in items:
        name  = item.get("name", "")
        price = _price_label(item)
        desc  = item.get("description", "")
        line  = f"• {name} — {price}" if (show_price and price) else f"• {name}"
        if desc and len(desc) < 60:
            line += f" ({desc})"
        lines.append(line)
    header = (
        f"Athe! Njangalkku {query_noun} options okke und:"
        if query_noun else
        "Athe! Ithokke available aanu:"
    )
    return f"{header}\n" + "\n".join(lines) + "\nEnthelum help venam? 😊"


def format_items_reply(
    items: list[dict],
    lang: str,
    query_noun: str = "",
    show_price: bool = True,
) -> str:
    if lang == "manglish":
        return format_items_manglish(items, query_noun, show_price)
    return format_items_english(items, query_noun, show_price)


def extract_query_noun(query: str, matched_items: list[dict] | None = None) -> str:
    """Extract the main subject noun from a query for use in reply headers."""
    normalized = _normalize_query(query)
    raw_tokens = re.findall(r"\b\w+\b", normalized.lower())
    stem_to_orig: dict[str, str] = {_stem(r): r for r in raw_tokens}

    tokens = _tokenize(normalized)
    _skip = {
        "available", "price", "cost", "rate", "service", "item",
        "items", "option", "options", "type", "types", "kind", "kinds",
        "show", "list", "there",
    }
    meaningful = [t for t in tokens if len(t) > 3 and t not in _skip]
    if not meaningful:
        return ""

    def _disp(stem: str) -> str:
        return stem_to_orig.get(stem, stem)

    if matched_items:
        # Try compound phrases first (2-word sequences in query)
        _raw_words = normalized.lower().split()
        _stop_set  = _AVAILABILITY_PARTICLES | {
            "i", "a", "an", "the", "is", "do", "you", "have",
            "what", "which", "show", "list", "there", "are",
        }
        for i in range(len(_raw_words) - 1):
            w1, w2 = _raw_words[i], _raw_words[i + 1]
            if w1 in _stop_set or w2 in _stop_set:
                continue
            phrase = w1 + " " + w2
            for item in matched_items:
                name = item.get("name", "").lower()
                cat  = item.get("category", "").lower()
                if phrase in name or phrase in cat:
                    return phrase  # compound phrase wins

        # Fall back to single token with best match
        best, best_score = "", 0
        for stem in meaningful:
            disp = _disp(stem)
            for item in matched_items:
                name = item.get("name", "").lower()
                cat  = item.get("category", "").lower()
                if stem in name or stem in cat or disp in name or disp in cat:
                    if len(disp) > best_score:
                        best_score = len(disp)
                        best = disp
        if best:
            return best

    by_len = sorted(meaningful, key=len, reverse=True)
    return _disp(by_len[0]) if by_len else ""


# ─────────────────────────────────────────────────────────────────────────────
# Category enumeration — "all facials", "full threading details", "wax ethoke und"
# Lists EVERY item whose NAME contains the service keyword, in the query language.
# Keys on item NAME (the 'category' field is unreliable — items may all share one
# category like "Hair Spa"). Shop-agnostic. Bypasses the result cap.
# ─────────────────────────────────────────────────────────────────────────────

_BREADTH_SIGNALS = {
    "all", "full", "list", "every", "complete", "entire", "details",
    "varieties", "types", "kinds", "options", "menu", "everything",
    "ellaam", "ellam", "okke", "oke", "ethoke", "enthoke", "ethokke",
    "enthokke", "ella", "ethellam", "mothham", "muzhuvan", "muzhuvanum",
}

_CAT_STOPWORDS = {
    "i", "we", "you", "do", "have", "the", "a", "an", "of", "for", "me",
    "need", "want", "show", "give", "tell", "what", "which", "your", "that",
    "and", "or", "is", "are", "with", "about", "njan", "enikku", "venam",
    "und", "undo", "undu", "indo", "kittumo", "cheyyumo", "cheyyaamo",
    "aano", "paranju", "tharamo", "please",
} | _BREADTH_SIGNALS


# A query can contain a category word AND a breadth word yet still NOT be a
# request to LIST items — e.g. "threading pain undakumo?" (does it hurt),
# "after facial enth cheyanam?" (aftercare). These ask ABOUT a service, so
# enumerating the whole category is wrong. Block enumeration when this fires.
_NON_LIST_INTENT = re.compile(
    r"\b(pain|hurt|undakumo|undaakumo|safe|side\s*effect|after|before|"
    r"during|while|how\s*long|how\s*often|can\s*i|should\s*i|"
    r"cheyaam|cheyyamo|cheyyanam|cheyyano|venamo|"
    r"enth\s*chey|enthu\s*chey|nallath|better|good\s*for|"
    r"recommend|suggest|advice|tip)\b",
    re.IGNORECASE,
)


def _query_has_breadth(query: str) -> bool:
    if _NON_LIST_INTENT.search(query):
        return False
    toks = set(re.sub(r"[^\w\s]", " ", query.lower()).split())
    singularized = {t[:-1] if t.endswith("s") and len(t) > 3 else t for t in toks}
    return bool((toks | singularized) & _BREADTH_SIGNALS)


def _extract_category_keyword(query: str, items: list) -> str:
    # Same spelling-normalization gap _bare_category_keyword had (biriyani vs
    # biryani) -- this function does exact set-membership matching against
    # item name words, so an unnormalized query token never matches even
    # when the item name is right there. Normalize before tokenizing.
    query = _normalize_query(query)
    q_toks = [t for t in re.sub(r"[^\w\s]", " ", query.lower()).split()
              if t not in _CAT_STOPWORDS and len(t) > 2]
    if not q_toks:
        return ""
    name_words: set = set()
    for it in items:
        for w in re.sub(r"[^\w\s]", " ", it.get("name", "").lower()).split():
            if len(w) > 2:
                name_words.add(w)
    for t in q_toks:
        for c in ([t, t[:-1]] if t.endswith("s") else [t]):
            if c in name_words:
                return c
    return ""


_AVAIL_PARTICLES = {
    "undo", "indo", "und", "unde", "undoo", "oke", "available", "aano", "ano",
    "aanu", "kittumo", "kitumo", "kittum", "cheyyumo", "cheyumo", "cheyunnundo", "cheyunundo",
    "ille", "illa", "do", "you", "have", "any", "is", "there", "the",
    "a", "an", "what", "about", "ningalude", "njangalude", "ivide",
}


def _bare_category_keyword(query: str) -> str | None:
    """'facial undo' / 'threading?' -> 'facial'/'threading'. Returns the lone
    content token when the query is just one keyword + availability particles;
    None otherwise (so specific multi-word items stay single-answer)."""
    if _NON_LIST_INTENT.search(query):
        return None
    toks = [w for w in re.sub(r"[^\w\s]", " ", query.lower()).split()
            if w not in _AVAIL_PARTICLES and len(w) >= 3]
    return toks[0] if len(toks) == 1 else None


def category_list_lookup(query: str, items: list, lang: str = "english"):
    """If the query asks for ALL of a category, return the full formatted list.
    Returns reply string, or None if not a breadth/category query."""
    if not items or not query.strip():
        return None
    query = _normalize_dietary_terms(query)
    _bare = None
    if not _query_has_breadth(query):
        _bare = _bare_category_keyword(query)
        if not _bare:
            return None
    keyword = _bare or _extract_category_keyword(query, items)
    if not keyword:
        return None
    keyword = _normalize_query(keyword)  # fix: biriyani->biryani etc before regex
    # "Non-Veg" contains "Veg" right after the hyphen, and a hyphen IS a
    # regex word boundary -- so a bare \bveg\b falsely matches inside
    # "Non-Veg" and pollutes a vegetarian customer's "veg" list. Exclude
    # any match immediately preceded by "non-"/"non " (case-insensitive).
    _kw_re = re.compile(r"(?<!non[- ])\b" + re.escape(keyword), re.IGNORECASE)
    matched = [it for it in items if _kw_re.search(it.get("name", ""))]
    if _bare and len(matched) < 2:
        return None   # single/zero match: let normal item_lookup answer it
    if len(matched) < 2:
        return None
    return format_items_reply(matched, lang, query_noun=keyword, show_price=True)


def item_lookup(
    query: str,
    items: list[dict],
    lang: str = "english",
    min_score: float = _MIN_SCORE_THRESHOLD,
) -> Optional[str]:
    # Yes/no inclusion questions ("Is hairstyling included in bridal
    # packages?", "Does it include X?") should answer from the
    # matched item's description, not dump the full price list.
    _is_inclusion_q = bool(re.search(
        r"\b(?:is|are|does|do)\b.{0,40}\b(?:include|included|includes|"
        r"comes? with|got)\b", query, re.IGNORECASE
    ))
    if _is_inclusion_q:
        _matches = find_matching_items(query, items)
        if _matches:
            _lines = []
            for it in _matches[:5]:
                _desc = (it.get("description") or "").strip()
                if _desc:
                    _lines.append(f"{it['name']}: {_desc}")
            if _lines:
                _body = " | ".join(_lines)
                if lang == "manglish":
                    return f"Athe! {_body}. Enthelum help venam? \U0001F60A"
                return f"Yes — {_body}. Let me know if you need anything else! \U0001F60A"

    """
    Main entry point.
    Returns formatted reply string (English or Manglish) or None if no match.
    """
    if not items or not query.strip():
        return None

    # Breadth query ("all facials", "wax ethoke und")? List the whole category.
    _cat = category_list_lookup(query, items, lang=lang)
    if _cat:
        return _cat

    matched = find_matching_items(query, items, min_score=min_score)
    if not matched:
        return None
    noun = extract_query_noun(query, matched_items=matched)
    return format_items_reply(matched, lang, query_noun=noun, show_price=True)
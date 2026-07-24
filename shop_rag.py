# """
# shop_rag.py — PDF-first RAG fallback for Chottu Bot  v4.1
# """
# from __future__ import annotations

# import json
# import re
# from pathlib import Path
# from typing import List

# import requests
# import ollama_client

# try:
#     from sentence_transformers import util as _st_util
#     _ST_AVAILABLE = True
# except ImportError:
#     _ST_AVAILABLE = False
#     print("[shop_rag] sentence-transformers not installed — using keyword fallback")

# def _check_ollama() -> bool:
#     return ollama_client.is_up()

# def reset_ollama_cache() -> None:
#     pass

# _TOP_K = 5
# _MIN_CHUNK_SCORE = 0.25

# _STOPWORDS = {
#     "do", "you", "is", "are", "have", "any", "the", "a", "an",
#     "what", "how", "can", "i", "me", "my", "your", "for", "of",
#     "in", "at", "on", "to",
#     "undo", "aano", "undu", "kittumo", "cheyyumo", "enthu", "ethu",
#     "entha", "und", "indo", "undaakumo", "kittumano", "cheyyaamo",
#     "parayuka", "nokam", "venam", "aanu", "alle", "njan", "njangal",
#     "ningal", "ippo", "okke", "sheri",
# }

# _embedder = None
# _embedder_loaded = False


# def _get_embedder():
#     global _embedder, _embedder_loaded
#     if _embedder_loaded:
#         return _embedder
#     if not _ST_AVAILABLE:
#         _embedder_loaded = True
#         return None
#     try:
#         from faq_engine import _get_model
#         _embedder = _get_model()
#         if _embedder is not None:
#             _embedder_loaded = True
#             return _embedder
#     except Exception:
#         pass
#     try:
#         from sentence_transformers import SentenceTransformer
#         _embedder = SentenceTransformer("all-MiniLM-L6-v2")
#         _embedder_loaded = True
#         return _embedder
#     except Exception as e:
#         print(f"[shop_rag] Could not load embedder: {e}")
#         _embedder_loaded = True
#         return None


# def _load_context(slug: str | None) -> dict:
#     # Never fall back to root shop_context.json when slug is given.
#     # Root file belongs to a different shop and causes data bleed.
#     if slug:
#         p = Path(f"shops/{slug}/shop_context.json")
#         if p.exists():
#             try:
#                 return json.loads(p.read_text(encoding="utf-8"))
#             except Exception:
#                 pass
#         return {}
#     p = Path("shop_context.json")
#     if p.exists():
#         try:
#             return json.loads(p.read_text(encoding="utf-8"))
#         except Exception:
#             pass
#     return {}


# def _retrieve_chunks_semantic(question: str, ctx: dict, top_k: int = _TOP_K) -> List[tuple]:
#     chunks = ctx.get("chunks", [])
#     if not chunks:
#         return []
#     embedder = _get_embedder()
#     if embedder is None:
#         return []
#     try:
#         q_emb  = embedder.encode(question, convert_to_tensor=True, normalize_embeddings=True)
#         c_embs = embedder.encode(chunks, convert_to_tensor=True, normalize_embeddings=True, batch_size=64)
#         scores = _st_util.cos_sim(q_emb, c_embs)[0].tolist()
#         ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
#         return ranked[:top_k]
#     except Exception as e:
#         print(f"[shop_rag] Semantic retrieval error: {e}")
#         return []


# def _tokenise(text: str) -> set:
#     words = set(re.sub(r"[^\w\s₹]", " ", text.lower()).split())
#     return words - _STOPWORDS


# def _bigrams(tokens: set) -> set:
#     lst = sorted(tokens)
#     return {frozenset([lst[i], lst[i + 1]]) for i in range(len(lst) - 1)}


# def _retrieve_chunks_keyword(question: str, ctx: dict, top_k: int = _TOP_K) -> List[tuple]:
#     chunks = ctx.get("chunks", [])
#     if not chunks:
#         return []
#     q_tok = _tokenise(question)
#     if not q_tok:
#         return [(c, 0.1) for c in chunks[:top_k]]
#     scored = []
#     for c in chunks:
#         c_tok = _tokenise(c)
#         score = len(q_tok & c_tok) / max(len(q_tok), 1)
#         scored.append((c, score))
#     scored.sort(key=lambda x: x[1], reverse=True)
#     return [pair for pair in scored[:top_k] if pair[1] > 0]


# def _retrieve_chunks(question: str, ctx: dict, top_k: int = _TOP_K) -> List[tuple]:
#     result = _retrieve_chunks_semantic(question, ctx, top_k)
#     if result:
#         return result
#     return _retrieve_chunks_keyword(question, ctx, top_k)


# def _build_soft_fallback(shop_name: str, whatsapp: str, lang: str) -> str:
#     if lang == "manglish":
#         return (
#             f"Athu pattichu sure alla — more details venam enkil "
#             f"njangalude WhatsApp {whatsapp} il contact cheyyuka! "
#             f"Njangal help cheyyaam 😊"
#         )
#     return (
#         f"I'm not sure about that — please WhatsApp us at {whatsapp} "
#         f"and we'll help you right away! 😊"
#     )


# def _build_english_rag_prompt(question: str, shop_name: str, core: str, context_text: str) -> str:
#     return f"""You are a helpful customer support assistant for {shop_name}.
# Reply in simple, friendly English. Answer ONLY from the shop facts below.
# 1-2 sentences maximum. End with "Let me know if you need anything else! 😊"
# If the answer is not in the facts, say you're not sure and give the WhatsApp number.
# NEVER say "we don't have X" unless X is explicitly listed as unavailable in the facts.
# NEVER make up prices, items, or details not in the facts.

# SHOP FACTS
# {core}

# RELEVANT DETAILS
# {context_text}

# Now answer using ONLY the shop facts above:
# Q: {question}
# A:"""


# def _build_manglish_rag_prompt(question: str, shop_name: str, core: str, context_text: str) -> str:
#     return f"""You are a Manglish customer support assistant for {shop_name}.

# WHAT IS MANGLISH
# Manglish = Malayalam words written in English letters, mixed naturally with English.
# Write ONLY in Manglish. NEVER reply in pure English or pure Malayalam script.

# RULES
# - Answer ONLY using the facts below — never invent prices or items.
# - NEVER say "njangalkku X illa" unless facts explicitly say it is unavailable.
# - If not in facts, give the WhatsApp number.
# - 1 to 2 sentences maximum.
# - End every reply with "Enthelum help venam? 😊"
# - NEVER use Malayalam script characters.

# SHOP FACTS
# {core}

# RELEVANT DETAILS
# {context_text}

# WORKED EXAMPLES

# Q: Facial undo?
# A: Athe! Njangalkku Gold Facial, Pearl Facial, Cleanup okke und! Enthelum help venam? 😊

# Q: Chicken items undo?
# A: Athe! Chicken Curry, Fry, Masala, Butter Chicken okke und! Enthelum help venam? 😊

# Q: Ethra mani open aanu?
# A: Njangal Monday-Sunday 9AM-8PM open aanu! Enthelum help venam? 😊

# Q: GPay cheyyaamo?
# A: Yes! GPay, PhonePe, Cash, Cards — ella payment modes um accept cheyyunnu! Enthelum help venam? 😊

# Now answer in Manglish using ONLY the shop facts above.
# If you cannot find the answer, DO NOT say the item doesn't exist — give the WhatsApp number instead.

# Customer: {question}
# Assistant:"""


# def rag_answer(question: str, slug: str | None, lang: str = "english") -> str | None:
#     ctx = _load_context(slug)
#     if not ctx:
#         return None

#     try:
#         from nlp import is_manglish as _is_ml
#         if _is_ml(question):
#             lang = "manglish"
#     except Exception:
#         pass

#     scored_chunks = _retrieve_chunks(question, ctx, top_k=_TOP_K)
#     shop_name = ctx.get("shop_name", "this shop")
#     whatsapp  = ctx.get("phone", "")

#     if not scored_chunks or scored_chunks[0][1] < _MIN_CHUNK_SCORE:
#         return _build_soft_fallback(shop_name, whatsapp, lang)

#     payment_str = ", ".join(ctx.get("payment", [])) if ctx.get("payment") else ""

#     core = "\n".join(filter(None, [
#         f"Shop name: {shop_name}",
#         f"Location: {ctx['location']}"      if ctx.get("location")   else "",
#         f"Phone/WhatsApp: {ctx['phone']}"    if ctx.get("phone")      else "",
#         f"Hours: {ctx['hours']}"             if ctx.get("hours")      else "",
#         f"Payment: {payment_str}"            if payment_str           else "",
#         f"Offer: {ctx['offer_code']} — {ctx['offer_desc']}"
#             if ctx.get("offer_code")         else "",
#         f"Delivery: {ctx['delivery']}"       if ctx.get("delivery")   else "",
#         f"Speciality: {ctx['speciality']}"   if ctx.get("speciality") else "",
#     ]))

#     good_chunks  = [c for c, s in scored_chunks if s >= _MIN_CHUNK_SCORE]
#     context_text = "\n".join(f"- {c}" for c in good_chunks) if good_chunks else \
#                    "\n".join(f"- {c}" for c, _ in scored_chunks)

#     if lang == "manglish":
#         prompt      = _build_manglish_rag_prompt(question, shop_name, core, context_text)
#         temperature = 0.15  # lower = less garbled Manglish from the small model
#     else:
#         prompt      = _build_english_rag_prompt(question, shop_name, core, context_text)
#         temperature = 0.15

#     reply, ok = ollama_client.generate(
#         prompt,
#         temperature=temperature,
#         num_predict=160,
#         lang=lang,
#     )

#     if not ok:
#         return _build_soft_fallback(shop_name, whatsapp, lang)

#     _PREAMBLE = re.compile(
#         r"^(?:here\s+is|here'?s|below\s+is|sure[!,]?\s*|answer\s*:|assistant\s*:)"
#         r"[^\n]*\n+",
#         re.IGNORECASE,
#     )
#     reply = _PREAMBLE.sub("", reply).strip()
#     if reply.lower().startswith("a:"):
#         reply = reply[2:].lstrip()

#     _DENIAL_RE = re.compile(
#         r"\b(don'?t have|do not have|njangalkku .{0,20} illa|sorry.{0,30}don'?t)\b",
#         re.IGNORECASE,
#     )
#     if _DENIAL_RE.search(reply) and good_chunks:
#         return _build_soft_fallback(shop_name, whatsapp, lang)

#     return reply if reply else _build_soft_fallback(shop_name, whatsapp, lang)


# def build_shop_context(shop_info: dict, full_text: str) -> dict:
#     chunks: list = []

#     for item in shop_info.get("shop_items", []):
#         name      = item.get("name", "").strip()
#         price     = item.get("price", "")
#         price_min = item.get("price_min", "")
#         price_max = item.get("price_max", "")
#         category  = item.get("category", "")
#         desc      = item.get("description", "")
#         if not name:
#             continue
#         price_str = (
#             f"₹{price_min}–₹{price_max}" if price_min and price_max
#             else f"₹{price}" if price else ""
#         )
#         parts = [name]
#         if category and category.lower() not in ("general", ""):
#             parts.append(f"[{category}]")
#         if price_str:
#             parts.append(f"— {price_str}")
#         if desc:
#             parts.append(f"({desc})")
#         chunks.append(" ".join(parts))

#     for para in full_text.split("\n\n"):
#         para = para.strip()
#         if not para:
#             continue
#         if 25 < len(para) <= 200:
#             chunks.append(para)
#         elif len(para) > 200:
#             for sent in re.split(r"(?<=[.!?])\s+", para):
#                 sent = sent.strip()
#                 if 20 < len(sent) < 300:
#                     chunks.append(sent)

#     for table in shop_info.get("tables", []):
#         for row in table:
#             cells = [str(c).strip() for c in row if c and str(c).strip()]
#             if not cells:
#                 continue
#             if len(cells) == 2:
#                 chunks.append(f"{cells[0]} — {cells[1]}")
#             elif len(cells) == 3:
#                 chunks.append(f"{cells[0]} — {cells[1]} / {cells[2]}")
#             else:
#                 chunks.append(" | ".join(cells))

#     # Promotional/programme facts that pdf.py correctly excluded
#     # from shop_items (loyalty cards, offer codes, happy-hour
#     # deals, combo packs, etc.) but ARE still real shop facts.
#     # Without this, they were captured by pdf.py but never
#     # reached anywhere RAG could retrieve them -- so a live
#     # question like "loyalty card undo" had zero grounding and
#     # fell back to whatever embedding was closest (wrong answer).
#     # Works identically for every shop type and every PDF since
#     # it just reads whatever extra_facts THIS shop's extraction
#     # produced -- no shop-specific code.
#     for fact in shop_info.get("extra_facts", []):
#         label  = str(fact.get("label", "")).strip()
#         detail = str(fact.get("detail", "")).strip()
#         if label and detail:
#             chunks.append(f"{label} — {detail}")

#     seen: set = set()
#     unique: list = []
#     for c in chunks:
#         key = c.strip().lower()[:80]
#         if key not in seen:
#             seen.add(key)
#             unique.append(c.strip())

#     d = shop_info.get("delivery", {})
#     d_areas = d.get("areas", "")
#     d_free  = d.get("free_above", "")
#     if d_areas and d_areas != "N/A":
#         delivery_line = f"Delivery: available in {d_areas}"
#         if d_free and d_free != "N/A":
#             delivery_line += f", free above {d_free}"
#         unique.insert(0, delivery_line)

#     offer = shop_info.get("first_offer", {})
#     if offer.get("code"):
#         unique.insert(0, f"Offer: use code {offer['code']} — {offer.get('description', '')}")

#     return {
#         "shop_name":  shop_info.get("shop_name", ""),
#         "shop_type":  shop_info.get("shop_type", "general"),
#         "location":   shop_info.get("location", ""),
#         "phone":      shop_info.get("phone", shop_info.get("whatsapp", "")),
#         "hours":      shop_info.get("hours_weekdays", ""),
#         "offer_code": shop_info.get("offer_code", offer.get("code", "")),
#         "offer_desc": shop_info.get("offer_desc", offer.get("description", "")),
#         "payment":    shop_info.get("payment", []),
#         "delivery":   f"{d_areas}, free above {d_free}" if d_areas and d_areas != "N/A" else "",
#         "speciality": shop_info.get("speciality", ""),
#         "chunks":     unique,
#     }













"""
shop_rag.py — PDF-first RAG fallback for Chottu Bot  v4.1
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

import requests
import ollama_client

try:
    from sentence_transformers import util as _st_util
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    print("[shop_rag] sentence-transformers not installed — using keyword fallback")

def _check_ollama() -> bool:
    return ollama_client.is_up()

def reset_ollama_cache() -> None:
    pass

_TOP_K = 5
_MIN_CHUNK_SCORE = 0.25

_STOPWORDS = {
    "do", "you", "is", "are", "have", "any", "the", "a", "an",
    "what", "how", "can", "i", "me", "my", "your", "for", "of",
    "in", "at", "on", "to",
    "undo", "aano", "undu", "kittumo", "cheyyumo", "enthu", "ethu",
    "entha", "und", "indo", "undaakumo", "kittumano", "cheyyaamo",
    "parayuka", "nokam", "venam", "aanu", "alle", "njan", "njangal",
    "ningal", "ippo", "okke", "sheri",
}

_embedder = None
_embedder_loaded = False


def _get_embedder():
    global _embedder, _embedder_loaded
    if _embedder_loaded:
        return _embedder
    if not _ST_AVAILABLE:
        _embedder_loaded = True
        return None
    try:
        from faq_engine import _get_model
        _embedder = _get_model()
        if _embedder is not None:
            _embedder_loaded = True
            return _embedder
    except Exception:
        pass
    try:
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        _embedder_loaded = True
        return _embedder
    except Exception as e:
        print(f"[shop_rag] Could not load embedder: {e}")
        _embedder_loaded = True
        return None


def _load_context(slug: str | None) -> dict:
    # Never fall back to root shop_context.json when slug is given.
    # Root file belongs to a different shop and causes data bleed.
    if slug:
        p = Path(f"shops/{slug}/shop_context.json")
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}
    p = Path("shop_context.json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _retrieve_chunks_semantic(question: str, ctx: dict, top_k: int = _TOP_K) -> List[tuple]:
    chunks = ctx.get("chunks", [])
    if not chunks:
        return []
    embedder = _get_embedder()
    if embedder is None:
        return []
    try:
        q_emb  = embedder.encode(question, convert_to_tensor=True, normalize_embeddings=True)
        c_embs = embedder.encode(chunks, convert_to_tensor=True, normalize_embeddings=True, batch_size=64)
        scores = _st_util.cos_sim(q_emb, c_embs)[0].tolist()
        ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
    except Exception as e:
        print(f"[shop_rag] Semantic retrieval error: {e}")
        return []


def _tokenise(text: str) -> set:
    words = set(re.sub(r"[^\w\s₹]", " ", text.lower()).split())
    return words - _STOPWORDS


def _bigrams(tokens: set) -> set:
    lst = sorted(tokens)
    return {frozenset([lst[i], lst[i + 1]]) for i in range(len(lst) - 1)}


def _retrieve_chunks_keyword(question: str, ctx: dict, top_k: int = _TOP_K) -> List[tuple]:
    chunks = ctx.get("chunks", [])
    if not chunks:
        return []
    q_tok = _tokenise(question)
    if not q_tok:
        return [(c, 0.1) for c in chunks[:top_k]]
    scored = []
    for c in chunks:
        c_tok = _tokenise(c)
        score = len(q_tok & c_tok) / max(len(q_tok), 1)
        scored.append((c, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [pair for pair in scored[:top_k] if pair[1] > 0]


def _retrieve_chunks(question: str, ctx: dict, top_k: int = _TOP_K) -> List[tuple]:
    result = _retrieve_chunks_semantic(question, ctx, top_k)
    if result:
        return result
    return _retrieve_chunks_keyword(question, ctx, top_k)


def _build_soft_fallback(shop_name: str, whatsapp: str, lang: str) -> str:
    if lang == "manglish":
        return (
            f"Athu pattichu sure alla — more details venam enkil "
            f"njangalude WhatsApp {whatsapp} il contact cheyyuka! "
            f"Njangal help cheyyaam 😊"
        )
    return (
        f"I'm not sure about that — please WhatsApp us at {whatsapp} "
        f"and we'll help you right away! 😊"
    )


def _build_english_rag_prompt(question: str, shop_name: str, core: str, context_text: str) -> str:
    return f"""You are a helpful customer support assistant for {shop_name}.
Reply in simple, friendly English. Answer ONLY from the shop facts below.
1-2 sentences maximum. End with "Let me know if you need anything else! 😊"
If the answer is not in the facts, say you're not sure and give the WhatsApp number.
NEVER say "we don't have X" unless X is explicitly listed as unavailable in the facts.
NEVER make up prices, items, or details not in the facts.

SHOP FACTS
{core}

RELEVANT DETAILS
{context_text}

Now answer using ONLY the shop facts above:
Q: {question}
A:"""


def _build_manglish_rag_prompt(question: str, shop_name: str, core: str, context_text: str) -> str:
    return f"""You are a Manglish customer support assistant for {shop_name}.

WHAT IS MANGLISH
Manglish = Malayalam words written in English letters, mixed naturally with English.
Write ONLY in Manglish. NEVER reply in pure English or pure Malayalam script.

RULES
- Answer ONLY using the facts below — never invent prices or items.
- NEVER say "njangalkku X illa" unless facts explicitly say it is unavailable.
- If not in facts, give the WhatsApp number.
- 1 to 2 sentences maximum.
- End every reply with "Enthelum help venam? 😊"
- NEVER use Malayalam script characters.

SHOP FACTS
{core}

RELEVANT DETAILS
{context_text}

STYLE EXAMPLES (format ONLY — the item names below are FAKE placeholders
from a DIFFERENT shop; NEVER copy any item, price, or name from these
examples into your answer; use ONLY items from the SHOP FACTS above)

Q: <item> undo?
A: Athe! Njangalkku <item from facts>, <item from facts> okke und! Enthelum help venam? 😊

Q: Ethra mani open aanu?
A: Njangal <hours from facts> open aanu! Enthelum help venam? 😊

Q: GPay cheyyaamo?
A: Yes! <payment modes from facts> — okke accept cheyyunnu! Enthelum help venam? 😊

Now answer in Manglish using ONLY the shop facts above.
If you cannot find the answer, DO NOT say the item doesn't exist — give the WhatsApp number instead.

Customer: {question}
Assistant:"""


def retrieve_shared_context(question: str, slug: str | None, top_k: int = _TOP_K):
    """Retrieve chunks ONCE for a given question/slug.

    Intended for callers (e.g. populate_faq_from_pdf.py) that generate BOTH
    an English and a Manglish answer for the SAME underlying FAQ. Passing the
    result to both rag_answer() calls via `shared=` ensures both language
    versions are grounded on the identical retrieved facts, instead of each
    language independently re-retrieving off its own (differently worded)
    question text -- which could otherwise pull a different chunk per
    language and cause the two saved answers to state different prices/
    details for what is supposed to be the same fact.

    Returns (scored_chunks, ctx) or (None, None) if there's no context.
    """
    ctx = _load_context(slug)
    if not ctx:
        return None, None
    return _retrieve_chunks(question, ctx, top_k=top_k), ctx


def rag_answer(question: str, slug: str | None, lang: str = "english",
                shared: tuple | None = None) -> str | None:
    if shared is not None:
        scored_chunks, ctx = shared
        if not ctx:
            return None
    else:
        ctx = _load_context(slug)
        if not ctx:
            return None
        scored_chunks = _retrieve_chunks(question, ctx, top_k=_TOP_K)

    try:
        from nlp import is_manglish as _is_ml
        if _is_ml(question):
            lang = "manglish"
    except Exception:
        pass

    shop_name = ctx.get("shop_name", "this shop")
    whatsapp  = ctx.get("phone", "")

    if not scored_chunks or scored_chunks[0][1] < _MIN_CHUNK_SCORE:
        return _build_soft_fallback(shop_name, whatsapp, lang)

    payment_str = ", ".join(ctx.get("payment", [])) if ctx.get("payment") else ""

    core = "\n".join(filter(None, [
        f"Shop name: {shop_name}",
        f"Location: {ctx['location']}"      if ctx.get("location")   else "",
        f"Phone/WhatsApp: {ctx['phone']}"    if ctx.get("phone")      else "",
        f"Hours: {ctx['hours']}"             if ctx.get("hours")      else "",
        f"Payment: {payment_str}"            if payment_str           else "",
        f"Offer: {ctx['offer_code']} — {ctx['offer_desc']}"
            if ctx.get("offer_code")         else "",
        f"Delivery: {ctx['delivery']}"       if ctx.get("delivery")   else "",
        f"Speciality: {ctx['speciality']}"   if ctx.get("speciality") else "",
    ]))

    good_chunks  = [c for c, s in scored_chunks if s >= _MIN_CHUNK_SCORE]
    context_text = "\n".join(f"- {c}" for c in good_chunks) if good_chunks else \
                   "\n".join(f"- {c}" for c, _ in scored_chunks)

    if lang == "manglish":
        prompt      = _build_manglish_rag_prompt(question, shop_name, core, context_text)
        temperature = 0.15  # lower = less garbled Manglish from the small model
    else:
        prompt      = _build_english_rag_prompt(question, shop_name, core, context_text)
        temperature = 0.15

    reply, ok = ollama_client.generate(
        prompt,
        temperature=temperature,
        num_predict=160,
        lang=lang,
    )

    if not ok:
        return _build_soft_fallback(shop_name, whatsapp, lang)

    _PREAMBLE = re.compile(
        r"^(?:here\s+is|here'?s|below\s+is|sure[!,]?\s*|answer\s*:|assistant\s*:)"
        r"[^\n]*\n+",
        re.IGNORECASE,
    )
    reply = _PREAMBLE.sub("", reply).strip()
    if reply.lower().startswith("a:"):
        reply = reply[2:].lstrip()

    _DENIAL_RE = re.compile(
        r"\b(don'?t have|do not have|njangalkku .{0,20} illa|sorry.{0,30}don'?t)\b",
        re.IGNORECASE,
    )
    if _DENIAL_RE.search(reply) and good_chunks:
        return _build_soft_fallback(shop_name, whatsapp, lang)

    return reply if reply else _build_soft_fallback(shop_name, whatsapp, lang)


def build_shop_context(shop_info: dict, full_text: str) -> dict:
    chunks: list = []

    for item in shop_info.get("shop_items", []):
        name      = item.get("name", "").strip()
        price     = item.get("price", "")
        price_min = item.get("price_min", "")
        price_max = item.get("price_max", "")
        category  = item.get("category", "")
        desc      = item.get("description", "")
        if not name:
            continue
        price_str = (
            f"₹{price_min}–₹{price_max}" if price_min and price_max
            else f"₹{price}" if price else ""
        )
        parts = [name]
        if category and category.lower() not in ("general", ""):
            parts.append(f"[{category}]")
        if price_str:
            parts.append(f"— {price_str}")
        if desc:
            parts.append(f"({desc})")
        chunks.append(" ".join(parts))

    for para in full_text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if 25 < len(para) <= 200:
            chunks.append(para)
        elif len(para) > 200:
            for sent in re.split(r"(?<=[.!?])\s+", para):
                sent = sent.strip()
                if 20 < len(sent) < 300:
                    chunks.append(sent)

    for table in shop_info.get("tables", []):
        for row in table:
            cells = [str(c).strip() for c in row if c and str(c).strip()]
            if not cells:
                continue
            if len(cells) == 2:
                chunks.append(f"{cells[0]} — {cells[1]}")
            elif len(cells) == 3:
                chunks.append(f"{cells[0]} — {cells[1]} / {cells[2]}")
            else:
                chunks.append(" | ".join(cells))

    # Promotional/programme facts that pdf.py correctly excluded
    # from shop_items (loyalty cards, offer codes, happy-hour
    # deals, combo packs, etc.) but ARE still real shop facts.
    # Without this, they were captured by pdf.py but never
    # reached anywhere RAG could retrieve them -- so a live
    # question like "loyalty card undo" had zero grounding and
    # fell back to whatever embedding was closest (wrong answer).
    # Works identically for every shop type and every PDF since
    # it just reads whatever extra_facts THIS shop's extraction
    # produced -- no shop-specific code.
    for fact in shop_info.get("extra_facts", []):
        label  = str(fact.get("label", "")).strip()
        detail = str(fact.get("detail", "")).strip()
        if label and detail:
            chunks.append(f"{label} — {detail}")

    seen: set = set()
    unique: list = []
    for c in chunks:
        key = c.strip().lower()[:80]
        if key not in seen:
            seen.add(key)
            unique.append(c.strip())

    d = shop_info.get("delivery", {})
    d_areas = d.get("areas", "")
    d_free  = d.get("free_above", "")
    if d_areas and d_areas != "N/A":
        delivery_line = f"Delivery: available in {d_areas}"
        if d_free and d_free != "N/A":
            delivery_line += f", free above {d_free}"
        unique.insert(0, delivery_line)

    offer = shop_info.get("first_offer", {})
    if offer.get("code"):
        unique.insert(0, f"Offer: use code {offer['code']} — {offer.get('description', '')}")

    return {
        "shop_name":  shop_info.get("shop_name", ""),
        "shop_type":  shop_info.get("shop_type", "general"),
        "location":   shop_info.get("location", ""),
        "phone":      shop_info.get("phone", shop_info.get("whatsapp", "")),
        "hours":      shop_info.get("hours_weekdays", ""),
        "offer_code": shop_info.get("offer_code", offer.get("code", "")),
        "offer_desc": shop_info.get("offer_desc", offer.get("description", "")),
        "payment":    shop_info.get("payment", []),
        "delivery":   f"{d_areas}, free above {d_free}" if d_areas and d_areas != "N/A" else "",
        "speciality": shop_info.get("speciality", ""),
        "chunks":     unique,
    }
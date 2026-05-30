"""
shop_rag.py — RAG fallback for Chottu Bot  v1.0
=================================================
Answers questions from shop_context.json when FAQ matching fails.
shop_context.json is written by pdf.py after PDF extraction.

Place in: AI_AGENT/shop_rag.py  (root, same level as chat.py)

How it fits in chat.py pipeline:
    FAQ match found  →  return FAQ answer  (existing)
    FAQ miss         →  try rag_answer()   (NEW — this file)
    RAG miss         →  free Ollama call   (existing fallback)
"""

from __future__ import annotations
import json
from pathlib import Path
import requests

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma3:4b"


# ─────────────────────────────────────────────────────────────
#  Load shop_context.json for a slug
# ─────────────────────────────────────────────────────────────

def _load_context(slug: str) -> dict:
    p = Path(f"shops/{slug}/shop_context.json")
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ─────────────────────────────────────────────────────────────
#  Simple keyword retrieval from context chunks
#  Upgrade to sentence-transformer cosine later if needed
# ─────────────────────────────────────────────────────────────

def _retrieve_chunks(question: str, ctx: dict, top_k: int = 3) -> list[str]:
    chunks = ctx.get("chunks", [])
    if not chunks:
        return []
    q_words = set(question.lower().split())
    # Remove stopwords that add noise
    stopwords = {"do","you","is","are","have","any","the","a","an",
                 "what","how","can","i","me","my","your","for","of",
                 "in","at","on","to","undo","aano","undo","undu","kittumo",
                 "cheyyumo","enthu","ethu","entha"}
    q_words -= stopwords
    if not q_words:
        return chunks[:top_k]  # no meaningful words, return first chunks

    scored = []
    for chunk in chunks:
        chunk_words = set(chunk.lower().split())
        overlap = len(q_words & chunk_words)
        scored.append((overlap, chunk))
    scored.sort(reverse=True)
    return [c for score, c in scored[:top_k] if score > 0]


# ─────────────────────────────────────────────────────────────
#  Main RAG function — called from chat.py pipeline
# ─────────────────────────────────────────────────────────────

def rag_answer(question: str, slug: str, lang: str = "english") -> str | None:
    """
    Try to answer question from extracted shop context.
    Returns None if no relevant context found → caller falls back to free Ollama.

    Args:
        question : customer message text
        slug     : shop slug (e.g. "hey-foodie")
        lang     : "english" or "manglish" — controls reply language

    Returns:
        str answer grounded in shop data, or None if no context matches
    """
    ctx = _load_context(slug)
    if not ctx:
        return None

    chunks = _retrieve_chunks(question, ctx)
    if not chunks:
        return None

    shop_name = ctx.get("shop_name", "this shop")

    lang_instruction = (
        "Reply in Manglish — Malayalam words written in English script, "
        "mixed naturally with English. Example style: "
        "'Athe, njangalku delivery undu. WhatsApp cheyyuka.'"
    ) if lang == "manglish" else (
        "Reply in simple, friendly English."
    )

    # Always inject core facts so Ollama doesn't hallucinate basics
    core = "\n".join(filter(None, [
        f"Shop name: {shop_name}",
        f"Location: {ctx.get('location', '')}" if ctx.get("location") else "",
        f"Phone/WhatsApp: {ctx.get('phone', '')}" if ctx.get("phone") else "",
        f"Hours: {ctx.get('hours', '')}" if ctx.get("hours") else "",
    ]))

    context_text = "\n".join(f"- {c}" for c in chunks)

    prompt = f"""You are a helpful customer support chatbot for {shop_name}.
{lang_instruction}
Answer ONLY based on the facts provided. Keep it short — 1 to 2 sentences.
If the answer is not in the facts, say you are not sure and suggest the customer call or WhatsApp the shop.
Do NOT make up any details.

Core shop facts:
{core}

Relevant details:
{context_text}

Customer question: {question}
Answer:"""

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model":   OLLAMA_MODEL,
            "prompt":  prompt,
            "stream":  False,
            "options": {"temperature": 0.1, "num_predict": 120},
        }, timeout=30)
        resp.raise_for_status()
        reply = resp.json().get("response", "").strip()
        return reply if reply else None
    except Exception as e:
        print(f"[shop_rag] Ollama error: {e}")
        return None


# ─────────────────────────────────────────────────────────────
#  Context builder — called from pdf.py after extraction
# ─────────────────────────────────────────────────────────────

def build_shop_context(shop_info: dict, full_text: str) -> dict:
    """
    Build shop_context.json from pdf.py extraction output.
    Call this in api.py /admin/extract-pdf after build_shop_info().

    Args:
        shop_info : dict from build_shop_info() in pdf.py
        full_text : raw extracted PDF text

    Returns:
        context dict — save this as shops/{slug}/shop_context.json
    """
    chunks: list[str] = []

    # Items as chunks — all items, no cap (price/availability queries need full catalogue)
    for item in shop_info.get("shop_items", []):
        name      = item.get("name", "").strip()
        price     = item.get("price", "")
        price_min = item.get("price_min", "")
        price_max = item.get("price_max", "")
        category  = item.get("category", "")
        desc      = item.get("description", "")
        if not name:
            continue
        if price_min and price_max:
            price_str = f"₹{price_min}–₹{price_max}"
        elif price:
            price_str = f"₹{price}"
        else:
            price_str = ""
        parts = [name]
        if category and category.lower() not in ("general", ""):
            parts.append(f"[{category}]")
        if price_str:
            parts.append(f"— {price_str}")
        if desc:
            parts.append(f"({desc})")
        chunks.append(" ".join(parts))

    # Paragraphs from raw text (loyalty, parking, events, specials, policies)
    for para in full_text.split("\n\n"):
        para = para.strip()
        if 25 < len(para) < 500:
            chunks.append(para)

    # Table rows that pdf.py extracted
    for table in shop_info.get("tables", []):
        for row in table:
            row_text = " | ".join(str(c) for c in row if c)
            if row_text.strip():
                chunks.append(row_text)

    # Deduplicate while preserving order
    seen: set = set()
    unique_chunks: list[str] = []
    for c in chunks:
        key = c.strip().lower()[:80]
        if key not in seen:
            seen.add(key)
            unique_chunks.append(c.strip())

    return {
        "shop_name":  shop_info.get("shop_name", ""),
        "shop_type":  shop_info.get("shop_type", "general"),
        "location":   shop_info.get("location", ""),
        "phone":      shop_info.get("phone", shop_info.get("whatsapp", "")),
        "hours":      shop_info.get("hours_weekdays", ""),
        "offer_code": shop_info.get("offer_code", ""),
        "offer_desc": shop_info.get("offer_desc", ""),
        "payment":    shop_info.get("payment", []),
        "speciality": shop_info.get("speciality", ""),
        "chunks":     unique_chunks,   # no arbitrary cap — full catalogue kept
    }
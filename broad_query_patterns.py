"""
broad_query_patterns.py — single source of truth for "show me everything"
style queries (services enthoke, what medicines do you have, full menu, etc).

Previously duplicated — and drifting out of sync — across:
  - chat.py         (_BROAD_SVC_CHAT)
  - faq_engine.py   (_BROAD_SVC, local var inside match_faq())
  - item_matcher.py (_BROAD_QUERY_PATTERNS)

That drift was the root cause of the "medicines enthoke und" mismatch:
item_matcher.py's list never had a medicines-shaped phrase, so the query
fell through into a narrow FAQ instead of being recognised as a broad
catalog ask. Import is_broad_query() everywhere instead of hardcoding a
local copy or a raw substring-list check.

GENERALIZATION: the literal BROAD_QUERY_PATTERNS list below only covers
nouns someone thought to enumerate ("medicines", "services") -- a jewellery
shop customer asking "jewellery enthoke undo" or a saree shop customer
asking "sarees ethoke und" would silently miss every entry here, because
Manglish expresses "show me all of category X" as "<noun> + enthoke-family
particle", and that structure doesn't have a noun-free phrasing the way
English "what do you have" does. is_broad_query() below detects that
NOUN+PARTICLE pattern generically via regex first (works for any noun, any
shop type, zero maintenance), and only falls back to the literal list for
English phrasings and any Manglish wording the regex doesn't cover.
"""

import re

BROAD_QUERY_PATTERNS = [
    # Manglish — services
    "services enthoke", "enthokke service", "enthokee service",
    "enthoke service", "enthoke und service", "enthoke anu service",
    "enthoke service available", "services ivide", "services undo",
    "services und", "enthellam services", "enthellam und",

    # Manglish — generic catalog nouns (medicines, items, etc.)
    "medicines enthoke", "enthoke medicines", "medicine list",
    "medicines undo", "medicines und", "medicines ivide",
    # "ethoke" (missing the 'n') and singular "medicine" are common real
    # spelling variants — confirmed slipping through in production logs
    # ("medicine ethoke und" fell through to generic RAG instead of the
    # broad catalog path) despite "medicines enthoke" being covered above.
    "medicine enthoke", "medicine ethoke", "medicines ethoke",
    "ethoke medicine", "ethoke medicines",

    # English — services
    "all services", "full service", "service details",
    "what services", "which services", "what do you offer",
    "what all services", "list of services", "services available",
    "service list", "all service", "what services do you",

    # English — generic catalog / menu
    "full menu", "menu list", "full details", "show me everything",
    "what do you have", "what all do you have", "full list",
    "everything you have", "what medicines", "all medicines",
    "medicines available",
]

# Generic Manglish "<any noun> + breadth particle" pattern -- e.g. "jewellery
# enthoke undo", "sarees ethoke und", "dishes enthokke available", in either
# noun-first or particle-first order. Deliberately does NOT include bare
# "okke" (means "all/okay" far more broadly in casual Manglish -- e.g. "okke
# sheriyano" = "is everything fine" -- and would false-positive on normal
# small talk that has nothing to do with a catalog request).
_BROAD_NOUN_PARTICLE_RE = re.compile(
    r'\b\w+\s+(?:enthoke|ethoke|enthokke|ethokke)\b'
    r'|\b(?:enthoke|ethoke|enthokke|ethokke)\s+\w+\b',
    re.IGNORECASE,
)


def is_broad_query(text: str) -> bool:
    """True if this looks like a 'show me everything in this category'
    request, for ANY shop type -- not just the specific nouns enumerated in
    BROAD_QUERY_PATTERNS above. Checks the generic noun+particle regex
    first (covers new shop types with zero maintenance), then falls back
    to the literal phrase list for English wording and any Manglish
    phrasing the regex doesn't happen to cover."""
    if not text:
        return False
    q = text.lower()
    if _BROAD_NOUN_PARTICLE_RE.search(q):
        return True
    return any(p in q for p in BROAD_QUERY_PATTERNS)
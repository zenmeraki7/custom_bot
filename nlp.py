
"""
nlp.py — Language detection, sentiment analysis, text utilities
===============================================================
Exported symbols used by faq_engine.py and chat.py:
  - is_manglish(text) → bool
  - is_english_text(text) → bool
  - detect_sentiment(text) → dict
  - lexicon_check(text) → str | None
  - normalize(text) → str
  - tokenize(text) → list[str]
  - expand_synonyms(tokens) → list[str]
  - fuzzy_match(a, b) → float
  - f1_score(query_tokens, faq_question) → float
  - embedder          — SentenceTransformer instance or None
  - sentiment_clf     — HuggingFace pipeline or None
  - ST_DEVICE         — "cuda" | "cpu"
  - SENT_DEVICE       — 0 | -1
  - device_name       — human-readable string
  - STOPWORDS, LEXICON, MANGLISH_SIGNALS, LANGUAGE_SWITCH_RE
  - SENTIMENT_LABELS, LABEL_MAP, SENTIMENT_THRESHOLD

v5.3 fixes:
  - MANGLISH_SIGNALS: added nthanu, paripadi, niyamam, sugamano variants
  - _MANGLISH_NORM: paripadi → "return policy" (not just "policy")
                    nthanu → "enthu" (already there, now also in SIGNALS)
  - SYNONYM_MAP: deduplicated (was full of triple-duplicate entries in v5.2)
                 added policy/paripadi/niyamam cross-links
                 added number → contact/phone/whatsapp
  - _PARTICLE_NO_EXPAND: removed "enthu"/"engane"/"evide" — these have
    real synonym expansions now and should expand
  - normalize(): applies _MANGLISH_NORM word-by-word BEFORE returning
"""

import re
import torch

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

SENTIMENT_THRESHOLD = 0.45   # XLM-R minimum confidence; below → "neutral"
VRAM_SAFE_MODE      = True

# ══════════════════════════════════════════════════════════════════════════════
#  DEVICE SETUP
# ══════════════════════════════════════════════════════════════════════════════

if torch.cuda.is_available():
    _gpu_name   = torch.cuda.get_device_name(0)
    _vram_mb    = torch.cuda.get_device_properties(0).total_memory // 1024 ** 2
    ST_DEVICE   = "cpu"
    SENT_DEVICE = -1 if (_vram_mb < 7000 or VRAM_SAFE_MODE) else 0
    device_name = f"GPU ({_gpu_name}, {_vram_mb} MiB)"
else:
    ST_DEVICE   = "cpu"
    SENT_DEVICE = -1
    _vram_mb    = 0
    device_name = "CPU"

print(f"[nlp] Device: {device_name}")

# ══════════════════════════════════════════════════════════════════════════════
#  SENTIMENT CONFIG
# ══════════════════════════════════════════════════════════════════════════════

SENTIMENT_LABELS = [
    "negative complaint",
    "positive feedback",
    "neutral query",
    "sarcastic frustrated",
    "urgent request",
]

LABEL_MAP = {
    "negative complaint":   "negative",
    "positive feedback":    "positive",
    "neutral query":        "neutral",
    "sarcastic frustrated": "sarcastic",
    "urgent request":       "urgent",
}

LEXICON: dict[str, list[str]] = {
    "negative": [
        "paisa waste", "case kodukum", "fraud", "cheating",
        "oru reply illa", "mosham", "sheriyalla", "thettanu",
        "refund tharilla", "kittiyilla", "late ayi",
        "ithra kooduthal", "vila kooduthal",
        "pathetic", "worst", "horrible", "terrible",
        "useless", "waste of money", "very bad", "not good",
        "disappointed", "no response", "scam", "rip off",
        "damaged", "defective", "broken", "torn", "missing",
        "wrong product", "not received", "never arrived",
        "compliant"
        "complaining"
        "complient"
        "complint"
        "compalint"
        "complent"
        "i want to complain"
        "want to compliant"
        "want to complain"
        "will compliant"
        "will complain"
        "very bad service"
        "bad service"
        "service mosham"
        "mosham service"
        "service bad"
        "not happy with"
        "not satisfied"
        "cheating shop"
        "fraud shop",
        "compliant"
        "complaining"
        "complient"
        "complint"
        "compalint"
        "complent"
        "i want to complain"
        "want to compliant"
        "want to complain"
        "will compliant"
        "will complain"
        "very bad service"
        "bad service"
        "service mosham"
        "mosham service"
        "service bad"
        "not happy with"
        "not satisfied"
        "cheating shop"
        "fraud shop",
        "compliant"
        "complaining"
        "complient"
        "complint"
        "compalint"
        "complent"
        "i want to complain"
        "want to compliant"
        "want to complain"
        "will compliant"
        "will complain"
        "very bad service"
        "bad service"
        "service mosham"
        "mosham service"
        "service bad"
        "not happy with"
        "not satisfied"
        "cheating shop"
        "fraud shop",
    ],
    "positive": [
        "nannayirunnu", "adipoli", "kollam",
        "njan recommend", "super aayirunnu", "mast",
        "superb", "excellent", "happy", "satisfied",
        "best", "loved it", "amazing", "fantastic",
        "great service", "very good", "awesome", "perfect",
        "thank you so much", "highly recommend",
    ],
    "sarcastic": [
        "ingane service alle", "ithu service ano",
        "ingane delivery aano", "ingane quality aano",
        "adipoli service alle", "superb service alle",
        "kollam service aanu alle",
        "oh great", "oh wonderful", "yeah right",
        "sure it is", "obviously not", "wow so helpful",
    ],
    "urgent": [
        "ippo venda", "ithu ippo",
        "urgent", "asap", "emergency", "right now",
        "immediately", "jaldi", "very urgent",
        "need help now", "help me now",
        "please fast", "hurry", "can't wait",
    ],
}

# ══════════════════════════════════════════════════════════════════════════════
#  LANGUAGE DETECTION
# ══════════════════════════════════════════════════════════════════════════════

LANGUAGE_SWITCH_RE = re.compile(
    r"\b(malayalam|manglish|ml|keralam|malyalam)\b",
    re.IGNORECASE,
)

MANGLISH_SIGNALS = [
    # Core particles
    "aanu", "alle", "aano", "ano", "undo", "undu",
    "cheyyam", "cheyyano", "cheythu", "cheyyunno", "cheyyuka",
    "cheyynam", "nokam", "nokkanam", "kittum", "kittiyilla",
    "njan", "njangal", "ningal", "avarkku",
    "engane", "enthu", "ethra", "evide", "ippo", "okke",
    # Who / there -- missing entirely, caused "avduthe pharmacist aaranu?"
    # to be misdetected as English
    "aaranu", "aaru", "avide", "avde", "avduthe", "aviduthe",
    "polum", "munpe", "athukond", "allenkil", "undenkil",
    "kollam", "mosham", "adipoli", "sheri", "sheriyalla",
    "kooduthal", "venda", "venam", "veno",
    "aayirunnu", "kazhinju",
    "pattumo", "patumo", "tharaamo",
    "kodukkum", "kodukkan", "njn", "undaakum",
    # give/provide variants — very common in customer messages
    "tharu", "tharilla", "tharaam", "tharamo", "tharanam", "tharaan",
    "kodukku", "kodukkilla", "koduthilla",
    # Phonetic variants
    "entha", "ntha", "enthinu", "ndhinu", "ethinu",
    "nthanu", "nthe", "enthe",
    "evideya", "evideyanu", "evideyaanu",
    "enganeya", "ngane", "nganeya", "ingane", "inganeya",
    "eppo", "eppol", "eppozha", "eppozhanu", "epo", "epol", "epola", "eppola",
    "ethranu", "ethrayanu", "etranu",
    "ellam", "nellam", "ithu", "athu",
    "ente", "pinne", "sherikkum",
    "vangi", "vangam", "vangan", "vangiyilla",
    "thettaya", "thettayit", "vilayil", "vilaykku",
    "divasam", "naal", "manikkoorkul",
    # Social / wellbeing
    "sugamano", "sugamaano", "sugamundo",
    # Policy / rule — critical: "paripadi" is how customers ask about return policy
    "paripadi", "niyamam", "niyamangal",
    # Item / menu / availability — these caused Ollama fallbacks
    "indo", "indoo", "indu", "kittumo", "kittuvo",
    "kazhicho", "kazhikkam", "kazhikkanam", "kazhikan",
    "vishakkunu", "vishakkund", "vishakkunnu",
    "sadhya",
    # Affirmation / negation variants
    "athe", "sheri", "sheriyanu",
    "illa", "illya", "alla", "alleda",
    # Price / cost
    "vila", "vilayil", "vilaykku",
    # Common Manglish query/social particles
    "parayumo", "parayuka", "parayamo", "paranju", "paranjutharaam", "onnu", "koodi", "nte", "nthoru", "vannu", "varam", "kanam", "cheythu", "cheyyumo", "ullath", "ulla", "undallo", "undaayirunnu", "cheyyan", "cheyan", "cheyyum", "kittumo", "kittum",
    # Spelling variants from real Kerala chat data
    "hlo", "hoi", "sukhamano", "sukhamallo",
    "enthada", "enthado", "enthanu",
    "evideyanu", "evideya",
    "varum", "varilla", "varunnundo",
    # ── BUG FIX: missing signals causing wrong lang="english" detection ──
    # "sugamalle" → social greeting variant ("all well?") — was Ollama free call
    "sugamalle", "sugamaalle",
    # "namaskaram"/"sugano" — real customer greetings from chat_logs.csv
    # that were falling through to English because they weren't listed
    # anywhere in this file (confirmed via log analysis).
    "namaskaram", "sugano",
    # "ivde"/"enthoke" — "ivde specials enthoke und" was classified English → RAG in English
    "ivde", "ividey", "ivideyund",
    "enthoke", "enthokke", "enthokkund",
    # ── BUG FIX: single-letter-drop typos causing English replies to real
    # Manglish questions (confirmed from live chat: "nan undavuo" and
    # "prebooking engne cheyam" both got English replies because neither
    # typo matched any existing signal, even via the trailing-"o" fallback) ──
    "kitumo",             # typo of "kittumo" (missing one t)
    "engne",              # typo of "engane" (missing the "a")
    "undavuo", "undavo",  # "will there be/is there" — common availability variant
]

STOPWORDS = {
    "i","a","an","the","is","it","in","of","to","do","my","me",
    "we","you","he","she","they","was","are","be","for","on","with",
    "at","by","from","this","that","have","has","had","not","but",
    "can","will","what","how","when","where","why","would","could",
    "should","just","so","if","or","and","any","all","get","got",
    "am","its","im","ur","dont","please","want","need","tell",
}

# ══════════════════════════════════════════════════════════════════════════════
#  MANGLISH PHONETIC NORMALIZATION
#  Applied word-by-word in normalize() BEFORE matching.
#  KEY FIX: "paripadi" → "return policy" so F1/fuzzy hits the return FAQ.
#            "nthanu"   → "enthu" (what is) so intent detection fires correctly.
# ══════════════════════════════════════════════════════════════════════════════

_MANGLISH_NORM: dict[str, str] = {
    # enthu / "what" variants
    "entha":        "enthu",
    "ntha":         "enthu",
    "enthanu":      "enthu",
    "nthanu":       "enthu",
    "ethanu":       "enthu",
    "ethu":         "enthu",
    "nthe":         "enthu",
    "enthe":        "enthu",
    # Policy words — map to English so they hit english FAQ tokens too
    "paripadi":     "return policy",
    "niyamam":      "policy",
    "niyamangal":   "policy rules",
    # sugam / how-are-you → keeps them as social bypass tokens
    "sugamano":     "sugam aano",
    "sugamaano":    "sugam aano",
    "sugamundo":    "sugam undo",
    # enthinu / why variants
    "enthinu":      "enthinanu",
    "ndhinu":       "enthinanu",
    "ethinu":       "enthinanu",
    "enthikku":     "enthinanu",
    "nthinu":       "enthinanu",
    # engane / how variants
    "ngane":        "engane",
    "nganeya":      "engane",
    "enganeya":     "engane",
    "ingane":       "engane",
    "inganeya":     "engane",
    # evide / where variants
    "evideya":      "evide",
    "evideyanu":    "evide",
    "evideyaanu":   "evide",
    "evideyond":    "evide",
    # eppo / when variants
    "eppozha":      "eppo",
    "eppozhanu":    "eppo",
    "eppozhaaanu":  "eppo",
    "eppozhum":     "eppo",
    # ethra / how much variants
    "ethranu":      "ethra",
    "ethrayanu":    "ethra",
    "etranu":       "ethra",
    "ethraanu":     "ethra",
    # alle variants
    "alleda":       "alle",
    "alleeda":      "alle",
    "allelo":       "alle",
    # aano variants
    "aanoo":        "aano",
    "anoo":         "aano",
    "aanoa":        "aano",
    # undo variants
    "undoo":        "undo",
    "unduu":        "undo",
    "undu":         "undo",
    # njan variants
    "njn":          "njan",
    # ellam variants
    "nellam":       "ellam",
    # ningal variants
    "ningalku":     "ningalkku",
    # common SMS shortenings
    "pls":          "please",
    "plz":          "please",
    "msg":          "message",
    "ordr":         "order",
    "dlvry":        "delivery",
    "delivry":      "delivery",
    "refnd":        "refund",
    "thnx":         "thanks",
    "thx":          "thanks",
    "hw":           "how",
    "whn":          "when",
    "whr":          "where",
    # Item availability — normalize question particles
    "indo":         "undo",
    "indoo":        "undo",
    "indu":         "undo",
    "kittumo":      "undo",
    "kittuvo":      "undo",
    "undoo":        "undo",
    "undaa":        "undo",
    "undu":         "undo",
    # Price question variants
    "ethraya":      "ethra",
    "vila":         "price",
    "vilayil":      "price",
    "vilaykku":     "price",
    # Food / meal
    "kazhicho":     "kazhichu",
    "kazhikkam":    "kazhikkan",
    "kazhikkanam":  "kazhikkan",
    # Spelling variants from Aswinpt2004 corpus patterns
    "enthada":      "enthu",
    "enthado":      "enthu",
    "enthanu":      "enthu",
    "sukhamano":    "sugam aano",
    "sukhamallo":   "sugam alle",
    "hlo":          "hello",
    "availavle":    "available",
    "availble":     "available",
    "avialable":    "available",
    "serrvice":     "service",
    "serivce":      "service",
    "homr":         "home",
    "hoi":          "hello",
    "evideyanu":    "evide",
    "evideya":      "evide",
    "nganeya":      "engane",
    "varum":        "kittumo",
    "varilla":      "kittiyilla",
}

# ══════════════════════════════════════════════════════════════════════════════
#  SYNONYM MAP  (deduplicated — v5.2 had triple duplicates throughout)
# ══════════════════════════════════════════════════════════════════════════════

SYNONYM_MAP: dict[str, list[str]] = {
    # Order / delivery
    "package":      ["order", "parcel", "shipment"],
    "parcel":       ["order", "package", "shipment"],
    "shipment":     ["order", "parcel", "delivery"],
    "stuff":        ["order", "product", "item"],
    "item":         ["product", "order"],
    "items":        ["products", "orders"],
    "things":       ["products", "items", "order"],
    "delivered":    ["delivery", "received", "arrived"],
    "arrive":       ["delivery", "received", "reached"],
    "reached":      ["delivery", "arrived", "received"],
    "late":         ["delayed", "delay", "overdue"],
    "delayed":      ["late", "delay", "overdue"],
    "slow":         ["delayed", "late", "delivery"],
    "stuck":        ["delayed", "tracking", "shipment"],
    # Returns / refunds
    "money":        ["refund", "payment", "paisa"],
    "cash":         ["payment", "refund", "cod"],
    "paisa":        ["refund", "money", "payment"],
    "refunded":     ["refund", "money back"],
    "exchange":     ["return", "replace", "swap"],
    "replace":      ["exchange", "return", "refund"],
    "swap":         ["exchange", "return"],
    # Policy — CRITICAL: "paripadi" / "niyamam" → "policy" / "return"
    "policy":       ["paripadi", "niyamam", "rule", "terms", "return"],
    "paripadi":     ["policy", "rule", "niyamam", "return"],
    "niyamam":      ["policy", "rule", "paripadi", "return"],
    "rule":         ["policy", "paripadi", "niyamam"],
    # Quality / damage
    "torn":         ["damaged", "defective", "broken"],
    "broken":       ["damaged", "defective", "torn"],
    "ripped":       ["torn", "damaged", "defective"],
    "stitch":       ["stitching", "quality", "fabric"],
    "stitching":    ["quality", "fabric", "complaint"],
    "cloth":        ["fabric", "material", "clothing"],
    "tearing":      ["torn", "damaged", "defective", "quality"],
    "peeling":      ["damaged", "quality", "complaint"],
    "fading":       ["faded", "color", "quality"],
    "faded":        ["color", "quality", "washing"],
    "shrunk":       ["size", "washing", "quality"],
    "smell":        ["quality", "complaint", "product"],
    "colour":       ["color", "fading", "quality"],
    "color":        ["colour", "fading", "quality"],
    "missing":      ["not received", "order", "delivery"],
    "empty":        ["missing", "not received", "wrong"],
    "cancel":       ["cancellation", "order cancel"],
    "cancellation": ["cancel", "order cancel"],
    # Complaint typos (deduplicated)
    "complient":    ["complaint", "issue", "problem"],
    "compliant":    ["complaint", "issue", "problem"],
    "complain":     ["complaint", "issue", "problem"],
    "complint":     ["complaint", "issue", "problem"],
    "compalint":    ["complaint", "issue", "problem"],
    "complent":     ["complaint", "issue", "problem"],
    "complaint":    ["issue", "quality", "problem"],
    "problem":      ["complaint", "issue", "defective"],
    "issue":        ["complaint", "problem", "defective"],
    "prblm":        ["problem", "complaint", "issue"],
    "prob":         ["problem", "complaint", "issue"],
    # Delivery / shipping typos
    "refnd":        ["refund", "money back"],
    "refudn":       ["refund", "money back"],
    "dlvry":        ["delivery"],
    "delivry":      ["delivery"],
    "dlvy":         ["delivery"],
    "shiping":      ["shipping", "delivery"],
    "shpping":      ["shipping", "delivery"],
    "ordr":         ["order"],
    "oder":         ["order"],
    "paymet":       ["payment"],
    "paymnt":       ["payment"],
    "paymnet":      ["payment", "pay"],
    "pyament":      ["payment", "pay"],
    "cancl":        ["cancel", "cancellation"],
    "cancell":      ["cancel", "cancellation"],
    "exchnge":      ["exchange", "return"],
    "returnn":      ["return"],
    "trackng":      ["tracking"],
    "trakcing":     ["tracking"],
    "recieve":      ["receive", "received", "delivery"],
    "recieved":     ["received", "delivery", "order"],
    # Manglish action words (deduplicated)
    "kodukkum":     ["submit", "give", "register", "file"],
    "kodukkam":     ["submit", "give", "file"],
    "kodukkan":     ["submit", "file", "give", "raise"],
    "kodukkanam":   ["submit", "give", "register"],
    "tharaam":      ["give", "provide", "refund"],
    "tharanam":     ["give", "submit", "provide"],
    "parayuka":     ["tell", "inform", "complaint"],
    "paranju":      ["told", "informed", "complained"],
    "parayam":      ["tell", "inform", "report", "complaint"],
    "parayanam":    ["tell", "report", "complaint"],
    "parayamo":     ["tell", "inform", "let me know"],
    "cheyyam":      ["do", "file", "submit", "process"],
    "cheyyuka":     ["do", "process", "handle"],
    "nokam":        ["check", "look", "verify"],
    # Contact / number
    "number":       ["contact", "phone", "whatsapp"],
    "call":         ["contact", "support", "phone"],
    "phone":        ["contact", "number", "support"],
    "whatsapp":     ["contact", "support", "phone"],
    "email":        ["contact", "support", "mail"],
    "talk":         ["contact", "support", "speak"],
    "speak":        ["contact", "support", "call"],
    "reach":        ["contact", "support"],
    # Payments
    "gpay":         ["upi", "payment", "phonepay"],
    "phonepay":     ["upi", "payment", "gpay"],
    "phonepe":      ["upi", "payment", "gpay"],
    "paytm":        ["upi", "payment"],
    "cod":          ["cash on delivery", "payment"],
    "netbanking":   ["payment", "bank", "online payment"],
    "emi":          ["installment", "payment", "credit"],
    "card":         ["payment", "credit", "debit"],
    "pay":          ["payment", "paying"],
    "paid":         ["payment", "charged", "billed"],
    "charged":      ["payment", "billed", "paid"],
    "billed":       ["charged", "payment", "invoice"],
    # Sizes
    "small":        ["size", "sizing", "fit"],
    "large":        ["size", "sizing", "fit"],
    "tight":        ["size", "fit", "sizing"],
    "loose":        ["size", "fit", "sizing"],
    "big":          ["size", "large", "fit"],
    "fit":          ["size", "sizing", "measurements"],
    # Manglish semantics
    "kittiyilla":   ["received", "delivered", "arrived"],
    "kittiilla":    ["received", "delivered", "arrived"],
    "kittum":       ["delivery", "received", "will get"],
    "thettaya":     ["wrong", "incorrect", "damaged"],
    "mosham":       ["bad", "poor", "quality"],
    "adipoli":      ["excellent", "great", "good"],
    "vilayil":      ["price", "cost", "rate"],
    "vila":         ["price", "cost", "rate"],
    "vangi":        ["bought", "purchased", "ordered"],
    "vangam":       ["buy", "purchase", "order"],
    "vangiyilla":   ["not received", "not bought"],
    "cheyyano":     ["can i", "how to", "is it possible"],
    "pattumo":      ["possible", "can", "is it available"],
    "undo":         ["available", "do you have", "is there"],
    "undenkil":     ["if available", "if possible"],
    "evide":        ["where", "location", "address"],
    "ethra":        ["how many", "how much", "how long"],
    "enthu":        ["what", "which"],
    "engane":       ["how", "process"],
    "eppo":         ["when", "time", "date"],
    "enthinanu":    ["why", "reason", "purpose"],
    "divasam":      ["days", "date", "time"],
    "naal":         ["days", "date"],
    "manikkoorkul": ["within an hour", "soon"],
    "njn":          ["njan", "i", "me"],
    # Food / menu / item availability — for restaurant shops
    "menu":         ["food", "items", "dishes", "list", "kazhikkan"],
    "dishes":       ["menu", "food", "items"],
    "food":         ["menu", "dishes", "items", "kazhikkan"],
    "sadhya":       ["menu", "food", "meals", "dishes"],
    "kazhikkan":    ["food", "eat", "menu", "order"],
    "kazhichu":     ["food", "ate", "ordered", "eaten"],
    "biriyani":     ["biryani", "fried rice", "rice dish"],
    "biryani":      ["biriyani", "rice", "meals"],
    "chicken":      ["poultry", "meat", "non veg"],
    "mutton":       ["meat", "lamb", "non veg"],
    "seafood":      ["fish", "prawn", "crab", "meat"],
    "indo":         ["available", "undo", "do you have", "is there"],
    "indu":         ["available", "undo", "do you have"],
    # Price synonyms
    "vila":         ["price", "cost", "rate", "amount"],
    "vilayil":      ["price", "cost", "rate"],
    "rate":         ["price", "cost", "vila", "amount"],
    "kittumo":      ["available", "possible", "can get", "undo"],
    "varum":        ["will come", "will deliver", "kittum"],
    "varilla":      ["wont come", "not available", "kittiyilla"],
    # Greeting variants from Aswinpt2004 corpus
    "hlo":          ["hello", "hi", "greet"],
    "hoi":          ["hello", "hi", "greet"],
    "sukhamano":    ["how are you", "wellbeing", "hello"],
    "enthada":      ["what", "enthu", "which"],
    "sheriyanu":    ["correct", "right", "true", "sheri"],
    "alleda":       ["no", "not correct", "wrong", "alla"],
}

# Manglish grammatical particles — NOT expanded (too ambiguous in isolation)
# NOTE: "enthu", "engane", "evide", "eppo" REMOVED from this set so their
# synonym expansions fire correctly (they have real mappings above).
_PARTICLE_NO_EXPAND = {
    "kittum", "kittiyilla", "cheyyam", "cheyyano", "cheyyuka", "cheythu",
    "aanu", "alle", "aano", "undo", "undu", "okke", "ippo",
    "njan", "njangal", "ningal", "avarkku",
    "polum", "venam", "venda", "pattumo", "tharaamo", "undenkil",
    "allenkil", "nokam", "nokkanam", "sheri", "kollam", "adipoli",
    "mosham", "ano", "ithu", "athu", "ente", "pinne",
}

# ══════════════════════════════════════════════════════════════════════════════
#  FUZZY MATCHING — rapidfuzz
# ══════════════════════════════════════════════════════════════════════════════

try:
    from rapidfuzz import fuzz as _rfuzz
    def fuzzy_match(a: str, b: str) -> float:
        """Token-set ratio (0.0–1.0). Handles typos, reordering, partial overlaps."""
        return _rfuzz.token_set_ratio(a, b) / 100.0
    print("[nlp] ✅  rapidfuzz loaded — fuzzy matching enabled")
except ImportError:
    def fuzzy_match(a: str, b: str) -> float:  # type: ignore[misc]
        return 0.0
    print("[nlp] ⚠   rapidfuzz not installed — run: pip install rapidfuzz")

# ══════════════════════════════════════════════════════════════════════════════
#  TEXT UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def normalize(text: str) -> str:
    """
    Lowercase + collapse whitespace + Manglish phonetic normalization.
    Applied word-by-word so "nthanu paripadi" → "enthu return policy"
    which then hits the return FAQ via F1/fuzzy.
    """
    text  = re.sub(r"\s+", " ", text.lower().strip())
    # Split brand spellings → canonical form, BEFORE word-level pass.
    # ("whats app number undo" was missing Pass 0 because of this.)
    text = re.sub(r"\bwhats\s*app\b",   "whatsapp",  text)
    text = re.sub(r"\bwhat'?s\s*app\b", "whatsapp",  text)
    text = re.sub(r"\bg\s+pay\b",       "gpay",      text)
    text = re.sub(r"\bphone\s*pe\b",    "phonepe",   text)
    text = re.sub(r"\binsta\s*gram\b",  "instagram", text)
    text = re.sub(r"\bface\s*book\b",   "facebook",  text)
    words = text.split()
    # Word-level replacement. Multi-word replacements (e.g. "return policy")
    # are inserted as-is; the space is fine because normalize output is
    # used as a full string in fuzzy_match and as tokens in tokenize().
    normalized: list[str] = []
    for w in words:
        replacement = _MANGLISH_NORM.get(w)
        if replacement:
            normalized.extend(replacement.split())
        else:
            normalized.append(w)
    return " ".join(normalized)


def tokenize(text: str) -> list[str]:
    tokens = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]


def expand_synonyms(tokens: list[str]) -> list[str]:
    """
    Returns original tokens PLUS synonym expansions.
    Manglish grammatical particles in _PARTICLE_NO_EXPAND are NOT expanded.
    """
    expanded = list(tokens)
    seen = set(tokens)
    for tok in tokens:
        if tok in _PARTICLE_NO_EXPAND:
            continue
        for syn in SYNONYM_MAP.get(tok, []):
            for word in syn.split():
                if word not in seen:
                    seen.add(word)
                    expanded.append(word)
    return expanded


def f1_score(query_tokens: list[str], faq_question: str) -> float:
    """F1 token overlap. query_tokens should be pre-expanded via expand_synonyms()."""
    faq_tokens = set(tokenize(faq_question))
    q_set      = set(query_tokens)
    if not faq_tokens or not q_set:
        return 0.0
    inter = len(q_set & faq_tokens)
    if inter == 0:
        return 0.0
    precision = inter / len(q_set)
    recall    = inter / len(faq_tokens)
    return 2 * precision * recall / (precision + recall)


_MANGLISH_SIGNALS_SET = set(MANGLISH_SIGNALS)

# Manglish grammatical particles short enough to collide with English
# substrings if matched loosely — must be checked as EXACT tokens only.
_SHORT_PARTICLES = {"nte", "und", "aanu", "alle", "ano", "illa"}


def is_manglish(text: str) -> bool:
    if LANGUAGE_SWITCH_RE.search(text):
        return True

    # Tokenize (lowercase, strip punctuation, split on whitespace) and match
    # WHOLE WORDS only. The previous version used a raw substring search
    # (`sig in t`), which meant a Manglish particle's *letters* appearing
    # anywhere in the text counted as a hit — so plain English sentences
    # were wrongly flagged as Manglish:
    #   "ano"  matched inside "an-ano-ther"   -> "another"
    #   "ente" matched inside "s-ente-nce"    -> "sentence", "enter"
    #   "illa" matched inside "v-illa"        -> "villa", "vanilla"
    #   "athe" matched inside "b-athe"        -> "bathe", "breathe"
    # Tokenizing first and requiring an exact word match removes all of
    # these false positives. It also fixes the reverse problem: a message
    # like "ningalude shop evide aanu?" used to only match via the risky
    # substring fallback, because "aanu?" (punctuation attached) never
    # equalled "aanu" in a plain word-boundary check. Stripping punctuation
    # before splitting fixes that too.
    _words = set(re.sub(r"[^\w\s]", " ", text.lower()).split())
    if _words & _SHORT_PARTICLES:
        return True
    if _words & _MANGLISH_SIGNALS_SET:
        return True

    # Malayalam questions very often add a trailing "-o" (interrogative
    # particle) to a verb root, e.g. "undaakum" -> "undaakumo?". The signals
    # list can't list every "-o" variant of every root, so as a targeted
    # fallback: if a word ends in "o" and the word MINUS that trailing "o"
    # is itself a known signal, count it. This is much safer than a raw
    # substring search — "photo"/"video"/"piano"/"auto" strip down to
    # "phot"/"vide"/"pian"/"aut", none of which are Manglish roots, so
    # plain English "-o" words are unaffected.
    for w in _words:
        if len(w) > 3 and w.endswith("o") and w[:-1] in _MANGLISH_SIGNALS_SET:
            return True

    return False


def is_english_text(text: str) -> bool:
    return not is_manglish(text)

# ══════════════════════════════════════════════════════════════════════════════
#  MODEL LOADING
# ══════════════════════════════════════════════════════════════════════════════

embedder      = None
sentiment_clf = None

try:
    from sentence_transformers import SentenceTransformer
    print("[nlp] Loading sentence-transformer…")
    embedder = SentenceTransformer(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        device=ST_DEVICE
    )
    print(f"[nlp] ✅  sentence-transformer ready ({ST_DEVICE.upper()})")
except ImportError:
    print("[nlp] ⚠   sentence-transformers not installed — F1 matching only")

try:
    from transformers import pipeline as hf_pipeline
    _label = "GPU" if SENT_DEVICE == 0 else "CPU"
    print(f"[nlp] Loading XLM-R zero-shot classifier → {_label}…")
    sentiment_clf = hf_pipeline(
        "zero-shot-classification",
        model="joeddav/xlm-roberta-large-xnli",
        device=SENT_DEVICE,
        tokenizer_kwargs={"use_fast": False},
    )
    print(f"[nlp] ✅  XLM-R ready ({_label})")
except ImportError:
    print("[nlp] ⚠   transformers not installed — lexicon-only sentiment")

# ══════════════════════════════════════════════════════════════════════════════
#  SENTIMENT DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def lexicon_check(text: str) -> str | None:
    t = text.lower()
    for sentiment in ("sarcastic", "urgent", "negative", "positive"):
        for phrase in LEXICON[sentiment]:
            if phrase in t:
                return sentiment
    return None



# ── Service context check — prevents XLM-R misclassifying service questions ──
SERVICE_QUERY_SIGNALS = {
    "wax", "waxing", "threading", "facial", "cleanup", "bleach",
    "manicure", "pedicure", "massage", "haircut", "trim", "color",
    "colour", "highlights", "straightening", "rebonding", "keratin",
    "bridal", "makeup", "eyebrow", "biriyani", "biryani", "chicken",
    "mutton", "fish", "prawn", "curry", "rice", "meals", "food", "menu",
    "undakumo", "cheythal", "cheyyumbo", "aakumo", "undaakumo",
}

def service_context_check(text: str) -> bool:
    """Returns True if message is a service/product inquiry (not emotional distress)."""
    tokens = set(text.lower().split())
    return bool(tokens & SERVICE_QUERY_SIGNALS)

def detect_sentiment(text: str) -> dict:
    lex = lexicon_check(text)
    if lex:
        return {"sentiment": lex, "confidence": 0.93, "source": "lexicon"}

    if sentiment_clf is not None:
        try:
            result    = sentiment_clf(text, SENTIMENT_LABELS)
            top_label = result["labels"][0]
            top_score = result["scores"][0]
            sentiment = LABEL_MAP.get(top_label, "neutral")
            if top_score < SENTIMENT_THRESHOLD:
                sentiment = "neutral"
            return {"sentiment": sentiment, "confidence": round(top_score, 3), "source": "xlmr"}
        except Exception:
            pass

    return {"sentiment": "neutral", "confidence": 0.5, "source": "default"}

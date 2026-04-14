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
  - f1_score(query_tokens, faq_question) → float
  - embedder          — SentenceTransformer instance or None
  - sentiment_clf     — HuggingFace pipeline or None
  - ST_DEVICE         — "cuda" | "cpu"
  - SENT_DEVICE       — 0 | -1
  - device_name       — human-readable string
  - STOPWORDS, LEXICON, MANGLISH_SIGNALS, LANGUAGE_SWITCH_RE
  - SENTIMENT_LABELS, LABEL_MAP, SENTIMENT_THRESHOLD
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
    ST_DEVICE   = "cuda"
    SENT_DEVICE = -1 if (_vram_mb < 7000 or VRAM_SAFE_MODE) else 0
    device_name = f"GPU ({_gpu_name}, {_vram_mb} MB)"
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
    "aanu", "alle", "aano", "ano", "undo", "undu",
    "cheyyam", "cheyyano", "cheythu", "cheyyunno", "cheyyuka",
    "cheyynam", "nokam", "nokkanam", "kittum", "kittiyilla",
    "njan", "njangal", "ningal", "avarkku",
    "engane", "enthu", "ethra", "evide", "ippo", "okke",
    "polum", "munpe", "athukond", "allenkil", "undenkil",
    "kollam", "mosham", "adipoli", "sheri", "sheriyalla",
    "kooduthal", "venda", "venam",
    "aayirunnu", "kazhinju",
    "pattumo", "tharaamo",
]

STOPWORDS = {
    "i","a","an","the","is","it","in","of","to","do","my","me",
    "we","you","he","she","they","was","are","be","for","on","with",
    "at","by","from","this","that","have","has","had","not","but",
    "can","will","what","how","when","where","why","would","could",
    "should","just","so","if","or","and","any","all","get","got",
    "am","its","im","ur","dont","please","want","need","tell",
}


def is_manglish(text: str) -> bool:
    if LANGUAGE_SWITCH_RE.search(text):
        return True
    t = text.lower()
    return any(sig in t for sig in MANGLISH_SIGNALS)


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
        device=ST_DEVICE,
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
#  TEXT UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def normalize(text: str) -> str:
    """Lowercase + collapse whitespace only. No suffix stripping."""
    return re.sub(r"\s+", " ", text.lower().strip())


def tokenize(text: str) -> list[str]:
    tokens = re.sub(r"[^\w\s]", " ", text.lower()).split()
    return [t for t in tokens if len(t) > 1 and t not in STOPWORDS]


def f1_score(query_tokens: list[str], faq_question: str) -> float:
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

# 🤖 Chottu Bot – Bilingual Multi-Shop Customer Support API (v5.5)

A production-ready AI-powered customer support chatbot for Kerala-based businesses.
Supports English and Manglish (Malayalam in English script) with sentiment-aware responses.
Fully white-label — deploy for any shop type (clothing, dental, beauty, jewellery, restaurant, gym...) by uploading a config file.

---

## ✨ Key Features

- 🌐 **Bilingual Support** – Handles English and Manglish (Malayalam in English script)
- 🎯 **Sentiment-Aware Responses** – Detects tone (positive, negative, sarcastic, urgent) and adapts replies
- 📚 **Hybrid FAQ Engine** – Semantic similarity + rapidfuzz fuzzy matching + F1 token fallback
- 🧠 **LLM Fallback (Ollama)** – Handles off-topic queries + Manglish rephrasing
- 🚀 **Fast-Path Guards** – Greeting, compliment, social chat, confirmation, language-switch bypass for instant replies
- 🔒 **Human Escalation** – Fraud, refund complaints, session booking, offers → WhatsApp
- 🏪 **Multi-Shop / White-Label** – Switch shops by uploading `shop_config.json` — no code changes
- 🚫 **Blocked Topics** – Per-shop topic blocking (dental blocks delivery/returns/size etc.)
- 🔄 **Hot Reload** – Change shop config or FAQs without server restart via `/admin` endpoints
- 📊 **Analytics & Logging** – Tracks conversations, FAQ gaps, and escalations
- ⚡ **Production-Ready API** – FastAPI v5.5 with async lifespan, Ollama warm-up, keep-alive

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI 0.115.11 |
| Embeddings | `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`) |
| Sentiment | XLM-RoBERTa (`joeddav/xlm-roberta-large-xnli`) |
| Fuzzy Matching | `rapidfuzz` (token set ratio) |
| LLM | Ollama (`gemma3:4b`) |
| Data & Logging | Pandas |
| Acceleration | CUDA (auto-detected, XLM-R on CPU to save VRAM) |
| Server | Uvicorn |

---

## 📁 Project Structure

```
AI_AGENT/
├── faqs/
│   ├── english.json               # Generic English FAQs (with {placeholders})
│   ├── english_sentiment.json     # Sentiment-aware English FAQs
│   ├── manglish.json              # Generic Manglish FAQs (with {placeholders})
│   ├── manglish_sentiment.json    # Sentiment-aware Manglish FAQs
│   └── shop_faq.json              # Shop-specific FAQs (upload per shop)
├── static/
│   └── index.html                 # Chat UI (dynamic — reads from /health)
├── shop_config.json               # Shop identity, contact, hours, blocked topics
├── api.py                         # FastAPI HTTP layer (v5.5)
├── chat.py                        # Pipeline, config loader, Ollama helpers, logger
├── faq_engine.py                  # FAQ loading, placeholder resolver, embedding index
├── nlp.py                         # Language detection, sentiment analysis, NLP utils
├── chat_logs.csv                  # Auto-generated conversation logs
├── requirements.txt
├── .gitignore
└── Readme.md
```

---

## 🚀 Getting Started

### 1. Clone

```bash
git clone https://github.com/zenmeraki7/custom_bot.git
cd custom_bot
git checkout bot
```

### 2. Virtual Environment

```bash
python -m venv manglish_env
```

**Activate:**

Windows:
```bash
manglish_env\Scripts\activate
```

Linux/Mac:
```bash
source manglish_env/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Setup Ollama

```bash
ollama pull gemma3:4b
ollama serve
```

### 5. Create Shop Config

Create `shop_config.json` in the root folder. See `shop_config.json` template in the repo.

```json
{
  "bot_name": "Chottu",
  "shop_name": "Zen Meraki Clothing Store",
  "shop_type": "clothing",
  "contact": { "whatsapp": "+91 98765 43210", "email": "support@shop.com" },
  "hours": { "weekdays": "Mon–Sat 9AM–8PM", "sunday": "Sunday 10AM–6PM" },
  "blocked_topics": []
}
```

### 6. (Optional) Hugging Face Token

```bash
# Windows
set HF_TOKEN=hf_xxxxx

# Linux/Mac
export HF_TOKEN=hf_xxxxx
```

### 7. Run Server

```bash
# Production (no auto-reload)
uvicorn api:app --host 0.0.0.0 --port 8000

# Development (auto-reload on file change)
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### 8. Access

- UI → http://localhost:8000
- Docs → http://localhost:8000/docs

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|---------|------------|
| POST | `/chat` | Process a customer message |
| GET | `/` | Serve chat UI |
| GET | `/health` | System + model status + full shop config |
| GET | `/faqs` | Browse FAQ pool (`?source=all\|english\|manglish\|sentiment_aware\|shop&limit=50`) |
| GET | `/stats` | Chat log analytics |
| GET | `/logs/review` | Ollama-handled messages — FAQ gap candidates |
| GET | `/logs/escalations` | Conversations flagged for human follow-up |
| GET | `/logs/bypass` | Messages routed via bypass guards |
| POST | `/admin/upload-config` | Upload new `shop_config.json` — hot reload |
| POST | `/admin/upload-faqs` | Upload new `shop_faq.json` — hot reload |
| GET | `/admin/config` | View current shop config |

---

## 📌 Example Request

```bash
curl -X POST http://localhost:8000/chat \
-H "Content-Type: application/json" \
-d '{"message": "Return policy enthu?"}'
```

## 📌 Example Response

```json
{
  "message": "Return policy enthu?",
  "lang": "manglish",
  "sentiment": "neutral",
  "confidence": 0.91,
  "sent_source": "xlmr",
  "reply": "Returns accepted within 7 days with original tags. Refund in 3-5 business days.",
  "source": "faq",
  "bypass": "",
  "faq_source": "manglish",
  "faq_id": "return_001",
  "faq_score": 0.922,
  "escalate": false,
  "ms": 42.3
}
```

---

## 🏪 Multi-Shop Support

Switch the bot to any shop type by replacing two files:

```bash
# Switch to dental clinic
curl -X POST http://localhost:8000/admin/upload-config \
  -F "file=@dental_shop_config.json"

curl -X POST http://localhost:8000/admin/upload-faqs \
  -F "file=@dental_shop_faq.json"
```

No restart needed. Bot identity, contact details, FAQ answers, UI chips, and blocked topics all update instantly.

### Supported Shop Types

| Shop Type | Bot Name | Blocked Topics |
|-----------|---------|----------------|
| `clothing` | Chottu | none |
| `dental_clinic` | Dento | delivery, returns, tracking, size, COD |
| `beauty_parlour` | Glam | delivery, tracking, size, COD |
| `jewellery` | Lakshmi | delivery, tracking, size, COD, clothing |
| Any custom type | Custom | Fully configurable |

### Placeholder System

Generic FAQ answers use `{placeholders}` resolved at load time from `shop_config.json`:

```json
"answer": "WhatsApp cheyyuka {whatsapp} il. {hours_weekdays} available aanu!"
```

Resolves to the current shop's number and hours automatically.

**Available placeholders:** `{whatsapp}`, `{phone}`, `{email}`, `{hours_weekdays}`, `{hours_sunday}`, `{hours_holiday}`, `{location}`, `{city}`, `{delivery_areas}`, `{delivery_free}`, `{delivery_days}`, `{return_days}`, `{return_condition}`, `{refund_days}`, `{offer_code}`, `{offer_desc}`, `{shop_name}`, `{bot_name}`

---

## 🗂️ FAQ File Formats

### Shop FAQ (`faqs/shop_faq.json`) — upload per shop

```json
[
  {
    "id": "sf_price_001",
    "category": "pricing",
    "lang": "english",
    "question_variants": ["Price range?", "How much do clothes cost?"],
    "answer": "Basics from ₹299. T-shirts ₹299–₹799. Visit {location} or WhatsApp {whatsapp}!"
  }
]
```

### Flat FAQ (`english.json` / `manglish.json`)

```json
{
  "id": "delivery_001",
  "category": "delivery",
  "question_variants": ["Delivery time?", "How long for delivery?"],
  "answer": "{delivery_days}. Free delivery above {delivery_free}."
}
```

### Sentiment-Aware FAQ (`english_sentiment.json` / `manglish_sentiment.json`)

```json
{
  "id": "return_001",
  "category": "returns",
  "questions": {
    "neutral": ["What is return policy?"],
    "negative": ["Product is defective, want refund"]
  },
  "answers": {
    "neutral": "Return within {return_days} days with original tags.",
    "negative": "Sorry for the trouble! WhatsApp {whatsapp} — we'll fix this immediately."
  }
}
```

---

## ⚙️ Configuration

| Variable | Default | Description |
|---------|--------|-------------|
| `FAQ_THRESHOLD` | `0.30` | F1 token match minimum score |
| `SEMANTIC_THRESHOLD` | `0.52` | Cosine similarity minimum score |
| `FUZZY_THRESHOLD` | `0.72` | rapidfuzz token set ratio minimum |
| `MANGLISH_BOOST` | `1.15` | Score boost for Manglish FAQ matches |
| `SENTIMENT_THRESHOLD` | `0.45` | Minimum confidence for sentiment label |
| `OLLAMA_MODEL` | `gemma3:4b` | LLM model for fallback + rephrasing |

Bot name, shop name, contact details — all from `shop_config.json`, not hardcoded.

---

## 🧠 Pipeline Flow (v5.5)

```
User Message
    │
    ├─ is_manglish()          → lang = "manglish" | "english"
    ├─ detect_sentiment()     → negative | positive | neutral | sarcastic | urgent
    │
    ├─ GREETING_RE            → static reply (hi, hello, hey bro, namaskaram)
    ├─ _is_compliment()       → static reply (nanni, adipoli, thank you)
    ├─ _CONFIRMATION_RE       → static reply (yes undu, ok aanu, sheri)
    ├─ SOCIAL_CHAT_RE         → Ollama social prompt (sugamano, how are you)
    ├─ _LANG_SWITCH_RE        → language switch reply (in english, manglish il)
    ├─ _LOCATION_QUERY_RE     → store location reply (eevide aanu kanan illalo)
    ├─ blocked_topics guard   → shop-specific redirect (dental blocks delivery etc.)
    ├─ _ESCALATE_RE           → WhatsApp escalation:
    │                           • Fraud / scam / legal threats
    │                           • Refund not received
    │                           • Session / appointment booking
    │                           • All offer / discount queries
    │                           • Complaint about store/service
    │
    ├─ match_faq()            → 3-pass matching:
    │   ├─ Pass 1: semantic cosine (threshold 0.52)
    │   ├─ Pass 1.5: rapidfuzz token set ratio (threshold 0.72)
    │   └─ Pass 2: F1 token overlap with synonym expansion (threshold 0.30)
    │       ├─ Hit → FAQ answer (rephrase to Manglish if needed via Ollama)
    │       └─ Miss → ollama_reply()
    │
    └─ log_chat() → chat_logs.csv
```

---

## 🔒 Escalation Triggers

Messages matching these patterns are routed to WhatsApp instead of FAQ:

| Category | Example Messages |
|---------|-----------------|
| Fraud / Scam | `"fraud aanu ithu"`, `"case kodukkum"`, `"police complaint"` |
| Refund not received | `"refund tharilla"`, `"paisa poyi"`, `"money not refunded"` |
| Session / Appointment | `"book a session"`, `"appointment book cheyyaan"` |
| Offers / Discounts | `"any offers?"`, `"offer undo?"`, `"onam offer?"` |
| Complaint | `"want to complaint"`, `"complaint about store"` |

---

## 📊 Logging & Analytics

Auto-saved to `chat_logs.csv`:

```
timestamp, lang, message, sentiment, confidence, sent_source,
faq_source, source, faq_id, faq_score, escalate, bypass, reply
```

View via API:
- `/stats` — hit rates, sentiment breakdown, Ollama call rate
- `/logs/review` — every Ollama-handled message (FAQ gap candidates)
- `/logs/escalations` — all escalated conversations
- `/logs/bypass` — messages that hit fast-path guards

---

## 🧪 Testing

- Swagger UI → http://localhost:8000/docs
- Browser chat UI → http://localhost:8000
- Health check → http://localhost:8000/health

---

## 📄 License

MIT

---

## 🙏 Credits

- [sentence-transformers](https://www.sbert.net/)
- [Hugging Face Transformers](https://huggingface.co/)
- [Ollama](https://ollama.com/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [rapidfuzz](https://github.com/maxbachmann/RapidFuzz)

---

## 👨‍💻 Author

Built for scalable bilingual AI customer support 🚀
[Zen Meraki](https://github.com/zenmeraki7)

# 🤖 Chottu Bot – Bilingual Customer Support API (v5.1)

A production-ready AI-powered customer support chatbot for Kerala-based businesses.
Supports English and Manglish (Malayalam in English script) with sentiment-aware responses.

---

## ✨ Key Features

- 🌐 **Bilingual Support** – Handles English and Manglish (Malayalam in English script)
- 🎯 **Sentiment-Aware Responses** – Detects tone (positive, negative, sarcastic, urgent) and adapts replies
- 📚 **Hybrid FAQ Engine** – Semantic similarity + F1 token fallback matching
- 🧠 **LLM Fallback (Ollama)** – Handles off-topic queries + Manglish rephrasing
- 🚀 **Fast-Path Guards** – Greeting, compliment, social chat bypass for instant replies
- 📊 **Analytics & Logging** – Tracks conversations, FAQ gaps, and escalations
- ⚡ **Production-Ready API** – FastAPI v5.1 with async lifespan support

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI 0.115.11 |
| Embeddings | `sentence-transformers` (`paraphrase-multilingual-MiniLM-L12-v2`) |
| Sentiment | XLM-RoBERTa (Hugging Face `transformers`) |
| LLM | Ollama (`gemma3:4b`) |
| Data & Logging | Pandas |
| Acceleration | CUDA (optional, auto-detected) |
| Server | Uvicorn |

---

## 📁 Project Structure

```
AI_AGENT/
├── faqs/
│   ├── english.json               # Flat English FAQs
│   ├── english_sentiment.json     # Sentiment-aware English FAQs
│   ├── manglish.json              # Flat Manglish FAQs
│   └── manglish_sentiment.json    # Sentiment-aware Manglish FAQs
├── static/
│   └── index.html                 # Chat UI
├── api.py                         # FastAPI HTTP layer (v5.1)
├── chat.py                        # Pipeline, Ollama helpers, logger
├── faq_engine.py                  # FAQ loading, embedding index, matching
├── nlp.py                         # Language detection, sentiment analysis
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

### 5. (Optional) Hugging Face Token

```bash
# Linux/Mac
export HF_TOKEN=hf_xxxxx

# Windows
set HF_TOKEN=hf_xxxxx
```

### 6. Run Server

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

### 7. Access

- UI → http://localhost:8000
- Docs → http://localhost:8000/docs

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|---------|------------|
| POST | `/chat` | Process a customer message |
| GET | `/` | Serve chat UI (static/index.html) |
| GET | `/health` | System + model status |
| GET | `/faqs` | Browse FAQ pool (`?source=all\|english\|manglish\|sentiment_aware\|shop&limit=50`) |
| GET | `/stats` | Chat log analytics (requires pandas) |
| GET | `/logs/review` | Ollama-handled messages — FAQ gap candidates |
| GET | `/logs/escalations` | Conversations flagged for human follow-up |
| GET | `/logs/bypass` | Messages routed via bypass guards |

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

## 🗂️ FAQ File Formats

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
    "neutral": "Return within 7 days with original tags.",
    "negative": "Sorry for the trouble! We'll process your return immediately."
  }
}
```

### Flat FAQ (`english.json` / `manglish.json`)

```json
{
  "id": "delivery_001",
  "category": "delivery",
  "question_variants": ["Delivery time?", "How long for delivery?"],
  "answer": "2-3 working days. Free delivery above ₹500."
}
```

---

## ⚙️ Configuration

| Variable | Default | Description |
|---------|--------|-------------|
| `FAQ_THRESHOLD` | `0.35` | F1 token match minimum score |
| `SEMANTIC_THRESHOLD` | `0.60` | Cosine similarity minimum score |
| `MANGLISH_BOOST` | `1.15` | Score boost for Manglish FAQ matches |
| `SENTIMENT_THRESHOLD` | `0.70` | Minimum confidence for sentiment label |
| `OLLAMA_MODEL` | `gemma3:4b` | LLM model for fallback + rephrasing |
| `BOT_NAME` | `Chottu` | Bot display name |
| `SHOP_NAME` | `Zen Meraki Clothing Store` | Shop name used in prompts |

---

## 🧠 Pipeline Flow

```
User Message
    │
    ├─ Greeting regex → instant reply
    ├─ Compliment regex → instant reply
    ├─ Social chat regex → Ollama
    │
    ├─ detect_sentiment() [XLM-RoBERTa]
    ├─ is_manglish() [signal detection]
    │
    ├─ match_faq() [semantic + F1]
    │   ├─ Hit → return FAQ answer
    │   │         (rephrase to Manglish if needed via Ollama)
    │   └─ Miss → ollama_reply()
    │
    └─ log_chat() → chat_logs.csv
```

---

## 📊 Logging

Auto-saved to `chat_logs.csv`:

```
timestamp, lang, message, sentiment, confidence, sent_source,
faq_source, source, faq_id, faq_score, escalate, bypass, reply
```

---

## 🧪 Testing

- Swagger UI → http://localhost:8000/docs
- Postman or curl
- Browser chat UI → http://localhost:8000

---

## 🔮 Roadmap

- [ ] WhatsApp / Telegram integration
- [ ] Admin dashboard
- [ ] Auto FAQ learning from Ollama logs
- [ ] Multi-store support
- [ ] Voice chatbot
- [ ] Hindi / Tamil support

---

## 📄 License

MIT

---

## 🙏 Credits

- [sentence-transformers](https://www.sbert.net/)
- [Hugging Face Transformers](https://huggingface.co/)
- [Ollama](https://ollama.com/)
- [FastAPI](https://fastapi.tiangolo.com/)

---

## 👨‍💻 Author

Built for scalable bilingual AI customer support 🚀  
[Zen Meraki](https://github.com/zenmeraki7)
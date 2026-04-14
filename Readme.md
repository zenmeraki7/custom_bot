## `README.md` (copy the entire block)

```markdown
# 🤖 Chottu Bot – Bilingual Customer Support API

**Chottu** is a smart, bilingual (English + Manglish) customer support chatbot for **Zen Meraki Clothing Store**.  
It combines **sentiment‑aware FAQ matching**, **semantic search**, and **Ollama LLM fallback** to deliver fast, empathetic, and locally‑flavoured replies.

---

## ✨ Features

- 🌐 **Bilingual** – Seamlessly handles English and Manglish (Malayalam written in English script)
- 🎯 **Sentiment‑aware replies** – Adjusts tone for positive, neutral, negative, sarcastic, or urgent messages
- 📚 **Hybrid FAQ engine** – Semantic cosine matching + F1 token overlap fallback
- 🧠 **Ollama LLM integration** – Answers social chat, off‑topic questions, and rephrases English FAQ answers into Manglish
- 📊 **Built‑in analytics** – Logs every conversation; endpoints for FAQ hit rates, escalation queue, and review candidates
- 🚀 **Production ready** – FastAPI with CORS, static UI, and async‑safe design

---

## 🛠️ Tech Stack

| Component          | Technology                                                                 |
|--------------------|----------------------------------------------------------------------------|
| API Framework      | [FastAPI](https://fastapi.tiangolo.com/)                                   |
| Embeddings         | [sentence-transformers](https://www.sbert.net/) (`paraphrase-multilingual-MiniLM-L12-v2`) |
| Sentiment Analysis | [XLM‑RoBERTa‑large‑XNLI](https://huggingface.co/joeddav/xlm-roberta-large-xnli) (zero‑shot) |
| LLM                | [Ollama](https://ollama.com/) – `gemma3:4b` (or any model you prefer)      |
| GPU Acceleration   | CUDA (optional) – falls back to CPU gracefully                             |
| Logging & Stats    | CSV + Pandas                                                               |

---

## 📁 Project Structure

```
AI_AGENT/
├── faqs/                     # FAQ JSON files
│   ├── faqs.json            # Sentiment‑aware FAQs (36)
│   ├── english.json         # English flat FAQs (117)
│   └── manglish.json        # Manglish flat FAQs (117)
├── shop_faqs/               # (Optional) shop‑specific FAQ files
├── static/                  # Frontend (index.html, CSS, JS)
├── api.py                   # FastAPI layer (routes, validation)
├── chat.py                  # Core pipeline (greeting, social, FAQ, Ollama)
├── faq_engine.py            # FAQ loading, embedding index, matching logic
├── nlp.py                   # Language detection, sentiment, tokenisation
├── chat_logs.csv            # Auto‑generated conversation logs
└── requirements.txt
```

---

## 🚀 Getting Started

### 1. Clone & Environment

```bash
git clone https://github.com/yourusername/chottu-bot.git
cd chottu-bot
python -m venv manglish_env
source manglish_env/bin/activate   # Linux/Mac
manglish_env\Scripts\activate      # Windows
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Install & Run Ollama

- Download [Ollama](https://ollama.com/download)
- Pull the model (default `gemma3:4b`):
  ```bash
  ollama pull gemma3:4b
  ```
- Keep Ollama running in a separate terminal:
  ```bash
  ollama serve
  ```

### 4. (Optional) Set Hugging Face Token

To avoid rate limits and warnings, set your HF token:

```bash
export HF_TOKEN=hf_xxxxxxxxxxxxx   # Linux/Mac
set HF_TOKEN=hf_xxxxxxxxxxxxx      # Windows
```

### 5. Run the Server

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Open `http://localhost:8000` to use the chat UI, or `http://localhost:8000/docs` for interactive API docs.

---

## 📡 API Endpoints

| Method | Endpoint               | Description                                                                 |
|--------|------------------------|-----------------------------------------------------------------------------|
| `POST` | `/chat`                | Send a customer message → returns reply + metadata (sentiment, source, etc.) |
| `GET`  | `/health`              | System status, model info, GPU memory, FAQ counts                           |
| `GET`  | `/faqs`                | Browse FAQs (filter by `source` and `limit`)                                |
| `GET`  | `/stats`               | Chat log statistics (requires pandas)                                       |
| `GET`  | `/logs/review`         | Messages answered by Ollama – candidates for new FAQs                       |
| `GET`  | `/logs/escalations`    | Conversations flagged for human follow‑up                                   |
| `GET`  | `/logs/bypass`         | Messages that bypassed FAQ (social, praise, off‑topic)                      |
| `GET`  | `/`                    | Serves the static chat UI (`static/index.html`)                             |

### Example `/chat` Request

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Return policy enthu?"}'
```

Response:

```json
{
  "message": "Return policy enthu?",
  "lang": "manglish",
  "sentiment": "neutral",
  "confidence": 0.372,
  "sent_source": "xlmr",
  "reply": "Yes! Returns are accepted within 7 days of delivery...",
  "source": "faq",
  "faq_source": "english",
  "faq_id": "",
  "faq_score": 0.922,
  "escalate": false,
  "ms": 1734.9
}
```

---

## 🗂️ FAQ File Formats

### Sentiment‑aware (`faqs.json`)

```json
[
  {
    "id": "return_001",
    "category": "returns",
    "source": "sentiment_aware",
    "questions": {
      "neutral": ["What is your return policy?", "Can I return an item?"],
      "negative": ["My product is defective. What can I do?"]
    },
    "answers": {
      "neutral": "You can return unused items within 7 days...",
      "negative": "We are sorry for the defect. Please contact support..."
    },
    "escalate_if": { "keywords": ["defective", "damaged"] }
  }
]
```

### Flat FAQs (`english.json` / `manglish.json`)

```json
[
  {
    "id": "delivery_001",
    "category": "delivery",
    "question_variants": ["How long does delivery take?", "Delivery time?"],
    "answer": "Standard delivery takes 2-3 working days in Kerala."
  }
]
```

---

## 📊 Logging & Monitoring

- All conversations are saved to `chat_logs.csv` with fields:  
  `timestamp, lang, message, sentiment, confidence, sent_source, faq_source, source, faq_id, faq_score, escalate, bypass, reply`
- Use the `/stats`, `/logs/review`, `/logs/escalations`, and `/logs/bypass` endpoints to analyse performance and identify FAQ gaps.

---

## ⚙️ Configuration

Key constants (adjust in `chat.py` and `faq_engine.py`):

| Variable                | Default | Description                                 |
|-------------------------|---------|---------------------------------------------|
| `FAQ_THRESHOLD`         | 0.35    | Minimum F1 score to accept a FAQ match      |
| `SEMANTIC_THRESHOLD`    | 0.60    | Cosine similarity threshold for semantic match |
| `MANGLISH_BOOST`        | 1.15    | Multiplier for Manglish F1 scores           |
| `SENTIMENT_THRESHOLD`   | 0.65    | Confidence threshold for sentiment classifier |
| `OLLAMA_MODEL`          | `gemma3:4b` | Ollama model name                       |

---

## 🧪 Testing

Run the server and use the built‑in Swagger UI:  
[http://localhost:8000/docs](http://localhost:8000/docs)

Or test with `curl`, Postman, or the static chat UI at `http://localhost:8000`.

---

## 📄 License

MIT License – free for personal and commercial use.

---

## 🙏 Acknowledgements

- [sentence-transformers](https://www.sbert.net/)
- [Hugging Face](https://huggingface.co/)
- [Ollama](https://ollama.com/)
- [FastAPI](https://fastapi.tiangolo.com/)

---

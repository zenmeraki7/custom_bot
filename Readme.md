# 🤖 Chottu Bot – Bilingual Customer Support API

**Chottu** is an intelligent, bilingual (English + Manglish) customer support chatbot designed for **Zen Meraki Clothing Store**.

It combines **semantic search**, **sentiment-aware responses**, and **LLM fallback (Ollama)** to deliver fast, context-aware, and locally natural conversations.

---

## ✨ Key Features

- 🌐 **Bilingual Support** – Handles English and Manglish (Malayalam in English script)
- 🎯 **Sentiment-Aware Responses** – Detects tone and adapts replies
- 📚 **Hybrid FAQ Engine** – Semantic similarity + F1 token fallback
- 🧠 **LLM Fallback (Ollama)** – Handles off-topic + rephrasing
- 📊 **Analytics & Logging** – Tracks conversations and gaps
- 🚀 **Production-Ready API** – FastAPI with async support

---

## 🛠️ Tech Stack

| Layer | Technology |
|------|-----------|
| Backend API | FastAPI |
| Embeddings | sentence-transformers (`paraphrase-multilingual-MiniLM-L12-v2`) |
| Sentiment | XLM-RoBERTa (Hugging Face) |
| LLM | Ollama (`gemma3:4b`) |
| Data | Pandas |
| Acceleration | CUDA (optional) |

---

## 📁 Project Structure

```
AI_AGENT/
├── faqs/
│   ├── faqs.json
│   ├── english.json
│   └── manglish.json
├── shop_faqs/
├── static/
├── api.py
├── chat.py
├── faq_engine.py
├── nlp.py
├── chat_logs.csv
└── requirements.txt
```

---

## 🚀 Getting Started

### 1. Clone

```bash
git clone https://github.com/yourusername/chottu-bot.git
cd chottu-bot
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

---

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 4. Setup Ollama

```bash
ollama pull gemma3:4b
ollama serve
```

---

### 5. (Optional) Hugging Face Token

```bash
# Linux/Mac
export HF_TOKEN=hf_xxxxx

# Windows
set HF_TOKEN=hf_xxxxx
```

---

### 6. Run Server

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

---

### 7. Access

- UI → http://localhost:8000  
- Docs → http://localhost:8000/docs  

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|---------|------------|
| POST | `/chat` | Chatbot response |
| GET | `/health` | Health check |
| GET | `/faqs` | FAQ list |
| GET | `/stats` | Analytics |
| GET | `/logs/review` | LLM responses |
| GET | `/logs/escalations` | Escalations |
| GET | `/logs/bypass` | Non-FAQ |
| GET | `/` | UI |

---

## 📌 Example Request

```bash
curl -X POST http://localhost:8000/chat \
-H "Content-Type: application/json" \
-d '{"message": "Return policy enthu?"}'
```

---

## 📌 Example Response

```json
{
  "message": "Return policy enthu?",
  "lang": "manglish",
  "sentiment": "neutral",
  "reply": "Returns accepted within 7 days...",
  "source": "faq",
  "faq_score": 0.922,
  "escalate": false
}
```

---

## 🗂️ FAQ Formats

### Sentiment-Aware

```json
{
  "id": "return_001",
  "questions": {
    "neutral": ["What is return policy?"],
    "negative": ["Product defective"]
  },
  "answers": {
    "neutral": "Return within 7 days",
    "negative": "Sorry, contact support"
  }
}
```

---

### Flat FAQ

```json
{
  "id": "delivery_001",
  "question_variants": ["Delivery time?"],
  "answer": "2-3 working days"
}
```

---

## 📊 Logging

Stored in:

```
chat_logs.csv
```

Fields:

```
timestamp, message, lang, sentiment, reply, source, faq_score, escalate
```

---

## ⚙️ Config

| Variable | Default |
|---------|--------|
| FAQ_THRESHOLD | 0.35 |
| SEMANTIC_THRESHOLD | 0.60 |
| MANGLISH_BOOST | 1.15 |
| SENTIMENT_THRESHOLD | 0.65 |
| OLLAMA_MODEL | gemma3:4b |

---

## 🧪 Testing

- `/docs` (Swagger)
- Postman / Curl
- Browser UI

---

## 🔮 Future

- WhatsApp integration  
- Admin dashboard  
- Auto FAQ learning  
- Multi-store support  
- Voice chatbot  

---

## 📄 License

MIT

---

## 🙏 Credits

- sentence-transformers  
- Hugging Face  
- Ollama  
- FastAPI  

---

## 👨‍💻 Author

Built for scalable AI customer support 🚀

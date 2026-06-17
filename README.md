# 🛡️ ClauseNLP — Automated Unfair Clause Detection in Terms of Service

> **Know What You Agree To — Before You Click Accept**

![Python](https://img.shields.io/badge/Python-3.10-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-2.3-black?logo=flask)
![MongoDB](https://img.shields.io/badge/MongoDB-6.0-green?logo=mongodb)
![DistilBERT](https://img.shields.io/badge/DistilBERT-HuggingFace-yellow?logo=huggingface)
![Accuracy](https://img.shields.io/badge/Accuracy-80.14%25-brightgreen)

---

## 📌 About The Project

**ClauseNLP** is an AI-powered web application that automatically analyzes Terms of Service (ToS) agreements and explains them in plain English. Most people click *"I Agree"* without reading ToS documents — which can be 10,000+ words of dense legal jargon hiding clauses that sell your data, remove your legal rights, or allow account deletion without warning.

ClauseNLP reads them **for you** — in under 1.05 minutes(65 seconds).

---

## ✨ Features

- 🔍 **Automated ToS Discovery** — Enter any company name and the system finds their ToS URL automatically
- 🌐 **Smart Web Scraping** — Handles both normal HTML pages and JavaScript-rendered websites via Selenium
- 📄 **PDF Upload Support** — Upload a local ToS PDF for instant analysis
- 🤖 **AI Clause Classification** — Fine-tuned DistilBERT classifies every clause as **Risky**, **Moderate**, or **Safe**
- 📊 **Risk Score** — Weighted score from 0–100 indicating overall document risk
- 📝 **Plain English Summary** — Local LLaMA 3.2 3B generates human-readable explanations
- 💾 **MongoDB Database** — Caches analyzed companies for faster repeat queries
- 🔒 **Privacy-First** — All AI processing runs locally — no data sent to external servers

---

## 🧠 How It Works

```
User enters company name or uploads PDF
        ↓
[Discovery] → Finds ToS URL (cached lookup → path scan → DDG + Google search)
        ↓
[Scraping] → Downloads ToS page (BeautifulSoup + Selenium for JS pages)
        ↓
[Segmentation] → Splits document into individual clauses (max 300)
        ↓
[Classification] → DistilBERT classifies each clause (batch of 16)
        ↓
[Risk Scoring] → Score = (Risky×1.0 + Moderate×0.5) / Total × 100
        ↓
[Summary] → LLaMA 3.2 3B generates plain English report via Ollama
        ↓
[Output] → Risk score + warnings + summary shown to user
```

---

## 📈 Model Performance

| Model | Accuracy | Precision | Recall | F1 Score | Parameters | Inference |
|---|---|---|---|---|---|---|
| **DistilBERT (Ours)** | **80.14%** | **0.849** | **0.884** | **0.79** | **66M** | **~5 sec** |
| BERT-base | 79% | 0.845 | 0.866 | 0.78 | 110M | ~9 sec |
| Legal-BERT | 78% | 0.838 | 0.852 | 0.76 | 110M | ~11 sec |

> DistilBERT outperforms both BERT-base and Legal-BERT while using **40% fewer parameters** and running **2x faster** — making it the optimal choice for consumer hardware deployment.

---

## 🗂️ Risk Classification

| Label | Score Range | Meaning |
|---|---|---|
| ✅ Safe | < 50 / 100 | Standard fair clauses |
| ⚠️ Moderate | 50 – 55 / 100 | Worth knowing, not immediately harmful |
| 🔴 High Risk | > 55 / 100 | Directly threatens user rights |

**Risk Formula:**
```
Risk Score = (Risky × 1.0 + Moderate × 0.5) / Total Clauses × 100
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | HTML5, CSS3, JavaScript (Vanilla) |
| **Backend** | Python, Flask, Flask-CORS |
| **AI Model** | DistilBERT (HuggingFace Transformers + PyTorch) |
| **Summary LLM** | LLaMA 3.2 3B via Ollama (local) |
| **Database** | MongoDB (pymongo) |
| **Web Scraping** | BeautifulSoup, lxml, Selenium, requests |
| **PDF Extraction** | PyMuPDF (fitz) |
| **Search** | DuckDuckGo API (ddgs), Google Search |
| **Training Dataset** | ToSDR — 29,619 annotated ToS clauses |

---


## 🚀 Getting Started

### Prerequisites

- Python 3.10+
- MongoDB running locally
- Google Chrome (for Selenium)
- Ollama installed ([download here](https://ollama.com))

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/rohiterror58/ClauseNLP.git
cd ClauseNLP

# 2. Install Python dependencies
pip install flask flask-cors transformers torch pandas requests \
            beautifulsoup4 ddgs lxml pymupdf pymongo selenium \
            webdriver-manager google-generativeai

# 3. Pull the LLaMA model via Ollama
ollama pull llama3.2:3b

# 4. Start MongoDB
mongod

# 5. Run the application
python app.py
```

### Usage

Open your browser and go to:
```
http://localhost:5000
```

- Type any company name (e.g. `Google`, `Reddit`, `Spotify`) and click **Analyze Now**
- Or upload a ToS PDF directly
- Get risk score, clause breakdown, and plain English summary in under 30 seconds

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/analyze` | Analyze by company name `{"company": "google"}` |
| `POST` | `/analyze-pdf` | Analyze uploaded PDF file |
| `GET` | `/companies` | List all previously analyzed companies |
| `DELETE` | `/companies/<name>` | Remove a company from database |
| `GET` | `/result/<name>` | Retrieve cached result for a company |

**Example Request:**
```bash
curl -X POST http://localhost:5000/analyze \
     -H "Content-Type: application/json" \
     -d '{"company": "spotify"}'
```

**Example Response:**
```json
{
  "company": "spotify",
  "tos_url": "https://www.spotify.com/legal/end-user-agreement/",
  "risk_score": 60.31,
  "risk_label": "Moderate",
  "counts": {
    "total": 194,
    "risky": 81,
    "moderate": 72,
    "safe": 41
  },
  "summary": {
    "plain_english_summary": "...",
    "key_warnings": "...",
    "whats_normal": "...",
    "verdict": "..."
  }
}
```

---

## 📊 Sample Results

| Platform | Risk Score | Label | Clauses |
|---|---|---|---|
| Google | 54.41 | ⚠️ Moderate | 136 |
| TikTok | 72.35 | 🔴 High Risk | 201 |
| GitHub | 41.30 | ✅ Safe | 87 |
| Reddit | 51.22 | ⚠️ Moderate | 246 |
| DuckDuckGo | 32.10 | ✅ Safe | 74 |
| Spotify | 60.31 | ⚠️ Moderate | 194 |

---

## 🔬 Training Details

```
Base Model:        distilbert-base-uncased
Dataset:           ToSDR (Terms of Service; Didn't Read)
Training Samples:  29,619 annotated ToS clauses
Categories:        25 topic categories → mapped to 3 risk labels
Epochs:            3
Learning Rate:     2e-5
Batch Size:        64
Optimizer:         AdamW
Mixed Precision:   FP16
Final Accuracy:    80.14%
```

---

## 🚧 Limitations

- Accuracy is 80.14% — approximately 1 in 5 clauses may be misclassified
- Cloudflare-protected websites may block scraping even with Selenium
- Scanned image PDFs cannot be processed (text-layer PDFs only)
- LLaMA summary generation takes 60–120 seconds on CPU-only machines

---

## 🔭 Future Scope

- [ ] Multi-label clause classification for overlapping risk dimensions
- [ ] Multilingual support (mBERT / XLM-RoBERTa)
- [ ] Browser extension for real-time ToS analysis on any website
- [ ] ToS change detection — alert users when terms are updated
- [ ] Fine-tuned in-house summary model trained on ToS-specific data
- [ ] Mobile application support

---




---

## 🙏 Acknowledgements

- [ToSDR](https://tosdr.org) — for the annotated Terms of Service dataset
- [HuggingFace](https://huggingface.co) — for Transformers library and DistilBERT
- [Ollama](https://ollama.com) — for local LLM inference
- [Meta AI](https://ai.meta.com) — for LLaMA language model

---

## Model Download
Download the fine-tuned DistilBERT model from Google Drive:
[Download Model](your_drive_link_here)

After downloading:
1. Extract tos_risk_model_2.zip
2. Place the tos_risk_model_2 folder in the project root
3. Run python app.py


Access to trained Model G-Drive Link
https://drive.google.com/file/d/1tlfP1kov6Dn5dTNAyVrU_8S8ePOxXQwk/view?usp=sharing

<div align="center">
  <b>⭐ If this project helped you, please give it a star on GitHub!</b><br/>
  Built with ❤️ to protect your digital rights
</div>

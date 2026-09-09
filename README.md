# WeatherGPT 🌤️

> **SIH Problem Statement & Project Overview**: AI-Powered Multilingual Weather Intelligence Assistant for India  
> **Context**: Smart India Hackathon (SIH) Presentation & Production System  
> **Stack**: React 19 · FastAPI · LangGraph AI Agent · Groq 8-Model Cascade · TailwindCSS 3.4

![React](https://img.shields.io/badge/React-19.2-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![LangGraph](https://img.shields.io/badge/LangGraph-0.2.28-orange)
![Tailwind](https://img.shields.io/badge/Tailwind-3.4-blue)
![Groq](https://img.shields.io/badge/Groq_Cloud-GPT--OSS_120B-purple)

---

## 🌟 Key Features

- **Multi-Source Ensemble Fusion Engine** — Fuses telemetry in real-time across 5 meteorological providers (**Open-Meteo ECMWF/IMD standard model**, **WeatherAPI.com**, **Tomorrow.io**, **OpenWeatherMap**, **AccuWeather**) for high-precision weather metrics.
- **Conversational AI Agent (LangGraph)** — Stateful ReAct agent powered by **`openai/gpt-oss-120b`** and an **8-model Groq LLM cascade** (`gpt-oss-120b` → `qwen3.8-27b` → `qwen3.6-27b` → `gpt-oss-20b` → `gpt-oss-safeguard-20b` → `groq/compound` → `groq/compound-mini` → `allam-2-7b`) with smart Indic postposition city extraction (`kolkata ma`, `mumbai me`, `delhi nu`) and deterministic telemetry fallback for 0% downtime.
- **10 Indian Languages i18n Engine** — Full native script UI rendering and browser Web Speech API (TTS & STT) support for Hindi, Gujarati, Marathi, Tamil, Telugu, Bengali, Kannada, Malayalam, Punjabi, and English.
- **Agricultural Farmer Advisory Mode** — Crop-specific guidance (Wheat, Cotton, Rice, Sugarcane, Groundnut, Mustard, Vegetables) covering irrigation timing, pesticide spraying windows, thermal/frost stress, and harvest safety.
- **5-Day Environmental Risk Outlook Engine** — Automated hazard classification card (`RiskOutlookCard.jsx`) with 3-tier severity color coding (RED / YELLOW / GREEN) and threshold warning triggers.
- **Rich Interactive UI Widgets** — Markdown widget parser rendering dynamic React components (`widget:weather`, `widget:forecast`, `widget:alert`).
- **Developer Diagnostic Control Panel (`/dev`)** — A 9-tab developer view accessible via `/dev` or `Shift + D` key shortcut, featuring CPU/RAM profiling, multi-city stress testing, hazard simulator, and AI sandbox.
- **Live Interactive Windy GIS Map** — Embedded Windy map engine with 7 overlay toggles (wind, rain, temperature, clouds, radar, waves, pressure).

---

## 📌 Architecture Documentation

For complete technical specifications, data flows, API contracts, and SIH compliance matrix, refer to the official architecture annex:
- 📖 [**Architecture & Technical Specifications Annex (`Architecture.md`)**](file:///home/om/sih/frontend/Architecture.md)

---

## 🌐 Multi-Source Weather Providers & API Key Guide

WeatherGPT automatically blends active providers to compute weighted mean temperature, humidity, pressure, and wind speed.

| Provider | Environment Variable (Frontend / Backend) | Grid Resolution | Setup Guide |
| :--- | :--- | :--- | :--- |
| **Open-Meteo (Priority 1)** | *Built-in (Zero key required)* | 9 km (ECMWF / IMD standard) | **Default Base Source** — Free forever, no registration needed. [open-meteo.com](https://open-meteo.com) |
| **WeatherAPI.com** | `VITE_WEATHERAPI_KEY` / `WEATHERAPI_KEY` | ~1 km | Sign up at [weatherapi.com](https://www.weatherapi.com/signup.aspx). Free tier: **1,000,000 req/mo** |
| **Tomorrow.io** | `VITE_TOMORROW_KEY` / `TOMORROW_KEY` | 100 meters | Sign up at [tomorrow.io](https://www.tomorrow.io/weather-api/). Free tier: **500 req/day** |
| **OpenWeatherMap** | `VITE_OPENWEATHER_KEY` / `OPENWEATHER_KEY` | 1–5 km | Sign up at [openweathermap.org](https://home.openweathermap.org/users/sign_up). Free tier: **1,000 req/day** |
| **AccuWeather** | `VITE_ACCUWEATHER_KEY` / `ACCUWEATHER_KEY` | ~1 km | Sign up at [developer.accuweather.com](https://developer.accuweather.com/). Free tier: **50 req/day** |

---

## 🚀 Quick Start

### Prerequisites
- Node.js 18+
- Python 3.10+
- Groq API Key (Free at [console.groq.com](https://console.groq.com))

### 1. Backend Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env     # Set your GROQ_API_KEY
uvicorn main:app --reload --port 8888
```

### 2. Frontend Setup

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## 🏗️ Repository Structure

```
sih/
├── backend/                            # FastAPI Python Server
│   ├── main.py                         # FastAPI endpoints & logging middleware
│   ├── agent.py                        # LangGraph agent graph & model cascade
│   ├── tools.py                        # 14 Specialized AI telemetry tools
│   ├── imd_service.py                  # Public CAP alert feed & sample schemas
│   ├── requirements.txt                # Python backend dependencies
│   └── tests/
│       └── test_api.py                 # Automated pytest test suite
├── frontend/                           # React 19 Client SPA
│   ├── index.html                      # HTML entry point & font links
│   ├── package.json                    # Node dependencies & build scripts
│   ├── Architecture.md                 # SIH Architecture & Specifications Annex
│   └── src/
│       ├── main.jsx                    # Application mounting root
│       ├── App.jsx                     # Top-level view router & state
│       ├── api.js                      # Centralized API service layer
│       ├── views/
│       │   ├── WeatherChatView.jsx     # Main AI chat & weather dashboard
│       │   ├── MapView.jsx             # Interactive Windy GIS map view
│       │   ├── DevView.jsx             # 9-Tab developer diagnostic suite
│       │   ├── IMDHubView.jsx          # Official IMD feature explorer
│       │   └── ExcalidrawArchitectureView.jsx # Architecture diagram viewer
│       ├── components/
│       │   ├── Sidebar.jsx             # Navigation drawer & crop selector
│       │   ├── LocationPickerModal.jsx # GPS & city search modal
│       │   ├── LanguagePickerModal.jsx # 10-language selector modal
│       │   ├── RiskOutlookCard.jsx     # 5-day risk assessment card
│       │   ├── PromptRotator.jsx       # Dynamic regional prompt suggestions
│       │   └── WeatherMarquee.jsx      # Multi-city weather marquee ticker
│       └── utils/
│           ├── ensembleEngine.js       # Multi-source weather fusion engine
│           ├── location.js             # GPS / IP / Reverse geocoding module
│           ├── speechEngine.js         # Web Speech API wrapper
│           └── translations.js         # 10-Language i18n translation dictionary
├── AGENT.md                            # Agent developer guidelines
└── README.md                           # Project documentation
```

---

## 🧪 Running Tests

### Backend Test Suite

```bash
cd backend
pytest
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

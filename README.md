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

- **Multi-Source Ensemble Fusion Engine** — Fuses telemetry in real-time across 5 meteorological providers with priority **Open-Meteo (ECMWF/IMD, 2.0×) > AccuWeather (1.5×) > WeatherAPI.com / Tomorrow.io (1.2×) > OpenWeatherMap (1.1×)**. The engine runs server-side (`backend/services/fusion.py`) and is shared by the web app and the Android app (`omsenjalia/weathergpt-app`).
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

WeatherGPT automatically blends active providers (queried in parallel, outliers > 7 °C from the Open-Meteo baseline excluded) to compute weighted mean temperature, humidity, pressure, and wind speed. Inspect it live at `GET /fusion?lat=&lon=`.

| Provider | Environment Variable (Frontend / Backend) | Grid Resolution | Setup Guide |
| :--- | :--- | :--- | :--- |
| **Open-Meteo (Priority 1)** | *Built-in (Zero key required)* | 9 km (ECMWF / IMD standard) | **Default Base Source** — Free forever, no registration needed. [open-meteo.com](https://open-meteo.com) |
| **WeatherAPI.com** | `VITE_WEATHERAPI_KEY` / `WEATHERAPI_KEY` | ~1 km | Sign up at [weatherapi.com](https://www.weatherapi.com/signup.aspx). Free tier: **1,000,000 req/mo** |
| **Tomorrow.io** | `VITE_TOMORROW_KEY` / `TOMORROW_KEY` | 100 meters | Sign up at [tomorrow.io](https://www.tomorrow.io/weather-api/). Free tier: **500 req/day** |
| **OpenWeatherMap** | `VITE_OPENWEATHER_KEY` / `OPENWEATHER_KEY` | 1–5 km | Sign up at [openweathermap.org](https://home.openweathermap.org/users/sign_up). Free tier: **1,000 req/day** |
| **AccuWeather** | `ACCUWEATHER_KEY` (server-side; avoid `VITE_`) | ~1 km | New portal at [developer.accuweather.com](https://developer.accuweather.com/). **No free tier since 2025-09-09** — 14-day trial (**500 req/day**), then Starter **$2/mo** (15,000 req/month, 5-day forecasts). Auth is `Authorization: Bearer <key>` |

### ⚠️ AccuWeather stopped working? (portal migration, 9 Sep 2025)

AccuWeather replaced its developer portal (Apigee → Zuplo/Akamai) on **2025-09-09** and, in the
same change, **retired every legacy API key** and **ended the free tier**. The practical effects:

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| `401 Unauthorized` / `"API authorization failed"` | Key was issued by the legacy portal, or is being sent as `?apikey=` | Issue a new key at [developer.accuweather.com](https://developer.accuweather.com) and keep `ACCUWEATHER_AUTH_MODE=bearer` (default) |
| `403 Forbidden` | The plan does not sell that endpoint — Starter/Standard cap daily forecasts at **5 days** (10 needs Prime, 15 needs Elite) | Set `ACCUWEATHER_MAX_FORECAST_DAYS=5`; the backend also auto-retries the 5-day endpoint on a 403 |
| `429` / quota exceeded | 14-day trial (500 calls/day) expired, or the 15,000 calls/month Starter budget is gone | Upgrade, or leave `ACCUWEATHER_KEY` unset and let Open-Meteo serve the request |
| Browser console `CORS` error | `dataservice.accuweather.com` is not a browser endpoint for every plan | Do not set `VITE_ACCUWEATHER_KEY`; use the server-side proxy (`GET /fusion`) |

If you do re-enable AccuWeather, note its **branding requirement**: the AccuWeather logo, linked to
[accuweather.com](https://www.accuweather.com/), must appear on every screen where its data is shown.

WeatherGPT never hard-fails on any of these: `auto` mode records a structured `fallback_reason`
(`invalid_credentials`, `subscription_limit`, `rate_limited`) and falls through to Open-Meteo, and a
rejected key is latched out for `ACCUWEATHER_CREDENTIAL_COOLDOWN_SECONDS` (default 900 s) so it cannot
add latency to every request. Diagnose live with `GET /v2/weather/health` or `GET /dev` →
`accuweather.diagnostics` (auth mode, plan horizon, last upstream error, latch state — never the key).

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

## Dual clients (web + mobile)

One backend deployment serves both:

| Client | Repo | Primary endpoints |
|--------|------|-------------------|
| Web | `weathergpt` | `POST /chat`, `GET /dev`, `POST /dev/sandbox` |
| Mobile | `weathergpt-app` | `GET /weather`, `POST /chat`, `/advisory`, `/historical`, `/comparison` |

Point both apps at the same `BACKEND_URL` / `VITE_API_URL` (e.g. `https://weathergpt-backend.vercel.app`).

`POST /chat` accepts web message history **or** a mobile single `message`, plus optional `lat`/`lon` from the app.

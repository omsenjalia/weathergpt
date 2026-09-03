# WeatherGPT 🌤️

A premium dark glassmorphism weather assistant for India featuring conversational AI, animated weather backgrounds, multi-view navigation, and a **Multi-Source Ensemble Fusion Weather Engine**.

![React](https://img.shields.io/badge/React-18-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![Tailwind](https://img.shields.io/badge/Tailwind-3.4-blue)
![Framer Motion](https://img.shields.io/badge/Framer_Motion-11-purple)

---

## 🌟 Key Features

- **Multi-Source Ensemble Weather Engine** — Fuses telemetry in real-time across top meteorological providers (**Open-Meteo ECMWF/GFS**, **WeatherAPI.com**, **Tomorrow.io**, **OpenWeatherMap**, **AccuWeather**) for unmatched precision.
- **Zero-Config Out-of-the-Box** — Works instantly using free high-precision physics models (ECMWF, ICON, GFS) with zero API keys required.
- **In-App & `.env` Key Manager** — Add optional provider keys via `.env` OR directly inside a sleek in-app **API Settings Modal** stored in browser `localStorage`.
- **Conversational AI Weather** — Ask about weather in any Indian city in English, Hindi, Gujarati, Tamil, Bengali, Telugu, Marathi, Kannada, Malayalam, Punjabi, etc.
- **Fully Accessible Mobile UX** — Header hamburger navigation drawer + floating bottom dock (auto-hides on Chat view for unobstructed chat input).
- **Official IMD Hazard Advisories** — Evaluates live weather telemetry against India Meteorological Department (IMD) Red, Orange, and Yellow alert criteria.
- **Live Animated Weather Map** — Windy.com map integration for real-time wind and radar visualization.

---

## 🌐 Multi-Source Weather Providers & API Key Guide

WeatherGPT automatically blends active providers to compute a weighted temperature, humidity, pressure, and wind mean, while applying max-risk rain prediction logic.

### Environment Variable Names & Provider Guide

| Provider | Environment Variable (Frontend / Backend) | Update Refresh Rate | Grid Resolution | Key Setup Guide & Link |
| :--- | :--- | :--- | :--- | :--- |
| **Open-Meteo** | *Built-in (No key needed)* | Hourly / 6h | 9 km (ECMWF) / 7 km (ICON) | **Default Base Engine** — Free forever, zero configuration required. [open-meteo.com](https://open-meteo.com) |
| **WeatherAPI.com** | `VITE_WEATHERAPI_KEY` / `WEATHERAPI_KEY` | 10–15 mins | ~1 km | 1. Sign up at [weatherapi.com/signup](https://www.weatherapi.com/signup.aspx)<br>2. Copy your API Key from Dashboard<br>3. Free Tier: **1,000,000 requests/month** |
| **Tomorrow.io** | `VITE_TOMORROW_KEY` / `TOMORROW_KEY` | 1–15 mins | 100 meters | 1. Sign up at [tomorrow.io/weather-api](https://www.tomorrow.io/weather-api/)<br>2. Copy your API key from your developer portal<br>3. Free Tier: **500 requests/day** |
| **OpenWeatherMap** | `VITE_OPENWEATHER_KEY` / `OPENWEATHER_KEY` | 10 mins | 1–5 km | 1. Sign up at [openweathermap.org](https://home.openweathermap.org/users/sign_up)<br>2. Generate an API key under API Keys section<br>3. Free Tier: **1,000 requests/day** |
| **AccuWeather** | `VITE_ACCUWEATHER_KEY` / `ACCUWEATHER_KEY` | Real-time | ~1 km | 1. Create an account at [developer.accuweather.com](https://developer.accuweather.com/)<br>2. Create an App under "My Apps" to obtain an API Key<br>3. Free Tier: **50 requests/day** |

---

## 🛠️ Environment Variables Reference

### Backend (`backend/.env`)

```env
# Required for AI Chatbot
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=qwen/qwen3.8-27b  # Optional override model

# Optional Multi-Provider Keys (Ensemble Weather Agent)
WEATHERAPI_KEY=your_weatherapi_key
TOMORROW_KEY=your_tomorrow_key
OPENWEATHER_KEY=your_openweather_key
ACCUWEATHER_KEY=your_accuweather_key
```

### Frontend (`frontend/.env`)

```env
# Backend API Endpoint URL
VITE_API_URL=http://localhost:8888

# Optional Multi-Provider Keys (Frontend Ensemble Engine)
VITE_WEATHERAPI_KEY=your_weatherapi_key
VITE_TOMORROW_KEY=your_tomorrow_key
VITE_OPENWEATHER_KEY=your_openweather_key
VITE_ACCUWEATHER_KEY=your_accuweather_key

# Optional Map Key
VITE_WINDY_API_KEY=your_windy_key
```

> 💡 **Tip**: You don't have to edit `.env` files if you don't want to! Simply click the **API Keys** button in the WeatherGPT UI header/sidebar to enter keys directly into the app settings modal.

---

## 🚀 Quick Start

### Prerequisites
- Node.js 18+
- Python 3.10+
- Groq API Key (Free at [console.groq.com](https://console.groq.com))

### 1. Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env     # Add your GROQ_API_KEY
uvicorn main:app --reload --port 8888
```

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## 🏗️ Architecture & Project Structure

```
weathergpt/
├── backend/
│   ├── main.py          # FastAPI server (/chat and /health endpoints)
│   ├── agent.py         # LangGraph ReAct agent with Groq LLM
│   ├── tools.py         # Multi-source weather tools & geocoding
│   └── requirements.txt # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── App.jsx                   # Root layout, routing & mobile header menu
│   │   ├── api.js                    # API client & IMD alert evaluator
│   │   ├── utils/
│   │   │   ├── ensembleEngine.js     # Multi-Source Telemetry Fusion Engine
│   │   │   └── translations.js       # Multilingual translations
│   │   ├── views/
│   │   │   ├── WeatherHome.jsx       # Weather dashboard with fused telemetry chips
│   │   │   ├── ChatView.jsx          # AI conversation interface
│   │   │   ├── VoiceView.jsx         # Voice assistant
│   │   │   └── MapView.jsx           # Animated Windy map
│   │   └── components/
│   │       ├── ApiSettingsModal.jsx  # In-app API Key Settings Modal
│   │       ├── LocationPickerModal.jsx
│   │       ├── LanguagePickerModal.jsx
│   │       ├── BottomDock.jsx
│   │       └── Sidebar.jsx
└── README.md
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

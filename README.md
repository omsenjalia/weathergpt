# WeatherGPT 🌤️

A premium dark glassmorphism weather assistant for India with conversational AI, animated weather backgrounds, and multi-view navigation.

![React](https://img.shields.io/badge/React-18-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![Tailwind](https://img.shields.io/badge/Tailwind-3.4-blue)
![Framer Motion](https://img.shields.io/badge/Framer_Motion-11-purple)

## Features

- **Conversational AI Weather** — Ask about weather in any Indian city in English, Hindi, Gujarati, Tamil, Bengali, Telugu, or Marathi
- **Premium Dark UI** — Glassmorphism design with animated aurora background
- **4 Views** — Weather dashboard, AI chat, voice input, live Windy map
- **macOS-style Dock** — Floating dock with magnification on mobile
- **Hamburger Sidebar** — Smooth slide-in navigation on desktop
- **Animated Transitions** — Framer Motion page transitions and blur-in text effects
- **Voice Input** — Web Speech API with Hindi/English toggle
- **Real-time Weather Data** — Open-Meteo API with hourly and 7-day forecasts

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18, Vite, Tailwind CSS, Framer Motion |
| Backend | FastAPI, LangGraph, LangChain, Groq (Llama 3.3 70B) |
| Weather API | Open-Meteo (free, no API key required) |
| Map | Windy.com animated weather map |
| Voice | Web Speech API (browser native) |

## Project Structure

```
weathergpt/
├── backend/
│   ├── main.py          # FastAPI server with /chat and /health endpoints
│   ├── agent.py         # LangGraph ReAct agent with Groq LLM
│   ├── tools.py         # Weather tools: geocode, current weather, forecast
│   ├── requirements.txt # Python dependencies
│   └── .env.example     # Environment variables template
├── frontend/
│   ├── src/
│   │   ├── App.jsx           # Root component with view routing
│   │   ├── main.jsx          # React entry point
│   │   ├── index.css         # Global styles, glassmorphism utility
│   │   ├── api.js            # API client for backend and weather services
│   │   ├── views/
│   │   │   ├── WeatherHome.jsx  # Main weather dashboard
│   │   │   ├── ChatView.jsx     # AI conversation interface
│   │   │   ├── VoiceView.jsx    # Voice input with speech recognition
│   │   │   └── MapView.jsx      # Windy animated weather map
│   │   └── components/
│   │       ├── BottomDock.jsx   # Mobile floating dock navigation
│   │       ├── Sidebar.jsx      # Desktop hamburger sidebar
│   │       └── bits/
│   │           ├── Aurora.jsx           # Animated gradient background
│   │           ├── BlurText.jsx         # Blur-in text animation
│   │           ├── AnimatedContent.jsx  # Fade + slide wrapper
│   │           └── Dock.jsx             # macOS-style magnification dock
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   └── postcss.config.js
└── README.md
```

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+
- Groq API key (free at [console.groq.com](https://console.groq.com))
- Windy API key (free at [api.windy.com](https://api.windy.com))

### Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env  # Add your GROQ_API_KEY
uvicorn main:app --reload --port 8888
```

### Frontend Setup

```bash
cd frontend
npm install
cp .env.example .env  # Add your VITE_WINDY_API_KEY
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

## Deploying to Vercel

Deploy this repository as two separate Vercel projects:

### Frontend project

- Set **Root Directory** to `frontend`.
- Use the detected Vite framework, `npm ci` as the install command, `npm run build` as the build command, and `dist` as the output directory.
- Set `VITE_API_URL` to the deployed backend origin, for example `https://your-backend.vercel.app`.
- Set `VITE_WINDY_API_KEY` if the map view is enabled.

### Backend project

- Set **Root Directory** to `backend`.
- Vercel uses `api/index.py` as the Python function entrypoint.
- Add `GROQ_API_KEY` to the backend project environment variables. Add `GROQ_MODEL` only when overriding the default model.
- Verify `https://your-backend.vercel.app/health` returns `{\"status\":\"ok\"}` before configuring `VITE_API_URL`.

The projects intentionally have separate `vercel.json` files; do not use the removed root-level service routing configuration.

## Environment Variables

### Backend (.env)

| Variable | Description | Required |
|----------|-------------|----------|
| `GROQ_API_KEY` | API key from console.groq.com | Yes |
| `OPENWEATHER_API_KEY` | OpenWeatherMap API key | No (uses Open-Meteo) |

### Frontend (.env)

| Variable | Description | Required |
|----------|-------------|----------|
| `VITE_WINDY_API_KEY` | API key from api.windy.com | No (map won't load without it) |

## Test Queries

1. **English**: "What is the weather in Mumbai today?"
2. **Hindi**: "आज दिल्ली में मौसम कैसा है?"
3. **Voice**: Tap mic → say "Will it rain in Ahmedabad this week?"
4. **Map**: Navigate to Map view for animated wind data
5. **Home**: Auto-loads weather for your current location

## Features in Detail

### Weather Dashboard
- Auto-detects location via browser geolocation
- Falls back to New Delhi if location access denied
- Current temperature with blur-in animation
- Hourly forecast (24 hours) with horizontal scroll
- 7-day forecast with weather icons
- City search with geocoding

### AI Chat
- Multilingual support (7 Indian languages)
- Automatic language detection
- Safety advisories for severe weather
- Glassmorphism message bubbles
- Loading animation with pulsing dots

### Voice Assistant
- Web Speech API (Chrome, Edge)
- Hindi/English language toggle
- Real-time transcript display
- Send voice query to chat

### Live Weather Map
- Windy.com integration
- Animated wind patterns
- Interactive map controls

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   React UI  │────▶│  FastAPI    │────▶│  Groq LLM   │
│  (Vite)     │◀────│  Backend    │◀────│  Llama 3.3   │
└─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Open-Meteo │
                    │  Weather API│
                    └─────────────┘
```

### Backend Flow
1. User sends message via POST /chat
2. LangGraph agent detects language
3. Agent calls geocode_city to get coordinates
4. Agent calls get_current_weather and/or get_weather_forecast
5. Agent formats response with safety advisories
6. Response returned in user's detected language

### Frontend Flow
1. App.jsx manages view state (home/chat/voice/map)
2. Aurora background renders on all views
3. WeatherHome fetches weather on mount via geolocation
4. ChatView sends messages to backend API
5. VoiceView uses Web Speech API for transcription
6. MapView initializes Windy map widget

## Custom React Bits

All animation components are implemented from scratch (no npm):

- **Aurora** — Full-screen animated gradient background with 3 floating orbs
- **BlurText** — Word-by-word blur-in entrance animation
- **AnimatedContent** — Fade + slide wrapper with directional control
- **Dock** — macOS-style floating dock with cursor-tracking magnification

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | Send message to weather AI |
| GET | `/health` | Health check |

### POST /chat

**Request:**
```json
{
  "message": "What is the weather in Mumbai?",
  "location": "Mumbai, India"
}
```

**Response:**
```json
{
  "response": "Currently in Mumbai, it's 32°C with partly cloudy skies..."
}
```

## Known Limitations

- Voice input requires Chrome/Edge browser
- Windy map requires API key (free tier available)
- Geolocation must be enabled for auto-location
- Backend LLM response time: 2-5 seconds

## Contributing

1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open Pull Request

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [Open-Meteo](https://open-meteo.com/) — Free weather API
- [Groq](https://groq.com/) — Fast LLM inference
- [Windy](https://www.windy.com/) — Animated weather maps
- [LangChain](https://www.langchain.com/) — LLM framework
- [LangGraph](https://github.com/langchain-ai/langgraph) — Agent orchestration
- [Framer Motion](https://www.framer.com/motion/) — React animations

---

Built with ❤️ for Smart India Hackathon

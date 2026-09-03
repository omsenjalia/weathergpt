# AGENT.md — WeatherGPT Codebase Intelligence

> **Purpose**: This file provides comprehensive context for AI coding agents (Claude, Gemini, GPT, Copilot, etc.) working on the WeatherGPT codebase. Read this before making any changes.

---

## Project Overview

**WeatherGPT** is a premium, multilingual AI-powered weather assistant built for the **Smart India Hackathon (SIH)**. It provides real-time weather data, conversational AI chat, voice input, and live animated weather maps — all wrapped in a dark glassmorphism UI with animated aurora backgrounds.

- **Domain**: Weather intelligence for India (all major cities, 10 Indian languages)
- **Users**: Indian citizens seeking weather information in their native language
- **Deployment**: Local dev (Vite + FastAPI); designed for production on any cloud

---

## Tech Stack

| Layer        | Technology                                                              |
| ------------ | ----------------------------------------------------------------------- |
| **Frontend** | React 18, Vite 8, Tailwind CSS 3.4, Framer Motion 11                   |
| **Backend**  | Python 3.10+, FastAPI 0.115, LangGraph 0.2, LangChain, Groq (Qwen3.8) |
| **Weather**  | Open-Meteo API (free, no key), Open-Meteo Air Quality API              |
| **Map**      | Windy.com embed (free tier, optional API key)                           |
| **Voice**    | Web Speech API (browser-native, Chrome/Edge)                            |
| **Geocoding**| Open-Meteo Geocoding API, Nominatim (reverse geocoding)                 |
| **Icons**    | Lucide React                                                            |
| **Markdown** | react-markdown + remark-gfm (for chat message rendering)               |

---

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌───────────────┐
│   React SPA     │────▶│  FastAPI Server  │────▶│   Groq LLM    │
│   (Vite dev)    │◀────│  (port 8888)     │◀────│  Qwen3.8-27B  │
│   port 5173     │     └────────┬─────────┘     └───────────────┘
└─────────────────┘              │
        │                        ▼
        │                 ┌─────────────┐
        │                 │  Open-Meteo  │  (geocode, weather, forecast)
        │                 └─────────────┘
        │
        ├──▶ Open-Meteo (direct weather fetch for dashboard)
        ├──▶ Open-Meteo Air Quality API
        ├──▶ Windy.com embed (map iframe)
        └──▶ Nominatim / ipapi.co (reverse geocoding / IP fallback)
```

### Data Flow

1. **Weather Dashboard** (`WeatherHome.jsx`): Fetches weather directly from Open-Meteo via `api.js` — does NOT go through the backend.
2. **AI Chat** (`ChatView.jsx`): Sends full conversation history to `POST /chat` → LangGraph agent calls tools → returns Markdown + JSON widget blocks.
3. **Voice** (`VoiceView.jsx`): Captures speech via Web Speech API → sends transcript to ChatView.
4. **Map** (`MapView.jsx`): Embeds Windy.com iframe with configurable overlay layers.

---

## Project Structure

```
sih/
├── backend/
│   ├── main.py              # FastAPI app: /chat and /health endpoints
│   ├── agent.py             # LangGraph ReAct agent with Groq LLM
│   ├── tools.py             # @tool functions: geocode, weather, forecast, language detect
│   ├── requirements.txt     # Pinned Python dependencies
│   ├── .env.example         # Template: GROQ_API_KEY, GROQ_MODEL
│   └── .env                 # (gitignored) Actual secrets
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx              # Root: view routing, location/language state, modals
│   │   ├── main.jsx             # React entry point
│   │   ├── index.css            # Global styles: glass utility, fonts, responsive helpers
│   │   ├── api.js               # API client: sendMessage, getWeatherByCoords, geocodeCity, getAirQuality, getIMDAlertBulletin
│   │   │
│   │   ├── views/
│   │   │   ├── WeatherHome.jsx  # Full dashboard: hero card, AQI, UV, wind compass, sun cycle, hourly, 7/14-day forecast
│   │   │   ├── ChatView.jsx     # AI chat: rich Markdown rendering, widget:weather/forecast/alert JSON blocks
│   │   │   ├── VoiceView.jsx    # Voice input: Web Speech API, language toggle, send-to-chat
│   │   │   └── MapView.jsx      # Windy embed with 7 overlay layer buttons
│   │   │
│   │   ├── components/
│   │   │   ├── Sidebar.jsx            # Desktop sidebar: nav, location/language controls
│   │   │   ├── BottomDock.jsx         # Mobile bottom dock navigation
│   │   │   ├── LocationPickerModal.jsx # GPS detect, search, 10 popular Indian cities
│   │   │   ├── LanguagePickerModal.jsx # 10 Indian language picker grid
│   │   │   └── bits/
│   │   │       ├── Aurora.jsx         # Animated gradient background (3 floating orbs)
│   │   │       ├── BlurText.jsx       # Word-by-word blur-in entrance animation
│   │   │       ├── AnimatedContent.jsx # Fade + slide wrapper (directional)
│   │   │       └── Dock.jsx           # macOS-style magnification dock
│   │   │
│   │   └── utils/
│   │       └── translations.js  # i18n: 10 languages × 30+ keys, translateCondition()
│   │
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js    # Custom: accent (#a78bfa), Syne + DM Sans fonts
│   └── postcss.config.js
│
├── .gitignore
├── README.md
└── AGENT.md                  # ← You are here
```

---

## Key Design Decisions & Conventions

### Frontend

1. **No React Router**: Views are switched via `activeView` state in `App.jsx` (`home | chat | map`). This is intentional — keeps the app as an SPA without URL-based routing.

2. **Lifted Chat State**: `chatMessages` state lives in `App.jsx` and is passed down to `ChatView`. This preserves conversation history when switching between views.

3. **Glassmorphism Design System**: The `.glass` CSS class (defined in `index.css`) is the core visual primitive — frosted glass with `backdrop-filter: blur(20px)` and a fallback for unsupported browsers.

4. **Accent Color**: `#a78bfa` (violet-400). Defined in `tailwind.config.js` as `accent`. Used throughout for highlights, buttons, and active states. Secondary: `accent-dim` = `#7c3aed`.

5. **Typography**: Display font = `Syne` (headings, `.font-display`). Body font = `DM Sans` (everything else). Both loaded from Google Fonts in `index.html`.

6. **Responsive Strategy**:
   - **Desktop**: Sidebar (`md:flex`, hidden on mobile) + full content area
   - **Mobile**: Bottom Dock (`md:hidden`) + collapsible header controls
   - Touch targets enforce `min-height: 44px` via `.touch-target` class

7. **Animation Components** (in `components/bits/`): All hand-written, no external animation libraries beyond Framer Motion:
   - `Aurora` — 3 floating gradient orbs with infinite `scale` + `x` animation
   - `BlurText` — word-by-word `filter: blur()` → `blur(0)` entrance
   - `AnimatedContent` — fade + slide (configurable direction/delay)
   - `Dock` — macOS magnification dock (cursor-tracking scale)

8. **Widget System in Chat**: The LLM outputs fenced code blocks like ` ```widget:weather ``` `, ` ```widget:forecast ``` `, ` ```widget:alert ``` ` containing JSON. `ChatView.jsx` parses these in the custom `code` renderer of `ReactMarkdown` and renders rich interactive cards (`ChatWeatherWidget`, `ChatForecastWidget`, `ChatAlertWidget`).

9. **IMD Alert System**: `api.js` → `getIMDAlertBulletin()` computes alert levels (GREEN/YELLOW/ORANGE/RED) based on thresholds for temperature, wind, rain probability, UV index, and AQI. This mirrors India Meteorological Department (IMD) alert tiers.

10. **Translations**: All UI strings are translated in `utils/translations.js` for 10 languages: English, Hindi, Gujarati, Marathi, Tamil, Telugu, Bengali, Kannada, Malayalam, Punjabi. Access via `Translations.get(langCode, key)`. Weather condition codes are translated via `translateCondition(code, langCode)`.

11. **LocalStorage Persistence**: Location, language, and favorite cities are stored in `localStorage` keys:
    - `weathergpt_location` (JSON: `{name, country, lat, lon}`)
    - `weathergpt_language` (JSON: `{code, name, native, speechCode}`)
    - `weathergpt_favorites` (JSON array of location objects)

### Backend

1. **LangGraph ReAct Agent**: The agent graph (`agent.py`) is compiled once at module load time (`_build_graph()` → `_app`). It follows a simple `agent → tools → agent → END` loop. Do not rebuild the graph per-request.

2. **LLM Model**: Default is `qwen/qwen3.8-27b` via Groq. Configurable via `GROQ_MODEL` env var. Chosen because Qwen3 natively supports 119 languages including all major Indian languages.

3. **Tools** (defined in `tools.py`):
   - `geocode_city(city_name)` → `{latitude, longitude, city, country, state}`
   - `get_current_weather(latitude, longitude)` → current conditions dict
   - `get_weather_forecast(latitude, longitude, days)` → daily forecast list
   - `get_user_language(text)` → detects language using `langdetect`

4. **System Prompt**: The agent is instructed to:
   - Respond in the user's detected language using native script
   - Always call `geocode_city` before weather tools
   - Embed `widget:weather`, `widget:forecast`, `widget:alert` JSON blocks for rich UI rendering
   - Provide safety advisories for severe weather

5. **API Contract**:
   ```
   POST /chat
   Request:  { message: str, messages: [{ role, content }], location: str, language: str }
   Response: { response: str }
   
   GET /health
   Response: { status: "ok" }
   ```

6. **CORS**: Wide open (`allow_origins=["*"]`). Tighten for production.

7. **Weather Code Handling**: Open-Meteo renamed `weathercode` → `weather_code`. The codebase handles both naming conventions via `_extract_weather_code()` and fallback `daily.get("weather_code", daily.get("weathercode", []))`.

---

## Environment Variables

### Backend (`backend/.env`)

| Variable            | Required | Default               | Description                                          |
| ------------------- | -------- | --------------------- | ---------------------------------------------------- |
| `GROQ_API_KEY`      | **Yes**  | —                     | API key from [console.groq.com](https://console.groq.com) |
| `GROQ_MODEL`        | No       | `qwen/qwen3.8-27b`   | Groq model ID. Must be accessible by your key.       |

### Frontend (`frontend/.env`)

| Variable                 | Required | Default                    | Description                                               |
| ------------------------ | -------- | -------------------------- | --------------------------------------------------------- |
| `VITE_WINDY_API_KEY`     | No       | —                          | Windy Map Forecast API key (map won't load without it)    |
| `VITE_OPENWEATHER_API_KEY` | No     | —                          | OpenWeatherMap key (for tile layers, currently unused)     |
| `VITE_API_URL`           | No       | `http://localhost:8888`    | Backend URL override for staging/prod                     |

---

## Running Locally

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # Add your GROQ_API_KEY
uvicorn main:app --reload --port 8888
```

### Frontend
```bash
cd frontend
npm install
cp .env.example .env     # Optionally add VITE_WINDY_API_KEY
npm run dev              # Starts on http://localhost:5173
```

---

## Common Modification Patterns

### Adding a New View
1. Create `frontend/src/views/NewView.jsx`
2. Add to the `views` object in `App.jsx`
3. Add navigation entry in `Sidebar.jsx` (`navItems` array) and `BottomDock.jsx`
4. Add translation keys to `utils/translations.js` for all 10 languages

### Adding a New Language
1. Add entry to `INDIAN_LANGUAGES` array in `LanguagePickerModal.jsx`
2. Add translation block in `utils/translations.js`
3. Add language mapping in `backend/tools.py` → `get_user_language()` → `language_map`

### Adding a New Weather Tool
1. Define a `@tool` function in `backend/tools.py`
2. Add it to the `TOOLS` list in `backend/agent.py`
3. Update the system prompt in `agent.py` if the agent needs specific instructions

### Adding a New Chat Widget
1. Define the widget component in `ChatView.jsx` (e.g., `ChatNewWidget`)
2. Add the widget type to the regex in the `code` renderer: `widget:(weather|forecast|alert|new)`
3. Instruct the LLM in the system prompt to emit ` ```widget:new ``` ` blocks

### Adding a New Dashboard Card
1. Add the card JSX in `WeatherHome.jsx` inside the appropriate grid column
2. Wrap it in `<AnimatedContent>` for entrance animation
3. Use the `.glass` class + `rounded-3xl` for consistent styling

---

## Code Style & Patterns

### Frontend
- **Functional components only** — no class components
- **Hooks**: `useState`, `useEffect`, `useRef` — no Redux, no Zustand
- **Named exports** for sub-components, **default export** for view/page components
- **Tailwind CSS** for all styling — no inline styles except dynamic values
- **Framer Motion** for animations — `motion.div`, `AnimatePresence`, `whileHover`/`whileTap`
- **Lucide icons** — import individually: `import { Sun, Cloud } from 'lucide-react'`
- **No semicolons** in JSX files (consistent codebase convention)
- **Single quotes** for JS strings

### Backend
- **Type hints** everywhere — `def func(param: str) -> dict:`
- **Pydantic models** for request/response schemas
- **`@tool` decorator** from LangChain for agent tools
- **`httpx.Client`** (sync) with `timeout=10` for external API calls inside tools
- **`run_in_threadpool`** to run sync agent code from async FastAPI endpoints
- **`dotenv`** loaded at module top before any imports that need env vars

---

## Known Issues & Gotchas

1. **VoiceView `lang` variable bug**: `VoiceView.jsx` references an undefined `lang` variable in `toggleListening()` and the language toggle buttons. Should use `activeLangCode` instead. The voice view works but the language toggle is non-functional.

2. **Open-Meteo API field naming**: The API accepts both `weathercode` and `weather_code` in requests but returns whichever name you sent. Always handle both in response parsing.

3. **Groq model availability**: The default model `qwen/qwen3.8-27b` may not be available on all Groq accounts. Check available models with:
   ```bash
   curl https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"
   ```

4. **CORS is wide open**: `allow_origins=["*"]` in `main.py`. Must be restricted for production.

5. **No error boundaries**: Frontend has no React error boundaries. A crash in any view will white-screen the app.

6. **No rate limiting**: Backend has no rate limiting on `/chat`. Groq has its own rate limits.

7. **Stale `-l` file**: There's an untracked `-l` file in the repo root — this is a shell artifact and should be deleted/gitignored.

8. **Voice requires HTTPS**: Web Speech API requires `https://` or `localhost`. Won't work on plain HTTP deployments.

---

## Testing

### Manual Test Queries
1. English: "What is the weather in Mumbai today?"
2. Hindi: "आज दिल्ली में मौसम कैसा है?"
3. Gujarati: "અમદાવાદમાં આજે હવામાન કેવું છે?"
4. Dashboard: Navigate to Weather Home → verify temperature, AQI, UV index, hourly, 7-day forecast all render
5. Map: Switch overlay layers (Wind, Rain, Temperature, Clouds, Radar, Waves, Pressure)
6. Location: Use GPS detect, manual search, and popular city quick-pick

### Health Check
```bash
curl http://localhost:8888/health
# → {"status":"ok"}
```

### Chat API Test
```bash
curl -X POST http://localhost:8888/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Weather in Mumbai?", "location": "Mumbai, India", "language": "English"}'
```

---

## Dependencies Summary

### Frontend (`package.json`)
| Package          | Purpose                                    |
| ---------------- | ------------------------------------------ |
| `react`          | UI framework                               |
| `react-dom`      | React DOM renderer                         |
| `axios`          | HTTP client for API calls                  |
| `framer-motion`  | Animations and transitions                 |
| `lucide-react`   | SVG icon library                           |
| `react-markdown` | Markdown rendering in chat messages        |
| `remark-gfm`     | GitHub Flavored Markdown support           |
| `leaflet`        | Map library (imported but unused currently)|
| `react-leaflet`  | React wrapper for Leaflet (unused)         |

### Backend (`requirements.txt`)
| Package           | Purpose                                   |
| ----------------- | ----------------------------------------- |
| `fastapi`         | Web framework                             |
| `uvicorn`         | ASGI server                               |
| `langgraph`       | Agent orchestration graph                 |
| `langchain-groq`  | Groq LLM integration                     |
| `langchain-core`  | LangChain base (messages, tools)          |
| `httpx`           | HTTP client for weather API calls         |
| `python-dotenv`   | Environment variable loading              |
| `langdetect`      | Language detection for user messages      |
| `pydantic`        | Request/response data validation          |

---

## Git Workflow

- **Branch**: `master` (main branch)
- **Remote**: `origin` → GitHub `omsenjalia/weathergpt`
- **Commit style**: Conventional commits (`feat:`, `fix:`, `chore:`)
- **`.gitignore`**: Excludes `node_modules/`, `venv/`, `.env`, `dist/`, `__pycache__/`, IDE files

---

## Security Notes

- **Never commit `.env` files** — they contain API keys
- **GROQ_API_KEY** is the only truly secret credential
- **Open-Meteo APIs** are free and require no authentication
- **Windy API key** is optional and low-sensitivity
- **CORS** must be restricted before production deployment
- **No authentication** on API endpoints — add auth for production

---

## Performance Considerations

- **LangGraph graph** is compiled once at import time, not per-request
- **Weather dashboard** fetches directly from Open-Meteo (no backend hop)
- **Aurora background** uses CSS transforms/opacity only (GPU-accelerated)
- **`prefers-reduced-motion`** media query disables all animations for accessibility
- **Windy iframe** uses `loading="lazy"` for deferred loading
- **Hourly forecast** is sliced to 24 hours client-side to limit DOM nodes

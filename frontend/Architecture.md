# WeatherGPT — Technical Architecture & Specifications Annex
> **Context**: Smart India Hackathon (SIH) Presentation Annex & Technical Reference  
> **Target Audience**: Evaluation Panel, Technical Judges & Systems Architects  
> **Last Updated**: September 2026  
> **Status**: [✅ Production Live System & 🚀 Future Roadmap]

---

## 📌 Judge Quick Navigation Panel

| Section | Topic / Feature | Live Production Status | Primary Technologies |
| :--- | :--- | :--- | :--- |
| [1. Executive Summary](#1-executive-summary) | High-level system overview & key innovations | ✅ Live | React 19, FastAPI, LangGraph |
| [2. System Architecture](#2-high-level-architecture) | End-to-end architecture & data flow | ✅ Live | Mermaid Flowcharts & Sequence Diagrams |
| [3. Tech Stack & Design](#3-technology-stack--design-system) | Frameworks, tools & design system tokens | ✅ Live | Vite, TailwindCSS, Groq, Framer Motion |
| [4. Repository Structure](#4-repository-structure) | File footprint & codebase organization | ✅ Live | 34 modular components/views/utils |
| [5. Environment Config](#5-environment-variables--secrets) | Configuration & key fallback management | ✅ Live | `.env`, dotenv, Vite runtime env |
| [6. Backend Architecture](#6-backend-architecture) | Async FastAPI server & middleware | ✅ Live | FastAPI, Uvicorn, Pydantic |
| [7. Frontend Architecture](#7-frontend-architecture) | React SPA views, state & components | ✅ Live | React 19, Lucide, Excalidraw, Leaflet |
| [8. Data Flow Lifecycle](#8-data-flow--request-lifecycle) | Request execution & payload routing | ✅ Live | Async REST, JSON Widgets |
| [9. AI Agent Engine](#9-ai-agent-architecture-langgraph) | LangGraph state machine & 5-model cascade | ✅ Live | Qwen 27B, Llama 3.1, Mixtral, Gemma 2 |
| [10. Ensemble Fusion](#10-multi-source-ensemble-fusion-engine) | Multi-provider weighted weather aggregation | ✅ Live | Open-Meteo (ECMWF/IMD standard), WeatherAPI, OWM |
| [11. API Reference](#11-api-contract-reference) | REST endpoints specification | ✅ Live | `/chat`, `/dev`, `/dev/sandbox`, `/health` |
| [12. Widget Protocol](#12-widget-protocol-chat-embed) | Dynamic JSON chat card renderer | ✅ Live | `widget:weather`, `widget:forecast`, `widget:alert` |
| [13. Multilingual Engine](#13-internationalization-i18n) | 10 Indian regional languages + Web Speech | ✅ Live | Native scripts, Web Speech TTS/STT, langdetect |
| [14. Risk Outlook Engine](#14-risk-assessment-engine) | 5-day hazard classification engine | ✅ Live | 3-tier severity scoring (RED/YELLOW/GREEN) |
| [15. Farmer Mode](#15-agricultural-farmer-advisory-mode) | Crop-specific advisories & safety windows | ✅ Live | Cotton, Wheat, Rice, Sugarcane, Groundnut |
| [16. Dev Suite](#16-developer-diagnostics-dashboard) | 9-tab diagnostics & hazard simulator | ✅ Live | Latency tracking, stress testing, AI sandbox |
| [17. Deployment Setup](#17-deployment-architecture) | Production cloud infrastructure | ✅ Live | Vercel SPA CDN + Vercel Python Serverless |
| [18. SIH Compliance](#18-problem-statement--sih-compliance-matrix) | Problem statement compliance & 10 use cases | ✅ Live | Full matrix & evaluation criteria mapping |
| [19. Future Roadmap](#19-future-roadmap--planned-enhancements) | Planned direct IMD API portal & IoT feeds | 🚀 Roadmap | Direct IMD REST API key integration, Radar, PWA |

---

## 1. Executive Summary

**WeatherGPT** is a production-ready, full-stack, AI-powered weather intelligence platform custom-engineered for the **Smart India Hackathon**. It bridges the gap between complex meteorological datasets and everyday citizens, farmers, disaster managers, and public safety officials by providing real-time, hyper-local weather insights in **10 Indian regional languages** through natural conversational interfaces.

> [!NOTE]
> **Production vs. Roadmap Transparency**: WeatherGPT is built with a resilient, live architecture. Live weather telemetry and official model outputs (ECMWF/IMD high-resolution datasets) are ingested via multi-source ensemble fusion and public government alert streams. Planned proprietary API key connections to government portals (e.g., direct key-authenticated `api.imd.gov.in` endpoints pending approval) are fully specified in [Section 19: Future Roadmap](#19-future-roadmap--planned-enhancements).

### Core Innovations & Key Differentiators
- **Conversational AI Agent**: Driven by a stateful **LangGraph** orchestration graph and a **5-model Groq LLM cascade** (`Qwen 27B` → `Llama 3.1 8B` → `Llama 3.3 70B` → `Mixtral 8x7B` → `Gemma 2 9B`) with 0ms deterministic telemetry fallback for zero downtime.
- **14 Specialized Telemetry Tools**: Dynamic tool execution covering current weather, 7-day forecast, 24-48h hourly trends, US AQI pollutants, solar UV radiation, barometric pressure, soil moisture/agromet telemetry, and geocoding.
- **Multi-Source Ensemble Engine**: Parallel data ingestion across up to 5 weather providers with weighted algorithm calculation. Open-Meteo (ECMWF/IMD standard NWP model) is assigned **Priority-1 trust weighting (3.0×)**.
- **Agricultural Farmer Advisory Mode**: Crop-specific advisories for 8 major crop types with irrigation, pesticide spraying, thermal/frost stress, and harvest window guidance.
- **10 Regional Indian Languages**: Native script rendering for Hindi, Gujarati, Marathi, Tamil, Telugu, Bengali, Kannada, Malayalam, Punjabi, and English, coupled with browser Web Speech API Voice Text-to-Speech and Speech-to-Text.
- **Rich Interactive Widgets**: Automated parsing of markdown widget tags (`widget:weather`, `widget:forecast`, `widget:alert`) into interactive React UI components.
- **Developer Diagnostic Suite**: A 9-tab built-in developer dashboard with live latency profiling, multi-city stress testing, hazard simulation, and AI model sandboxing.

---

## 2. High-Level Architecture

```mermaid
graph TB
    subgraph "User Interface (Client Side)"
        UI["React 19 SPA<br/>(Vite + TailwindCSS)"]
        EE["Ensemble Engine<br/>(Client-Side Fusion)"]
        LOC["Location Services<br/>(GPS / IP / Reverse Geocode)"]
        TTS["Speech Engine<br/>(Web Speech API TTS/STT)"]
        I18N["i18n Engine<br/>(10 Native Languages)"]
    end

    subgraph "FastAPI Server Infrastructure"
        API["FastAPI App<br/>(Python 3.12 Serverless / Uvicorn)"]
        AGT["LangGraph Agent<br/>(State Machine Router)"]
        LLM["Groq Multi-Model Cascade<br/>(Qwen 27B → Llama 8B → Llama 70B → Mixtral → Gemma 2)"]
        TOOLS["14 Telemetry AI Tools<br/>(Geocode, Weather, Forecast, AQI, UV, Soil, Alerts)"]
        FB["Deterministic Telemetry Synthesizer<br/>(0% Downtime Fallback)"]
    end

    subgraph "Live External Telemetry APIs"
        OM["Open-Meteo Weather<br/>(ECMWF/IMD Standard — Weight 3.0×)"]
        WA["WeatherAPI.com<br/>(Weight 1.2×)"]
        TM["Tomorrow.io<br/>(Weight 1.2×)"]
        OWM["OpenWeatherMap<br/>(Weight 1.1×)"]
        AW["AccuWeather<br/>(Weight 1.25×)"]
        AQ["Open-Meteo Air Quality<br/>(AQI, PM2.5, PM10, Gases)"]
    end

    subgraph "Public Government Feeds & GIS"
        CAP["IMD CAP Alert Feed<br/>(Public RSS/XML Stream)"]
        WDY["Windy GIS Map Engine<br/>(Interactive Map Embed)"]
    end

    UI -->|"POST /chat"| API
    UI -->|"GET /dev"| API
    UI -->|"POST /dev/sandbox"| API
    UI -->|"GET /health"| API

    API --> AGT
    AGT --> LLM
    AGT --> TOOLS
    AGT -->|"If LLM Limit Hit"| FB

    TOOLS --> OM
    TOOLS --> WA
    TOOLS --> OWM
    TOOLS --> CAP
    FB --> OM

    EE --> OM
    EE --> WA
    EE --> TM
    EE --> OWM
    EE --> AW

    UI --> EE
    UI --> LOC
    UI --> TTS
    UI --> I18N
    UI --> AQ
    UI --> WDY
```

---

## 3. Technology Stack & Design System

### 3.1 Frontend Stack

| Layer | Technology | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **UI Library** | React | 19.2.0 | Core view rendering engine |
| **Build System** | Vite | 8.2.2 | Fast HMR dev server & production bundler |
| **Styling** | TailwindCSS | 3.4.0 | Utility-first responsive CSS framework |
| **Animations** | Framer Motion | 11.0.0 | Fluid spring animations & layout transitions |
| **HTTP Client** | Axios | 1.7.0 | Backend REST communication |
| **Markdown** | React Markdown + Remark GFM | 10.1.0 / 4.0.1 | Markdown rendering with GFM tables & code blocks |
| **Icons** | Lucide React | 1.39.0 | Crisp SVG vector icon set |
| **Maps** | Leaflet + React-Leaflet | 1.9.4 / 5.0.0 | Interactive GIS map containers |
| **Architecture Viz** | Excalidraw | 0.18.1 | Embedded architectural diagram viewer |
| **Speech** | Web Speech API | Native Browser | Regional Text-to-Speech & Speech-to-Text |

### 3.2 Backend Stack

| Layer | Technology | Version | Purpose |
| :--- | :--- | :--- | :--- |
| **Web Framework** | FastAPI | 0.115.0 | High-performance async REST API server |
| **ASGI Server** | Uvicorn | 0.30.6 | Production ASGI web server |
| **Agent Orchestrator** | LangGraph | 0.2.28 | Stateful state machine graph for AI agent execution |
| **LLM Provider** | LangChain-Groq | 0.2.0 | Groq Cloud LPU inference connector |
| **Core AI Tools** | LangChain-Core | 0.3.0 | Tool definition decorators & message schema |
| **Async HTTP** | httpx | 0.27.2 | Non-blocking telemetry ingestion |
| **Language Detection**| langdetect | 1.0.9 | Automatic ISO language detection from user input |
| **Validation** | Pydantic | Latest | Request/response schema validation |

### 3.3 Design System & Aesthetics

WeatherGPT employs a modern **Glassmorphism Dark Aesthetics** design tailored for high visual impact:

| Token / Asset | Value | Visual Purpose |
| :--- | :--- | :--- |
| **Accent Primary** | `#f59e0b` (Amber-500) | Primary interactive buttons, key weather indicators |
| **Accent Hover** | `#d97706` (Amber-600) | Active hover & focus states |
| **Background Base** | `#000000` / `#0a0a0c` | Deep space obsidian dark mode |
| **Typography — Body** | Inter | High legibility UI body text |
| **Typography — Display** | Playfair Display | Elegant hero temperature typography |
| **Typography — Brand** | Bricolage Grotesque | Tech logo & header identity |
| **Typography — Accent** | Caveat | Handwritten tactical badges & notes |
| **Surface Glass** | `backdrop-blur-md bg-white/5 border-white/10` | Floating glassmorphic card elements |

---

## 4. Repository Structure

```
weathergpt/
├── frontend/                           # React 19 Client SPA
│   ├── index.html                      # HTML entry point & font links
│   ├── package.json                    # Node dependencies & build scripts
│   ├── vite.config.js                  # Vite bundler configuration
│   ├── tailwind.config.js              # Tailwind design tokens & plugins
│   ├── vercel.json                     # Production deployment rewrites
│   ├── src/
│   │   ├── main.jsx                    # Application mounting root
│   │   ├── App.jsx                     # Top-level view router & state
│   │   ├── api.js                      # Centralized API service layer
│   │   ├── index.css                   # Tailwind directives & custom CSS
│   │   ├── views/
│   │   │   ├── WeatherChatView.jsx     # Main AI conversation & dashboard
│   │   │   ├── MapView.jsx             # Interactive Windy GIS map embed
│   │   │   ├── DevView.jsx             # 9-Tab developer diagnostic suite
│   │   │   └── ExcalidrawArchitectureView.jsx # Interactive diagram viewer
│   │   ├── components/
│   │   │   ├── Sidebar.jsx             # Navigation drawer & crop selector
│   │   │   ├── LocationPickerModal.jsx # GPS & city search modal
│   │   │   ├── LanguagePickerModal.jsx # 10-language selector modal
│   │   │   ├── RiskOutlookCard.jsx     # 5-day risk assessment card
│   │   │   ├── PromptRotator.jsx       # Dynamic regional prompt suggestions
│   │   │   ├── WeatherMarquee.jsx      # Ticker tape for major Indian cities
│   │   │   └── MarkdownContent.jsx     # Markdown renderer with widget detection
│   │   └── utils/
│   │       ├── ensembleEngine.js       # Multi-source weather fusion algorithm
│   │       ├── location.js             # GPS / IP / Reverse geocoding module
│   │       ├── speechEngine.js         # Web Speech API wrapper
│   │       └── translations.js         # 10-Language i18n translation dictionary
└── backend/                            # FastAPI AI Agent Server
    ├── main.py                         # FastAPI routes & logging middleware
    ├── agent.py                        # LangGraph state machine & LLM cascade
    ├── tools.py                        # 14 Specialized AI telemetry tools
    ├── imd_service.py                  # Public CAP alert feed & sample schemas
    └── requirements.txt                # Python backend dependencies
```

---

## 5. Environment Variables & Secrets

### 5.1 Frontend `.env`

| Key | Mandatory | Description |
| :--- | :--- | :--- |
| `VITE_API_URL` | Production | FastAPI backend endpoint (defaults to `http://localhost:8888` in dev) |
| `VITE_WINDY_API_KEY` | ✅ | Windy API key for GIS interactive map rendering |
| `VITE_OPENWEATHER_API_KEY` | Optional | OpenWeatherMap key for GIS map tiles |
| `VITE_WEATHERAPI_KEY` | Optional | WeatherAPI key for client-side ensemble fusion |
| `VITE_TOMORROW_KEY` | Optional | Tomorrow.io key for client-side ensemble fusion |
| `VITE_ACCUWEATHER_KEY` | Optional | AccuWeather key for client-side ensemble fusion |

### 5.2 Backend `.env`

| Key | Mandatory | Description |
| :--- | :--- | :--- |
| `GROQ_API_KEY` | ✅ | Groq API key for LPU high-speed LLM inference |
| `GROQ_MODEL` | Optional | Primary model override (default: `qwen/qwen3.8-27b`) |
| `WEATHERAPI_KEY` | Optional | WeatherAPI key for backend tool-level fusion |
| `OPENWEATHER_KEY` | Optional | OpenWeatherMap key for backend tool-level fusion |

> [!TIP]
> **Graceful Key Fallbacks**: The system operates out-of-the-box even with minimal environment keys. If secondary provider keys are omitted, the ensemble engine gracefully recalibrates weights among active providers.

---

## 6. Backend Architecture

### 6.1 Server Endpoints

| Path | Method | Functionality | Auth | Response |
| :--- | :--- | :--- | :--- | :--- |
| `/chat` | `POST` | Core AI conversation endpoint (invokes LangGraph agent) | Open (CORS `*`) | `ChatResponse` JSON |
| `/health` | `GET` | Instant health check | Open | `{"status": "ok"}` |
| `/dev` | `GET` | Returns 9-category system diagnostics & logs | Open | Comprehensive JSON |
| `/dev/sandbox` | `POST` | Direct single-prompt testing with latency profiling | Open | Sandbox result JSON |

### 6.2 Middleware & Request Logging

Every request passing through FastAPI is profiled by custom logging middleware:
1. Records request start timestamp.
2. Injects CORS headers allowing multi-origin SPA access.
3. Computes execution duration in milliseconds.
4. Appends non-sensitive logs to an in-memory ring buffer (`RECENT_LOGS`, max 50 entries) exposed via `/dev`.

---

## 7. Frontend Architecture

### 7.1 View Routing & Layout Structure

The frontend operates as a stateful Single Page Application (SPA) in `App.jsx`:

```mermaid
graph TD
    APP["App.jsx (Root View Router)"] --> NAV["Sidebar & Navigation Dock"]
    APP --> V1["WeatherChatView ('home')"]
    APP --> V2["MapView ('map')"]
    APP --> V3["DevView ('dev')"]
    APP --> V4["ExcalidrawArchitectureView ('architecture')"]

    V1 --> W1["WeatherDashboardCard (Overview / 24h / 7-Day)"]
    V1 --> W2["AI Conversational Chat Log"]
    V1 --> W3["RiskOutlookCard (5-Day Environmental Hazards)"]
    V1 --> W4["WeatherMarquee & PromptRotator"]

    W2 --> WIDGETS["Widget Parsers (ChatWeatherWidget / ChatForecastWidget / ChatAlertWidget)"]
```

### 7.2 Local Storage Persistence

Client-side preferences are automatically synchronized to `localStorage` under `weathergpt_*` keys:
- `weathergpt_location`: Active user coordinates and location label.
- `weathergpt_language`: Selected target language object (code, native name, speech locale).
- `weathergpt_favorites`: Array of saved favorite cities.

---

## 8. Data Flow & Request Lifecycle

```mermaid
sequenceDiagram
    actor User
    participant UI as React Frontend
    participant API as FastAPI Server
    participant Agent as LangGraph Agent Graph
    participant LLM as Groq Model Cascade
    participant Tools as Telemetry AI Tools
    participant Telemetry as Weather Data APIs

    User->>UI: Types query ("Will it rain in Jaipur tomorrow?")
    UI->>API: POST /chat {messages, location, language, farmer_mode, crop}
    API->>Agent: Execute run_weather_agent()
    
    Agent->>Agent: Build dynamic prompt (inject location, language, farmer mode)
    Agent->>LLM: Invoke Qwen 27B with tools bound
    
    alt LLM triggers tool invocation
        LLM-->>Agent: Returns tool_call (e.g. get_weather_forecast)
        Agent->>Tools: Execute tool function
        Tools->>Telemetry: HTTP GET telemetry request
        Telemetry-->>Tools: Raw telemetry JSON
        Tools-->>Agent: Formatted tool response
        Agent->>LLM: Re-invoke LLM with tool output
    end

    LLM-->>Agent: Final Markdown answer + Widget JSON block
    Agent-->>API: Return synthesized text
    API-->>UI: HTTP 200 OK {"response": "..."}
    
    UI->>UI: Parse markdown & detect widget tags
    UI->>UI: Render interactive widget cards (ChatForecastWidget)
    UI->>User: Display response + Speak TTS audio (if enabled)
```

---

## 9. AI Agent Architecture (LangGraph)

### 9.1 Multi-Model Groq Cascade

To prevent rate limits or model outages from disrupting service, the AI agent uses a **5-tier fallback cascade** via `.with_fallbacks()`:

```mermaid
graph TD
    START["User Query"] --> M1["Primary: Qwen 27B (qwen/qwen3.8-27b)"]
    M1 -->|429 Rate Limit / Error| M2["Fallback 1: Llama 3.1 8B Instant"]
    M2 -->|Error| M3["Fallback 2: Llama 3.3 70B Versatile"]
    M3 -->|Error| M4["Fallback 3: Mixtral 8x7B"]
    M4 -->|Error| M5["Fallback 4: Gemma 2 9B"]
    M5 -->|All Fail| DET["Deterministic Telemetry Synthesizer (0% Downtime)"]
```

### 9.2 14 Specialized AI Telemetry Tools

| Tool Name | Key Parameters | Functionality | Primary Telemetry Source |
| :--- | :--- | :--- | :--- |
| `geocode_city` | `city_name` | Geocodes city string into lat/lon coordinates | Open-Meteo Geocoding |
| `get_current_weather` | `latitude`, `longitude` | Current temperature, humidity, wind & conditions | Fused Multi-Source |
| `get_weather_forecast` | `latitude`, `longitude`, `days` | 7-day daily forecast with rain probability | Open-Meteo Forecast |
| `get_hourly_forecast` | `latitude`, `longitude` | 24-48h hourly temperature & rain sequence | Open-Meteo Hourly |
| `get_air_quality` | `latitude`, `longitude` | Real-time US AQI, PM2.5, PM10, CO, NO₂, SO₂, O₃ | Open-Meteo Air Quality |
| `get_uv_index_and_sun` | `latitude`, `longitude` | Solar UV index & sunrise/sunset times | Open-Meteo Solar |
| `get_surface_pressure_and_wind`| `latitude`, `longitude` | Barometric pressure (hPa) & wind gusts | Open-Meteo Surface |
| `get_agricultural_crop_telemetry`| `latitude`, `longitude` | Soil moisture, ET0 evapotranspiration & soil temp | Open-Meteo Agromet |
| `get_official_imd_alerts` | `latitude`, `longitude` | Severe weather hazard alerts (RED/ORANGE/YELLOW) | IMD CAP Feed / Weather Stream |
| `get_imd_city_forecast` | `station_id` | Official city bulletin data | Public IMD Bulletin / Schema |
| `get_imd_district_warning` | `district_id` | Official district alert bulletin | Public IMD Bulletin / Schema |
| `get_imd_cyclone_track` | None | Cyclone position and intensity track | Public IMD Bulletin / Schema |
| `get_imd_agromet_official_advisory`| `district`, `crop` | Crop advisory guidelines | Public Agromet Bulletin / Schema |
| `query_any_imd_api_feature` | `api_id`, `params_json` | Generic telemetry catalog query | Internal ImdService Routing |

### 9.3 System Guardrails

1. **Casual Conversation Allowed**: Friendly greetings, banter, and general inquiries are supported naturally.
2. **Strict Code Generation Ban**: Explicitly prevents software programming code generation (Python, JS, C++, HTML/CSS, SQL scripts) to enforce domain specialization.
3. **Farmer Mode Session Isolation**: When Farmer Mode is toggled off, agricultural prompt rules are cleared to prevent context bleeding.

---

## 10. Multi-Source Ensemble Fusion Engine

### 10.1 Telemetry Providers & Priority Weighting

WeatherGPT fuses data across 5 distinct meteorological sources. **Open-Meteo (ECMWF/IMD global standard model)** is weighted highest to reflect government-grade accuracy over the Indian subcontinent:

| Provider | Trust Weight | Coverage | Provided Metrics |
| :--- | :--- | :--- | :--- |
| **Open-Meteo (ECMWF/IMD Standard)** | **3.0× (Priority 1)** | Global / India | Temp, feels like, humidity, wind, pressure, UV, hourly, daily |
| **WeatherAPI.com** | **1.2×** | Global / India | Temp, feels like, humidity, wind, AQI, PM2.5, PM10 |
| **Tomorrow.io** | **1.2×** | Global | Temp, feels like, humidity, wind speed, surface pressure |
| **AccuWeather** | **1.25×** | Global | Temp, RealFeel, humidity, wind, UV index |
| **OpenWeatherMap** | **1.1×** | Global | Temp, feels like, humidity, wind speed, conditions |

### 10.2 Mathematical Fusion Formula

For any continuous weather metric $M$ (e.g., Temperature, Humidity, Pressure):

$$\text{Fused Metric } M = \frac{\sum_{i=1}^{N} (M_i \times W_i)}{\sum_{i=1}^{N} W_i}$$

Where $M_i$ is the value reported by provider $i$, and $W_i$ is the designated trust weight of provider $i$.

---

## 11. API Contract Reference

### `POST /chat`

**Request Payload**:
```json
{
  "messages": [
    {"role": "user", "content": "What is the rain outlook for Ahmedabad?"}
  ],
  "location": "Ahmedabad, Gujarat, India",
  "language": "English",
  "farmer_mode": false,
  "crop": ""
}
```

**Response Payload**:
```json
{
  "response": "## Weather Outlook for Ahmedabad\n\n```widget:weather\n{\n  \"city\": \"Ahmedabad\",\n  \"temp\": 34,\n  \"feelsLike\": 38,\n  \"condition\": \"Partly Cloudy\",\n  \"humidity\": 65,\n  \"windSpeed\": 14,\n  \"advisory\": \"Warm afternoon conditions with moderate humidity.\"\n}\n```\n\nRain is unlikely over the next 24 hours."
}
```

---

## 12. Widget Protocol (Chat Embed)

The AI agent embeds dynamic UI cards directly in its markdown output using structured code tags:

```
```widget:weather
{ "city": "Delhi", "temp": 32, "feelsLike": 35, "condition": "Sunny", "humidity": 50, "windSpeed": 12, "advisory": "Stay hydrated." }
```
```

### Supported Widget Types
- `` ```widget:weather `` → Renders `ChatWeatherWidget` (Current conditions card).
- `` ```widget:forecast `` → Renders `ChatForecastWidget` (Multi-day strip card).
- `` ```widget:alert `` → Renders `ChatAlertWidget` (Color-coded hazard alert card).

---

## 13. Internationalization (i18n)

WeatherGPT provides native UI rendering and voice capabilities in **10 Indian regional languages**:

| Language | ISO Code | Native Script | Web Speech TTS Locale |
| :--- | :--- | :--- | :--- |
| **English** | `en` | English | `en-IN` |
| **Hindi** | `hi` | हिंदी | `hi-IN` |
| **Gujarati** | `gu` | ગુજરાતી | `gu-IN` |
| **Marathi** | `mr` | मराठी | `mr-IN` |
| **Tamil** | `ta` | தமிழ் | `ta-IN` |
| **Telugu** | `te` | తెలుగు | `te-IN` |
| **Bengali** | `bn` | বাংলা | `bn-IN` |
| **Kannada** | `kn` | ಕನ್ನಡ | `kn-IN` |
| **Malayalam** | `ml` | മലയാളം | `ml-IN` |
| **Punjabi** | `pa` | ਪੰਜਾਬੀ | `pa-IN` |

---

## 14. Risk Assessment Engine

The `RiskOutlookCard` evaluates upcoming 5-day weather telemetry against critical thresholds:

```mermaid
graph TD
    DATA["5-Day Telemetry Feed"] --> COND{Check Severity Triggers}
    COND -->|Thunderstorm / Temp ≥ 44°C / Rain ≥ 50mm / Wind ≥ 50 km/h| RED["🔴 RED HAZARD<br/>Severe: Stay indoors & defer field activity"]
    COND -->|Drizzle / Temp ≥ 40°C / Rain ≥ 15mm / Wind ≥ 30 km/h| YEL["🟡 YELLOW WATCH<br/>Watch: Monitor forecasts & carry umbrella"]
    COND -->|Normal Thresholds| GRN["🟢 GREEN FAVORABLE<br/>Favorable: Safe for routine activities"]
```

---

## 15. Agricultural Farmer Advisory Mode

When **Farmer Mode** is enabled, WeatherGPT tailors its advice to specific crop life-cycles:

| Supported Crop | Primary Advisory Focus |
| :--- | :--- |
| **Cotton (કપાસ / कपास)** | Bollworm pest risk, field drainage, and picking dry windows |
| **Wheat (ઘઉં / गेहूं)** | Terminal heat stress prevention, critical irrigation stages |
| **Rice / Paddy (ડાંગર / धान)** | Water submergence management, fertilizer application timing |
| **Sugarcane (શેરડી / गन्ना)** | Irrigation scheduling, lodging prevention during high winds |
| **Groundnut (મગફળી / मूंगफली)** | Soil moisture management, leaf spot disease risk warnings |
| **Mustard (રાઈ / सरसों)** | Aphid infestation alerts during humid/cloudy spells |
| **Vegetables (શાકભાજી / सब्जियां)** | Nursery protection, drip irrigation frequency, spray windows |

---

## 16. Developer Diagnostics Dashboard

Accessible via `/dev` or pressing `Shift + D`, the **DevView** provides 9 interactive diagnostic tabs:

1. **Overview**: Live CPU, memory, uptime, process PID, and LLM model status.
2. **Data Pipeline**: Active data ingestion state and response latency tracking.
3. **AI Sandbox**: Interactive prompt tester with model execution timers.
4. **Hazard Simulator**: Test RED/YELLOW alert widget rendering.
5. **Multi-City Stress Tester**: Concurrent multi-city API response latency profiler.
6. **API Endpoint Tester**: Direct backend REST endpoint tester.
7. **Ensemble Inspector**: Live comparison of variance across weather providers.
8. **Client Storage**: View and purge client `localStorage` keys.
9. **System Logs**: Live ring-buffer log viewer (`RECENT_LOGS`).

---

## 17. Deployment Architecture

```mermaid
graph TB
    subgraph "Vercel Cloud Edge Network"
        CDN["Vercel Global Edge CDN<br/>(Static React SPA Assets)"]
        SLS["Vercel Serverless Function<br/>(FastAPI Python Runtime)"]
    end

    subgraph "External Cloud Infrastructure"
        GROQ["Groq Cloud LPUs<br/>(LLM Inference)"]
        MET["Weather Data Providers<br/>(Open-Meteo, WeatherAPI, OWM)"]
    end

    USER["User Web Browser"] -->|"HTTPS GET /"| CDN
    USER -->|"HTTPS POST /chat"| SLS
    SLS --> GROQ
    SLS --> MET
```

---

## 18. Problem Statement & SIH Compliance Matrix

### 18.1 SIH Key Features Ingestion Matrix

| Key Feature | SIH Requirement | WeatherGPT Implementation Status | Primary Implementation File(s) |
| :--- | :--- | :--- | :--- |
| **1. Real-time Telemetry** | Real-time weather data retrieval | ✅ **Fully Implemented** — Fuses live weather telemetry (temp, feels-like, humidity, wind, pressure, UV, AQI) from up to 5 providers. | [`ensembleEngine.js`](file:///home/om/sih/frontend/src/utils/ensembleEngine.js)<br/>[`tools.py`](file:///home/om/sih/backend/tools.py) |
| **2. Natural Language Querying** | Conversational weather forecasting | ✅ **Fully Implemented** — LangGraph state machine powered by Groq Qwen 27B LLM with automated tool invocation. | [`agent.py`](file:///home/om/sih/backend/agent.py)<br/>[`WeatherChatView.jsx`](file:///home/om/sih/frontend/src/views/WeatherChatView.jsx) |
| **3. NWP Model Integration** | Integration with GFS/ECMWF models | ✅ **Fully Implemented** — ECMWF/IMD model data given **Priority-1 trust weight (3.0×)** + Windy GIS map support for GFS/ECMWF. | [`ensembleEngine.js`](file:///home/om/sih/frontend/src/utils/ensembleEngine.js)<br/>[`MapView.jsx`](file:///home/om/sih/frontend/src/views/MapView.jsx) |
| **4. Extreme Weather Warnings** | Early alert dissemination | ✅ **Fully Implemented** — Official alert widget (`widget:alert`), 5-day risk assessment engine, and public CAP warning stream integration. | [`RiskOutlookCard.jsx`](file:///home/om/sih/frontend/src/components/RiskOutlookCard.jsx)<br/>[`imd_service.py`](file:///home/om/sih/backend/imd_service.py) |
| **5. Location-Based Advisories**| Location forecasting & advisory | ✅ **Fully Implemented** — GPS auto-location + IP fallback + Agricultural Farmer Mode for crop-specific advisory generation. | [`location.js`](file:///home/om/sih/frontend/src/utils/location.js)<br/>[`agent.py`](file:///home/om/sih/backend/agent.py) |
| **6. Multilingual Support** | Multilingual support for Indian languages | ✅ **Fully Implemented** — **10 Indian languages** in native scripts (Hindi, Gujarati, Marathi, Tamil, etc.) + `langdetect`. | [`translations.js`](file:///home/om/sih/frontend/src/utils/translations.js)<br/>[`agent.py`](file:///home/om/sih/backend/agent.py) |
| **7. Historical & Trend Analysis**| Trend & historical analysis | ✅ **Fully Implemented** — 14-day extended outlooks, 24-hour telemetry trend visualization with Bézier curves. | [`WeatherChatView.jsx`](file:///home/om/sih/frontend/src/views/WeatherChatView.jsx) |
| **8. Voice Accessibility** | Voice interaction for rural users | ✅ **Fully Implemented** — Web Speech API Speech-to-Text and Text-to-Speech across regional locales (`hi-IN`, `gu-IN`, `ta-IN`, etc.). | [`speechEngine.js`](file:///home/om/sih/frontend/src/utils/speechEngine.js) |

### 18.2 Expanded 10-Domain Use-Case Matrix

WeatherGPT provides specialized intelligence across 10 key domain use cases:

| Domain / Use Case | Stakeholders | Data Telemetry | Key System Capabilities |
| :--- | :--- | :--- | :--- |
| **1. 🌾 Agriculture** | Farmers, KVK Agronomists | Soil moisture, rain %, temp, wind | **Farmer Mode**: Crop advisories (Wheat, Cotton, Rice) in 10 languages with TTS. |
| **2. ✈️ Aviation** | Pilots, ATC, Drone Operators | Cloud cover %, surface pressure, wind gusts | **Windy GIS Overlay Engine**: Real-time radar, cloud layers, and pressure trends. |
| **3. ⛵ Maritime Fisheries** | Coastal Fishermen, Port Authorities | Wave height, swells, squally wind speed | **Marine Telemetry**: Squally wind warnings & voice bulletins for coastal communities. |
| **4. 🚨 Disaster Preparedness** | NDRF / SDRF, Disaster Managers | Rainfall sum, extreme codes, wind gusts | **Early Alert Engine**: Color-coded alert banners (RED/YELLOW) with safety steps. |
| **5. 🏙️ Smart City & AQI** | Municipalities, Urban Citizens | US AQI, PM2.5, PM10, UV index, gases | **Urban Environmental Dashboard**: Live 24h telemetry & AQI health classifications. |
| **6. 📊 Climate Research** | Climatologists, Researchers | 14-day min/max temp, precipitation trends | **Ensemble Inspector**: Compare weighted telemetry variance across 5 providers. |
| **7. ⚡ Renewable Energy** | Solar & Wind Farm Operators | Solar UV index, cloud cover %, 10m wind | **Clean Energy Insights**: Solar UV & wind velocity metrics to predict power output. |
| **8. 🚚 Logistics & Haulage** | Freight Carriers, Site Supervisors | Rain prob max, wind speed, precipitation | **Operations Advisories**: Crane wind hazard alerts and haulage rain warnings. |
| **9. 🏥 Public Health** | Health Officials, Outdoor Workers | Apparent temp ("Feels Like"), UV index | **Heat-Health Risk Advisories**: Heat index alerts & peak UV avoidance guidance. |
| **10. ⛰️ Pilgrimage & Tourism** | Mountain Pilgrims, Tour Operators | High-altitude temp, snow, thunderstorm risk | **Travel Safety Advisories**: Conversational guide for mountain passes & landslide risks. |

---

## 19. Future Roadmap & Planned Enhancements

The following features and integrations represent the **Phase 2 & Phase 3 Expansion Plan** for WeatherGPT:

```mermaid
graph LR
    subgraph "Phase 2 Roadmap (Q4 2026)"
        R1["Direct Government Portal Integration<br/>(Key-authenticated api.imd.gov.in REST suite)"]
        R2["Satellite Doppler Radar Ingestion<br/>(Live reflectivity tile overlays)"]
        R3["Offline Progressive Web App (PWA)<br/>(Service Workers & Local Caching)"]
    end

    subgraph "Phase 3 Roadmap (2027)"
        R4["IoT Hardware Sensor Mesh<br/>(LoRaWAN Field Weather Station Data)"]
        R5["Fine-Tuned Small Language Model<br/>(SLM for offline regional dialect chat)"]
    end

    R1 --> R4
    R2 --> R4
    R3 --> R5
```

### 19.1 Direct Government IMD Portal API Suite (`api.imd.gov.in`)
- **Status**: [🚀 Planned — Pending Official Key Approval]
- **Overview**: Upon receipt of official government API key approval, WeatherGPT will transition from public CAP warning feeds to direct REST endpoint connections covering all 28 IMD catalogued APIs (City Forecast, District Warning, Cyclone Track, Agromet Advisory, Marine Bulletins, RADAR Reflectivity, and Astronomical Data).
- **Architecture Prep**: `imd_service.py` is pre-engineered with client handlers to accept `IMD_API_KEY` and `IMD_JWT_TOKEN` headers instantly upon key issuance.

### 19.2 Satellite Radar & Lightning Nowcasting
- **Status**: [🚀 Planned]
- **Overview**: Ingesting high-resolution Doppler Weather Radar (DWR) composite tiles for major Indian metros (Mumbai, Delhi, Chennai, Kolkata) to provide sub-30 minute nowcasting for urban flash floods and severe lightning strikes.

### 19.3 Offline Progressive Web App (PWA)
- **Status**: [🚀 Planned]
- **Overview**: Implementing Service Worker background sync and IndexedDB offline storage so farmers in remote areas with intermittent connectivity can view cached weather advisories and risk outlooks offline.

### 19.4 Micro-Local IoT Sensor Mesh Integration
- **Status**: [🚀 Planned]
- **Overview**: Ingesting real-time field telemetry from low-cost LoRaWAN hardware weather stations deployed at Krishi Vigyan Kendras (KVKs) to ground-truth satellite weather models with localized soil moisture and leaf wetness readings.
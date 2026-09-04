import { useState } from 'react'
import { Cpu, Server, Globe, Sparkles, MapPin, Languages, Layers, ShieldCheck, Download, Code, ArrowRight, Activity, Terminal, Radio } from 'lucide-react'

export default function ExcalidrawArchitectureView() {
  const [selectedNode, setSelectedNode] = useState('hero-card')

  const sections = [
    {
      title: 'SECTION 1: USER INTERFACE & INPUT CONTROLS',
      color: 'text-purple-400',
      nodes: [
        {
          id: 'user-loc',
          title: '📍 Location & Geolocation Pipeline',
          category: 'Location Engine',
          color: 'border-purple-500/50 bg-purple-500/10 text-purple-300',
          icon: MapPin,
          file: 'src/utils/location.js & LocationPickerModal.jsx',
          summary: 'IP Geolocation & GPS auto-detection with fallback to 35+ major Indian cities registry and geocoding search.',
          details: [
            'autoDetectUserLocation() [IP & Browser GPS]',
            'INDIAN_CITIES_REGISTRY (35+ cities latitude/longitude mapping)',
            'LocationPickerModal manual geocoding search',
            'State persistence in localStorage (\'weathergpt_location\')',
          ],
        },
        {
          id: 'user-lang',
          title: '🌐 10 Indian Languages Engine',
          category: 'Multilingual Engine',
          color: 'border-amber-500/50 bg-amber-500/10 text-amber-300',
          icon: Languages,
          file: 'src/utils/translations.js',
          summary: 'Zero-dependency translation engine supporting 10 major Indian languages with dynamic fallback.',
          details: [
            '10 Languages: EN, HI, GU, MR, TA, TE, BN, KN, ML, PA',
            'Translations.get(langCode, key) lookup dictionary',
            'translateCondition(code, langCode) weather condition mapping',
            'LanguagePickerModal native script selection',
          ],
        },
        {
          id: 'farmer-mode',
          title: '🌾 Farmer Advisory Mode Sub-System',
          category: 'Agri-Advisory Engine',
          color: 'border-lime-500/50 bg-lime-500/10 text-lime-300',
          icon: Activity,
          file: 'src/components/Sidebar.jsx & App.jsx',
          summary: 'Agricultural mode providing crop-specific advisory guidance based on humidity, rain, and soil weather context.',
          details: [
            'Sidebar toggle switch (farmerMode boolean state)',
            'Crop selector: Cotton (કપાસ / कपास), Wheat, Rice/Paddy, Sugarcane, Groundnut, Mustard, Vegetables',
            'Injects crop guidance prompt context into FastAPI LLaMA LLM',
          ],
        },
        {
          id: 'voice-tts',
          title: '🔊 Web Speech API & Audio TTS Engine',
          category: 'Voice Sub-System',
          color: 'border-pink-500/50 bg-pink-500/10 text-pink-300',
          icon: Radio,
          file: 'src/utils/speechEngine.js & VoiceComingSoonToast.jsx',
          summary: 'Browser-native text-to-speech engine reading weather advisories aloud in native Indian voices.',
          details: [
            'speakText(text, langCode, setIsSpeaking) with SpeechSynthesisUtterance',
            '🔊 Listen / Stop Speech button on every bot message',
            'Voice mic input toast notification for browser compatibility',
          ],
        },
      ],
    },
    {
      title: 'SECTION 2: ZERO-SCROLL ATMOSPHERIC WEATHER DASHBOARD',
      color: 'text-emerald-400',
      nodes: [
        {
          id: 'hero-card',
          title: '☀️ Atmospheric Hero Weather Card',
          category: 'Hero Telemetry Card',
          color: 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300',
          icon: Sparkles,
          file: 'src/views/WeatherChatView.jsx',
          summary: 'Zero-scroll atmospheric card displaying current temperature, condition, high/low range, and ambient backdrop.',
          details: [
            'Big Temperature Display (text-5xl font-extrabold 31°c)',
            'Weather Condition Description (\'Clear sky\')',
            'High / Low Pill (High 34° / Low 24°)',
            'Humidity %, Wind Speed (km/h), Feels Like °C',
            'Ambient Glow Backdrop (slate-950 to neutral-950)',
          ],
        },
        {
          id: 'spline-graph',
          title: '📈 Spline Bezier Temperature Graph',
          category: 'SVG Graphing Subsystem',
          color: 'border-sky-500/50 bg-sky-500/10 text-sky-300',
          icon: Activity,
          file: 'BezierTemperatureGraph in WeatherChatView.jsx',
          summary: 'Interactive SVG Cubic Bezier spline curve graph visualizing 7-point hourly temperature trends.',
          details: [
            'SVG ViewBox 500x80 with Gaussian Glow Filter (#curveGlow)',
            'Cubic Bezier Path: C cp1x,cp1y cp2x,cp2y nextX,nextY',
            'Active node indicator circle & translucent outer halo',
            'Hourly temperature node labels (text-xs font-mono)',
          ],
        },
        {
          id: 'telemetry-array',
          title: '📊 5-Tile Telemetry Metrics Array',
          category: 'Telemetry Subsystem',
          color: 'border-amber-500/50 bg-amber-500/10 text-amber-300',
          icon: Layers,
          file: 'WeatherDashboardCard in WeatherChatView.jsx',
          summary: '5 dedicated telemetry cards calculating air quality, UV index, wind compass, daylight, and surface pressure.',
          details: [
            '1. Air Quality: getAQIStatus (Good <=50, Mod <=100, Unhealthy Sens <=150) + PM2.5',
            '2. UV Index: getUVStatus (Low <=2, Mod <=5, High <=7, Very High >7) + Protection advice',
            '3. Wind Compass: getCardinalDirection(angle / 45 % 8) -> N, NE, E, SE, S, SW, W, NW',
            '4. Daylight Progress: getDaylightProgress(sunrise, sunset) minute ratio calculation',
            '5. Surface Pressure: Atmospheric pressure in hPa vs 1013 hPa standard baseline',
          ],
        },
        {
          id: 'haversine-engine',
          title: '🌐 Haversine Nearest Cities Engine',
          category: 'Spatial Distance Math',
          color: 'border-cyan-500/50 bg-cyan-500/10 text-cyan-300',
          icon: Globe,
          file: 'getNearestCities in WeatherChatView.jsx',
          summary: 'Dynamic distance calculation engine deriving the 3 closest Indian cities relative to user coordinates.',
          details: [
            'Haversine Formula: d = 2R * asin(sqrt(sin²(Δlat/2) + cos(lat1)*cos(lat2)*sin²(Δlon/2)))',
            'Scans INDIAN_CITIES_REGISTRY (35+ major cities)',
            'Fetches live temperature in parallel for closest 3 cities',
            'Renders quick-switch city buttons (\'Mumbai 28°\', \'Pune 26°\')',
          ],
        },
      ],
    },
    {
      title: 'SECTION 3: CLIENT API GATEWAY & BACKEND AI ENGINE',
      color: 'text-cyan-400',
      nodes: [
        {
          id: 'client-api',
          title: '🔌 Client API Router (src/api.js)',
          category: 'HTTP Data Bridge',
          color: 'border-cyan-500/50 bg-cyan-500/10 text-cyan-300',
          icon: Layers,
          file: 'src/api.js',
          summary: 'Central HTTP API client fetching telemetry, IMD warnings, and communicating with FastAPI AI backend.',
          details: [
            'getWeatherByCoords(lat, lon, days) -> Open-Meteo Forecast API',
            'getAirQualityByCoords(lat, lon) -> Open-Meteo Air Quality API',
            'getIMDAlertBulletin(lat, lon) -> IMD Weather Bulletin Feed',
            'sendMessage(messages, locationContext, languageName, farmerMode, selectedCrop) -> FastAPI Backend',
          ],
        },
        {
          id: 'fastapi-backend',
          title: '🧠 FastAPI & LangGraph AI Backend',
          category: 'AI Backend Agent',
          color: 'border-rose-500/50 bg-rose-500/10 text-rose-300',
          icon: Server,
          file: 'FastAPI + LangGraph + LLaMA',
          summary: 'Stateful LangGraph agent executing prompt-engineered LLaMA LLM with crop advisory and IMD alert overlays.',
          details: [
            'State Node 1: Intent Classification (Forecast vs Advisory vs Alert)',
            'State Node 2: System Prompt Engineering (Language rules & Crop advisory context)',
            'State Node 3: LLaMA Model Execution (Structured markdown & widget:weather code-blocks)',
            'State Node 4: Official IMD Alert Bulletin Overlay (RED / ORANGE / YELLOW alerts)',
          ],
        },
        {
          id: 'external-meteo',
          title: '🌐 Open-Meteo & IMD Services',
          category: 'External Data Services',
          color: 'border-indigo-500/50 bg-indigo-500/10 text-indigo-300',
          icon: ShieldCheck,
          file: 'https://api.open-meteo.com & IMD Feeds',
          summary: 'External meteorological APIs providing high-precision weather forecasts, air quality telemetry, and warning feeds.',
          details: [
            'Open-Meteo GFS & ECMWF forecast data models',
            'US AQI, PM2.5, PM10, UV index, and surface pressure feeds',
            'IMD Cyclone, Heavy Rain, Heatwave, and Extreme Weather warnings',
          ],
        },
      ],
    },
  ]

  const allNodes = sections.flatMap((s) => s.nodes)
  const activeNodeData = allNodes.find((n) => n.id === selectedNode) || allNodes[0]

  const handleDownloadExcalidraw = () => {
    const link = document.createElement('a')
    link.href = '/weathergpt_architecture.excalidraw'
    link.download = 'weathergpt_architecture.excalidraw'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-black text-white p-4 sm:p-6 overflow-y-auto">
      <div className="max-w-6xl mx-auto w-full flex flex-col gap-6">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-white/[0.06]">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-sky-500/20 text-sky-300 border border-sky-500/30">
                EXHAUSTIVE EXCALIDRAW SYSTEM ARCHITECTURE
              </span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-display font-bold text-white tracking-tight">
              WeatherGPT Complete Architecture & Flowchart
            </h1>
            <p className="text-xs text-white/50 mt-1">
              Full end-to-end blueprint detailing UI controls, zero-scroll telemetry math, Haversine algorithms, API router, and FastAPI LangGraph AI.
            </p>
          </div>

          <button
            type="button"
            onClick={handleDownloadExcalidraw}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-white/[0.05] hover:bg-white/10 border border-white/[0.1] text-xs font-semibold text-white transition-all cursor-pointer shadow-md"
          >
            <Download size={15} className="text-sky-400" />
            <span>Download .excalidraw File</span>
          </button>
        </div>

        {/* Visual Architecture Flow Canvas */}
        <div className="bg-neutral-950/80 border border-white/[0.06] rounded-3xl p-5 sm:p-6 shadow-2xl backdrop-blur-2xl flex flex-col gap-6 relative overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-tr from-sky-950/10 via-transparent to-purple-950/10 pointer-events-none" />

          {sections.map((sec, secIdx) => (
            <div key={secIdx} className="flex flex-col gap-3">
              <span className={`text-xs uppercase tracking-wider font-bold block font-mono ${sec.color}`}>
                {sec.title}
              </span>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                {sec.nodes.map((n) => (
                  <button
                    key={n.id}
                    type="button"
                    onClick={() => setSelectedNode(n.id)}
                    className={`p-4 rounded-2xl border text-left transition-all cursor-pointer flex flex-col justify-between gap-2.5 ${
                      selectedNode === n.id ? `${n.color} ring-2 ring-white/30 shadow-xl scale-[1.02]` : 'border-white/[0.06] bg-white/[0.02] hover:bg-white/[0.05] text-white/80'
                    }`}
                  >
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center justify-between">
                        <n.icon size={16} />
                        <span className="text-[9px] font-mono opacity-50 uppercase font-semibold">{n.category}</span>
                      </div>
                      <h4 className="font-bold text-xs text-white tracking-tight mt-1">{n.title}</h4>
                    </div>
                    <p className="text-[11px] text-white/60 line-clamp-2 leading-relaxed">{n.summary}</p>
                  </button>
                ))}
              </div>
              {secIdx < sections.length - 1 && (
                <div className="flex justify-center my-1 text-white/20">
                  <ArrowRight size={18} className="rotate-90" />
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Selected Component Inspector Card */}
        {activeNodeData && (
          <div className="bg-neutral-950/80 border border-white/[0.06] rounded-3xl p-5 shadow-xl flex flex-col gap-3">
            <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
              <div className="flex items-center gap-2">
                <activeNodeData.icon size={18} className="text-accent" />
                <h3 className="font-bold text-base text-white">{activeNodeData.title}</h3>
              </div>
              <span className="text-xs font-mono text-white/40 flex items-center gap-1">
                <Code size={12} />
                {activeNodeData.file}
              </span>
            </div>

            <p className="text-xs text-white/80 leading-relaxed font-medium">
              {activeNodeData.summary}
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-2">
              {activeNodeData.details.map((d, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-white/80 bg-white/[0.02] border border-white/[0.06] px-3 py-2 rounded-xl">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent flex-shrink-0" />
                  <span>{d}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

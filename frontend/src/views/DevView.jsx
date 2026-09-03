import { useState, useEffect } from 'react'
import {
  Terminal,
  Activity,
  Cpu,
  Server,
  RefreshCw,
  Zap,
  Layers,
  Database,
  CheckCircle2,
  XCircle,
  Clock,
  Code,
  ShieldCheck,
  ChevronDown,
  ChevronUp,
  Download,
  Play,
  Sliders,
  Globe2,
  AlertTriangle,
  GitMerge,
  ArrowRight,
  FileCode,
} from 'lucide-react'
import { getDevDiagnostics, runSandboxPrompt } from '../api'
import { getEnsembleWeather } from '../utils/ensembleEngine'

const TEST_CITIES = [
  { name: 'New Delhi', lat: 28.6139, lon: 77.209 },
  { name: 'Mumbai', lat: 19.076, lon: 72.8777 },
  { name: 'Leh (Ladakh)', lat: 34.1526, lon: 77.5771 },
  { name: 'Srinagar', lat: 34.0837, lon: 74.7973 },
  { name: 'Cherrapunji', lat: 25.27, lon: 91.73 },
  { name: 'Jaisalmer', lat: 26.9157, lon: 70.9083 },
]

export default function DevView({ location, language }) {
  const [devData, setDevData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [testResult, setTestResult] = useState(null)
  const [testingEndpoint, setTestingEndpoint] = useState(false)
  const [ensembleData, setEnsembleData] = useState(null)
  const [testingEnsemble, setTestingEnsemble] = useState(false)
  const [expandedJson, setExpandedJson] = useState({})
  const [activeTab, setActiveTab] = useState('overview')
  const [selectedRawProvider, setSelectedRawProvider] = useState(null)

  // AI Sandbox state
  const [sandboxPrompt, setSandboxPrompt] = useState('Will it rain in Ahmedabad this week?')
  const [sandboxLocation, setSandboxLocation] = useState('Ahmedabad')
  const [sandboxResult, setSandboxResult] = useState(null)
  const [runningSandbox, setRunningSandbox] = useState(false)

  // Hazard Simulator state
  const [simTemp, setSimTemp] = useState(38)
  const [simRain, setSimRain] = useState(85)
  const [simWind, setSimWind] = useState(40)
  const [simAqi, setSimAqi] = useState(165)
  const [simUv, setSimUv] = useState(9)

  // City Stress Test state
  const [stressResults, setStressResults] = useState([])
  const [testingStress, setTestingStress] = useState(false)

  const fetchDiagnostics = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getDevDiagnostics()
      setDevData(data)
    } catch (err) {
      setError(err.message || 'Failed to connect to backend GET /dev')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchDiagnostics()
    runEnsembleTest()
  }, [])

  const runLatencyTest = async (type) => {
    setTestingEndpoint(true)
    const start = performance.now()
    const apiBase = (import.meta.env.VITE_API_URL || 'http://localhost:8888').replace(/\/+$/, '')
    try {
      let resData = null
      let url = ''
      if (type === 'health') {
        url = `${apiBase}/health`
        const res = await fetch(url)
        resData = await res.json()
      } else if (type === 'dev') {
        url = `${apiBase}/dev`
        const res = await fetch(url)
        resData = await res.json()
      } else if (type === 'chat') {
        url = `${apiBase}/chat`
        const res = await fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: 'Diagnostic ping test', location: 'New Delhi' }),
        })
        resData = await res.json()
      }
      const duration = Math.round(performance.now() - start)
      setTestResult({
        type,
        url,
        status: 200,
        latencyMs: duration,
        payload: resData,
        timestamp: new Date().toLocaleTimeString(),
      })
    } catch (err) {
      const duration = Math.round(performance.now() - start)
      setTestResult({
        type,
        status: 'FAILED',
        latencyMs: duration,
        error: err.message,
        timestamp: new Date().toLocaleTimeString(),
      })
    } finally {
      setTestingEndpoint(false)
    }
  }

  const runEnsembleTest = async () => {
    setTestingEnsemble(true)
    try {
      const lat = location?.lat || 28.6139
      const lon = location?.lon || 77.209
      const res = await getEnsembleWeather(lat, lon, 7)
      setEnsembleData(res)
    } catch (err) {
      setEnsembleData({ error: err.message })
    } finally {
      setTestingEnsemble(false)
    }
  }

  const handleRunSandbox = async () => {
    if (!sandboxPrompt.trim()) return
    setRunningSandbox(true)
    setSandboxResult(null)
    try {
      const data = await runSandboxPrompt(sandboxPrompt.trim(), sandboxLocation, language?.name || 'English')
      setSandboxResult(data)
    } catch (err) {
      setSandboxResult({ status: 'error', error: err.message })
    } finally {
      setRunningSandbox(false)
    }
  }

  const runMultiCityStress = async () => {
    setTestingStress(true)
    setStressResults([])
    const results = []
    for (const city of TEST_CITIES) {
      const start = performance.now()
      try {
        const res = await getEnsembleWeather(city.lat, city.lon, 3)
        const duration = Math.round(performance.now() - start)
        results.push({
          city: city.name,
          status: 'SUCCESS',
          latencyMs: duration,
          temp: res.fused?.temp,
          providersCount: res.providersUsed?.length || 0,
        })
      } catch (err) {
        const duration = Math.round(performance.now() - start)
        results.push({ city: city.name, status: 'FAILED', latencyMs: duration, error: err.message })
      }
    }
    setStressResults(results)
    setTestingStress(false)
  }

  const exportDiagnosticsReport = () => {
    const report = {
      timestamp: new Date().toISOString(),
      app: 'WeatherGPT AI Diagnostics Report',
      activeLocation: location,
      activeLanguage: language,
      devData,
      ensembleData,
      testResult,
      sandboxResult,
      localStorage: localStorageEntries(),
    }
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `weathergpt-diagnostics-${Date.now()}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  const toggleJsonExpand = (key) => {
    setExpandedJson((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  // Get local storage dump
  const localStorageEntries = () => {
    const items = {}
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i)
        if (k.startsWith('weathergpt')) {
          items[k] = localStorage.getItem(k)
        }
      }
    } catch {
      // Ignore
    }
    return items
  }

  // Computed hazard warnings for simulator
  const simulatedHazards = []
  if (simUv >= 8) simulatedHazards.push(`Extreme UV Index (${simUv}). Wear SPF 30+ & seek shade.`)
  if (simWind >= 35) simulatedHazards.push(`High Wind Warning (${simWind} km/h). Secure loose outdoor objects.`)
  if (simAqi >= 150) simulatedHazards.push(`Unhealthy Air Quality (AQI ${simAqi}). Limit outdoor exertion.`)
  if (simRain >= 75) simulatedHazards.push(`High Rain Probability (${simRain}%). Carry an umbrella today!`)
  if (simTemp >= 40) simulatedHazards.push(`Heatwave Advisory (${simTemp}°C). Stay hydrated and avoid peak sun.`)

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-[#0a0814] text-white p-4 md:p-6 no-scrollbar">
      <div className="max-w-6xl mx-auto w-full flex flex-col gap-6 h-full overflow-y-auto no-scrollbar pb-20">
        
        {/* Top Header Banner */}
        <div className="glass rounded-3xl p-6 border border-accent/40 bg-accent/10 flex flex-wrap items-center justify-between gap-4 shadow-2xl">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-accent/20 border border-accent/50 flex items-center justify-center shadow-lg">
              <Terminal size={24} className="text-accent" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl md:text-2xl font-bold font-display">Developer Diagnostics</h1>
                <span className="text-xs bg-accent/30 text-accent font-mono font-bold px-2.5 py-0.5 rounded-full border border-accent/50">
                  /dev
                </span>
              </div>
              <p className="text-white/60 text-xs md:text-sm mt-0.5">
                Real-time telemetry, visual data pipeline model, raw JSON inspector & AI prompt sandbox
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button
              onClick={exportDiagnosticsReport}
              className="glass hover:bg-white/15 text-white/90 px-3.5 py-2 rounded-2xl text-xs font-semibold flex items-center gap-1.5 border border-white/15 cursor-pointer transition-all"
            >
              <Download size={14} />
              <span>Export JSON Report</span>
            </button>

            <button
              onClick={fetchDiagnostics}
              disabled={loading}
              className="bg-accent hover:bg-accent/90 text-white px-4 py-2 rounded-2xl text-xs font-semibold flex items-center gap-2 cursor-pointer transition-all shadow-md"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              <span>Refresh Telemetry</span>
            </button>
          </div>
        </div>

        {/* Top Metrics Cards Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Card 1: Backend Connection */}
          <div className="glass rounded-3xl p-5 border border-white/10 flex flex-col justify-between">
            <div className="flex items-center justify-between text-xs text-white/50 mb-2">
              <span className="font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <Server size={14} className="text-accent" /> Backend Status
              </span>
              {devData?.status === 'ok' ? (
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
              ) : (
                <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
              )}
            </div>
            <div className="my-1">
              <span className="text-2xl font-bold font-display text-white">
                {devData?.status === 'ok' ? 'ONLINE' : error ? 'OFFLINE' : 'CHECKING...'}
              </span>
              <p className="text-[11px] text-white/50 truncate mt-1 font-mono">
                API: {import.meta.env.VITE_API_URL || 'http://localhost:8888'}
              </p>
            </div>
          </div>

          {/* Card 2: Server Uptime */}
          <div className="glass rounded-3xl p-5 border border-white/10 flex flex-col justify-between">
            <div className="flex items-center justify-between text-xs text-white/50 mb-2">
              <span className="font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <Clock size={14} className="text-sky-400" /> Uptime
              </span>
            </div>
            <div className="my-1">
              <span className="text-2xl font-bold font-display text-white">
                {devData?.uptime_seconds != null ? `${devData.uptime_seconds}s` : '--'}
              </span>
              <p className="text-[11px] text-white/50 truncate mt-1">
                Started: {devData?.server_start_time ? new Date(devData.server_start_time).toLocaleTimeString() : '--'}
              </p>
            </div>
          </div>

          {/* Card 3: Memory & CPU */}
          <div className="glass rounded-3xl p-5 border border-white/10 flex flex-col justify-between">
            <div className="flex items-center justify-between text-xs text-white/50 mb-2">
              <span className="font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <Cpu size={14} className="text-teal-400" /> Resources
              </span>
            </div>
            <div className="my-1">
              <span className="text-2xl font-bold font-display text-white">
                {devData?.system?.memory_usage_mb && devData.system.memory_usage_mb !== 'N/A'
                  ? `${devData.system.memory_usage_mb} MB`
                  : 'Serverless'}
              </span>
              <p className="text-[11px] text-white/50 truncate mt-1">
                PID: {devData?.system?.process_pid || '--'} | OS: {devData?.system?.platform?.split('-')[0] || 'Linux'}
              </p>
            </div>
          </div>

          {/* Card 4: AI LLM Engine */}
          <div className="glass rounded-3xl p-5 border border-white/10 flex flex-col justify-between">
            <div className="flex items-center justify-between text-xs text-white/50 mb-2">
              <span className="font-semibold uppercase tracking-wider flex items-center gap-1.5">
                <Zap size={14} className="text-amber-400" /> LLM Model
              </span>
            </div>
            <div className="my-1">
              <span className="text-lg font-bold font-display text-amber-300 truncate block">
                {devData?.llm_config?.model || 'qwen3.8-27b'}
              </span>
              <p className="text-[11px] text-white/50 truncate mt-1">
                Groq Key: {devData?.llm_config?.has_groq_key ? '✅ Configured' : '❌ Missing'}
              </p>
            </div>
          </div>
        </div>

        {/* Tab Switcher — Sticky Navigation Bar */}
        <div className="sticky top-0 z-30 bg-[#0a0814]/95 backdrop-blur-xl py-3 border-b border-white/10 flex items-center gap-2 overflow-x-auto no-scrollbar">
          {[
            { id: 'overview', label: 'Overview & Telemetry', icon: Activity },
            { id: 'pipeline', label: 'Data Pipeline & Raw JSON Model', icon: GitMerge },
            { id: 'sandbox', label: 'AI Agent Sandbox', icon: Play },
            { id: 'simulator', label: 'Hazard Advisory Simulator', icon: Sliders },
            { id: 'stress', label: 'Multi-City Stress Tester', icon: Globe2 },
            { id: 'endpoints', label: 'API Endpoint Tester', icon: Code },
            { id: 'ensemble', label: 'Ensemble Inspector', icon: Layers },
            { id: 'storage', label: 'Client Storage & Geo', icon: Database },
            { id: 'logs', label: 'System Logs', icon: Terminal },
          ].map((tab) => {
            const Icon = tab.icon
            const isActive = activeTab === tab.id
            return (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-2xl text-xs font-semibold transition-all cursor-pointer whitespace-nowrap ${
                  isActive
                    ? 'bg-accent text-white shadow-md border border-accent/40'
                    : 'glass text-white/60 hover:text-white hover:bg-white/10'
                }`}
              >
                <Icon size={14} />
                <span>{tab.label}</span>
              </button>
            )
          })}
        </div>

        {/* TAB 1: OVERVIEW */}
        {activeTab === 'overview' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-6 glass rounded-3xl p-6 border border-white/10 flex flex-col gap-4">
              <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                <Server size={16} className="text-accent" /> System Runtime Details
              </h3>

              <div className="flex flex-col gap-2.5 text-xs font-mono">
                <div className="flex justify-between py-2 border-b border-white/10">
                  <span className="text-white/50">Python Version:</span>
                  <span className="text-white font-semibold">{devData?.system?.python_version || '--'}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-white/10">
                  <span className="text-white/50">Platform:</span>
                  <span className="text-white font-semibold truncate max-w-[250px]">{devData?.system?.platform || '--'}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-white/10">
                  <span className="text-white/50">Server Start Time:</span>
                  <span className="text-white font-semibold">{devData?.server_start_time || '--'}</span>
                </div>
                <div className="flex justify-between py-2 border-b border-white/10">
                  <span className="text-white/50">Backend Process PID:</span>
                  <span className="text-white font-semibold">{devData?.system?.process_pid || '--'}</span>
                </div>
              </div>
            </div>

            <div className="lg:col-span-6 flex flex-col gap-6">
              <div className="glass rounded-3xl p-6 border border-white/10 flex flex-col gap-3">
                <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                  <Code size={16} className="text-sky-400" /> Active Endpoints ({devData?.registered_endpoints?.length || 0})
                </h3>
                <div className="flex flex-wrap gap-2">
                  {devData?.registered_endpoints?.map((ep, i) => (
                    <span key={i} className="glass rounded-xl px-3 py-1.5 text-xs font-mono text-emerald-300 border border-emerald-500/30">
                      {ep}
                    </span>
                  ))}
                </div>
              </div>

              <div className="glass rounded-3xl p-6 border border-white/10 flex flex-col gap-3">
                <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                  <Zap size={16} className="text-amber-400" /> Registered AI Tools ({devData?.registered_ai_tools?.length || 0})
                </h3>
                <div className="flex flex-wrap gap-2">
                  {devData?.registered_ai_tools?.map((tool, i) => (
                    <span key={i} className="glass rounded-xl px-3 py-1.5 text-xs font-mono text-amber-300 border border-amber-500/30">
                      🛠️ {tool}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="lg:col-span-12 glass rounded-3xl p-6 border border-white/10">
              <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider mb-4 flex items-center gap-2">
                <ShieldCheck size={16} className="text-emerald-400" /> Provider Environment Key Statuses
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
                {Object.entries(devData?.provider_keys_status || {}).map(([key, active]) => (
                  <div key={key} className="glass rounded-2xl p-3 flex flex-col items-center text-center border border-white/10">
                    <span className="text-[11px] text-white/50 uppercase font-mono mb-1 truncate w-full">{key.replace('_key', '')}</span>
                    {active ? (
                      <span className="text-xs font-bold text-emerald-400 flex items-center gap-1">
                        <CheckCircle2 size={12} /> Present
                      </span>
                    ) : (
                      <span className="text-xs font-bold text-white/40 flex items-center gap-1">
                        <XCircle size={12} /> Missing
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: VISUAL DATA PIPELINE MODEL & RAW JSON INSPECTOR */}
        {activeTab === 'pipeline' && (
          <div className="flex flex-col gap-8">
            <div className="glass rounded-3xl p-6 border border-accent/40 bg-black/40">
              <h3 className="text-white font-bold font-display text-base uppercase tracking-wider flex items-center gap-2 mb-2">
                <GitMerge size={20} className="text-accent" /> Live Architecture Data Pipeline Model
              </h3>
              <p className="text-white/60 text-xs leading-relaxed">
                Visual step-by-step model illustrating concurrent API provider ingestion, weighting algorithms, max-risk decision voting, and raw JSON response inspection.
              </p>
            </div>

            {/* Pipeline Stage 1: Concurrent Provider Ingestion */}
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-2">
                <span className="w-6 h-6 rounded-full bg-accent text-white font-bold text-xs flex items-center justify-center font-mono">1</span>
                <h4 className="text-white font-bold text-sm uppercase tracking-wider font-display">
                  Concurrent Provider Ingestion Layer
                </h4>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
                {[
                  { name: 'Open-Meteo (ECMWF)', key: 'openmeteo', weight: '1.0', active: true },
                  { name: 'WeatherAPI.com', key: 'weatherapi', weight: '1.2', active: !!ensembleData?.providersUsed?.some((p) => p.name.includes('WeatherAPI')) },
                  { name: 'Tomorrow.io', key: 'tomorrow', weight: '1.2', active: !!ensembleData?.providersUsed?.some((p) => p.name.includes('Tomorrow')) },
                  { name: 'OpenWeatherMap', key: 'openweather', weight: '1.1', active: !!ensembleData?.providersUsed?.some((p) => p.name.includes('OpenWeather')) },
                  { name: 'AccuWeather', key: 'accuweather', weight: '1.25', active: !!ensembleData?.providersUsed?.some((p) => p.name.includes('AccuWeather')) },
                ].map((p, i) => {
                  const providerObj = ensembleData?.providersUsed?.find((used) => used.name.toLowerCase().includes(p.key.toLowerCase())) || (p.key === 'openmeteo' ? ensembleData?.providersUsed?.[0] : null)
                  return (
                    <div
                      key={i}
                      className={`glass rounded-2xl p-4 border flex flex-col justify-between transition-all ${
                        p.active ? 'border-emerald-500/50 bg-emerald-500/10' : 'border-white/10 bg-white/5 opacity-60'
                      }`}
                    >
                      <div>
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-bold text-white truncate">{p.name}</span>
                          <span className="text-[10px] bg-accent/20 text-accent font-semibold px-2 py-0.5 rounded-full font-mono">W: {p.weight}</span>
                        </div>

                        {providerObj ? (
                          <div className="text-xs font-mono flex flex-col gap-1 text-emerald-300">
                            <span>Temp: {providerObj.temp}°C</span>
                            <span>Feels: {providerObj.feelsLike}°C</span>
                          </div>
                        ) : (
                          <span className="text-[11px] text-white/40 italic">Key Not Configured</span>
                        )}
                      </div>

                      <button
                        onClick={() => setSelectedRawProvider(providerObj || { name: p.name, raw: { note: 'No key provided for this provider in .env' } })}
                        className="mt-3 bg-white/10 hover:bg-white/20 text-white text-[11px] font-semibold py-1.5 rounded-xl flex items-center justify-center gap-1 cursor-pointer transition-all border border-white/15"
                      >
                        <FileCode size={12} className="text-accent" />
                        <span>View Raw JSON</span>
                      </button>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Pipeline Stage 2: Weighting & Fusion Math Engine */}
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-2">
                <span className="w-6 h-6 rounded-full bg-amber-400 text-black font-bold text-xs flex items-center justify-center font-mono">2</span>
                <h4 className="text-white font-bold text-sm uppercase tracking-wider font-display">
                  Mathematical Fusion & Weighting Engine
                </h4>
              </div>

              <div className="glass rounded-3xl p-6 border border-amber-500/30 bg-amber-500/5 flex flex-col gap-4 font-mono text-xs">
                <div className="p-4 bg-black/60 rounded-2xl border border-white/10 text-amber-300">
                  <p className="font-bold text-white mb-1 font-sans text-sm">Weighted Average Formula:</p>
                  <p className="text-emerald-300">Fused Temperature = Σ ( Temp_i × Weight_i ) / Σ ( Weight_i )</p>
                </div>

                {ensembleData?.providersUsed?.length > 0 && (
                  <div className="flex flex-col gap-2">
                    <span className="text-white/60 font-sans font-semibold">Live Weighted Calculation Trace:</span>
                    <div className="glass rounded-2xl p-4 bg-black/40 border border-white/10 text-white/80 space-y-1">
                      {ensembleData.providersUsed.map((p, i) => (
                        <div key={i} className="flex justify-between text-[11px]">
                          <span>{p.name}: {p.temp}°C × {p.weight} = {(p.temp * p.weight).toFixed(2)}</span>
                          <span className="text-emerald-400">Weight: {p.weight}</span>
                        </div>
                      ))}
                      <div className="pt-2 border-t border-white/10 flex justify-between font-bold text-emerald-300 text-xs">
                        <span>Fused Output Result:</span>
                        <span>{ensembleData.fused?.temp}°C</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Pipeline Stage 3: Synthesized Output JSON */}
            <div className="flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-emerald-400 text-black font-bold text-xs flex items-center justify-center font-mono">3</span>
                  <h4 className="text-white font-bold text-sm uppercase tracking-wider font-display">
                    Final Synthesized Telemetry Stream (JSON)
                  </h4>
                </div>
              </div>

              <pre className="text-xs font-mono text-emerald-300 bg-black/80 rounded-3xl p-6 overflow-x-auto border border-white/15 shadow-2xl max-h-96">
                {JSON.stringify(ensembleData?.fused || ensembleData, null, 2)}
              </pre>
            </div>
          </div>
        )}

        {/* RAW PROVIDER JSON MODAL */}
        {selectedRawProvider && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-md">
            <div className="glass rounded-3xl p-6 border border-accent/40 bg-[#0d0b1a] max-w-3xl w-full max-h-[85vh] flex flex-col gap-4 shadow-2xl">
              <div className="flex items-center justify-between pb-3 border-b border-white/10">
                <div className="flex items-center gap-2">
                  <FileCode size={18} className="text-accent" />
                  <h3 className="text-white font-bold font-display text-sm uppercase">{selectedRawProvider.name} Raw JSON Payload</h3>
                </div>
                <button
                  onClick={() => setSelectedRawProvider(null)}
                  className="text-white/50 hover:text-white text-xs font-mono px-3 py-1 glass rounded-xl border border-white/15 cursor-pointer"
                >
                  ✕ Close
                </button>
              </div>

              <pre className="text-xs font-mono text-emerald-300 bg-black/80 rounded-2xl p-5 overflow-y-auto max-h-[60vh] border border-white/10 no-scrollbar">
                {JSON.stringify(selectedRawProvider.raw || selectedRawProvider, null, 2)}
              </pre>
            </div>
          </div>
        )}

        {/* TAB 3: AI AGENT SANDBOX */}
        {activeTab === 'sandbox' && (
          <div className="flex flex-col gap-6">
            <div className="glass rounded-3xl p-6 border border-white/10 flex flex-col gap-4">
              <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                <Play size={16} className="text-accent" /> AI Weather Agent Prompt Sandbox
              </h3>
              <p className="text-white/60 text-xs">
                Directly execute prompts against ChatGroq (`qwen/qwen3.8-27b`) and monitor execution latency & model tool calls.
              </p>

              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-2">
                  <input
                    type="text"
                    value={sandboxPrompt}
                    onChange={(e) => setSandboxPrompt(e.target.value)}
                    placeholder="Enter test prompt..."
                    className="flex-1 glass rounded-2xl px-4 py-2.5 text-xs text-white bg-white/5 border border-white/15 focus:outline-none focus:border-accent"
                  />
                  <input
                    type="text"
                    value={sandboxLocation}
                    onChange={(e) => setSandboxLocation(e.target.value)}
                    placeholder="Location"
                    className="w-36 glass rounded-2xl px-4 py-2.5 text-xs text-white bg-white/5 border border-white/15 focus:outline-none focus:border-accent"
                  />
                  <button
                    onClick={handleRunSandbox}
                    disabled={runningSandbox}
                    className="bg-accent hover:bg-accent/90 text-white font-semibold px-5 py-2.5 rounded-2xl text-xs flex items-center gap-2 cursor-pointer transition-all shadow-md"
                  >
                    <Play size={14} className={runningSandbox ? 'animate-spin' : ''} />
                    <span>{runningSandbox ? 'Executing...' : 'Run Prompt'}</span>
                  </button>
                </div>
              </div>
            </div>

            {sandboxResult && (
              <div className="glass rounded-3xl p-6 border border-white/15 bg-black/40 shadow-2xl flex flex-col gap-4">
                <div className="flex items-center justify-between pb-3 border-b border-white/10 text-xs font-mono">
                  <span className="text-emerald-400 font-bold">STATUS: {sandboxResult.status?.toUpperCase()}</span>
                  <span className="text-sky-300">Duration: {sandboxResult.duration_ms} ms</span>
                  <span className="text-amber-300">Model: {sandboxResult.model_used || 'qwen3.8-27b'}</span>
                </div>

                <div>
                  <h4 className="text-xs text-white/50 uppercase font-mono mb-1">Agent Response:</h4>
                  <div className="glass rounded-2xl p-4 text-xs text-white/90 leading-relaxed bg-white/5 border border-white/10 whitespace-pre-wrap font-sans">
                    {sandboxResult.response || sandboxResult.error}
                  </div>
                </div>

                <div>
                  <h4 className="text-xs text-white/50 uppercase font-mono mb-1">Raw Execution Payload:</h4>
                  <pre className="text-xs font-mono text-emerald-300 bg-black/60 rounded-2xl p-4 overflow-x-auto border border-white/10">
                    {JSON.stringify(sandboxResult, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 4: HAZARD SIMULATOR */}
        {activeTab === 'simulator' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-6 glass rounded-3xl p-6 border border-white/10 flex flex-col gap-5">
              <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                <Sliders size={16} className="text-amber-400" /> IMD Hazard Advisory Rule Simulator
              </h3>

              <div className="flex flex-col gap-4 text-xs">
                <div>
                  <div className="flex justify-between mb-1">
                    <span className="text-white/70">Temperature (°C):</span>
                    <span className="text-amber-300 font-bold">{simTemp}°C</span>
                  </div>
                  <input type="range" min="0" max="50" value={simTemp} onChange={(e) => setSimTemp(Number(e.target.value))} className="w-full accent-accent" />
                </div>

                <div>
                  <div className="flex justify-between mb-1">
                    <span className="text-white/70">Rain Probability (%):</span>
                    <span className="text-sky-300 font-bold">{simRain}%</span>
                  </div>
                  <input type="range" min="0" max="100" value={simRain} onChange={(e) => setSimRain(Number(e.target.value))} className="w-full accent-accent" />
                </div>

                <div>
                  <div className="flex justify-between mb-1">
                    <span className="text-white/70">Wind Speed (km/h):</span>
                    <span className="text-teal-300 font-bold">{simWind} km/h</span>
                  </div>
                  <input type="range" min="0" max="100" value={simWind} onChange={(e) => setSimWind(Number(e.target.value))} className="w-full accent-accent" />
                </div>

                <div>
                  <div className="flex justify-between mb-1">
                    <span className="text-white/70">Air Quality (US AQI):</span>
                    <span className="text-purple-300 font-bold">{simAqi}</span>
                  </div>
                  <input type="range" min="0" max="400" value={simAqi} onChange={(e) => setSimAqi(Number(e.target.value))} className="w-full accent-accent" />
                </div>

                <div>
                  <div className="flex justify-between mb-1">
                    <span className="text-white/70">UV Index:</span>
                    <span className="text-rose-300 font-bold">{simUv}</span>
                  </div>
                  <input type="range" min="0" max="12" value={simUv} onChange={(e) => setSimUv(Number(e.target.value))} className="w-full accent-accent" />
                </div>
              </div>
            </div>

            <div className="lg:col-span-6 glass rounded-3xl p-6 border border-white/10 flex flex-col gap-4">
              <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                <AlertTriangle size={16} className="text-rose-400" /> Simulated Dashboard Banner Output
              </h3>

              {simulatedHazards.length > 0 ? (
                <div className="glass rounded-2xl p-4 border border-amber-500/40 bg-amber-500/10 flex flex-col gap-2">
                  <div className="flex items-center gap-2 text-amber-400 font-bold text-xs uppercase tracking-wider">
                    <AlertTriangle size={16} /> Live Severe Environmental Advisories ({simulatedHazards.length})
                  </div>
                  <ul className="flex flex-col gap-1 text-xs text-white/90 list-disc list-inside">
                    {simulatedHazards.map((h, i) => (
                      <li key={i}>{h}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <div className="glass rounded-2xl p-6 text-center border border-emerald-500/30 bg-emerald-500/10 text-emerald-300 text-xs">
                  ✅ Standard Conditions — No severe hazard advisories triggered.
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 5: STRESS TESTER */}
        {activeTab === 'stress' && (
          <div className="flex flex-col gap-6">
            <div className="glass rounded-3xl p-6 border border-white/10 flex items-center justify-between gap-4">
              <div>
                <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                  <Globe2 size={16} className="text-sky-400" /> Multi-City Ensemble Telemetry Stress Tester
                </h3>
                <p className="text-white/50 text-xs mt-1">
                  Tests ensemble data fetching across 6 diverse geographical regions (Delhi, Mumbai, Ladakh, Kashmir, Meghalaya, Thar Desert).
                </p>
              </div>

              <button
                onClick={runMultiCityStress}
                disabled={testingStress}
                className="bg-sky-500 hover:bg-sky-600 text-white font-semibold px-4 py-2.5 rounded-2xl text-xs flex items-center gap-2 transition-all cursor-pointer shadow-md flex-shrink-0"
              >
                <RefreshCw size={14} className={testingStress ? 'animate-spin' : ''} />
                <span>Run Stress Test</span>
              </button>
            </div>

            {stressResults.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {stressResults.map((r, i) => (
                  <div key={i} className="glass rounded-2xl p-4 border border-white/10 flex flex-col justify-between">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs font-bold text-white font-display">{r.city}</span>
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${r.status === 'SUCCESS' ? 'bg-emerald-500/20 text-emerald-300' : 'bg-rose-500/20 text-rose-300'}`}>
                        {r.status}
                      </span>
                    </div>
                    {r.status === 'SUCCESS' ? (
                      <div>
                        <p className="text-xl font-bold text-emerald-300">{r.temp}°C</p>
                        <p className="text-xs text-white/50">Latency: {r.latencyMs} ms | Providers: {r.providersCount}</p>
                      </div>
                    ) : (
                      <p className="text-xs text-rose-300">{r.error}</p>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* TAB 6: ENDPOINT TESTER */}
        {activeTab === 'endpoints' && (
          <div className="flex flex-col gap-6">
            <div className="glass rounded-3xl p-6 border border-white/10 flex flex-col gap-4">
              <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                <Zap size={16} className="text-accent" /> Execute Live Endpoint Latency Test
              </h3>

              <div className="flex flex-wrap gap-3">
                <button
                  onClick={() => runLatencyTest('health')}
                  disabled={testingEndpoint}
                  className="bg-accent/20 hover:bg-accent/40 text-accent font-semibold px-4 py-2.5 rounded-2xl text-xs border border-accent/40 transition-all cursor-pointer"
                >
                  Test GET /health
                </button>

                <button
                  onClick={() => runLatencyTest('dev')}
                  disabled={testingEndpoint}
                  className="bg-sky-500/20 hover:bg-sky-500/40 text-sky-300 font-semibold px-4 py-2.5 rounded-2xl text-xs border border-sky-500/40 transition-all cursor-pointer"
                >
                  Test GET /dev
                </button>

                <button
                  onClick={() => runLatencyTest('chat')}
                  disabled={testingEndpoint}
                  className="bg-amber-500/20 hover:bg-amber-500/40 text-amber-300 font-semibold px-4 py-2.5 rounded-2xl text-xs border border-amber-500/40 transition-all cursor-pointer"
                >
                  Test POST /chat (Sample Ping)
                </button>
              </div>
            </div>

            {testResult && (
              <div className="glass rounded-3xl p-6 border border-white/15 bg-black/40 shadow-2xl">
                <div className="flex items-center justify-between pb-3 border-b border-white/10 mb-4">
                  <div className="flex items-center gap-2 font-mono text-xs">
                    <span className="text-emerald-400 font-bold">STATUS {testResult.status}</span>
                    <span className="text-white/40">|</span>
                    <span className="text-sky-300 font-bold">{testResult.latencyMs} ms</span>
                    <span className="text-white/40">|</span>
                    <span className="text-white/60">{testResult.timestamp}</span>
                  </div>
                  <button
                    onClick={() => toggleJsonExpand('testResult')}
                    className="text-xs text-accent underline flex items-center gap-1"
                  >
                    {expandedJson['testResult'] ? <ChevronUp size={14} /> : <ChevronDown size={14} />} JSON Payload
                  </button>
                </div>

                <pre className="text-xs font-mono text-emerald-300 bg-black/60 rounded-2xl p-4 overflow-x-auto border border-white/10 max-h-96">
                  {JSON.stringify(testResult.payload || testResult, null, 2)}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* TAB 7: ENSEMBLE INSPECTOR */}
        {activeTab === 'ensemble' && (
          <div className="flex flex-col gap-6">
            <div className="glass rounded-3xl p-6 border border-white/10 flex items-center justify-between gap-4">
              <div>
                <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                  <Layers size={16} className="text-emerald-400" /> Multi-Source Ensemble Telemetry Debugger
                </h3>
                <p className="text-white/50 text-xs mt-1">
                  Executes live concurrent requests to Open-Meteo, WeatherAPI, Tomorrow.io, OpenWeather, and AccuWeather.
                </p>
              </div>

              <button
                onClick={runEnsembleTest}
                disabled={testingEnsemble}
                className="bg-emerald-500 hover:bg-emerald-600 text-white font-semibold px-4 py-2.5 rounded-2xl text-xs flex items-center gap-2 transition-all cursor-pointer shadow-md flex-shrink-0"
              >
                <RefreshCw size={14} className={testingEnsemble ? 'animate-spin' : ''} />
                <span>Run Ensemble Test</span>
              </button>
            </div>

            {ensembleData && (
              <div className="glass rounded-3xl p-6 border border-white/15 bg-black/40 shadow-2xl flex flex-col gap-4">
                <h4 className="text-white font-bold text-xs uppercase tracking-wider text-accent">Providers Responded ({ensembleData.providersUsed?.length || 0})</h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                  {ensembleData.providersUsed?.map((p, i) => (
                    <div key={i} className="glass rounded-2xl p-4 border border-white/10">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-bold text-white font-display">{p.name}</span>
                        <span className="text-[10px] bg-accent/20 text-accent font-semibold px-2 py-0.5 rounded-full">Weight {p.weight}</span>
                      </div>
                      <p className="text-lg font-bold text-emerald-300">{p.temp}°C</p>
                      <p className="text-xs text-white/50 truncate">Feels Like: {p.feelsLike}°C</p>
                      <p className="text-xs text-white/40 truncate">Condition: {p.condition}</p>
                    </div>
                  ))}
                </div>

                <div className="pt-4 border-t border-white/10">
                  <span className="text-xs text-white/50 block mb-2 font-mono">Fused Output Metrics:</span>
                  <pre className="text-xs font-mono text-emerald-300 bg-black/60 rounded-2xl p-4 overflow-x-auto border border-white/10">
                    {JSON.stringify(ensembleData.fused, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        )}

        {/* TAB 8: CLIENT STORAGE & GEO */}
        {activeTab === 'storage' && (
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            <div className="lg:col-span-6 glass rounded-3xl p-6 border border-white/10 flex flex-col gap-3">
              <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                <Database size={16} className="text-sky-400" /> Active Client Location & Language Prop
              </h3>
              <pre className="text-xs font-mono text-sky-300 bg-black/60 rounded-2xl p-4 overflow-x-auto border border-white/10">
                {JSON.stringify({ location, language }, null, 2)}
              </pre>
            </div>

            <div className="lg:col-span-6 glass rounded-3xl p-6 border border-white/10 flex flex-col gap-3">
              <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2">
                <Code size={16} className="text-amber-400" /> Browser LocalStorage Dump
              </h3>
              <pre className="text-xs font-mono text-amber-300 bg-black/60 rounded-2xl p-4 overflow-x-auto border border-white/10">
                {JSON.stringify(localStorageEntries(), null, 2)}
              </pre>
            </div>
          </div>
        )}

        {/* TAB 9: SYSTEM LOGS */}
        {activeTab === 'logs' && (
          <div className="glass rounded-3xl p-6 border border-white/15 bg-black/50 shadow-2xl flex flex-col gap-3">
            <h3 className="text-white font-bold font-display text-sm uppercase tracking-wider flex items-center gap-2 mb-2">
              <Terminal size={16} className="text-emerald-400" /> Live Backend Event & Log Console
            </h3>

            <div className="bg-black/80 rounded-2xl p-4 font-mono text-xs border border-white/10 max-h-96 overflow-y-auto flex flex-col gap-2 no-scrollbar">
              {devData?.recent_logs?.length > 0 ? (
                devData.recent_logs.map((log, i) => (
                  <div key={i} className="flex flex-col gap-0.5 pb-2 border-b border-white/10 last:border-0">
                    <div className="flex items-center gap-2">
                      <span className="text-white/40 text-[10px]">{new Date(log.timestamp).toLocaleTimeString()}</span>
                      <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${log.level === 'ERROR' ? 'bg-rose-500/30 text-rose-400' : 'bg-emerald-500/20 text-emerald-400'}`}>
                        {log.level}
                      </span>
                      <span className="text-white/90 font-medium">{log.message}</span>
                    </div>
                    {Object.keys(log.details || {}).length > 0 && (
                      <span className="text-[11px] text-white/50 pl-4">{JSON.stringify(log.details)}</span>
                    )}
                  </div>
                ))
              ) : (
                <p className="text-white/40 italic">No system logs recorded yet.</p>
              )}
            </div>
          </div>
        )}

      </div>
    </div>
  )
}

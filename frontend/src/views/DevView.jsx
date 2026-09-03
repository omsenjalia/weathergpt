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
} from 'lucide-react'
import { getDevDiagnostics } from '../api'
import { getEnsembleWeather } from '../utils/ensembleEngine'

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
  }, [])

  const runLatencyTest = async (type) => {
    setTestingEndpoint(true)
    const start = performance.now()
    try {
      let resData = null
      let url = ''
      if (type === 'health') {
        url = `${import.meta.env.VITE_API_URL || 'http://localhost:8888'}/health`
        const res = await fetch(url)
        resData = await res.json()
      } else if (type === 'dev') {
        url = `${import.meta.env.VITE_API_URL || 'http://localhost:8888'}/dev`
        const res = await fetch(url)
        resData = await res.json()
      } else if (type === 'chat') {
        url = `${import.meta.env.VITE_API_URL || 'http://localhost:8888'}/chat`
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
                Real-time backend telemetry, API latency benchmarker & ensemble inspector
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
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
              <p className="text-[11px] text-white/50 truncate mt-1">
                Port: 8888 | Endpoint: /dev
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
                {devData?.system?.memory_usage_mb != null ? `${devData.system.memory_usage_mb} MB` : '--'}
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

        {/* Tab Switcher */}
        <div className="flex items-center gap-2 border-b border-white/10 pb-3 overflow-x-auto no-scrollbar">
          {[
            { id: 'overview', label: 'Overview & Telemetry', icon: Activity },
            { id: 'endpoints', label: 'API Endpoint Tester', icon: Code },
            { id: 'ensemble', label: 'Ensemble Inspector', icon: Layers },
            { id: 'storage', label: 'Client Storage & Geo', icon: Database },
            { id: 'logs', label: 'Recent System Logs', icon: Terminal },
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
            {/* System Details */}
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

            {/* Registered Endpoints & AI Tools */}
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

            {/* Provider Keys Configuration Status */}
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

        {/* TAB 2: ENDPOINT TESTER */}
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

            {/* Test Result Display */}
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

        {/* TAB 3: ENSEMBLE INSPECTOR */}
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

        {/* TAB 4: CLIENT STORAGE & GEO */}
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

        {/* TAB 5: SYSTEM LOGS */}
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

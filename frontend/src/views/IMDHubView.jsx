import { useState, useEffect } from 'react'
import { getIMDFeatures, queryIMDAPI } from '../api'
import AnimatedContent from '../components/bits/AnimatedContent'
import {
  ShieldCheck,
  Terminal,
  Play,
  Copy,
  Check,
  Search,
  ExternalLink,
  Zap,
  Radio,
  FileCode,
  Layers,
  CloudRain,
  Wind,
  Sun,
  AlertTriangle,
  Anchor,
  Compass,
  Cpu,
  Sprout
} from 'lucide-react'

const CATEGORIES = [
  'All APIs',
  'Weather Forecast',
  'Current Weather & Nowcast',
  'Warning APIs',
  'Rainfall APIs',
  'Marine APIs',
  'Cyclone APIs',
  'Astronomical API',
  'NHAI API',
  'RADAR & Lightning API',
  'Agromet Advisory API'
]

export default function IMDHubView({ location }) {
  const [features, setFeatures] = useState([])
  const [selectedApi, setSelectedApi] = useState(null)
  const [selectedCategory, setSelectedCategory] = useState('All APIs')
  const [searchQuery, setSearchQuery] = useState('')
  const [params, setParams] = useState({})
  const [queryResult, setQueryResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)
  const [viewTab, setViewTab] = useState('visual') // 'visual' or 'json'

  useEffect(() => {
    async function loadCatalog() {
      const res = await getIMDFeatures()
      if (res && res.features && res.features.length > 0) {
        setFeatures(res.features)
        const firstApi = res.features[0]
        setSelectedApi(firstApi)
        setParams(firstApi.default_params || {})
      }
    }
    loadCatalog()
  }, [])

  const handleSelectApi = (api) => {
    setSelectedApi(api)
    setParams(api.default_params || {})
    setQueryResult(null)
  }

  const handleParamChange = (key, value) => {
    setParams((prev) => ({ ...prev, [key]: value }))
  }

  const handleRunQuery = async () => {
    if (!selectedApi) return
    setLoading(true)
    try {
      const res = await queryIMDAPI(selectedApi.id, params)
      setQueryResult(res)
    } catch (err) {
      setQueryResult({ status: 500, error: err.message })
    } finally {
      setLoading(false)
    }
  }

  const copyCurl = () => {
    if (!queryResult?.curl_command && !selectedApi) return
    const cmd = queryResult?.curl_command || `curl -s -X GET "https://api.imd.gov.in/api/v1${selectedApi.endpoint}" -H "x-api-key: $IMD_API_KEY"`
    navigator.clipboard.writeText(cmd)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const filteredApis = features.filter((api) => {
    const matchesCategory = selectedCategory === 'All APIs' || api.category === selectedCategory
    const matchesSearch =
      api.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      api.endpoint.toLowerCase().includes(searchQuery.toLowerCase()) ||
      api.id.toLowerCase().includes(searchQuery.toLowerCase())
    return matchesCategory && matchesSearch
  })

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-black text-white relative">
      {/* IMD Official Portal Header */}
      <div className="glass border-b border-white/10 px-4 py-4 flex-shrink-0 z-20">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-blue-600 to-indigo-700 p-0.5 shadow-lg flex items-center justify-center">
              <ShieldCheck className="w-7 h-7 text-amber-300" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl md:text-2xl font-bold font-display text-white tracking-tight">
                  IMD Official API Hub
                </h1>
                <span className="bg-amber-500/20 text-amber-300 border border-amber-500/40 text-[10px] uppercase font-bold px-2 py-0.5 rounded-full tracking-wider flex items-center gap-1">
                  <Zap size={10} /> Priority 1 Official Trust
                </span>
              </div>
              <p className="text-white/60 text-xs mt-0.5">
                India Meteorological Department • Ministry of Earth Sciences • Government of India
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <a
              href="https://api.imd.gov.in/public/api_reference.html"
              target="_blank"
              rel="noreferrer"
              className="glass hover:bg-white/15 text-white/80 hover:text-white px-3.5 py-2 rounded-xl text-xs font-semibold flex items-center gap-1.5 border border-white/10 transition-all cursor-pointer"
            >
              <ExternalLink size={14} /> Official IMD Doc
            </a>
          </div>
        </div>
      </div>

      {/* Main Content Area: Left Catalog & Right Tester */}
      <div className="flex-1 overflow-y-auto no-scrollbar p-4 md:p-6">
        <div className="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-6 pb-20 md:pb-6">
          
          {/* Left Column: API Search & 28 API Catalog List */}
          <div className="lg:col-span-5 flex flex-col gap-4">
            
            {/* Search Bar */}
            <div className="relative">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 text-white/40" size={16} />
              <input
                type="text"
                placeholder="Search 28 IMD APIs (e.g. City Forecast, Cyclone, Agromet)..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-white/5 border border-white/15 rounded-2xl pl-10 pr-4 py-2.5 text-xs text-white placeholder-white/40 focus:outline-none focus:border-accent transition-all"
              />
            </div>

            {/* Category Filter Pills */}
            <div className="flex gap-1.5 overflow-x-auto no-scrollbar pb-1">
              {CATEGORIES.map((cat, i) => (
                <button
                  key={i}
                  onClick={() => setSelectedCategory(cat)}
                  className={`px-3 py-1.5 rounded-xl text-[11px] font-medium whitespace-nowrap transition-all cursor-pointer border ${
                    selectedCategory === cat
                      ? 'bg-accent text-white border-accent shadow-md'
                      : 'bg-white/5 text-white/60 hover:text-white border-white/10 hover:bg-white/10'
                  }`}
                >
                  {cat}
                </button>
              ))}
            </div>

            {/* API List Catalog */}
            <div className="glass rounded-3xl p-3 border border-white/10 flex flex-col gap-2 max-h-[600px] overflow-y-auto no-scrollbar">
              <div className="flex items-center justify-between px-2 py-1 border-b border-white/10 mb-1">
                <span className="text-white/50 text-xs font-semibold uppercase tracking-wider">
                  Available APIs ({filteredApis.length})
                </span>
                <span className="text-[10px] text-amber-400 font-bold bg-amber-400/10 px-2 py-0.5 rounded-full border border-amber-400/20">
                  Government of India
                </span>
              </div>

              {filteredApis.map((api) => {
                const isSelected = selectedApi?.id === api.id
                return (
                  <button
                    key={api.id}
                    onClick={() => handleSelectApi(api)}
                    className={`text-left p-3.5 rounded-2xl transition-all border cursor-pointer flex flex-col gap-1 ${
                      isSelected
                        ? 'bg-accent/25 border-accent shadow-lg scale-[1.01]'
                        : 'bg-white/5 hover:bg-white/10 border-white/10 hover:border-white/20'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-bold text-accent font-mono">{api.id}</span>
                      <span className="text-[10px] text-white/50 font-medium px-2 py-0.5 rounded-md bg-white/5 border border-white/10 truncate max-w-[140px]">
                        {api.category}
                      </span>
                    </div>
                    <h3 className="text-white text-sm font-semibold truncate">{api.name}</h3>
                    <p className="text-white/50 text-[11px] line-clamp-2 leading-relaxed">{api.description}</p>
                    <div className="text-[10px] font-mono text-emerald-400 mt-1 truncate">
                      {api.endpoint}
                    </div>
                  </button>
                )
              })}
            </div>

          </div>

          {/* Right Column: Selected API Explorer & Live curl Tester */}
          <div className="lg:col-span-7 flex flex-col gap-6">
            {selectedApi ? (
              <AnimatedContent key={selectedApi.id} delay={0.1}>
                <div className="glass rounded-3xl p-6 border border-white/15 shadow-2xl flex flex-col gap-5">
                  
                  {/* API Header & Info */}
                  <div className="border-b border-white/10 pb-4">
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <span className="bg-accent/20 text-accent font-mono font-bold text-xs px-2.5 py-1 rounded-lg border border-accent/30">
                        {selectedApi.id}
                      </span>
                      <span className="text-xs font-semibold text-amber-400 bg-amber-400/10 px-3 py-1 rounded-full border border-amber-400/20 flex items-center gap-1">
                        <ShieldCheck size={12} /> {selectedApi.category}
                      </span>
                    </div>
                    <h2 className="text-xl font-bold font-display text-white mb-1">{selectedApi.name}</h2>
                    <p className="text-white/70 text-xs leading-relaxed">{selectedApi.description}</p>
                    <div className="mt-3 flex items-center gap-2 text-xs font-mono text-emerald-400 bg-emerald-500/10 px-3 py-1.5 rounded-xl border border-emerald-500/20 w-fit">
                      <span className="font-bold text-emerald-300">GET</span> https://api.imd.gov.in/api/v1{selectedApi.endpoint}
                    </div>
                  </div>

                  {/* Parameter Customizer Inputs */}
                  <div>
                    <h3 className="text-white/70 text-xs font-bold uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <Layers size={14} className="text-accent" /> API Query Parameters
                    </h3>
                    
                    {Object.keys(selectedApi.default_params || {}).length > 0 ? (
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        {Object.entries(selectedApi.default_params).map(([paramKey, defaultVal]) => (
                          <div key={paramKey} className="flex flex-col gap-1">
                            <label className="text-white/60 text-[11px] font-mono font-semibold uppercase">{paramKey}</label>
                            <input
                              type="text"
                              value={params[paramKey] !== undefined ? params[paramKey] : defaultVal}
                              onChange={(e) => handleParamChange(paramKey, e.target.value)}
                              className="bg-white/5 border border-white/15 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-accent font-mono"
                            />
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-white/40 text-xs italic bg-white/5 p-3 rounded-xl border border-white/10">
                        This endpoint does not require mandatory query parameters. Click 'Execute curl Query' to fetch telemetry.
                      </p>
                    )}
                  </div>

                  {/* Execution Control & Live curl Code Box */}
                  <div className="flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <span className="text-white/70 text-xs font-bold uppercase tracking-wider flex items-center gap-1.5">
                        <Terminal size={14} className="text-emerald-400" /> CLI `curl` Command
                      </span>
                      <button
                        onClick={copyCurl}
                        className="text-xs text-white/70 hover:text-white flex items-center gap-1 cursor-pointer transition-colors bg-white/5 hover:bg-white/10 px-2.5 py-1 rounded-lg border border-white/10"
                      >
                        {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
                        <span>{copied ? 'Copied!' : 'Copy curl'}</span>
                      </button>
                    </div>

                    <div className="bg-slate-950 rounded-2xl p-3.5 border border-white/10 font-mono text-xs text-emerald-400 overflow-x-auto relative">
                      <pre className="whitespace-pre-wrap word-break-all">
                        {queryResult?.curl_command || `curl -s -X GET "https://api.imd.gov.in/api/v1${selectedApi.endpoint}" \\\n  -H "x-api-key: $IMD_API_KEY" \\\n  -H "Authorization: Bearer $IMD_JWT_TOKEN"`}
                      </pre>
                    </div>

                    <button
                      onClick={handleRunQuery}
                      disabled={loading}
                      className="bg-accent hover:bg-accent/90 text-white rounded-2xl py-3 px-6 text-sm font-bold shadow-lg transition-all flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
                    >
                      {loading ? (
                        <>
                          <Radio className="animate-spin" size={16} /> Fetching from IMD API...
                        </>
                      ) : (
                        <>
                          <Play size={16} className="fill-white" /> Execute curl Query & Fetch Telemetry
                        </>
                      )}
                    </button>
                  </div>

                  {/* Results & Visual Output Tabs */}
                  {queryResult && (
                    <div className="pt-4 border-t border-white/10 flex flex-col gap-3">
                      <div className="flex items-center justify-between flex-wrap gap-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-white uppercase tracking-wider">Response:</span>
                          <span className="text-xs font-mono font-semibold px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                            HTTP {queryResult.status || 200} OK
                          </span>
                          {queryResult.is_live_imd_server ? (
                            <span className="text-[10px] font-bold text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full border border-emerald-400/30">
                              Live Server Connected
                            </span>
                          ) : (
                            <span className="text-[10px] font-bold text-amber-400 bg-amber-400/10 px-2 py-0.5 rounded-full border border-amber-400/30">
                              IMD Verified Telemetry Schema
                            </span>
                          )}
                        </div>

                        {/* Visual vs JSON Switcher */}
                        <div className="flex gap-1 bg-white/5 p-1 rounded-xl border border-white/10">
                          <button
                            onClick={() => setViewTab('visual')}
                            className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                              viewTab === 'visual' ? 'bg-accent text-white shadow-sm' : 'text-white/60 hover:text-white'
                            }`}
                          >
                            Visual View
                          </button>
                          <button
                            onClick={() => setViewTab('json')}
                            className={`px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
                              viewTab === 'json' ? 'bg-accent text-white shadow-sm' : 'text-white/60 hover:text-white'
                            }`}
                          >
                            Raw JSON
                          </button>
                        </div>
                      </div>

                      {/* Display View Content */}
                      {viewTab === 'json' ? (
                        <div className="bg-slate-950 rounded-2xl p-4 border border-white/10 font-mono text-xs text-sky-300 max-h-96 overflow-y-auto no-scrollbar">
                          <pre>{JSON.stringify(queryResult.data, null, 2)}</pre>
                        </div>
                      ) : (
                        <div className="bg-white/5 rounded-2xl p-4 border border-white/10 flex flex-col gap-3">
                          {Array.isArray(queryResult.data) ? (
                            <div className="flex flex-col gap-3">
                              {queryResult.data.map((item, idx) => (
                                <div key={idx} className="glass rounded-xl p-3.5 border border-white/10 flex flex-col gap-2">
                                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                                    {Object.entries(item).map(([k, v]) => (
                                      <div key={k} className="bg-white/5 p-2 rounded-lg border border-white/5">
                                        <span className="text-white/50 text-[10px] block font-mono uppercase">{k.replace(/_/g, ' ')}</span>
                                        <span className="text-white font-medium break-all">{String(v)}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ))}
                            </div>
                          ) : typeof queryResult.data === 'object' && queryResult.data !== null ? (
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                              {Object.entries(queryResult.data).map(([k, v]) => (
                                <div key={k} className="glass rounded-xl p-3 border border-white/10">
                                  <span className="text-white/50 text-[10px] block font-mono uppercase">{k.replace(/_/g, ' ')}</span>
                                  <span className="text-white font-medium break-all">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <p className="text-white text-xs font-mono">{String(queryResult.data)}</p>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                </div>
              </AnimatedContent>
            ) : (
              <div className="glass rounded-3xl p-12 text-center text-white/50 flex flex-col items-center justify-center">
                <ShieldCheck size={48} className="text-accent mb-3" />
                <p className="text-lg font-bold text-white mb-1">Select an IMD API Endpoint</p>
                <p className="text-xs text-white/60">Choose any of the 28 official IMD APIs from the left catalog to inspect and test with curl.</p>
              </div>
            )}
          </div>

        </div>
      </div>
    </div>
  )
}

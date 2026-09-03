import { useState, useEffect } from 'react'
import { X, Key, CheckCircle, ShieldCheck, ExternalLink, RefreshCw } from 'lucide-react'
import { getProviderKeys } from '../utils/ensembleEngine'

export default function ApiSettingsModal({ isOpen, onClose }) {
  const [keys, setKeys] = useState({
    weatherapi: '',
    tomorrow: '',
    openweather: '',
    accuweather: '',
  })
  const [savedStatus, setSavedStatus] = useState(false)

  useEffect(() => {
    if (isOpen) {
      setKeys(getProviderKeys())
      setSavedStatus(false)
    }
  }, [isOpen])

  if (!isOpen) return null

  const handleSave = () => {
    try {
      localStorage.setItem('weathergpt_weatherapi_key', keys.weatherapi.trim())
      localStorage.setItem('weathergpt_tomorrow_key', keys.tomorrow.trim())
      localStorage.setItem('weathergpt_openweather_key', keys.openweather.trim())
      localStorage.setItem('weathergpt_accuweather_key', keys.accuweather.trim())
      setSavedStatus(true)
      setTimeout(() => {
        setSavedStatus(false)
        onClose()
        window.location.reload()
      }, 1000)
    } catch {
      // Ignore
    }
  }

  const providers = [
    {
      id: 'openmeteo',
      name: 'Open-Meteo (ECMWF & GFS)',
      envVar: 'Built-in (Zero Key)',
      status: 'Active (Free Base Engine)',
      link: 'https://open-meteo.com',
      isFreeAlways: true,
    },
    {
      id: 'weatherapi',
      name: 'WeatherAPI.com',
      envVar: 'VITE_WEATHERAPI_KEY',
      keyVal: keys.weatherapi,
      link: 'https://www.weatherapi.com/signup.aspx',
    },
    {
      id: 'tomorrow',
      name: 'Tomorrow.io',
      envVar: 'VITE_TOMORROW_KEY',
      keyVal: keys.tomorrow,
      link: 'https://www.tomorrow.io/weather-api/',
    },
    {
      id: 'openweather',
      name: 'OpenWeatherMap',
      envVar: 'VITE_OPENWEATHER_KEY',
      keyVal: keys.openweather,
      link: 'https://home.openweathermap.org/users/sign_up',
    },
    {
      id: 'accuweather',
      name: 'AccuWeather API',
      envVar: 'VITE_ACCUWEATHER_KEY',
      keyVal: keys.accuweather,
      link: 'https://developer.accuweather.com/',
    },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-md animate-fade-in">
      <div className="glass rounded-3xl p-6 border border-white/20 shadow-2xl max-w-lg w-full relative max-h-[90vh] overflow-y-auto no-scrollbar">
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-white/10 mb-4">
          <div className="flex items-center gap-2.5">
            <div className="w-9 h-9 rounded-2xl bg-accent/20 border border-accent/40 flex items-center justify-center">
              <Key size={18} className="text-accent" />
            </div>
            <div>
              <h2 className="text-white text-lg font-bold font-display">Weather Provider Settings</h2>
              <p className="text-white/50 text-xs">Manage Multi-Source Fusion API Keys</p>
            </div>
          </div>

          <button
            onClick={onClose}
            aria-label="Close modal"
            className="text-white/60 hover:text-white p-1 rounded-full touch-target flex items-center justify-center cursor-pointer"
          >
            <X size={20} />
          </button>
        </div>

        {/* Info Banner */}
        <div className="glass rounded-2xl p-3.5 mb-5 border border-emerald-500/30 bg-emerald-500/10 flex items-start gap-3">
          <ShieldCheck size={20} className="text-emerald-400 flex-shrink-0 mt-0.5" />
          <p className="text-white/90 text-xs leading-relaxed">
            Open-Meteo is active by default. Enter optional API keys below (or set environment variables) to blend real-time station data from WeatherAPI, Tomorrow.io, OpenWeather, and AccuWeather!
          </p>
        </div>

        {/* Providers List */}
        <div className="flex flex-col gap-4 mb-6">
          {providers.map((p) => (
            <div key={p.id} className="glass rounded-2xl p-4 border border-white/10 flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-white text-sm font-bold font-display">{p.name}</span>
                  {p.isFreeAlways && (
                    <span className="text-[10px] bg-emerald-500/20 text-emerald-400 font-semibold px-2 py-0.5 rounded-full border border-emerald-500/40">
                      Default Active
                    </span>
                  )}
                  {!p.isFreeAlways && p.keyVal && (
                    <span className="text-[10px] bg-accent/20 text-accent font-semibold px-2 py-0.5 rounded-full border border-accent/40 flex items-center gap-1">
                      <CheckCircle size={10} /> Active Key
                    </span>
                  )}
                </div>

                <a
                  href={p.link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] text-accent hover:underline flex items-center gap-1 font-semibold"
                >
                  Get Key <ExternalLink size={10} />
                </a>
              </div>

              <div className="text-[11px] text-white/40">ENV Variable: <code className="text-white/70">{p.envVar}</code></div>

              {!p.isFreeAlways && (
                <input
                  type="password"
                  value={keys[p.id] || ''}
                  onChange={(e) => setKeys({ ...keys, [p.id]: e.target.value })}
                  placeholder={`Paste ${p.name} Key here...`}
                  className="w-full bg-white/5 border border-white/15 rounded-xl px-3 py-2 text-white text-xs placeholder:text-white/30 focus:outline-none focus:ring-1 focus:ring-accent"
                />
              )}
            </div>
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center justify-between pt-4 border-t border-white/10">
          {savedStatus ? (
            <span className="text-emerald-400 text-xs font-semibold flex items-center gap-1.5">
              <CheckCircle size={16} /> Saved! Reloading engine...
            </span>
          ) : (
            <span className="text-white/40 text-xs">Keys stored securely in browser storage</span>
          )}

          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-white/70 hover:text-white text-xs font-semibold cursor-pointer"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="bg-accent hover:bg-accent/90 text-white font-semibold px-5 py-2 rounded-xl text-xs shadow-md cursor-pointer transition-all flex items-center gap-1.5"
            >
              <RefreshCw size={14} /> Save & Apply
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

import { useState, useEffect, useRef, useCallback } from 'react'
import { ArrowRight, Loader2, Mic, Sun, ShieldAlert, Droplets, Wind, Thermometer, CloudSun, Cloud, CloudFog, CloudDrizzle, CloudRain, CloudSnow, CloudLightning, Volume2, VolumeX, MapPin, Search, Eye, Compass, Sunrise, Sunset, Gauge } from 'lucide-react'
import { sendMessage, getWeatherByCoords, getAirQualityByCoords, getIMDAlertBulletin } from '../api'
import { Translations, translateCondition } from '../utils/translations'
import PromptRotator from '../components/PromptRotator'
import WeatherMarquee from '../components/WeatherMarquee'
import MarkdownContent from '../components/MarkdownContent'
import VoiceComingSoonToast from '../components/VoiceComingSoonToast'
import RiskOutlookCard from '../components/RiskOutlookCard'
import { speakText } from '../utils/speechEngine'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// ─── Weather Icon ─────────────────────────────────────────────────────────────

function WeatherIcon({ code, size = 48 }) {
  let Icon = Sun
  if (code === 0 || code === 1) Icon = Sun
  else if (code === 2) Icon = CloudSun
  else if (code === 3) Icon = Cloud
  else if (code === 45 || code === 48) Icon = CloudFog
  else if (code >= 51 && code <= 55) Icon = CloudDrizzle
  else if (code >= 61 && code <= 65) Icon = CloudRain
  else if (code >= 71 && code <= 77) Icon = CloudSnow
  else if (code >= 80 && code <= 82) Icon = CloudRain
  else if (code === 85 || code === 86) Icon = CloudSnow
  else if (code >= 95 && code <= 99) Icon = CloudLightning
  return <Icon className="text-accent" size={size} strokeWidth={1.5} />
}

// ─── Chat Widgets (Weather/Alert/Forecast) ────────────────────────────────────

function ChatWeatherWidget({ data, langCode = 'en' }) {
  if (!data) return null
  const { city, temp, feelsLike, condition, humidity, windSpeed, advisory } = data
  return (
    <div className="rounded-xl p-4 my-3 border border-accent/30 bg-accent/5 text-white max-w-full">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <Sun className="text-accent" size={18} />
          <span className="font-bold text-sm">{city || Translations.get(langCode, 'weatherTelemetry')}</span>
        </div>
        <span className="text-[10px] uppercase font-bold text-accent bg-accent/20 px-2 py-0.5 rounded-full">
          {Translations.get(langCode, 'liveCard')}
        </span>
      </div>
      <div className="flex items-baseline gap-3 my-2">
        <span className="text-3xl font-display font-extrabold">{temp != null ? `${temp}°C` : '--'}</span>
        {condition && <span className="text-white/80 text-sm font-medium">{condition}</span>}
      </div>
      <div className="grid grid-cols-3 gap-2 pt-2 border-t border-white/10 text-center">
        {feelsLike != null && (
          <div className="bg-white/5 rounded-lg p-2">
            <span className="text-[10px] text-white/50 block">{Translations.get(langCode, 'feelsLike')}</span>
            <span className="text-xs font-bold text-orange-300">{feelsLike}°C</span>
          </div>
        )}
        {humidity != null && (
          <div className="bg-white/5 rounded-lg p-2">
            <span className="text-[10px] text-white/50 block">{Translations.get(langCode, 'humidity')}</span>
            <span className="text-xs font-bold text-sky-300">{humidity}%</span>
          </div>
        )}
        {windSpeed != null && (
          <div className="bg-white/5 rounded-lg p-2">
            <span className="text-[10px] text-white/50 block">{Translations.get(langCode, 'wind')}</span>
            <span className="text-xs font-bold text-emerald-300">{windSpeed} km/h</span>
          </div>
        )}
      </div>
      {advisory && (
        <p className="text-xs text-accent/90 mt-2.5 pt-2 border-t border-white/10 font-medium">
          💡 {advisory}
        </p>
      )}
    </div>
  )
}

function ChatAlertWidget({ data, langCode = 'en' }) {
  if (!data) return null
  const { level, title, advisory, action } = data
  const badgeBg = level === 'RED' ? '#ef4444' : level === 'ORANGE' ? '#f97316' : level === 'YELLOW' ? '#f59e0b' : '#10b981'
  return (
    <div className="rounded-xl p-4 my-3 border shadow-lg text-white max-w-full" style={{ borderColor: badgeBg, background: `${badgeBg}18` }}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <ShieldAlert size={18} style={{ color: badgeBg }} />
          <span className="font-bold text-sm">{title || Translations.get(langCode, 'officialWarning')}</span>
        </div>
        <span className="text-[10px] uppercase font-bold text-white px-2 py-0.5 rounded-full" style={{ background: badgeBg }}>
          {level || 'IMD'} ALERT
        </span>
      </div>
      {advisory && <p className="text-xs text-white/90 leading-relaxed mb-2 font-medium">{advisory}</p>}
      {action && (
        <div className="bg-white/5 rounded-lg p-2.5 mt-2 text-xs font-semibold text-white/95 flex items-center gap-2 border border-white/10">
          <span>⚡ {action}</span>
        </div>
      )}
    </div>
  )
}

function ChatForecastWidget({ data, langCode = 'en' }) {
  if (!data || !Array.isArray(data.days)) return null
  return (
    <div className="rounded-xl p-4 my-3 border border-white/15 text-white max-w-full">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-bold uppercase tracking-wider text-accent flex items-center gap-1">
          <Sun size={14} /> {data.city ? `${data.city} ${Translations.get(langCode, 'forecast')}` : Translations.get(langCode, 'forecast')}
        </span>
        <span className="text-[10px] text-white/40">{data.days.length} {Translations.get(langCode, 'days')}</span>
      </div>
      <div className="flex gap-2.5 overflow-x-auto no-scrollbar pb-1">
        {data.days.map((d, i) => (
          <div key={i} className="flex-shrink-0 bg-white/5 rounded-lg p-2.5 text-center min-w-[75px] border border-white/10">
            <p className="text-[11px] text-white/60 font-semibold mb-1">{d.day}</p>
            <p className="text-sm font-bold text-white mb-0.5">{d.temp != null ? `${d.temp}°` : '--'}</p>
            <p className="text-[10px] text-white/70 truncate max-w-[70px]">{d.condition}</p>
            {d.rainProb > 0 && <p className="text-[9px] text-sky-300 font-semibold mt-1">{d.rainProb}% rain</p>}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Bot Message with Widget Detection & TTS Support ─────────────────────────

function BotMessage({ text, langCode = 'en' }) {
  const [isSpeaking, setIsSpeaking] = useState(false)

  const handleSpeak = () => {
    speakText(text, langCode, setIsSpeaking)
  }

  return (
    <div className="prose-bot relative group">
      <div className="flex items-center justify-end mb-1">
        <button
          type="button"
          onClick={handleSpeak}
          className={`flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border transition-all cursor-pointer ${
            isSpeaking
              ? 'bg-accent text-white border-accent animate-pulse'
              : 'text-white/50 border-white/10 hover:text-white hover:bg-white/10'
          }`}
          title="Read response aloud (Text-to-Speech)"
        >
          {isSpeaking ? <VolumeX size={12} /> : <Volume2 size={12} />}
          <span>{isSpeaking ? 'Stop Speech' : 'Listen'}</span>
        </button>
      </div>

      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" className="text-accent hover:text-accent-light underline underline-offset-2 transition-colors" />
          ),
          strong: ({ node, ...props }) => <strong {...props} className="font-semibold text-white" />,
          h1: ({ node, ...props }) => <h1 {...props} className="text-base font-bold text-white mt-4 mb-2" />,
          h2: ({ node, ...props }) => <h2 {...props} className="text-sm font-bold text-white mt-3 mb-1.5" />,
          h3: ({ node, ...props }) => <h3 {...props} className="text-xs font-bold text-white/90 mt-2.5 mb-1" />,
          ul: ({ node, ...props }) => <ul {...props} className="list-disc list-outside ml-5 my-2 space-y-1 text-sm text-white/85" />,
          ol: ({ node, ...props }) => <ol {...props} className="list-decimal list-outside ml-5 my-2 space-y-1 text-sm text-white/85" />,
          li: ({ node, ...props }) => <li {...props} className="leading-relaxed my-0.5" />,
          table: ({ node, ...props }) => (
            <div className="overflow-x-auto my-2">
              <table {...props} className="text-xs w-full border-collapse" />
            </div>
          ),
          th: ({ node, ...props }) => <th {...props} className="border border-white/15 px-2 py-1 text-accent font-semibold text-left" />,
          td: ({ node, ...props }) => <td {...props} className="border border-white/15 px-2 py-1 align-top" />,
          code: ({ node, inline, className, children, ...props }) => {
            const rawStr = String(children).trim()
            const match = /widget:(weather|forecast|alert)/.exec(className || '') || /widget:(weather|forecast|alert)/.exec(rawStr)
            if (!inline && match) {
              try {
                const cleanedJson = rawStr.replace(/^widget:(weather|forecast|alert)/, '').trim()
                const parsedData = JSON.parse(cleanedJson)
                if (match[1] === 'weather') return <ChatWeatherWidget data={parsedData} langCode={langCode} />
                if (match[1] === 'forecast') return <ChatForecastWidget data={parsedData} langCode={langCode} />
                if (match[1] === 'alert') return <ChatAlertWidget data={parsedData} langCode={langCode} />
              } catch (err) { /* Fall back */ }
            }
            return inline ? (
              <code {...props} className="bg-white/10 rounded px-1 py-0.5 text-xs text-amber-300">{children}</code>
            ) : (
              <pre className="my-2 bg-neutral-900 rounded-lg p-3 overflow-x-auto border border-white/10">
                <code {...props} className="text-xs text-amber-200">{children}</code>
              </pre>
            )
          },
          blockquote: ({ node, ...props }) => <blockquote {...props} className="border-l-2 border-accent/50 pl-3 my-2 text-white/80" />,
          hr: ({ node, ...props }) => <hr {...props} className="border-white/10 my-3" />,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

// ─── Weather Summary Card (Empty State) ───────────────────────────────────────

// ─── Format Helpers ───────────────────────────────────────────────────────────

function formatHour(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  const h = d.getHours()
  if (h === 0) return '12 AM'
  if (h === 12) return '12 PM'
  return h > 12 ? `${h - 12} PM` : `${h} AM`
}

function formatFullDate(langCode = 'en') {
  const d = new Date()
  const localeMap = {
    en: 'en-US', hi: 'hi-IN', gu: 'gu-IN', mr: 'mr-IN', ta: 'ta-IN',
    te: 'te-IN', bn: 'bn-IN', kn: 'kn-IN', ml: 'ml-IN', pa: 'pa-IN'
  }
  const locale = localeMap[langCode] || 'en-US'
  return d.toLocaleDateString(locale, { weekday: 'long', month: 'short', day: 'numeric' })
}

function getCardinalDirection(angle = 0) {
  const directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  return directions[Math.round(angle / 45) % 8]
}

// ─── SVG Bezier Curve Temperature Graph ───────────────────────────────────────

function BezierTemperatureGraph({ temps, activeIndex = 4 }) {
  if (!temps || temps.length === 0) return null
  const height = 80
  const width = 500
  const paddingX = 30
  const paddingY = 20

  const minVal = Math.min(...temps) - 2
  const maxVal = Math.max(...temps) + 2
  const range = maxVal - minVal || 1

  const points = temps.map((val, idx) => {
    const x = paddingX + (idx / (temps.length - 1)) * (width - 2 * paddingX)
    const y = height - paddingY - ((val - minVal) / range) * (height - 2 * paddingY)
    return { x, y, val }
  })

  let pathD = `M ${points[0].x},${points[0].y}`
  for (let i = 0; i < points.length - 1; i++) {
    const curr = points[i]
    const next = points[i + 1]
    const cp1x = curr.x + (next.x - curr.x) / 2
    const cp1y = curr.y
    const cp2x = curr.x + (next.x - curr.x) / 2
    const cp2y = next.y
    pathD += ` C ${cp1x},${cp1y} ${cp2x},${cp2y} ${next.x},${next.y}`
  }

  const activePoint = points[Math.min(activeIndex, points.length - 1)] || points[0]

  return (
    <div className="w-full relative mt-4 pt-1">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-20 overflow-visible">
        <defs>
          <filter id="curveGlow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>

        <line
          x1={activePoint.x}
          y1={activePoint.y + 6}
          x2={activePoint.x}
          y2={height - 2}
          stroke="rgba(255,255,255,0.4)"
          strokeDasharray="2 2"
          strokeWidth="1.2"
        />

        <path
          d={pathD}
          fill="none"
          stroke="rgba(235, 235, 245, 0.85)"
          strokeWidth="2.5"
          strokeLinecap="round"
          filter="url(#curveGlow)"
        />

        <circle
          cx={activePoint.x}
          cy={activePoint.y}
          r="5"
          fill="#ffffff"
        />
        <circle
          cx={activePoint.x}
          cy={activePoint.y}
          r="9"
          fill="rgba(255, 255, 255, 0.3)"
        />
      </svg>

      <div className="flex justify-between px-1 -mt-1 text-white/90 font-mono font-semibold text-xs sm:text-sm">
        {temps.map((t, idx) => (
          <span
            key={idx}
            className={idx === activeIndex ? 'text-white font-extrabold scale-110' : 'text-white/70'}
          >
            {t}°c
          </span>
        ))}
      </div>
    </div>
  )
}

// ─── Preset Cities List ──────────────────────────────────────────────────────

// ─── Major Indian Cities Registry for Distance Calculation ───────────────────

const INDIAN_CITIES_REGISTRY = [
  { name: 'Mumbai', country: 'India', lat: 19.076, lon: 72.8777 },
  { name: 'Thane', country: 'India', lat: 19.2183, lon: 72.9781 },
  { name: 'Pune', country: 'India', lat: 18.5204, lon: 73.8567 },
  { name: 'Nashik', country: 'India', lat: 20.0059, lon: 73.7898 },
  { name: 'Nagpur', country: 'India', lat: 21.1458, lon: 79.0882 },
  { name: 'Delhi', country: 'India', lat: 28.6139, lon: 77.209 },
  { name: 'Noida', country: 'India', lat: 28.5355, lon: 77.391 },
  { name: 'Gurugram', country: 'India', lat: 28.4595, lon: 77.0266 },
  { name: 'Faridabad', country: 'India', lat: 28.4089, lon: 77.3178 },
  { name: 'Bengaluru', country: 'India', lat: 12.9716, lon: 77.5946 },
  { name: 'Mysuru', country: 'India', lat: 12.2958, lon: 76.6394 },
  { name: 'Hyderabad', country: 'India', lat: 17.385, lon: 78.4867 },
  { name: 'Chennai', country: 'India', lat: 13.0827, lon: 80.2707 },
  { name: 'Coimbatore', country: 'India', lat: 11.0168, lon: 76.9558 },
  { name: 'Kolkata', country: 'India', lat: 22.5726, lon: 88.3639 },
  { name: 'Howrah', country: 'India', lat: 22.5958, lon: 88.2636 },
  { name: 'Ahmedabad', country: 'India', lat: 23.0225, lon: 72.5714 },
  { name: 'Gandhinagar', country: 'India', lat: 23.2156, lon: 72.6369 },
  { name: 'Surat', country: 'India', lat: 21.1702, lon: 72.8311 },
  { name: 'Vadodara', country: 'India', lat: 22.3072, lon: 73.1812 },
  { name: 'Rajkot', country: 'India', lat: 22.3039, lon: 70.8022 },
  { name: 'Jaipur', country: 'India', lat: 26.9124, lon: 75.7873 },
  { name: 'Lucknow', country: 'India', lat: 26.8467, lon: 80.9462 },
  { name: 'Kanpur', country: 'India', lat: 26.4499, lon: 80.3319 },
  { name: 'Patna', country: 'India', lat: 25.5941, lon: 85.1376 },
  { name: 'Bhopal', country: 'India', lat: 23.2599, lon: 77.4126 },
  { name: 'Indore', country: 'India', lat: 22.7196, lon: 75.8577 },
  { name: 'Visakhapatnam', country: 'India', lat: 17.6868, lon: 83.2185 },
  { name: 'Vijayawada', country: 'India', lat: 16.5062, lon: 80.648 },
  { name: 'Chandigarh', country: 'India', lat: 30.7333, lon: 76.7794 },
  { name: 'Kochi', country: 'India', lat: 9.9312, lon: 76.2673 },
  { name: 'Guwahati', country: 'India', lat: 26.1445, lon: 91.7362 },
  { name: 'Bhubaneswar', country: 'India', lat: 20.2961, lon: 85.8245 },
]

function getNearestCities(currentLat, currentLon, currentName = '', count = 3) {
  if (!currentLat || !currentLon) return INDIAN_CITIES_REGISTRY.slice(0, count)

  const calcDist = (lat1, lon1, lat2, lon2) => {
    const R = 6371
    const dLat = ((lat2 - lat1) * Math.PI) / 180
    const dLon = ((lon2 - lon1) * Math.PI) / 180
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) * Math.sin(dLon / 2)
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
  }

  const normalizedCurrent = (currentName || '').toLowerCase().trim()
  return INDIAN_CITIES_REGISTRY
    .filter(c => !normalizedCurrent.includes(c.name.toLowerCase()) && !c.name.toLowerCase().includes(normalizedCurrent))
    .map(c => ({ ...c, distance: calcDist(currentLat, currentLon, c.lat, c.lon) }))
    .sort((a, b) => a.distance - b.distance)
    .slice(0, count)
}

function getAQIStatus(aqi, t) {
  const val = aqi ?? 42
  if (val <= 50) return { text: t('aqiGood') || 'Good', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)' }
  if (val <= 100) return { text: t('aqiModerate') || 'Moderate', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)' }
  if (val <= 150) return { text: t('aqiUnhealthySensitive') || 'Unhealthy (Sens.)', color: '#f97316', bg: 'rgba(249, 115, 22, 0.15)' }
  if (val <= 200) return { text: t('aqiUnhealthy') || 'Unhealthy', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)' }
  return { text: t('aqiHazardous') || 'Hazardous', color: '#881337', bg: 'rgba(136, 19, 55, 0.15)' }
}

function getUVStatus(uv, t) {
  const val = uv ?? 5.3
  if (val <= 2) return { text: t('uvLow') || 'Low', color: '#10b981', bg: 'rgba(16, 185, 129, 0.15)', desc: t('uvLowDesc') || 'Minimal risk. Enjoy outdoor activities!' }
  if (val <= 5) return { text: t('uvModerate') || 'Moderate', color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.15)', desc: t('uvModDesc') || 'Wear sunglasses & SPF 30+.' }
  if (val <= 7) return { text: t('uvHigh') || 'High', color: '#f97316', bg: 'rgba(249, 115, 22, 0.15)', desc: t('uvHighDesc') || 'Reduce sun exposure between 10am - 4pm.' }
  return { text: t('uvVeryHigh') || 'Very High', color: '#ef4444', bg: 'rgba(239, 68, 68, 0.15)', desc: t('uvVeryHighDesc') || 'Extra protection needed. Seek shade.' }
}

function getDaylightProgress(sunriseStr, sunsetStr) {
  try {
    const now = new Date()
    const currentMinutes = now.getHours() * 60 + now.getMinutes()
    const [srH, srM] = (sunriseStr || '06:22').split(':').map(Number)
    const [ssH, ssM] = (sunsetStr || '18:52').split(':').map(Number)
    const srMinutes = srH * 60 + (srM || 0)
    const ssMinutes = ssH * 60 + (ssM || 0)
    if (currentMinutes < srMinutes) return 0
    if (currentMinutes > ssMinutes) return 100
    return Math.round(((currentMinutes - srMinutes) / (ssMinutes - srMinutes)) * 100)
  } catch {
    return 50
  }
}

// ─── Redesigned Minimalist Atmospheric Weather Dashboard ────────────────────

function WeatherDashboardCard({
  weather,
  location,
  forecast,
  hourly = [],
  langCode = 'en',
  onSelectLocation,
}) {
  const [activeTab, setActiveTab] = useState('overview')
  const [searchQuery, setSearchQuery] = useState('')
  const [closestCities, setClosestCities] = useState([])

  if (!weather) return null

  const t = (key) => Translations.get(langCode, key)
  const activeCityName = location?.name || t('selectedLocation')
  const todayForecast = forecast?.[0] || {}
  const maxTemp = todayForecast.max != null ? Math.round(todayForecast.max) : Math.round(weather.temp)
  const minTemp = todayForecast.min != null ? Math.round(todayForecast.min) : Math.round(weather.temp - 4)

  const aqiStatus = getAQIStatus(weather.aqi, t)
  const uvStatus = getUVStatus(weather.uvIndex, t)

  // Dynamically calculate and fetch weather for the 3 closest cities to user location
  useEffect(() => {
    if (!location?.lat || !location?.lon) return
    const nearest = getNearestCities(location.lat, location.lon, location.name, 3)

    Promise.all(
      nearest.map(async (city) => {
        try {
          const data = await getWeatherByCoords(city.lat, city.lon, 1)
          const temp = data?.current?.temperature_2m != null ? Math.round(data.current.temperature_2m) : Math.round(weather.temp)
          const code = data?.current?.weather_code ?? 0
          return { ...city, temp, code }
        } catch {
          return { ...city, temp: Math.round(weather.temp), code: 0 }
        }
      })
    ).then(setClosestCities)
  }, [location?.lat, location?.lon, location?.name, weather.temp])

  const curveTemps = hourly.length >= 7
    ? hourly.slice(0, 7).map((h) => Math.round(h.temp))
    : [
        Math.round(weather.temp - 4),
        Math.round(weather.temp - 6),
        Math.round(weather.temp + 4),
        Math.round(weather.temp + 6),
        Math.round(weather.temp),
        Math.round(weather.temp + 2),
        Math.round(weather.temp + 4),
      ]

  const handleCitySearchSubmit = (e) => {
    e.preventDefault()
    if (!searchQuery.trim() || !onSelectLocation) return
    onSelectLocation({ name: searchQuery.trim(), country: 'India', lat: 20.5937, lon: 78.9629 })
    setSearchQuery('')
  }

  return (
    <div className="w-full max-w-4xl mx-auto text-left flex flex-col gap-2.5">
      {/* Top Bar: Search Location & Minimalist Tab Switcher */}
      <div className="flex flex-wrap items-center justify-between gap-2 bg-white/[0.02] border border-white/[0.06] rounded-2xl p-2 backdrop-blur-md">
        {/* City Search Box */}
        <form onSubmit={handleCitySearchSubmit} className="relative flex items-center min-w-[200px] flex-1 sm:flex-none">
          <Search size={14} className="absolute left-3 text-white/40" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('searchLocation') || 'Search city...'}
            className="w-full bg-white/[0.04] border border-white/[0.08] rounded-xl pl-8 pr-3 py-1.5 text-xs text-white placeholder-white/30 focus:outline-none focus:border-white/20 transition-all"
          />
        </form>

        {/* Navigation Tabs */}
        <div className="flex items-center gap-1.5 text-xs font-medium">
          <button
            type="button"
            onClick={() => setActiveTab('overview')}
            className={`px-3 py-1 rounded-xl transition-all cursor-pointer ${
              activeTab === 'overview'
                ? 'bg-white/12 text-white font-bold border border-white/15 shadow-sm'
                : 'text-white/40 hover:text-white/80'
            }`}
          >
            {t('overviewTab') || 'Overview'}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('hourly')}
            className={`px-3 py-1 rounded-xl transition-all cursor-pointer ${
              activeTab === 'hourly'
                ? 'bg-white/12 text-white font-bold border border-white/15 shadow-sm'
                : 'text-white/40 hover:text-white/80'
            }`}
          >
            {t('hourlyTab') || '24-Hour'}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('daily')}
            className={`px-3 py-1 rounded-xl transition-all cursor-pointer ${
              activeTab === 'daily'
                ? 'bg-white/12 text-white font-bold border border-white/15 shadow-sm'
                : 'text-white/40 hover:text-white/80'
            }`}
          >
            {t('weeklyTab') || '7-Day'}
          </button>
        </div>
      </div>

      {/* Main Overview Tab */}
      {activeTab === 'overview' && (
        <div className="flex flex-col gap-2.5">
          {/* Main Hero Weather Card */}
          <div className="bg-neutral-950/80 border border-white/[0.06] rounded-3xl p-4 sm:p-5 shadow-2xl backdrop-blur-2xl relative overflow-hidden flex flex-col justify-between gap-3">
            <div className="absolute inset-0 bg-gradient-to-tr from-slate-950/80 via-neutral-950/90 to-black pointer-events-none" />

            <div className="relative z-10 flex flex-col gap-3">
              {/* Header: Location & Date */}
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <MapPin size={16} className="text-accent" />
                  <span className="font-bold text-base text-white tracking-tight">{activeCityName}</span>
                  <span className="text-xs text-white/40 border-l border-white/10 pl-2 font-mono">
                    {formatFullDate(langCode)}
                  </span>
                </div>
                {/* Nearest Cities Quick Switch */}
                <div className="hidden sm:flex items-center gap-1.5 text-xs">
                  <span className="text-white/30 font-medium">Nearby:</span>
                  {(closestCities.length > 0 ? closestCities : INDIAN_CITIES_REGISTRY.slice(0, 3)).map((city) => (
                    <button
                      key={city.name}
                      type="button"
                      onClick={() => onSelectLocation?.({ name: city.name, country: city.country, lat: city.lat, lon: city.lon })}
                      className="px-2 py-0.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] border border-white/[0.06] text-white/70 text-xs transition-colors cursor-pointer"
                    >
                      {city.name} <span className="font-bold text-white ml-0.5">{city.temp != null ? `${city.temp}°` : ''}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Temperature & Condition Row */}
              <div className="flex flex-wrap items-baseline justify-between gap-4 mt-1">
                <div className="flex items-baseline gap-4">
                  <span className="text-5xl sm:text-6xl font-display font-extrabold text-white tracking-tight">
                    {Math.round(weather.temp)}°c
                  </span>
                  <div>
                    <h2 className="text-xl sm:text-2xl font-display font-bold text-white/90">
                      {translateCondition(weather.code, langCode)}
                    </h2>
                    <p className="text-xs text-white/50">
                      {t('feelsLike') || 'Feels like'} {Math.round(weather.feelsLike)}°c
                    </p>
                  </div>
                </div>

                {/* High / Low & Quick Stats */}
                <div className="flex items-center gap-2 text-xs">
                  <div className="bg-white/[0.04] border border-white/[0.06] rounded-xl px-3 py-1.5 text-center">
                    <span className="text-white/40 block text-[10px] uppercase font-medium">{t('high') || 'HIGH'} / {t('low') || 'LOW'}</span>
                    <span className="font-bold text-white">{maxTemp}° / {minTemp}°</span>
                  </div>
                  <div className="bg-white/[0.04] border border-white/[0.06] rounded-xl px-3 py-1.5 text-center">
                    <span className="text-white/40 block text-[10px] uppercase font-medium">{t('humidity') || 'HUMIDITY'}</span>
                    <span className="font-bold text-white">{weather.humidity}%</span>
                  </div>
                  <div className="bg-white/[0.04] border border-white/[0.06] rounded-xl px-3 py-1.5 text-center">
                    <span className="text-white/40 block text-[10px] uppercase font-medium">{t('wind') || 'WIND'}</span>
                    <span className="font-bold text-white">{weather.windSpeed} <span className="text-[10px] font-normal text-white/40">km/h</span></span>
                  </div>
                </div>
              </div>

              {/* Spline Temperature Curve */}
              <div className="pt-1">
                <BezierTemperatureGraph temps={curveTemps} activeIndex={4} />
              </div>
            </div>
          </div>

          {/* Telemetry Cards Grid (5 Natural Tiles) */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
            {/* 1. Air Quality (AQI) */}
            <div className="bg-neutral-950/80 border border-white/[0.06] rounded-2xl p-3 text-left flex flex-col justify-between gap-1 shadow-lg backdrop-blur-xl min-w-0 overflow-hidden">
              <div className="flex items-center justify-between text-xs text-white/50 font-semibold uppercase tracking-wider gap-1 min-w-0 overflow-hidden">
                <span className="shrink-0 font-bold">AQI</span>
                <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-tight truncate max-w-[70%] inline-block text-right" style={{ color: aqiStatus.color, backgroundColor: aqiStatus.bg }} title={aqiStatus.text}>
                  {aqiStatus.text}
                </span>
              </div>
              <span className="text-2xl font-bold text-white my-0.5">{weather.aqi ?? 118}</span>
              <span className="text-xs text-white/50 truncate">PM2.5: {weather.pm25 ?? '21.4'} µg/m³</span>
            </div>

            {/* 2. UV Index */}
            <div className="bg-neutral-950/80 border border-white/[0.06] rounded-2xl p-3 text-left flex flex-col justify-between gap-1 shadow-lg backdrop-blur-xl min-w-0 overflow-hidden">
              <div className="flex items-center justify-between text-xs text-white/50 font-semibold uppercase tracking-wider gap-1 min-w-0 overflow-hidden">
                <span className="shrink-0 font-bold">UV INDEX</span>
                <span className="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-tight truncate max-w-[65%] inline-block text-right" style={{ color: uvStatus.color, backgroundColor: uvStatus.bg }} title={uvStatus.text}>
                  {uvStatus.text}
                </span>
              </div>
              <span className="text-2xl font-bold text-white my-0.5">
                {weather.uvIndex ? weather.uvIndex.toFixed(1) : '1.7'} <span className="text-xs font-normal text-white/40">/ 12</span>
              </span>
              <span className="text-xs text-white/50 truncate">{uvStatus.desc ? uvStatus.desc.slice(0, 20) : 'Minimal risk'}</span>
            </div>

            {/* 3. Wind & Compass */}
            <div className="bg-neutral-950/80 border border-white/[0.06] rounded-2xl p-3 text-left flex flex-col justify-between gap-1 shadow-lg backdrop-blur-xl min-w-0 overflow-hidden">
              <div className="flex items-center justify-between text-xs text-white/50 font-semibold uppercase tracking-wider min-w-0 overflow-hidden">
                <span className="shrink-0 font-bold">WIND</span>
                <span className="text-sky-400 font-mono text-xs shrink-0">{getCardinalDirection(weather.windDirection)}</span>
              </div>
              <span className="text-2xl font-bold text-white my-0.5">
                {weather.windSpeed} <span className="text-xs font-normal text-white/40">km/h</span>
              </span>
              <span className="text-xs text-white/50 truncate">Bearing {weather.windDirection ?? 0}°</span>
            </div>

            {/* 4. Daylight Cycle */}
            <div className="bg-neutral-950/80 border border-white/[0.06] rounded-2xl p-3 text-left flex flex-col justify-between gap-1 shadow-lg backdrop-blur-xl min-w-0 overflow-hidden">
              <div className="flex items-center justify-between text-xs text-white/50 font-semibold uppercase tracking-wider min-w-0 overflow-hidden">
                <span className="shrink-0 font-bold">DAYLIGHT</span>
                <span className="text-amber-400 text-xs font-medium shrink-0">Sun</span>
              </div>
              <div className="text-xs font-bold text-white my-0.5 flex justify-between">
                <span>{weather.sunrise || '06:22 AM'}</span>
                <span className="text-white/30 font-normal">-</span>
                <span>{weather.sunset || '06:52 PM'}</span>
              </div>
              <div className="w-full h-1.5 bg-white/10 rounded-full overflow-hidden mt-0.5">
                <div
                  className="h-full bg-gradient-to-r from-amber-400 to-rose-400 rounded-full"
                  style={{ width: `${getDaylightProgress(weather.sunrise, weather.sunset)}%` }}
                />
              </div>
            </div>

            {/* 5. Surface Pressure */}
            <div className="bg-neutral-950/80 border border-white/[0.06] rounded-2xl p-3 text-left flex flex-col justify-between gap-1 shadow-lg backdrop-blur-xl min-w-0 overflow-hidden">
              <div className="flex items-center justify-between text-xs text-white/50 font-semibold uppercase tracking-wider min-w-0 overflow-hidden">
                <span className="shrink-0 font-bold">PRESSURE</span>
                <span className="text-emerald-400 text-xs font-medium shrink-0">hPa</span>
              </div>
              <span className="text-2xl font-bold text-white my-0.5">
                {Math.round(weather.pressure || 1007)}
              </span>
              <span className="text-xs text-emerald-400/80 truncate">{t('standardPressure') || 'Standard atmospheric'}</span>
            </div>
          </div>
        </div>
      )}

      {/* 24-Hour Timeline Tab */}
      {activeTab === 'hourly' && (
        <div className="bg-neutral-950/80 border border-white/[0.06] rounded-3xl p-4 shadow-2xl backdrop-blur-2xl flex gap-2 overflow-x-auto no-scrollbar">
          {hourly.length > 0 ? (
            hourly.map((h, i) => {
              const hourLabel = i === 0 ? t('now') || 'Now' : formatHour(h.time)
              return (
                <div
                  key={i}
                  className="flex-shrink-0 bg-white/[0.03] border border-white/[0.06] rounded-2xl p-3 text-center min-w-[80px] flex flex-col items-center gap-1.5"
                >
                  <span className="text-xs text-white/50 font-medium">{hourLabel}</span>
                  <WeatherIcon code={h.code} size={24} />
                  <span className="text-base font-bold text-white">{h.temp}°</span>
                  {h.precipProb > 0 && (
                    <span className="text-[10px] font-semibold text-sky-400 bg-sky-500/10 border border-sky-500/20 px-1.5 py-0.5 rounded">
                      {h.precipProb}%
                    </span>
                  )}
                </div>
              )
            })
          ) : (
            <p className="text-xs text-white/40 py-4 w-full text-center">{t('gatheringTelemetry')}</p>
          )}
        </div>
      )}

      {/* 7-Day Forecast Tab */}
      {activeTab === 'daily' && (
        <div className="bg-neutral-950/80 border border-white/[0.06] rounded-3xl p-4 shadow-2xl backdrop-blur-2xl flex flex-col gap-2">
          {forecast.slice(0, 7).map((d, i) => (
            <div
              key={i}
              className="flex items-center justify-between bg-white/[0.03] border border-white/[0.06] rounded-2xl px-4 py-2.5 text-xs sm:text-sm"
            >
              <span className="w-28 font-semibold text-white/90">
                {i === 0 ? t('today') || 'Today' : d.date}
              </span>
              <div className="flex items-center gap-2 flex-1 justify-center">
                <WeatherIcon code={d.code} size={20} />
                <span className="text-white/60 truncate max-w-[140px]">
                  {translateCondition(d.code, langCode)}
                </span>
              </div>
              <div className="flex items-center gap-3 text-right">
                {d.rainProb > 0 && (
                  <span className="text-xs text-sky-300 font-semibold">{d.rainProb}% rain</span>
                )}
                <span className="font-mono font-bold text-white">
                  {Math.round(d.max)}° <span className="text-white/40 font-normal">/ {Math.round(d.min)}°</span>
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Main View ────────────────────────────────────────────────────────────────

export default function WeatherChatView({
  location,
  language,
  favorites = [],
  onSelectLocation,
  farmerMode = false,
  selectedCrop = 'Cotton',
}) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [weather, setWeather] = useState(null)
  const [forecast, setForecast] = useState([])
  const [hourly, setHourly] = useState([])
  const [weatherLoading, setWeatherLoading] = useState(true)
  const [showVoiceToast, setShowVoiceToast] = useState(false)

  const scrollRef = useRef(null)
  const langCode = language?.code || 'en'
  const locationContext = location?.name ? `${location.name}${location.country ? `, ${location.country}` : ''}` : ''
  const languageName = language?.name || 'English'

  // Load weather data
  useEffect(() => {
    if (!location?.lat || !location?.lon) return
    setWeatherLoading(true)
    Promise.all([
      getWeatherByCoords(location.lat, location.lon, 14),
      getAirQualityByCoords(location.lat, location.lon),
    ]).then(([data, aqiData]) => {
      const current = data.current
      setWeather({
        temp: current.temperature_2m,
        feelsLike: current.apparent_temperature,
        humidity: current.relative_humidity_2m,
        windSpeed: current.wind_speed_10m,
        windDirection: current.wind_direction_10m ?? 0,
        pressure: current.surface_pressure ?? 1013,
        uvIndex: current.uv_index ?? 0,
        code: current.weather_code ?? current.weathercode ?? 0,
        aqi: aqiData?.current?.us_aqi ?? null,
      })
      if (data.daily) {
        const codes = data.daily.weather_code ?? data.daily.weathercode ?? []
        setForecast(data.daily.time.map((date, i) => ({
          date,
          max: data.daily.temperature_2m_max[i],
          min: data.daily.temperature_2m_min[i],
          rainProb: data.daily.precipitation_probability_max?.[i] ?? 0,
          rainSum: data.daily.rain_sum?.[i] ?? 0,
          maxWind: data.daily.wind_speed_10m_max?.[i] ?? 0,
          code: codes[i] ?? 0,
        })))
      }
      if (data.hourly) {
        const now = new Date()
        const hourlyCodes = data.hourly.weather_code ?? data.hourly.weathercode ?? []
        const hours = data.hourly.time
          .map((time, i) => ({
            time,
            temp: Math.round(data.hourly.temperature_2m[i]),
            feelsLike: Math.round(data.hourly.apparent_temperature?.[i] ?? data.hourly.temperature_2m[i]),
            precipProb: data.hourly.precipitation_probability?.[i] ?? 0,
            code: hourlyCodes[i] ?? 0,
          }))
          .filter((h) => new Date(h.time) >= now)
          .slice(0, 24)
        setHourly(hours)
      }
    }).catch(err => {
      console.error('Weather fetch failed:', err)
    }).finally(() => {
      setWeatherLoading(false)
    })
  }, [location])

  // Auto-scroll on new messages
  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = useCallback(async (text) => {
    if (!text.trim() || loading) return

    const userMsg = { text: text.trim(), isUser: true }
    const updatedMessages = [...messages, userMsg]
    setMessages(updatedMessages)
    setInput('')
    setLoading(true)

    try {
      const farmerContext = farmerMode ? `[Farmer Mode Active - Crop: ${selectedCrop}]` : ''
      const fullCtx = `${locationContext} ${farmerContext}`.trim()
      const response = await sendMessage(updatedMessages, fullCtx, languageName, farmerMode, selectedCrop)
      setMessages(prev => [...prev, { text: response, isUser: false }])
    } catch {
      setMessages(prev => [
        ...prev,
        { text: Translations.get(langCode, 'chatErrorMessage') || 'Something went wrong. Try again.', isUser: false },
      ])
    } finally {
      setLoading(false)
    }
  }, [messages, loading, locationContext, languageName, langCode, farmerMode, selectedCrop])

  const handleSubmit = (e) => {
    e.preventDefault()
    send(input)
  }

  const empty = messages.length === 0

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-black relative min-w-0 overflow-hidden">
      {/* Main Body — scrollable */}
      <div className="flex-1 min-h-0 overflow-y-auto px-3 sm:px-6 pt-3 pb-8">
        <div className="max-w-4xl mx-auto w-full flex flex-col items-center">
          {empty ? (
            /* ── Empty State Hero ──────────────────────────────────── */
            <div className="w-full flex flex-col items-center justify-center text-center gap-8 sm:gap-10 py-4">
              <h1 className="font-display tracking-tight text-center select-none text-xl sm:text-2xl font-bold text-white/90">
                {Translations.get(langCode, 'welcomeTag') || 'your weather, always clear.'}
              </h1>

              {/* Weather Dashboard Card */}
              {!weatherLoading && weather && (
                <WeatherDashboardCard
                  weather={weather}
                  location={location}
                  forecast={forecast}
                  hourly={hourly}
                  langCode={langCode}
                  onSelectLocation={onSelectLocation}
                />
              )}

              {weatherLoading && (
                <div className="flex items-center gap-2 text-white/40 text-sm py-4">
                  <Loader2 size={16} className="animate-spin" />
                  <span>{Translations.get(langCode, 'gatheringTelemetry') || 'Loading weather...'}</span>
                </div>
              )}
            </div>
          ) : (
            /* ── Active Conversation ──────────────────────────────── */
            <div className="flex flex-col gap-8 pb-12 pt-4 w-full">
              {messages.map((msg, i) => (
                <div key={i} className="flex flex-col gap-1 text-left">
                  <span className="text-[11px] font-mono lowercase text-white/40">
                    {msg.isUser ? 'you' : 'weathergpt'}
                  </span>

                  {msg.isUser ? (
                    <p className="text-sm font-medium text-white/90 leading-relaxed">
                      {msg.text}
                    </p>
                  ) : (
                    <div className="flex flex-col gap-3 w-full">
                      <BotMessage text={msg.text} langCode={langCode} />
                    </div>
                  )}
                </div>
              ))}

              {/* Loading indicator */}
              {loading && (
                <div className="flex flex-col gap-1 text-left">
                  <span className="text-[11px] font-mono lowercase text-white/40">weathergpt</span>
                  <div className="flex items-center gap-2 py-2">
                    <span className="thinking-shimmer font-mono text-xs font-medium tracking-wide">
                      Thinking
                      <span className="thinking-dot-1">.</span>
                      <span className="thinking-dot-2">.</span>
                      <span className="thinking-dot-3">.</span>
                    </span>
                  </div>
                </div>
              )}

              <div ref={scrollRef} />
            </div>
          )}
        </div>
      </div>

      {/* ── Floating Bottom Input Bar ──────────────────────────────── */}
      <div className="flex-shrink-0 z-30 px-3 sm:px-6 pt-2 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:pb-6 bg-gradient-to-t from-black via-black/95 to-black/40 border-t border-white/10 sm:border-t-0 shadow-2xl backdrop-blur-md">
        {empty && (
          <div className="mb-2 sm:mb-2.5 max-w-xl mx-auto">
            <PromptRotator onSelectPrompt={send} langCode={langCode} />
          </div>
        )}

        {farmerMode && (
          <div className="max-w-xl mx-auto mb-1.5 flex items-center justify-between text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/30 px-3 py-1 rounded-md">
            <span className="flex items-center gap-1.5 font-medium truncate">
              <span>🌾</span> <strong>Farmer Advisory Mode Active</strong> — {selectedCrop} Crop Guidance
            </span>
          </div>
        )}
        <form
          onSubmit={handleSubmit}
          className="max-w-xl mx-auto relative flex items-center gap-2"
        >
          <div className="flex-1 relative flex items-center">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={Translations.get(langCode, 'chatPlaceholder') || 'message weathergpt...'}
              disabled={loading}
              className="w-full h-11 bg-neutral-900/90 border border-white/20 rounded-xl px-4 pr-10 text-sm sm:text-xs text-white placeholder:text-white/40 focus:outline-none focus:border-white/50 shadow-inner transition-all"
            />
            <button
              type="submit"
              disabled={loading || !input.trim()}
              className="absolute right-3 p-1.5 text-white/50 hover:text-white disabled:opacity-30 transition-colors cursor-pointer"
            >
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <ArrowRight className="w-4 h-4" />
              )}
            </button>
          </div>

          {/* Voice Button */}
          <button
            type="button"
            onClick={() => setShowVoiceToast(true)}
            className="h-11 w-11 flex items-center justify-center rounded-xl border border-white/20 bg-neutral-900/90 text-white/60 hover:text-white hover:border-white/40 transition-all cursor-pointer flex-shrink-0"
            aria-label="Voice input"
          >
            <Mic className="w-4 h-4" />
          </button>
        </form>
      </div>

      {/* Voice Coming Soon Toast */}
      <VoiceComingSoonToast
        show={showVoiceToast}
        onClose={() => setShowVoiceToast(false)}
      />
    </div>
  )
}

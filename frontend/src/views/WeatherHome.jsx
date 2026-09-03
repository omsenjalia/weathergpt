import { useState, useEffect } from 'react'
import { getWeatherByCoords, geocodeCity, getAirQualityByCoords } from '../api'
import { Translations, translateCondition } from '../utils/translations'
import BlurText from '../components/bits/BlurText'
import AnimatedContent from '../components/bits/AnimatedContent'
import {
  Sun,
  CloudSun,
  Cloud,
  CloudFog,
  CloudDrizzle,
  CloudRain,
  CloudSnow,
  CloudLightning,
  Thermometer,
  Droplets,
  Wind,
  Search,
  X,
  Compass,
  Sunrise,
  Sunset,
  Gauge,
  Calendar,
  Clock,
  ChevronRight,
  ShieldAlert,
  Star,
  Activity,
  AlertTriangle,
} from 'lucide-react'

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

function formatHour(isoString) {
  const d = new Date(isoString)
  const h = d.getHours()
  if (h === 0) return '12AM'
  if (h === 12) return '12PM'
  return h > 12 ? `${h - 12}PM` : `${h}AM`
}

function formatDay(isoString) {
  const d = new Date(isoString + 'T00:00:00')
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

function formatClockTime(isoString) {
  if (!isoString) return '--:--'
  const d = new Date(isoString)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function getCardinalDirection(angle) {
  const directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  return directions[Math.round(angle / 45) % 8]
}

function getUVCategory(uv) {
  if (uv <= 2) return { label: 'Low', color: '#10b981', desc: 'Minimal risk. Enjoy outdoor activities!' }
  if (uv <= 5) return { label: 'Moderate', color: '#f59e0b', desc: 'Wear sunglasses & SPF 30+.' }
  if (uv <= 7) return { label: 'High', color: '#f97316', desc: 'Reduce sun exposure between 10am - 4pm.' }
  if (uv <= 10) return { label: 'Very High', color: '#ef4444', desc: 'Extra protection needed. Seek shade.' }
  return { label: 'Extreme', color: '#a855f7', desc: 'Avoid outdoor sun during peak hours.' }
}

function getAQICategory(aqi) {
  if (aqi <= 50) return { label: 'Good', color: '#10b981', desc: 'Air quality is satisfactory.' }
  if (aqi <= 100) return { label: 'Moderate', color: '#f59e0b', desc: 'Acceptable air quality.' }
  if (aqi <= 150) return { label: 'Unhealthy for Sensitive', color: '#f97316', desc: 'Limit outdoor exertion.' }
  if (aqi <= 200) return { label: 'Unhealthy', color: '#ef4444', desc: 'Health effects for everyone.' }
  if (aqi <= 300) return { label: 'Very Unhealthy', color: '#a855f7', desc: 'Health alert.' }
  return { label: 'Hazardous', color: '#881337', desc: 'Emergency warnings.' }
}

export default function WeatherHome({ location, language, onOpenLocationPicker }) {
  const langCode = language?.code || 'en'
  const [weather, setWeather] = useState(null)
  const [forecast, setForecast] = useState([])
  const [hourly, setHourly] = useState([])
  const [loading, setLoading] = useState(true)
  const [city, setCity] = useState('New Delhi')
  const [cityInput, setCityInput] = useState('')
  const [forecastTab, setForecastTab] = useState('7days')
  const [selectedHour, setSelectedHour] = useState(null)
  const [favorites, setFavorites] = useState([])

  const t = (key) => Translations.get(langCode, key)

  // Load saved favorites on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem('weathergpt_favorites')
      if (saved) {
        setFavorites(JSON.parse(saved))
      }
    } catch {
      // Ignore
    }
  }, [])

  const toggleFavorite = (cityObj) => {
    let updated
    const exists = favorites.some((f) => f.name.toLowerCase() === cityObj.name.toLowerCase())
    if (exists) {
      updated = favorites.filter((f) => f.name.toLowerCase() !== cityObj.name.toLowerCase())
    } else {
      updated = [...favorites, cityObj]
    }
    setFavorites(updated)
    try {
      localStorage.setItem('weathergpt_favorites', JSON.stringify(updated))
    } catch {
      // Ignore
    }
  }

  const loadWeather = async (lat, lon, cityName) => {
    setLoading(true)
    try {
      const [data, aqiData] = await Promise.all([
        getWeatherByCoords(lat, lon, 14),
        getAirQualityByCoords(lat, lon),
      ])

      const current = data.current
      const currentCode = current.weather_code ?? current.weathercode ?? 0
      const aqiVal = aqiData?.current?.us_aqi ?? null

      setWeather({
        temp: current.temperature_2m,
        feelsLike: current.apparent_temperature,
        humidity: current.relative_humidity_2m,
        windSpeed: current.wind_speed_10m,
        windDirection: current.wind_direction_10m ?? 0,
        pressure: current.surface_pressure ?? 1013,
        uvIndex: current.uv_index ?? 0,
        code: currentCode,
        aqi: aqiVal,
        pm25: aqiData?.current?.pm2_5 ?? null,
        pm10: aqiData?.current?.pm10 ?? null,
        no2: aqiData?.current?.nitrogen_dioxide ?? null,
      })

      const daily = data.daily
      if (daily) {
        const codes = daily.weather_code ?? daily.weathercode ?? []
        const days = daily.time.map((date, i) => ({
          date,
          max: daily.temperature_2m_max[i],
          min: daily.temperature_2m_min[i],
          rainProb: daily.precipitation_probability_max?.[i] ?? 0,
          rainSum: daily.rain_sum?.[i] ?? 0,
          code: codes[i] ?? 0,
          sunrise: daily.sunrise?.[i],
          sunset: daily.sunset?.[i],
          uvMax: daily.uv_index_max?.[i] ?? 0,
        }))
        setForecast(days)
      }

      const hourlyData = data.hourly
      if (hourlyData) {
        const now = new Date()
        const hourlyCodes = hourlyData.weather_code ?? hourlyData.weathercode ?? []
        const hours = hourlyData.time
          .map((time, i) => ({
            time,
            temp: hourlyData.temperature_2m[i],
            feelsLike: hourlyData.apparent_temperature?.[i] ?? hourlyData.temperature_2m[i],
            precipProb: hourlyData.precipitation_probability?.[i] ?? 0,
            humidity: hourlyData.relative_humidity_2m?.[i] ?? 50,
            windSpeed: hourlyData.wind_speed_10m?.[i] ?? 0,
            windDirection: hourlyData.wind_direction_10m?.[i] ?? 0,
            uvIndex: hourlyData.uv_index?.[i] ?? 0,
            code: hourlyCodes[i] ?? 0,
          }))
          .filter((h) => new Date(h.time) >= now)
          .slice(0, 24)
        setHourly(hours)
      }

      setCity(cityName)
    } catch (err) {
      console.error('Weather fetch failed:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (location?.lat && location?.lon) {
      loadWeather(location.lat, location.lon, location.name || 'Selected Location')
    }
  }, [location])

  const handleSearch = async () => {
    if (!cityInput.trim()) return
    try {
      const result = await geocodeCity(cityInput.trim())
      if (result) {
        loadWeather(result.latitude, result.longitude, result.name || cityInput.trim())
        setCityInput('')
      }
    } catch (err) {
      console.error('Geocoding failed:', err)
    }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center pb-24">
        <p className="text-white/50 animate-pulse text-lg">Gathering telemetry...</p>
      </div>
    )
  }

  const uvInfo = getUVCategory(weather.uvIndex)
  const aqiInfo = weather.aqi ? getAQICategory(weather.aqi) : null
  const displayedForecast = forecastTab === '7days' ? forecast.slice(0, 7) : forecast
  const isCurrentFavorite = favorites.some((f) => f.name.toLowerCase() === city.toLowerCase())

  // Detect severe hazards
  const hazards = []
  if (weather?.uvIndex >= 8) hazards.push(`Extreme UV Index (${weather.uvIndex.toFixed(1)}). Wear SPF 30+ & seek shade.`)
  if (weather?.windSpeed >= 35) hazards.push(`High Wind Warning (${weather.windSpeed} km/h). Secure loose outdoor objects.`)
  if (weather?.aqi >= 150) hazards.push(`Unhealthy Air Quality (AQI ${Math.round(weather.aqi)}). Limit outdoor exertion.`)
  if (forecast[0]?.rainProb >= 75) hazards.push(`High Rain Probability (${forecast[0].rainProb}%). Carry an umbrella today!`)

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden relative">
      {/* Search & Location Bar */}
      <div className="glass border-b border-white/10 px-4 py-3 flex-shrink-0 z-20">
        <div className="max-w-6xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <h1 className="text-white text-lg md:text-xl font-bold font-display truncate">{city}</h1>
            <button
              onClick={() => toggleFavorite({ name: city, country: location?.country || 'India', lat: location?.lat, lon: location?.lon })}
              aria-label="Bookmark city"
              className="text-white/50 hover:text-amber-400 p-1 cursor-pointer transition-colors"
            >
              <Star size={20} className={isCurrentFavorite ? 'fill-amber-400 text-amber-400' : ''} />
            </button>
          </div>

          <div className="flex items-center gap-2 flex-1 max-w-xs sm:max-w-sm">
            <div className="relative w-full">
              <input
                value={cityInput}
                onChange={(e) => setCityInput(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder={t('searchCityPlaceholder')}
                className="w-full bg-white/5 border border-white/15 rounded-2xl pl-10 pr-4 py-2 text-white text-sm placeholder:text-white/40 focus:outline-none focus:ring-1 focus:ring-accent/60"
              />
              <Search size={16} className="absolute left-3.5 top-3 text-white/40" />
            </div>
            <button
              onClick={onOpenLocationPicker}
              className="bg-accent hover:bg-accent/90 text-white rounded-2xl px-3.5 py-2 text-xs md:text-sm font-semibold transition-all shadow-sm cursor-pointer whitespace-nowrap"
            >
              {t('change')}
            </button>
          </div>
        </div>

        {/* Favorites Quick Chips Bar */}
        {favorites.length > 0 && (
          <div className="max-w-6xl mx-auto mt-2.5 pt-2 border-t border-white/10 flex items-center gap-2 overflow-x-auto no-scrollbar">
            <span className="text-[10px] uppercase font-bold text-amber-400 tracking-wider flex items-center gap-1 flex-shrink-0">
              <Star size={12} className="fill-amber-400" /> {t('favorites')}:
            </span>
            {favorites.map((f, i) => (
              <button
                key={i}
                onClick={() => onOpenLocationPicker?.()}
                className="glass rounded-full px-3 py-1 text-xs text-white/80 hover:text-white hover:bg-white/15 flex items-center gap-1 flex-shrink-0 border border-white/10"
              >
                <span>{f.name}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Main Dashboard Scroll Area */}
      <div className="flex-1 overflow-y-auto no-scrollbar p-4 md:p-6">
        <div className="max-w-6xl mx-auto flex flex-col gap-6 pb-20 md:pb-6">
          
          {/* Severe Hazard Banner */}
          {hazards.length > 0 && (
            <AnimatedContent delay={0} direction="down">
              <div className="bg-gradient-to-r from-amber-500/20 via-rose-500/20 to-amber-500/20 border border-amber-500/40 rounded-3xl p-4 flex items-center gap-3 backdrop-blur-md shadow-lg">
                <AlertTriangle size={22} className="text-amber-400 flex-shrink-0" />
                <div className="flex-1">
                  <span className="text-amber-300 font-bold text-xs uppercase tracking-wider block mb-0.5">
                    Weather & Environmental Hazard Advisory
                  </span>
                  <p className="text-white text-xs md:text-sm leading-snug">{hazards[0]}</p>
                </div>
              </div>
            </AnimatedContent>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            
            {/* Left Column: Hero Weather Widget & Interactive Gauges */}
            <div className="lg:col-span-5 flex flex-col gap-6">
              {/* Hero Card */}
              <AnimatedContent delay={0}>
                <div className="glass rounded-3xl p-6 md:p-8 flex flex-col items-center text-center relative overflow-hidden border border-white/15 shadow-2xl">
                  <div className="absolute top-0 right-0 p-6 opacity-20 pointer-events-none">
                    <WeatherIcon code={weather.code} size={140} />
                  </div>

                  <div className="mb-4">
                    <WeatherIcon code={weather.code} size={84} />
                  </div>

                  <div className="text-5xl md:text-6xl font-display font-extrabold text-white mb-2 tracking-tight">
                    <BlurText text={`${Math.round(weather.temp)}°C`} />
                  </div>

                  <p className="text-white/80 text-lg md:text-xl font-medium mb-6">
                    {translateCondition(weather.code, langCode)}
                  </p>

                  {/* Quick Environmental Metrics Grid */}
                  <div className="grid grid-cols-3 gap-3 w-full pt-4 border-t border-white/10">
                    <div className="glass rounded-2xl p-3 flex flex-col items-center">
                      <Droplets size={18} className="text-sky-400 mb-1" />
                      <span className="text-white/50 text-xs">{t('humidity')}</span>
                      <span className="text-white font-semibold text-sm">{weather.humidity}%</span>
                    </div>

                    <div className="glass rounded-2xl p-3 flex flex-col items-center">
                      <Wind size={18} className="text-emerald-400 mb-1" />
                      <span className="text-white/50 text-xs">{t('wind')}</span>
                      <span className="text-white font-semibold text-sm">{weather.windSpeed} km/h</span>
                    </div>

                    <div className="glass rounded-2xl p-3 flex flex-col items-center">
                      <Thermometer size={18} className="text-orange-400 mb-1" />
                      <span className="text-white/50 text-xs">{t('feelsLike')}</span>
                      <span className="text-white font-semibold text-sm">{Math.round(weather.feelsLike)}°</span>
                    </div>
                  </div>
                </div>
              </AnimatedContent>

              {/* Air Quality Index (AQI) Widget */}
              {aqiInfo && (
                <AnimatedContent delay={0.1}>
                  <div className="glass rounded-3xl p-5 border border-white/10 flex flex-col justify-between">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-white/60 text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5">
                        <Activity size={14} className="text-emerald-400" /> {t('airQuality')}
                      </span>
                      <span className="text-xs font-bold px-2.5 py-0.5 rounded-full text-white" style={{ background: aqiInfo.color }}>
                        {aqiInfo.label}
                      </span>
                    </div>

                    <div className="my-2">
                      <div className="text-3xl font-display font-bold text-white mb-1">
                        {Math.round(weather.aqi)} <span className="text-sm font-normal text-white/50">US AQI</span>
                      </div>
                      <div className="w-full h-2.5 rounded-full bg-white/10 overflow-hidden relative mt-2">
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{ width: `${Math.min((weather.aqi / 300) * 100, 100)}%`, background: aqiInfo.color }}
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-2 mt-3 pt-3 border-t border-white/10">
                      {weather.pm25 != null && (
                        <div className="glass rounded-xl p-2 text-center">
                          <span className="text-[10px] text-white/50 block">PM2.5</span>
                          <span className="text-xs font-bold text-white">{weather.pm25.toFixed(1)} µg/m³</span>
                        </div>
                      )}
                      {weather.pm10 != null && (
                        <div className="glass rounded-xl p-2 text-center">
                          <span className="text-[10px] text-white/50 block">PM10</span>
                          <span className="text-xs font-bold text-white">{weather.pm10.toFixed(1)} µg/m³</span>
                        </div>
                      )}
                    </div>
                  </div>
                </AnimatedContent>
              )}

              {/* Interactive Grid Widgets (UV Gauge & Wind Compass) */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* UV Index Widget */}
                <AnimatedContent delay={0.15}>
                  <div className="glass rounded-3xl p-5 border border-white/10 flex flex-col justify-between h-full">
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-white/60 text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5">
                        <Sun size={14} className="text-amber-400" /> {t('uvIndex')}
                      </span>
                      <span className="text-xs font-bold px-2 py-0.5 rounded-full text-white" style={{ background: uvInfo.color }}>
                        {uvInfo.label}
                      </span>
                    </div>
                    
                    <div className="my-2">
                      <div className="text-3xl font-display font-bold text-white mb-1">
                        {weather.uvIndex.toFixed(1)} <span className="text-sm font-normal text-white/50">/ 12</span>
                      </div>
                      <div className="w-full h-2 rounded-full bg-white/10 overflow-hidden relative">
                        <div
                          className="h-full rounded-full transition-all duration-500"
                          style={{ width: `${Math.min((weather.uvIndex / 12) * 100, 100)}%`, background: uvInfo.color }}
                        />
                      </div>
                    </div>

                    <p className="text-white/60 text-xs mt-2 leading-relaxed">{uvInfo.desc}</p>
                  </div>
                </AnimatedContent>

                {/* Wind Compass Widget */}
                <AnimatedContent delay={0.2}>
                  <div className="glass rounded-3xl p-5 border border-white/10 flex flex-col justify-between h-full">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-white/60 text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5">
                        <Compass size={14} className="text-teal-400" /> {t('wind')}
                      </span>
                      <span className="text-xs font-semibold text-accent bg-accent/15 px-2 py-0.5 rounded-md">
                        {getCardinalDirection(weather.windDirection)}
                      </span>
                    </div>

                    <div className="flex items-center justify-around my-2">
                      <div className="relative w-14 h-14 rounded-full border border-white/20 flex items-center justify-center bg-white/5">
                        <span className="absolute top-0 text-[9px] text-white/40 font-bold">N</span>
                        <span className="absolute bottom-0 text-[9px] text-white/40 font-bold">S</span>
                        <span className="absolute left-1 text-[9px] text-white/40 font-bold">W</span>
                        <span className="absolute right-1 text-[9px] text-white/40 font-bold">E</span>
                        <div
                          className="w-8 h-8 flex items-center justify-center transition-transform duration-700"
                          style={{ transform: `rotate(${weather.windDirection}deg)` }}
                        >
                          <ChevronRight size={22} className="text-teal-300 font-bold -rotate-90" />
                        </div>
                      </div>

                      <div>
                        <p className="text-2xl font-bold text-white">{weather.windSpeed} <span className="text-xs text-white/50">km/h</span></p>
                        <p className="text-xs text-white/50">Bearing {weather.windDirection}°</p>
                      </div>
                    </div>
                  </div>
                </AnimatedContent>
              </div>

              {/* Sun Cycle & Pressure Widgets */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* Sun Cycle Widget */}
                <AnimatedContent delay={0.25}>
                  <div className="glass rounded-3xl p-5 border border-white/10 flex flex-col justify-between h-full">
                    <span className="text-white/60 text-xs font-semibold uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <Sunrise size={14} className="text-orange-400" /> {t('daylightCycle')}
                    </span>

                    <div className="flex justify-between items-center my-2 px-2">
                      <div className="flex items-center gap-2">
                        <Sunrise size={20} className="text-amber-400" />
                        <div>
                          <p className="text-xs text-white/50">{t('sunrise')}</p>
                          <p className="text-sm font-semibold text-white">{formatClockTime(forecast[0]?.sunrise)}</p>
                        </div>
                      </div>

                      <div className="flex items-center gap-2">
                        <Sunset size={20} className="text-rose-400" />
                        <div>
                          <p className="text-xs text-white/50">{t('sunset')}</p>
                          <p className="text-sm font-semibold text-white">{formatClockTime(forecast[0]?.sunset)}</p>
                        </div>
                      </div>
                    </div>

                    <div className="w-full bg-white/10 rounded-full h-1.5 mt-2">
                      <div className="bg-gradient-to-r from-amber-400 to-rose-400 h-1.5 rounded-full w-2/3" />
                    </div>
                  </div>
                </AnimatedContent>

                {/* Barometric Pressure Widget */}
                <AnimatedContent delay={0.3}>
                  <div className="glass rounded-3xl p-5 border border-white/10 flex flex-col justify-between h-full">
                    <span className="text-white/60 text-xs font-semibold uppercase tracking-wider mb-3 flex items-center gap-1.5">
                      <Gauge size={14} className="text-sky-400" /> {t('surfacePressure')}
                    </span>

                    <div className="my-1">
                      <p className="text-3xl font-bold font-display text-white">
                        {Math.round(weather.pressure)} <span className="text-sm text-white/50 font-normal">hPa</span>
                      </p>
                      <span className="text-xs text-emerald-400 font-medium">Standard Pressure</span>
                    </div>
                  </div>
                </AnimatedContent>
              </div>

            </div>

            {/* Right Column: Interactive Hourly Slider & Forecast Tabs */}
            <div className="lg:col-span-7 flex flex-col gap-6">
              
              {/* Interactive Hourly Forecast (Clickable Timeslots) */}
              {hourly.length > 0 && (
                <AnimatedContent delay={0.2} direction="up">
                  <div className="glass rounded-3xl p-5 border border-white/10">
                    <div className="flex items-center justify-between mb-4">
                      <h3 className="text-white/60 text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5">
                        <Clock size={14} className="text-accent" /> {t('hourlyForecast')}
                      </h3>
                      <span className="text-xs text-white/40">24 Hours</span>
                    </div>

                    <div className="flex gap-3 overflow-x-auto no-scrollbar pb-2">
                      {hourly.map((h, i) => (
                        <button
                          key={i}
                          onClick={() => setSelectedHour(h)}
                          className={`flex-shrink-0 w-20 text-center glass rounded-2xl p-3 flex flex-col items-center gap-2 border transition-all cursor-pointer ${
                            selectedHour?.time === h.time
                              ? 'border-accent bg-accent/25 shadow-lg scale-105'
                              : 'border-white/10 hover:border-accent/40 hover:bg-white/10'
                          }`}
                        >
                          <span className="text-white/60 text-xs font-medium">
                            {i === 0 ? 'Now' : formatHour(h.time)}
                          </span>
                          <WeatherIcon code={h.code} size={24} />
                          <span className="text-white text-sm font-bold">
                            {Math.round(h.temp)}°
                          </span>
                          {h.precipProb > 0 && (
                            <span className="text-[10px] text-sky-400 font-semibold">
                              {h.precipProb}% {t('rain')}
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                </AnimatedContent>
              )}

              {/* Selected Hourly Detail Drawer / Modal */}
              {selectedHour && (
                <AnimatedContent delay={0} direction="up">
                  <div className="glass rounded-3xl p-6 border border-accent/40 bg-accent/10 relative shadow-2xl">
                    <button
                      onClick={() => setSelectedHour(null)}
                      aria-label="Close detail"
                      className="absolute top-4 right-4 text-white/50 hover:text-white p-1 rounded-full touch-target flex items-center justify-center cursor-pointer"
                    >
                      <X size={18} />
                    </button>

                    <div className="flex items-center gap-3 mb-4">
                      <WeatherIcon code={selectedHour.code} size={36} />
                      <div>
                        <h4 className="text-white font-bold text-base font-display">
                          Hourly Telemetry ({formatHour(selectedHour.time)})
                        </h4>
                        <p className="text-white/60 text-xs">{translateCondition(selectedHour.code, langCode)}</p>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                      <div className="glass rounded-2xl p-3">
                        <p className="text-white/50 text-xs">{t('feelsLike')}</p>
                        <p className="text-white font-bold text-base">{Math.round(selectedHour.feelsLike)}°C</p>
                      </div>
                      <div className="glass rounded-2xl p-3">
                        <p className="text-white/50 text-xs">{t('humidity')}</p>
                        <p className="text-white font-bold text-base">{selectedHour.humidity}%</p>
                      </div>
                      <div className="glass rounded-2xl p-3">
                        <p className="text-white/50 text-xs">{t('rain')}</p>
                        <p className="text-sky-300 font-bold text-base">{selectedHour.precipProb}%</p>
                      </div>
                      <div className="glass rounded-2xl p-3">
                        <p className="text-white/50 text-xs">{t('wind')}</p>
                        <p className="text-emerald-300 font-bold text-base">{selectedHour.windSpeed} km/h</p>
                      </div>
                    </div>
                  </div>
                </AnimatedContent>
              )}

              {/* Forecast View Switcher (7-Day vs 14-Day Extended) */}
              {forecast.length > 0 && (
                <AnimatedContent delay={0.3} direction="up">
                  <div className="glass rounded-3xl p-6 border border-white/10">
                    <div className="flex items-center justify-between mb-5 flex-wrap gap-2">
                      <h3 className="text-white/60 text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5">
                        <Calendar size={14} className="text-accent" /> {t('forecastOutlook')}
                      </h3>

                      {/* Tabs Switcher */}
                      <div className="glass rounded-full p-1 border border-white/10 flex gap-1">
                        <button
                          onClick={() => setForecastTab('7days')}
                          className={`px-4 py-1.5 rounded-full text-xs font-semibold transition-all cursor-pointer ${
                            forecastTab === '7days'
                              ? 'bg-accent text-white shadow-md'
                              : 'text-white/60 hover:text-white'
                          }`}
                        >
                          {t('sevenDays')}
                        </button>
                        <button
                          onClick={() => setForecastTab('14days')}
                          className={`px-4 py-1.5 rounded-full text-xs font-semibold transition-all cursor-pointer ${
                            forecastTab === '14days'
                              ? 'bg-accent text-white shadow-md'
                              : 'text-white/60 hover:text-white'
                          }`}
                        >
                          {t('fourteenDays')}
                        </button>
                      </div>
                    </div>

                    <div className="flex flex-col gap-2.5">
                      {displayedForecast.map((day, i) => (
                        <div
                          key={i}
                          className="flex justify-between items-center px-4 py-3 rounded-2xl hover:bg-white/5 transition-colors border border-transparent hover:border-white/10"
                        >
                          <span className="text-white font-medium w-28 text-sm">
                            {i === 0 ? t('today') : formatDay(day.date)}
                          </span>

                          <div className="flex items-center gap-3 flex-1 justify-center sm:justify-start">
                            <WeatherIcon code={day.code} size={22} />
                            <span className="text-white/70 text-xs hidden sm:inline w-28 text-left">
                              {translateCondition(day.code, langCode)}
                            </span>
                          </div>

                          {day.rainProb > 0 && (
                            <span className="text-xs text-sky-400 font-semibold px-2 py-0.5 rounded-md bg-sky-400/10 border border-sky-400/20 mr-3 hidden sm:inline">
                              {day.rainProb}% {t('rain')}
                            </span>
                          )}

                          <div className="flex items-center gap-2 text-sm font-semibold">
                            <span className="text-white">{Math.round(day.max)}°</span>
                            <span className="text-white/40">/</span>
                            <span className="text-white/50">{Math.round(day.min)}°</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </AnimatedContent>
              )}

            </div>

          </div>

        </div>
      </div>
    </div>
  )
}

import { useState, useEffect } from 'react'
import { getWeatherByCoords, geocodeCity } from '../api'
import BlurText from '../components/bits/BlurText'
import AnimatedContent from '../components/bits/AnimatedContent'

const WEATHER_EMOJI = {
  0: '☀️',
  1: '🌤️', 2: '⛅', 3: '☁️',
  45: '🌫️', 48: '🌫️',
  51: '🌦️', 53: '🌦️', 55: '🌦️',
  61: '🌧️', 63: '🌧️', 65: '🌧️',
  71: '🌨️', 73: '🌨️', 75: '❄️', 77: '🌨️',
  80: '🌦️', 81: '🌦️', 82: '🌦️',
  85: '🌨️', 86: '❄️',
  95: '⛈️', 96: '⛈️', 99: '⛈️',
}

function getEmoji(code) {
  return WEATHER_EMOJI[code] || '🌡️'
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
  return d.toLocaleDateString('en-US', { weekday: 'short' })
}

function getCondition(code) {
  if (code === 0) return 'Clear sky'
  if (code === 1) return 'Mainly clear'
  if (code === 2) return 'Partly cloudy'
  if (code === 3) return 'Overcast'
  if (code === 45 || code === 48) return 'Foggy'
  if (code >= 51 && code <= 55) return 'Drizzle'
  if (code >= 61 && code <= 65) return 'Rain'
  if (code >= 71 && code <= 77) return 'Snow'
  if (code >= 80 && code <= 82) return 'Rain showers'
  if (code === 85 || code === 86) return 'Snow showers'
  if (code >= 95 && code <= 99) return 'Thunderstorm'
  return 'Unknown'
}

export default function WeatherHome({ onCoordsChange }) {
  const [weather, setWeather] = useState(null)
  const [forecast, setForecast] = useState([])
  const [hourly, setHourly] = useState([])
  const [loading, setLoading] = useState(true)
  const [city, setCity] = useState('New Delhi')
  const [cityInput, setCityInput] = useState('')
  const [showSearch, setShowSearch] = useState(false)

  const loadWeather = async (lat, lon, cityName) => {
    setLoading(true)
    try {
      const data = await getWeatherByCoords(lat, lon)
      const current = data.current
      // Handle both 'weather_code' (new) and 'weathercode' (old) field names
      const currentCode = current.weather_code ?? current.weathercode ?? 0
      setWeather({
        temp: current.temperature_2m,
        feelsLike: current.apparent_temperature,
        humidity: current.relative_humidity_2m,
        windSpeed: current.wind_speed_10m,
        code: currentCode,
        condition: getCondition(currentCode),
      })

      const daily = data.daily
      if (daily) {
        const codes = daily.weather_code ?? daily.weathercode ?? []
        const days = daily.time.map((date, i) => ({
          date,
          max: daily.temperature_2m_max[i],
          min: daily.temperature_2m_min[i],
          code: codes[i] ?? 0,
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
            code: hourlyCodes[i] ?? 0,
          }))
          // Only keep hours from now onwards. The previous double-condition
          // `d >= now && d.getHours() >= currentHour` incorrectly dropped
          // early-morning hours from tomorrow and beyond.
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
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude: lat, longitude: lon } = pos.coords
        onCoordsChange?.({ lat, lon })
        try {
          // Use OpenStreetMap Nominatim for reverse geocoding (lat/lon → city
          // name). The Open-Meteo geocoding API only does forward lookup (city
          // name → coords) and silently returns no results when lat/lon params
          // are passed, always falling back to 'Your Location'.
          const res = await fetch(
            `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`
          )
          const data = await res.json()
          const name =
            data.address?.city ||
            data.address?.town ||
            data.address?.village ||
            data.address?.county ||
            'Your Location'
          loadWeather(lat, lon, name)
        } catch {
          loadWeather(lat, lon, 'Your Location')
        }
      },
      () => {
        const fallback = { lat: 28.6139, lon: 77.209 }
        onCoordsChange?.(fallback)
        loadWeather(fallback.lat, fallback.lon, 'New Delhi')
      }
    )
  }, [])

  const handleSearch = async () => {
    if (!cityInput.trim()) return
    try {
      const result = await geocodeCity(cityInput.trim())
      if (result) {
        onCoordsChange?.({ lat: result.latitude, lon: result.longitude })
        loadWeather(result.latitude, result.longitude, result.name || cityInput.trim())
        setShowSearch(false)
        setCityInput('')
      }
    } catch (err) {
      console.error('Geocoding failed:', err)
    }
  }

  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center pb-24">
        <p className="text-white/50 animate-pulse text-lg">Gathering weather data...</p>
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto no-scrollbar pb-28">
      {/* Header */}
      <AnimatedContent className="fixed top-0 left-0 right-0 z-20 px-6 pt-10 pb-4 glass border-b border-white/10">
        <div className="flex items-center justify-between">
          <h1 className="text-white text-xl font-semibold font-display">{city}</h1>
          <button
            onClick={() => setShowSearch(!showSearch)}
            className="text-white/70 hover:text-white text-xl transition-colors"
          >
            🔍
          </button>
        </div>
        {showSearch && (
          <div className="mt-3 flex gap-2">
            <input
              autoFocus
              value={cityInput}
              onChange={(e) => setCityInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
              placeholder="Search city..."
              className="flex-1 bg-white/5 border border-white/10 rounded-xl px-4 py-2 text-white text-sm placeholder:text-white/30 focus:outline-none focus:ring-1 focus:ring-accent/50"
            />
            <button
              onClick={() => { setShowSearch(false); setCityInput('') }}
              className="text-white/50 hover:text-white text-sm px-2"
            >
              ✕
            </button>
          </div>
        )}
      </AnimatedContent>

      {/* Weather Content */}
      <div className="pt-28 px-4">
        {/* Temperature Section */}
        <div className="text-center mb-6">
          <AnimatedContent delay={0} className="text-7xl mb-2">
            {getEmoji(weather.code)}
          </AnimatedContent>
          <div className="text-8xl font-display font-extrabold text-white mb-2">
            <BlurText text={`${Math.round(weather.temp)}°`} />
          </div>
          <AnimatedContent delay={0.2}>
            <p className="text-white/70 text-lg font-light">{weather.condition}</p>
          </AnimatedContent>
          <AnimatedContent delay={0.25}>
            <div className="flex justify-center gap-3 mt-4">
              <span className="glass rounded-full px-3 py-1 text-white/70 text-xs">
                💧 {weather.humidity}%
              </span>
              <span className="glass rounded-full px-3 py-1 text-white/70 text-xs">
                💨 {weather.windSpeed} km/h
              </span>
              <span className="glass rounded-full px-3 py-1 text-white/70 text-xs">
                🌡 Feels {Math.round(weather.feelsLike)}°
              </span>
            </div>
          </AnimatedContent>
        </div>

        {/* Hourly Forecast */}
        {hourly.length > 0 && (
          <AnimatedContent delay={0.3} direction="up">
            <div className="glass rounded-3xl p-4 mb-3">
              <div className="flex gap-3 overflow-x-auto no-scrollbar">
                {hourly.map((h, i) => (
                  <div key={i} className="flex-shrink-0 w-16 text-center flex flex-col items-center gap-1">
                    <span className="text-white/50 text-xs">
                      {i === 0 ? 'Now' : formatHour(h.time)}
                    </span>
                    <span className="text-xl">{getEmoji(h.code)}</span>
                    <span className="text-white text-sm font-semibold">
                      {Math.round(h.temp)}°
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </AnimatedContent>
        )}

        {/* 7-Day Forecast */}
        {forecast.length > 0 && (
          <AnimatedContent delay={0.4} direction="up">
            <div className="glass rounded-3xl p-4 mb-4">
              <p className="text-white/50 text-xs uppercase tracking-wider mb-3">
                7-Day Forecast
              </p>
              {forecast.map((day, i) => (
                <div
                  key={i}
                  className={`flex justify-between items-center py-2 ${
                    i < forecast.length - 1 ? 'border-b border-white/10' : ''
                  }`}
                >
                  <span className="text-white font-medium w-10">
                    {i === 0 ? 'Today' : formatDay(day.date)}
                  </span>
                  <span className="text-xl">{getEmoji(day.code)}</span>
                  <span className="text-white/70 text-sm">
                    {Math.round(day.max)}° / {Math.round(day.min)}°
                  </span>
                </div>
              ))}
            </div>
          </AnimatedContent>
        )}
      </div>
    </div>
  )
}

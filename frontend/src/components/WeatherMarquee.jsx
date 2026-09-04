import { useState, useEffect } from 'react'
import { Sun, CloudRain, CloudSnow, Cloud, CloudLightning, CloudDrizzle, CloudSun, CloudFog } from 'lucide-react'
import { getWeatherByCoords } from '../api'
import { translateCondition } from '../utils/translations'

function WeatherIcon({ code, size = 20 }) {
  if (code === 0 || code === 1) return <Sun size={size} className="text-amber-400" />
  if (code === 2) return <CloudSun size={size} className="text-amber-300" />
  if (code === 3) return <Cloud size={size} className="text-white/60" />
  if (code === 45 || code === 48) return <CloudFog size={size} className="text-white/50" />
  if (code >= 51 && code <= 55) return <CloudDrizzle size={size} className="text-sky-300" />
  if (code >= 61 && code <= 65) return <CloudRain size={size} className="text-sky-400" />
  if (code >= 71 && code <= 77) return <CloudSnow size={size} className="text-blue-200" />
  if (code >= 80 && code <= 82) return <CloudRain size={size} className="text-sky-400" />
  if (code === 85 || code === 86) return <CloudSnow size={size} className="text-blue-200" />
  if (code >= 95 && code <= 99) return <CloudLightning size={size} className="text-amber-300" />
  return <Sun size={size} className="text-amber-400" />
}

function MarqueeSkeletonCard() {
  return (
    <div className="flex-shrink-0 w-36 sm:w-40 block text-left">
      <div className="w-full aspect-[16/9] rounded-sm overflow-hidden bg-white/5 mb-1.5 animate-pulse" />
      <div className="h-3 w-16 rounded bg-white/5 animate-pulse mb-1" />
      <div className="h-2.5 w-full rounded bg-white/5 animate-pulse mb-0.5" />
      <div className="h-2.5 w-4/5 rounded bg-white/5 animate-pulse" />
    </div>
  )
}

const DEFAULT_CITIES = [
  { name: 'Mumbai', country: 'India', lat: 19.076, lon: 72.8777 },
  { name: 'New Delhi', country: 'India', lat: 28.6139, lon: 77.209 },
  { name: 'Bengaluru', country: 'India', lat: 12.9716, lon: 77.5946 },
  { name: 'Kolkata', country: 'India', lat: 22.5726, lon: 88.3639 },
  { name: 'Chennai', country: 'India', lat: 13.0827, lon: 80.2707 },
  { name: 'Jaipur', country: 'India', lat: 26.9124, lon: 75.7873 },
  { name: 'Hyderabad', country: 'India', lat: 17.385, lon: 78.4867 },
  { name: 'Goa', country: 'India', lat: 15.2993, lon: 74.124 },
]

function WeatherCard({ city, onSelect, langCode = 'en' }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let isMounted = true
    async function fetchWeather() {
      try {
        const result = await getWeatherByCoords(city.lat, city.lon, 1)
        if (isMounted && result?.current) {
          setData({
            temp: Math.round(result.current.temperature_2m),
            code: result.current.weather_code ?? result.current.weathercode ?? 0,
            humidity: result.current.relative_humidity_2m,
            windSpeed: result.current.wind_speed_10m,
          })
        }
      } catch (err) {
        console.error('WeatherCard fetch failed:', err)
      } finally {
        if (isMounted) setLoading(false)
      }
    }
    fetchWeather()
    return () => { isMounted = false }
  }, [city.lat, city.lon])

  if (loading) {
    return <MarqueeSkeletonCard />
  }

  if (!data) return null

  return (
    <div
      onClick={() => onSelect?.(city)}
      className="flex-shrink-0 w-36 sm:w-40 block text-left group cursor-pointer transition-transform hover:scale-105"
    >
      {/* Card with gradient background based on weather */}
      <div className="w-full aspect-[16/9] rounded-lg overflow-hidden mb-1.5 relative bg-neutral-900 border border-white/10 flex items-center justify-center group-hover:border-accent/40 transition-colors">
        <div className="absolute inset-0 bg-gradient-to-br from-amber-500/10 via-transparent to-sky-500/10" />
        <div className="relative flex flex-col items-center gap-1">
          <WeatherIcon code={data.code} size={28} />
          <span className="text-xl font-bold text-white tracking-tight">{data.temp}°C</span>
        </div>
      </div>
      <p className="text-xs font-semibold text-white truncate group-hover:text-accent transition-colors">{city.name}</p>
      <p className="text-[11px] text-white/50 leading-snug truncate">
        {translateCondition(data.code, langCode)} · {data.humidity}%
      </p>
    </div>
  )
}

export default function WeatherMarquee({ currentCity, favorites = [], onSelectCity, langCode = 'en' }) {
  const combined = currentCity ? [currentCity, ...favorites] : [...favorites]
  DEFAULT_CITIES.forEach(defCity => {
    if (!combined.some(c => c?.name?.toLowerCase() === defCity.name.toLowerCase())) {
      combined.push(defCity)
    }
  })
  const allCities = combined.filter(Boolean)

  if (allCities.length === 0) return null

  // Duplicate for seamless infinite loop
  const marqueeItems = [...allCities, ...allCities]

  return (
    <div
      className="w-full overflow-hidden py-2 select-none"
      style={{
        maskImage: 'linear-gradient(to right, transparent, black 10%, black 90%, transparent)',
      }}
    >
      <div className="animate-marquee flex items-start gap-4">
        {marqueeItems.map((city, index) => (
          <WeatherCard
            key={`${city.name}-${index}`}
            city={city}
            onSelect={onSelectCity}
            langCode={langCode}
          />
        ))}
      </div>
    </div>
  )
}

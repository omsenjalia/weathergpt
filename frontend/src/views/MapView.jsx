import { useState, useEffect, useRef } from 'react'
import AnimatedContent from '../components/bits/AnimatedContent'
import { Map, MapPin, Loader2 } from 'lucide-react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

const LAYERS = {
  temp: { tile: 'temp_new', label: 'Temperature', color: '#fbbf24' },
  precip: { tile: 'precipitation_new', label: 'Precipitation', color: '#38bdf8' },
  wind: { tile: 'wind_new', label: 'Wind', color: '#34d399' },
  clouds: { tile: 'clouds_new', label: 'Clouds', color: '#94a3b8' },
  pressure: { tile: 'pressure_new', label: 'Pressure', color: '#f472b6' },
}

export default function MapView({ lat = 20.5937, lon = 78.9629, zoom = 5, onCoordsChange }) {
  const [loading, setLoading] = useState(true)
  const [activeLayer, setActiveLayer] = useState('temp')
  const mapContainerRef = useRef(null)
  const mapRef = useRef(null)
  const tileLayerRef = useRef(null)
  const markerRef = useRef(null)

  const apiKey = import.meta.env.VITE_OPENWEATHER_API_KEY

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return

    const map = L.map(mapContainerRef.current, {
      zoomControl: true,
      attributionControl: true,
    }).setView([lat, lon], zoom)

    // Base OSM tiles (always visible)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors &copy; OpenWeatherMap',
    }).addTo(map)

    // Weather overlay layer
    tileLayerRef.current = L.tileLayer(
      `https://tile.openweathermap.org/map/${LAYERS[activeLayer].tile}/{z}/{x}/{y}.png?appid=${apiKey}`,
      { maxZoom: 19, opacity: 0.75 }
    )
    tileLayerRef.current.addTo(map)

    const marker = L.marker([lat, lon]).addTo(map)
    marker.bindPopup(`Selected location: ${lat.toFixed(2)}, ${lon.toFixed(2)}`).openPopup()
    markerRef.current = marker

    mapRef.current = map
    setLoading(false)

    return () => {
      map.remove()
      mapRef.current = null
      tileLayerRef.current = null
      markerRef.current = null
    }
  }, [])

  // Update view + marker when lat/lon changes
  useEffect(() => {
    if (!mapRef.current) return
    mapRef.current.setView([lat, lon], mapRef.current.getZoom())
    if (markerRef.current) {
      markerRef.current.setLatLng([lat, lon])
      markerRef.current.setPopupContent(`Selected location: ${lat.toFixed(2)}, ${lon.toFixed(2)}`)
    }
  }, [lat, lon])

  // Swap weather layer when selection changes
  useEffect(() => {
    if (!tileLayerRef.current || !mapRef.current) return
    tileLayerRef.current.setUrl(
      `https://tile.openweathermap.org/map/${LAYERS[activeLayer].tile}/{z}/{x}/{y}.png?appid=${apiKey}`
    )
  }, [activeLayer, apiKey])

  return (
    <div className="flex-1 flex flex-col h-full">
      {/* Header */}
      <AnimatedContent
        className="glass border-b border-white/10 px-4 pb-3 flex items-center justify-between flex-shrink-0"
        style={{ paddingTop: 'calc(env(safe-area-inset-top, 0px) + 2.5rem)' }}
      >
        <h1 className="text-white text-lg font-display font-semibold flex items-center gap-2">
          <Map className="text-accent" size={20} /> Live Weather Map
        </h1>
        <span className="text-white/30 text-xs hidden sm:inline">OpenWeatherMap</span>
      </AnimatedContent>

      {/* Layer Switcher */}
      <div className="glass border-b border-white/10 px-3 py-2 flex gap-1.5 overflow-x-auto no-scrollbar flex-shrink-0">
        {Object.entries(LAYERS).map(([key, layer]) => (
          <button
            key={key}
            onClick={() => setActiveLayer(key)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium whitespace-nowrap transition-colors touch-target ${
              activeLayer === key
                ? 'bg-accent/25 text-white ring-1 ring-accent/50'
                : 'text-white/60 hover:text-white hover:bg-white/10'
            }`}
          >
            <span className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle" style={{ background: layer.color }} />
            {layer.label}
          </button>
        ))}
      </div>

      {/* Map */}
      <div className="flex-1 relative overflow-hidden">
        <div ref={mapContainerRef} className="absolute inset-0" />

        {loading && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-black/30 backdrop-blur-sm">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="text-accent animate-spin" size={32} />
              <p className="text-white/60 text-sm">Loading map...</p>
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2 text-center flex-shrink-0">
        <p className="text-white/30 text-xs flex items-center justify-center gap-1">
          <MapPin size={12} /> {lat.toFixed(2)}, {lon.toFixed(2)}
        </p>
      </div>
    </div>
  )
}
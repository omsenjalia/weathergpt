import { useState } from 'react'
import { Map, Wind, CloudRain, Thermometer, Cloud, Radio, Waves, Gauge } from 'lucide-react'
import { Translations } from '../utils/translations'

const WINDY_OVERLAYS = [
  { id: 'wind', translationKey: 'layerWind', icon: Wind, color: '#38bdf8' },
  { id: 'rain', translationKey: 'layerRain', icon: CloudRain, color: '#60a5fa' },
  { id: 'temp', translationKey: 'layerTemp', icon: Thermometer, color: '#f59e0b' },
  { id: 'clouds', translationKey: 'layerClouds', icon: Cloud, color: '#94a3b8' },
  { id: 'radar', translationKey: 'layerRadar', icon: Radio, color: '#10b981' },
  { id: 'waves', translationKey: 'layerWaves', icon: Waves, color: '#06b6d4' },
  { id: 'pressure', translationKey: 'layerPressure', icon: Gauge, color: '#ec4899' },
]

export default function MapView({ location, language, zoom = 6 }) {
  const [activeOverlay, setActiveOverlay] = useState('wind')
  const langCode = language?.code || 'en'

  const lat = location?.lat ?? 20.5937
  const lon = location?.lon ?? 78.9629

  const embedUrl = `https://embed.windy.com/embed2.html?lat=${lat}&lon=${lon}&detailLat=${lat}&detailLon=${lon}&width=100%25&height=100%25&zoom=${zoom}&level=surface&overlay=${activeOverlay}&product=ecmwf&menu=&message=true&marker=true&calendar=now&pressure=&type=map&location=coordinates&detail=&metricWind=default&metricTemp=default&radarRange=-1`

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Layer Control Bar */}
      <div className="glass border-b border-white/10 px-4 py-3 flex gap-2 overflow-x-auto no-scrollbar flex-shrink-0 items-center">
        <span className="text-xs font-semibold text-white/50 uppercase tracking-wider hidden sm:inline mr-2">
          {Translations.get(langCode, 'mapLayer')}
        </span>
        {WINDY_OVERLAYS.map((layer) => {
          const Icon = layer.icon
          const isActive = activeOverlay === layer.id
          const label = Translations.get(langCode, layer.translationKey)
          return (
            <button
              key={layer.id}
              onClick={() => setActiveOverlay(layer.id)}
              className={`px-3.5 py-2 rounded-2xl text-xs font-medium whitespace-nowrap transition-all duration-200 cursor-pointer flex items-center gap-2 border ${
                isActive
                  ? 'bg-accent/30 text-white border-accent/60 shadow-lg'
                  : 'glass border-white/10 text-white/70 hover:text-white hover:bg-white/10'
              }`}
            >
              <Icon size={14} style={{ color: isActive ? '#fff' : layer.color }} />
              <span>{label}</span>
            </button>
          )
        })}
      </div>

      {/* Windy Embed Iframe Container */}
      <div className="flex-1 relative w-full h-full bg-slate-950 overflow-hidden">
        <iframe
          key={`${lat}-${lon}-${activeOverlay}`}
          title="Windy Interactive Map"
          src={embedUrl}
          className="w-full h-full border-0 absolute inset-0"
          loading="lazy"
          allow="geolocation"
        />
      </div>
    </div>
  )
}
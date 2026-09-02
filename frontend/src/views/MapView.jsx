import { useState, useEffect } from 'react'
import AnimatedContent from '../components/bits/AnimatedContent'

export default function MapView({ lat = 20.5937, lon = 78.9629, zoom = 5 }) {
  const [initialized, setInitialized] = useState(false)

  useEffect(() => {
    const apiKey = import.meta.env.VITE_WINDY_API_KEY
    if (!apiKey) {
      console.warn('VITE_WINDY_API_KEY is not set. Windy map will not load.')
      return
    }

    let attempts = 0
    const maxAttempts = 10

    const tryInit = () => {
      attempts++
      if (window.windyInit) {
        try {
          window.windyInit(
            {
              key: apiKey,
              lat,
              lon,
              zoom,
            },
            () => setInitialized(true)
          )
        } catch (err) {
          console.error('Windy init failed:', err)
        }
      } else if (attempts < maxAttempts) {
        setTimeout(tryInit, 300)
      }
    }

    const timer = setTimeout(tryInit, 200)
    return () => clearTimeout(timer)
  }, [lat, lon, zoom])

  return (
    <div className="flex-1 flex flex-col h-full">
      {/* Header */}
      <AnimatedContent className="glass border-b border-white/10 px-4 pt-10 pb-3 flex items-center justify-between flex-shrink-0">
        <h1 className="text-white text-lg font-display font-semibold">🗺 Live Weather Map</h1>
        <span className="text-white/30 text-xs">Powered by Windy</span>
      </AnimatedContent>

      {/* Map */}
      <div className="flex-1 overflow-hidden relative">
        <div id="windy" style={{ width: '100%', height: '100%' }} />
        {!initialized && import.meta.env.VITE_WINDY_API_KEY && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-white/50 animate-pulse">Loading map...</p>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-2 text-center flex-shrink-0">
        <p className="text-white/30 text-xs">
          Tap the map to explore. Animated wind data by Windy.com
        </p>
      </div>
    </div>
  )
}

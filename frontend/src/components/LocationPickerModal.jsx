import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { MapPin, Search, Navigation, X, Check, Loader2 } from 'lucide-react'
import axios from 'axios'
import { reverseGeocode, detectLocationFromIP } from '../utils/location'

const POPULAR_CITIES = [
  { name: 'Mumbai', country: 'India', lat: 19.076, lon: 72.8777 },
  { name: 'New Delhi', country: 'India', lat: 28.6139, lon: 77.209 },
  { name: 'Bengaluru', country: 'India', lat: 12.9716, lon: 77.5946 },
  { name: 'Hyderabad', country: 'India', lat: 17.385, lon: 78.4867 },
  { name: 'Chennai', country: 'India', lat: 13.0827, lon: 80.2707 },
  { name: 'Kolkata', country: 'India', lat: 22.5726, lon: 88.3639 },
  { name: 'Ahmedabad', country: 'India', lat: 23.0225, lon: 72.5714 },
  { name: 'Pune', country: 'India', lat: 18.5204, lon: 73.8567 },
  { name: 'Jaipur', country: 'India', lat: 26.9124, lon: 75.7873 },
  { name: 'Surat', country: 'India', lat: 21.1702, lon: 72.8311 },
]

export default function LocationPickerModal({ isOpen, onClose, onSelectLocation, currentLocation }) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [detectingGps, setDetectingGps] = useState(false)

  // Search auto-complete
  useEffect(() => {
    if (!query.trim() || query.length < 2) {
      setResults([])
      return
    }

    const timer = setTimeout(async () => {
      setSearching(true)
      try {
        const res = await axios.get('https://geocoding-api.open-meteo.com/v1/search', {
          params: { name: query.trim(), count: 6, language: 'en' },
        })
        const items = (res.data.results || []).map((item) => ({
          name: item.name,
          country: item.country || '',
          state: item.admin1 || '',
          lat: item.latitude,
          lon: item.longitude,
        }))
        setResults(items)
      } catch (err) {
        console.error('Geocoding search error:', err)
      } finally {
        setSearching(false)
      }
    }, 250)

    return () => clearTimeout(timer)
  }, [query])

  const handleSelect = (loc) => {
    onSelectLocation(loc)
    setQuery('')
    setResults([])
    onClose()
  }

  const handleDetectGps = () => {
    setDetectingGps(true)
    if (!navigator.geolocation) {
      detectLocationFromIP().then((ipLoc) => {
        setDetectingGps(false)
        if (ipLoc) {
          handleSelect(ipLoc)
        } else {
          alert('Could not detect location automatically. Please pick or search your city manually.')
        }
      })
      return
    }

    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const { latitude: lat, longitude: lon } = pos.coords
        try {
          const loc = await reverseGeocode(lat, lon)
          handleSelect(loc)
        } catch {
          handleSelect({ name: 'My Location', country: 'India', lat, lon })
        } finally {
          setDetectingGps(false)
        }
      },
      async (err) => {
        console.warn('GPS failed, attempting IP location fallback...', err)
        try {
          const ipLoc = await detectLocationFromIP()
          if (ipLoc) {
            handleSelect(ipLoc)
            return
          }
        } catch (ipErr) {
          console.error('IP location fallback failed:', ipErr)
        } finally {
          setDetectingGps(false)
        }
        alert('Could not detect location automatically. Please pick or search your city manually.')
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 300000 }
    )
  }

  if (!isOpen) return null

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-md"
          onClick={onClose}
        />

        {/* Modal Window */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: 15 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: 15 }}
          transition={{ duration: 0.2 }}
          className="glass rounded-3xl w-full max-w-lg p-6 relative z-10 border border-white/20 shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
        >
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <div className="w-9 h-9 rounded-xl bg-accent/20 border border-accent/40 flex items-center justify-center">
                <MapPin size={18} className="text-accent" />
              </div>
              <div>
                <h3 className="text-white text-lg font-bold font-display">Select Location</h3>
                <p className="text-white/50 text-xs">Search worldwide or pick a popular city</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="text-white/50 hover:text-white p-2 rounded-xl glass touch-target flex items-center justify-center cursor-pointer"
            >
              <X size={18} />
            </button>
          </div>

          {/* GPS Auto Detect Button */}
          <button
            onClick={handleDetectGps}
            disabled={detectingGps}
            className="w-full mb-4 bg-accent/20 hover:bg-accent/30 border border-accent/40 rounded-2xl p-3 text-white text-sm font-semibold flex items-center justify-center gap-2 transition-all cursor-pointer shadow-sm"
          >
            {detectingGps ? (
              <>
                <Loader2 size={16} className="animate-spin text-accent" />
                <span>Detecting GPS Location...</span>
              </>
            ) : (
              <>
                <Navigation size={16} className="text-accent" />
                <span>Use My Current Location (GPS)</span>
              </>
            )}
          </button>

          {/* Manual Search Input */}
          <div className="relative mb-4">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search city manually (e.g. Jaipur, Dubai, London)..."
              className="w-full bg-white/5 border border-white/15 rounded-2xl pl-10 pr-10 py-3 text-white text-sm placeholder:text-white/40 focus:outline-none focus:ring-1 focus:ring-accent/60"
            />
            <Search size={18} className="absolute left-3.5 top-3.5 text-white/40" />
            {searching && (
              <Loader2 size={18} className="absolute right-3.5 top-3.5 text-accent animate-spin" />
            )}
          </div>

          {/* Search Results List */}
          {results.length > 0 ? (
            <div className="flex flex-col gap-1.5 overflow-y-auto no-scrollbar max-h-48 mb-4">
              {results.map((item, i) => (
                <button
                  key={i}
                  onClick={() => handleSelect(item)}
                  className="flex items-center justify-between p-3 rounded-2xl hover:bg-white/10 transition-colors text-left border border-transparent hover:border-white/10 cursor-pointer"
                >
                  <div className="flex items-center gap-2.5">
                    <MapPin size={16} className="text-accent" />
                    <div>
                      <span className="text-white font-medium text-sm">{item.name}</span>
                      <span className="text-white/50 text-xs ml-2">
                        {item.state ? `${item.state}, ` : ''}{item.country}
                      </span>
                    </div>
                  </div>
                  <Check size={16} className="text-white/20" />
                </button>
              ))}
            </div>
          ) : query.length >= 2 && !searching ? (
            <div className="text-center py-4 text-white/40 text-sm">
              No matching cities found for &quot;{query}&quot;.
            </div>
          ) : null}

          {/* Popular Cities Section */}
          <div className="mt-2 pt-4 border-t border-white/10">
            <p className="text-white/50 text-xs uppercase font-semibold tracking-wider mb-3">
              Popular Cities in India
            </p>
            <div className="flex flex-wrap gap-2 overflow-y-auto no-scrollbar max-h-40">
              {POPULAR_CITIES.map((c, i) => {
                const isSelected = currentLocation?.name?.toLowerCase() === c.name.toLowerCase()
                return (
                  <button
                    key={i}
                    onClick={() => handleSelect(c)}
                    className={`px-3.5 py-2 rounded-2xl text-xs font-semibold transition-all cursor-pointer flex items-center gap-1.5 border ${
                      isSelected
                        ? 'bg-accent text-white border-accent shadow-md'
                        : 'glass text-white/70 hover:text-white hover:bg-white/15 border-white/10'
                    }`}
                  >
                    <MapPin size={12} className={isSelected ? 'text-white' : 'text-accent'} />
                    <span>{c.name}</span>
                  </button>
                )
              })}
            </div>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  )
}

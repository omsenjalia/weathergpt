import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { MapPin, ChevronDown, Languages } from 'lucide-react'
import Aurora from './components/bits/Aurora'
import Sidebar from './components/Sidebar'
import BottomDock from './components/BottomDock'
import LocationPickerModal from './components/LocationPickerModal'
import LanguagePickerModal, { INDIAN_LANGUAGES } from './components/LanguagePickerModal'
import WeatherHome from './views/WeatherHome'
import ChatView from './views/ChatView'
import MapView from './views/MapView'

const DEFAULT_LOCATION = {
  name: 'New Delhi',
  country: 'India',
  lat: 28.6139,
  lon: 77.209,
}

export default function App() {
  const [activeView, setActiveView] = useState('home')
  const [location, setLocation] = useState(DEFAULT_LOCATION)
  const [language, setLanguage] = useState(INDIAN_LANGUAGES[0]) // Default English
  const [isLocationModalOpen, setIsLocationModalOpen] = useState(false)
  const [isLanguageModalOpen, setIsLanguageModalOpen] = useState(false)

  // Lifted state: keeps Chat history alive across view switches.
  const [chatMessages, setChatMessages] = useState([])

  // Load saved location & language on mount
  useEffect(() => {
    try {
      const savedLoc = localStorage.getItem('weathergpt_location')
      if (savedLoc) {
        const parsed = JSON.parse(savedLoc)
        if (parsed?.lat && parsed?.lon && parsed?.name) {
          setLocation(parsed)
        }
      }

      const savedLang = localStorage.getItem('weathergpt_language')
      if (savedLang) {
        const parsedLang = JSON.parse(savedLang)
        if (parsedLang?.code && parsedLang?.name) {
          setLanguage(parsedLang)
        }
      }
    } catch {
      // Ignore parse errors
    }

    // Fallback: try GPS detection once
    if (navigator.geolocation && !localStorage.getItem('weathergpt_location')) {
      navigator.geolocation.getCurrentPosition(
        async (pos) => {
          const { latitude: lat, longitude: lon } = pos.coords
          try {
            const res = await fetch(
              `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json`
            )
            const data = await res.json()
            const name =
              data.address?.city ||
              data.address?.town ||
              data.address?.village ||
              data.address?.county ||
              'My Location'
            const country = data.address?.country || 'India'
            const newLoc = { name, country, lat, lon }
            setLocation(newLoc)
            localStorage.setItem('weathergpt_location', JSON.stringify(newLoc))
          } catch {
            const fallback = { name: 'My Location', country: 'India', lat, lon }
            setLocation(fallback)
          }
        },
        () => {},
        { timeout: 5000 }
      )
    }
  }, [])

  const handleSelectLocation = (newLoc) => {
    setLocation(newLoc)
    try {
      localStorage.setItem('weathergpt_location', JSON.stringify(newLoc))
    } catch {
      // Ignore
    }
  }

  const handleSelectLanguage = (newLang) => {
    setLanguage(newLang)
    try {
      localStorage.setItem('weathergpt_language', JSON.stringify(newLang))
    } catch {
      // Ignore
    }
  }

  const views = {
    home: (
      <WeatherHome
        location={location}
        language={language}
        onOpenLocationPicker={() => setIsLocationModalOpen(true)}
      />
    ),
    chat: (
      <ChatView
        messages={chatMessages}
        setMessages={setChatMessages}
        location={location}
        language={language}
      />
    ),
    map: <MapView location={location} />,
  }

  return (
    <div className="h-screen h-[100dvh] overflow-hidden relative flex bg-[#0d0b1a]">
      {/* Aurora Background */}
      <Aurora />

      {/* Persistent Sidebar — desktop screen */}
      <Sidebar
        activeView={activeView}
        onNavigate={setActiveView}
        location={location}
        onOpenLocationPicker={() => setIsLocationModalOpen(true)}
        language={language}
        onOpenLanguagePicker={() => setIsLanguageModalOpen(true)}
      />

      {/* Main Content Area */}
      <div className="relative z-10 flex-1 flex flex-col h-full overflow-hidden">
        {/* Universal Header Bar */}
        <header className="glass border-b border-white/10 px-4 py-2.5 flex items-center justify-between flex-shrink-0 z-30">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsLocationModalOpen(true)}
              className="glass hover:bg-white/15 px-3 py-1.5 rounded-2xl text-white text-xs md:text-sm font-semibold flex items-center gap-1.5 border border-white/15 cursor-pointer transition-all shadow-sm"
            >
              <MapPin size={14} className="text-accent" />
              <span>{location.name}</span>
              <ChevronDown size={14} className="text-white/50 ml-0.5" />
            </button>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setIsLanguageModalOpen(true)}
              className="glass hover:bg-white/15 px-3 py-1.5 rounded-2xl text-white text-xs md:text-sm font-semibold flex items-center gap-1.5 border border-white/15 cursor-pointer transition-all shadow-sm"
            >
              <Languages size={14} className="text-accent" />
              <span>{language.native}</span>
              <ChevronDown size={14} className="text-white/50 ml-0.5" />
            </button>
          </div>
        </header>

        {/* View Content */}
        <AnimatePresence mode="wait">
          <motion.div
            key={activeView}
            initial={{ opacity: 0, scale: 0.99 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 1.01 }}
            transition={{ duration: 0.2 }}
            className="flex-1 flex flex-col h-full overflow-hidden"
          >
            {views[activeView]}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Bottom Dock — mobile screen only */}
      <div className="md:hidden">
        <BottomDock activeView={activeView} onNavigate={setActiveView} />
      </div>

      {/* Modals */}
      <LocationPickerModal
        isOpen={isLocationModalOpen}
        onClose={() => setIsLocationModalOpen(false)}
        onSelectLocation={handleSelectLocation}
        currentLocation={location}
      />

      <LanguagePickerModal
        isOpen={isLanguageModalOpen}
        onClose={() => setIsLanguageModalOpen(false)}
        onSelectLanguage={handleSelectLanguage}
        currentLanguage={language}
      />
    </div>
  )
}

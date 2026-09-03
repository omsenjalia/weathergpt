import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { MapPin, ChevronDown, Languages, Menu, X, Sun, MessageSquare, Map, Key } from 'lucide-react'
import Aurora from './components/bits/Aurora'
import Sidebar from './components/Sidebar'
import BottomDock from './components/BottomDock'
import LocationPickerModal from './components/LocationPickerModal'
import LanguagePickerModal, { INDIAN_LANGUAGES } from './components/LanguagePickerModal'
import ApiSettingsModal from './components/ApiSettingsModal'
import WeatherHome from './views/WeatherHome'
import ChatView from './views/ChatView'
import MapView from './views/MapView'

const DEFAULT_LOCATION = {
  name: 'New Delhi',
  country: 'India',
  lat: 28.6139,
  lon: 77.209,
}

const mobileNavItems = [
  { id: 'home', icon: Sun, label: 'Weather' },
  { id: 'chat', icon: MessageSquare, label: 'Chat' },
  { id: 'map', icon: Map, label: 'Map' },
]

export default function App() {
  const [activeView, setActiveView] = useState('home')
  const [location, setLocation] = useState(DEFAULT_LOCATION)
  const [language, setLanguage] = useState(INDIAN_LANGUAGES[0]) // Default English
  const [isLocationModalOpen, setIsLocationModalOpen] = useState(false)
  const [isLanguageModalOpen, setIsLanguageModalOpen] = useState(false)
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)
  const [isApiSettingsOpen, setIsApiSettingsOpen] = useState(false)

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
        onOpenApiSettings={() => setIsApiSettingsOpen(true)}
      />

      {/* Main Content Area */}
      <div className="relative z-10 flex-1 flex flex-col h-full overflow-hidden">
        {/* Universal Header Bar */}
        <header className="glass border-b border-white/10 px-4 py-2.5 flex items-center justify-between flex-shrink-0 z-30 relative">
          <div className="flex items-center gap-2">
            {/* Mobile Hamburger Menu Button */}
            <button
              onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
              className="md:hidden glass hover:bg-white/15 p-2 rounded-2xl text-white border border-white/15 cursor-pointer transition-all shadow-sm flex items-center justify-center"
              aria-label="Toggle navigation menu"
            >
              {isMobileMenuOpen ? <X size={18} className="text-accent" /> : <Menu size={18} className="text-white" />}
            </button>

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
              onClick={() => setIsApiSettingsOpen(true)}
              className="glass hover:bg-white/15 px-2.5 py-1.5 rounded-2xl text-white text-xs md:text-sm font-semibold flex items-center gap-1.5 border border-white/15 cursor-pointer transition-all shadow-sm"
              title="Weather API Settings"
            >
              <Key size={14} className="text-accent" />
              <span className="hidden sm:inline">API Keys</span>
            </button>

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

        {/* Mobile Dropdown Navigation Drawer */}
        <AnimatePresence>
          {isMobileMenuOpen && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.2 }}
              className="md:hidden absolute top-14 left-4 right-4 z-40 glass rounded-3xl p-3 border border-white/20 shadow-2xl flex flex-col gap-1.5 backdrop-blur-xl bg-[#0d0b1a]/95"
            >
              {mobileNavItems.map((item) => {
                const Icon = item.icon
                const isActive = activeView === item.id
                return (
                  <button
                    key={item.id}
                    onClick={() => {
                      setActiveView(item.id)
                      setIsMobileMenuOpen(false)
                    }}
                    className={`flex items-center gap-3 px-4 py-3 rounded-2xl text-sm font-semibold transition-all cursor-pointer ${
                      isActive
                        ? 'bg-accent text-white shadow-md border border-accent/40'
                        : 'text-white/80 hover:bg-white/10'
                    }`}
                  >
                    <Icon size={18} className={isActive ? 'text-white' : 'text-accent'} />
                    <span>{item.label}</span>
                  </button>
                )
              })}
            </motion.div>
          )}
        </AnimatePresence>

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

      {/* Bottom Dock — mobile screen only, hidden in chat view so chat input is fully accessible */}
      {activeView !== 'chat' && !isMobileMenuOpen && (
        <div className="md:hidden">
          <BottomDock activeView={activeView} onNavigate={setActiveView} />
        </div>
      )}

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

      <ApiSettingsModal
        isOpen={isApiSettingsOpen}
        onClose={() => setIsApiSettingsOpen(false)}
      />
    </div>
  )
}

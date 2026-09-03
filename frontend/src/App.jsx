import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { MapPin, ChevronDown, Languages, Menu, X, Sun, MessageSquare, Map, Terminal } from 'lucide-react'
import Aurora from './components/bits/Aurora'
import Sidebar from './components/Sidebar'
import LocationPickerModal from './components/LocationPickerModal'
import LanguagePickerModal, { INDIAN_LANGUAGES } from './components/LanguagePickerModal'
import WeatherHome from './views/WeatherHome'
import ChatView from './views/ChatView'
import MapView from './views/MapView'
import DevView from './views/DevView'
import { autoDetectUserLocation } from './utils/location'
import { Translations } from './utils/translations'

const DEFAULT_LOCATION = {
  name: 'New Delhi',
  country: 'India',
  lat: 28.6139,
  lon: 77.209,
}

const mobileNavItems = [
  { id: 'home', icon: Sun, label: 'Weather', translationKey: 'navWeather' },
  { id: 'chat', icon: MessageSquare, label: 'Chat', translationKey: 'navChat' },
  { id: 'map', icon: Map, label: 'Map', translationKey: 'navMap' },
  { id: 'dev', icon: Terminal, label: 'Developer', translationKey: 'navDev' },
]

export default function App() {
  const [activeView, setActiveView] = useState('home')
  const [location, setLocation] = useState(DEFAULT_LOCATION)
  const [language, setLanguage] = useState(INDIAN_LANGUAGES[0]) // Default English
  const [isLocationModalOpen, setIsLocationModalOpen] = useState(false)
  const [isLanguageModalOpen, setIsLanguageModalOpen] = useState(false)
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)

  // Lifted state: keeps Chat history alive across view switches.
  const [chatMessages, setChatMessages] = useState([])

  // Check URL path for /dev or shortcut listener
  useEffect(() => {
    if (window.location.pathname === '/dev') {
      setActiveView('dev')
    }

    const handleKeyDown = (e) => {
      if (e.shiftKey && (e.key === 'D' || e.key === 'd')) {
        e.preventDefault()
        setActiveView((prev) => (prev === 'dev' ? 'home' : 'dev'))
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Load saved location & language on mount, or auto-detect location
  useEffect(() => {
    try {
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

    // Auto-detect user location via GPS or IP fallback
    autoDetectUserLocation().then((detectedLoc) => {
      if (detectedLoc) {
        setLocation(detectedLoc)
      }
    })
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
    map: <MapView location={location} language={language} />,
    dev: <DevView location={location} language={language} />,
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
                const label = Translations.get(language?.code, item.translationKey)
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
                    <span>{label}</span>
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

      {/* Modals */}
      <LocationPickerModal
        isOpen={isLocationModalOpen}
        onClose={() => setIsLocationModalOpen(false)}
        onSelectLocation={handleSelectLocation}
        currentLocation={location}
        language={language}
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


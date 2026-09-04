import { useState, useEffect } from 'react'
import { Menu, Sun } from 'lucide-react'
import Sidebar from './components/Sidebar'
import LocationPickerModal from './components/LocationPickerModal'
import LanguagePickerModal, { INDIAN_LANGUAGES } from './components/LanguagePickerModal'
import WeatherChatView from './views/WeatherChatView'
import MapView from './views/MapView'
import DevView from './views/DevView'
import IMDHubView from './views/IMDHubView'
import ExcalidrawArchitectureView from './views/ExcalidrawArchitectureView'
import { autoDetectUserLocation } from './utils/location'

const DEFAULT_LOCATION = {
  name: 'New Delhi',
  country: 'India',
  lat: 28.6139,
  lon: 77.209,
}

export default function App() {
  const [activeView, setActiveView] = useState('home')
  const [location, setLocation] = useState(DEFAULT_LOCATION)
  const [language, setLanguage] = useState(INDIAN_LANGUAGES[0])
  const [isLocationModalOpen, setIsLocationModalOpen] = useState(false)
  const [isLanguageModalOpen, setIsLanguageModalOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [favorites, setFavorites] = useState([])
  const [farmerMode, setFarmerMode] = useState(false)
  const [selectedCrop, setSelectedCrop] = useState('Cotton')

  // Check URL path for /dev, /imd or shortcut listener
  useEffect(() => {
    if (window.location.pathname === '/dev') {
      setActiveView('dev')
    } else if (window.location.pathname === '/imd') {
      setActiveView('imd')
    } else if (window.location.pathname === '/architecture') {
      setActiveView('architecture')
    }

    const handleKeyDown = (e) => {
      // Shift+D toggles dev view
      if (e.shiftKey && (e.key === 'D' || e.key === 'd')) {
        e.preventDefault()
        setActiveView((prev) => (prev === 'dev' ? 'home' : 'dev'))
      }
      // ⌘K / Ctrl+K starts new chat (goes home)
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setActiveView('home')
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  // Load saved settings on mount
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

    try {
      const savedFavs = localStorage.getItem('weathergpt_favorites')
      if (savedFavs) {
        setFavorites(JSON.parse(savedFavs))
      }
    } catch {
      // Ignore
    }

    // Auto-detect user location
    autoDetectUserLocation().then((detectedLoc) => {
      if (detectedLoc) {
        setLocation(detectedLoc)
      }
    })
  }, [])

  // Close sidebar when screen becomes desktop-sized
  useEffect(() => {
    const mq = window.matchMedia('(min-width: 768px)')
    const handler = (e) => {
      if (e.matches) setSidebarOpen(false)
    }
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
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

  const renderView = () => {
    switch (activeView) {
      case 'imd':
        return <IMDHubView location={location} />
      case 'map':
        return <MapView location={location} language={language} />
      case 'dev':
        return <DevView location={location} language={language} />
      case 'architecture':
        return <ExcalidrawArchitectureView />
      case 'home':
      default:
        return (
          <WeatherChatView
            location={location}
            language={language}
            favorites={favorites}
            onSelectLocation={handleSelectLocation}
            farmerMode={farmerMode}
            selectedCrop={selectedCrop}
          />
        )
    }
  }

  return (
    <div className="flex h-screen h-[100dvh] w-full max-w-full overflow-hidden bg-black text-white font-sans">
      {/* Sidebar */}
      <Sidebar
        activeView={activeView}
        onNavigate={setActiveView}
        location={location}
        onOpenLocationPicker={() => setIsLocationModalOpen(true)}
        language={language}
        onOpenLanguagePicker={() => setIsLanguageModalOpen(true)}
        favorites={favorites}
        sidebarOpen={sidebarOpen}
        onCloseSidebar={() => setSidebarOpen(false)}
        farmerMode={farmerMode}
        onToggleFarmerMode={() => setFarmerMode((prev) => !prev)}
        selectedCrop={selectedCrop}
        onSelectCrop={setSelectedCrop}
      />

      {/* Main Area */}
      <main className="flex-1 flex flex-col min-h-0 bg-black relative min-w-0 overflow-hidden">
        {/* Mobile top bar with hamburger */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-white/10 md:hidden flex-shrink-0 z-20">
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="p-1.5 text-white/60 hover:text-white transition-colors cursor-pointer"
            aria-label="Open sidebar"
          >
            <Menu className="w-5 h-5" />
          </button>
          <div
            className="flex items-center gap-2 cursor-pointer"
            onClick={() => setActiveView('home')}
          >
            <div className="w-5 h-5 rounded-sm bg-accent/20 border border-accent/30 flex items-center justify-center">
              <Sun size={12} className="text-accent" />
            </div>
            <span className="font-bricolage text-lg font-bold tracking-tight text-white/95">
              WeatherGPT
            </span>
          </div>
          <div className="w-8" /> {/* Spacer for centering */}
        </div>

        {/* View Content */}
        {renderView()}
      </main>

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

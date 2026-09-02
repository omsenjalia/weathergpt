import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import Aurora from './components/bits/Aurora'
import Sidebar from './components/Sidebar'
import BottomDock from './components/BottomDock'
import WeatherHome from './views/WeatherHome'
import ChatView from './views/ChatView'
import VoiceView from './views/VoiceView'
import MapView from './views/MapView'

export default function App() {
  const [activeView, setActiveView] = useState('home')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [coords, setCoords] = useState({ lat: 20.5937, lon: 78.9629 })

  const views = {
    home: <WeatherHome onCoordsChange={setCoords} />,
    chat: <ChatView />,
    voice: <VoiceView onNavigate={setActiveView} />,
    map: <MapView lat={coords.lat} lon={coords.lon} />,
  }

  return (
    <div className="h-screen overflow-hidden relative">
      {/* Aurora Background */}
      <Aurora />

      {/* Sidebar — desktop only */}
      <Sidebar
        activeView={activeView}
        onNavigate={(v) => {
          setActiveView(v)
          setSidebarOpen(false)
        }}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Main Content */}
      <div className="relative z-10 h-screen flex flex-col">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeView}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.25 }}
            className="flex-1 overflow-hidden flex flex-col"
          >
            {views[activeView]}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Bottom Dock — mobile only */}
      <BottomDock activeView={activeView} onNavigate={setActiveView} />

      {/* Hamburger trigger for sidebar — desktop only */}
      {!sidebarOpen && (
        <button
          onClick={() => setSidebarOpen(true)}
          className="fixed top-6 left-6 z-50 glass w-10 h-10 rounded-xl items-center justify-center cursor-pointer hidden md:flex"
        >
          <span className="text-white text-lg">☰</span>
        </button>
      )}
    </div>
  )
}

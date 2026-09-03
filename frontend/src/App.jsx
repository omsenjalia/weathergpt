import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Menu } from 'lucide-react'
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

  // Lifted state: keeps Chat history alive across view switches.
  const [chatMessages, setChatMessages] = useState([])
  // Set by VoiceView; ChatView auto-sends this then clears it.
  const [voiceQuery, setVoiceQuery] = useState('')

  // Called by VoiceView when the user taps "Send to Chat".
  const handleVoiceSend = (text) => {
    setVoiceQuery(text)
    setActiveView('chat')
  }

  const views = {
    home: <WeatherHome onCoordsChange={setCoords} />,
    chat: (
      <ChatView
        messages={chatMessages}
        setMessages={setChatMessages}
        initialMessage={voiceQuery}
        onVoiceProcessed={() => setVoiceQuery('')}
      />
    ),
    voice: <VoiceView onSendVoice={handleVoiceSend} />,
    map: <MapView lat={coords.lat} lon={coords.lon} />,
  }

  return (
    <div className="h-screen h-[100dvh] overflow-hidden relative">
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
      <div className="relative z-10 flex flex-col h-full">
        <AnimatePresence mode="wait">
          <motion.div
            key={activeView}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.25 }}
            className="flex-1 flex flex-col"
          >
            {views[activeView]}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Bottom Dock — mobile only */}
      <BottomDock activeView={activeView} onNavigate={setActiveView} />

      {/* Hamburger trigger for sidebar — desktop only, shown only when sidebar is closed */}
      {!sidebarOpen && (
        <button
          onClick={() => setSidebarOpen(true)}
          aria-label="Open menu"
          className="fixed top-6 left-6 z-50 glass w-11 h-11 rounded-xl items-center justify-center cursor-pointer hidden md:flex touch-target"
        >
          <Menu className="text-white" size={22} />
        </button>
      )}
    </div>
  )
}

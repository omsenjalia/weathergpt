import { motion, AnimatePresence } from 'framer-motion'

const navItems = [
  { id: 'home', icon: '🌤️', label: 'Weather' },
  { id: 'chat', icon: '💬', label: 'Chat' },
  { id: 'voice', icon: '🎤', label: 'Voice' },
  { id: 'map', icon: '🗺️', label: 'Map' },
]

export default function Sidebar({ activeView, onNavigate, open, onClose }) {
  return (
    <>
      {/*
        Close button — only rendered while the sidebar is open.
        The open button lives in App.jsx and renders when the sidebar is closed.
        Previously both were rendered simultaneously at the same position
        (fixed top-6 left-6), and the sidebar's button had a dead `null` branch
        when open===false plus a ternary that always returned the same class.
      */}
      {open && (
        <button
          onClick={onClose}
          className="fixed top-6 left-6 z-50 glass w-10 h-10 rounded-xl items-center justify-center cursor-pointer hidden md:flex"
        >
          <span className="text-white text-lg">✕</span>
        </button>
      )}

      {/* Backdrop */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/40 backdrop-blur-sm z-30 hidden md:block"
            onClick={onClose}
          />
        )}
      </AnimatePresence>

      {/* Sidebar Panel */}
      <motion.div
        initial={{ x: -264 }}
        animate={{ x: open ? 0 : -264 }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
        className="fixed left-0 top-0 bottom-0 w-64 z-40 glass border-r border-white/10 hidden md:flex flex-col pt-20 px-4"
      >
        {/* Logo */}
        <div className="mb-8 px-4">
          <span className="text-3xl">🌤️</span>
          <h1 className="text-white text-xl font-display font-bold mt-2">WeatherGPT</h1>
          <p className="text-white/40 text-xs mt-1">AI Weather Assistant</p>
        </div>

        {/* Nav Items */}
        <div className="flex flex-col gap-2">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`flex items-center gap-3 px-4 py-3 rounded-2xl cursor-pointer transition-all ${
                activeView === item.id
                  ? 'bg-accent/20 text-white border border-accent/30'
                  : 'text-white/70 hover:text-white hover:bg-white/10'
              }`}
            >
              <span className="text-xl">{item.icon}</span>
              <span className="text-sm font-medium">{item.label}</span>
            </button>
          ))}
        </div>
      </motion.div>
    </>
  )
}

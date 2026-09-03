import { motion, AnimatePresence } from 'framer-motion'
import { Languages, X, Check } from 'lucide-react'

export const INDIAN_LANGUAGES = [
  { code: 'en', name: 'English', native: 'English', speechCode: 'en-IN' },
  { code: 'hi', name: 'Hindi', native: 'हिंदी', speechCode: 'hi-IN' },
  { code: 'gu', name: 'Gujarati', native: 'ગુજરાતી', speechCode: 'gu-IN' },
  { code: 'mr', name: 'Marathi', native: 'मराठी', speechCode: 'mr-IN' },
  { code: 'ta', name: 'Tamil', native: 'தமிழ்', speechCode: 'ta-IN' },
  { code: 'te', name: 'Telugu', native: 'తెలుగు', speechCode: 'te-IN' },
  { code: 'bn', name: 'Bengali', native: 'বাংলা', speechCode: 'bn-IN' },
  { code: 'kn', name: 'Kannada', native: 'ಕನ್ನಡ', speechCode: 'kn-IN' },
  { code: 'ml', name: 'Malayalam', native: 'മലയാളം', speechCode: 'ml-IN' },
  { code: 'pa', name: 'Punjabi', native: 'ਪੰਜਾਬੀ', speechCode: 'pa-IN' },
]

export default function LanguagePickerModal({ isOpen, onClose, onSelectLanguage, currentLanguage }) {
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
          className="glass rounded-3xl w-full max-w-md p-6 relative z-10 border border-white/20 shadow-2xl overflow-hidden flex flex-col max-h-[85vh]"
        >
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-accent/20 border border-accent/40 flex items-center justify-center">
                <Languages size={18} className="text-accent" />
              </div>
              <div>
                <h3 className="text-white text-lg font-bold font-display">Select Language</h3>
                <p className="text-white/50 text-xs">Choose preferred Indian regional language</p>
              </div>
            </div>
            <button
              onClick={onClose}
              className="text-white/50 hover:text-white p-2 rounded-xl glass touch-target flex items-center justify-center cursor-pointer"
            >
              <X size={18} />
            </button>
          </div>

          {/* Languages Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 overflow-y-auto no-scrollbar max-h-96 pr-1">
            {INDIAN_LANGUAGES.map((lang) => {
              const isSelected = currentLanguage?.code === lang.code
              return (
                <button
                  key={lang.code}
                  onClick={() => {
                    onSelectLanguage(lang)
                    onClose()
                  }}
                  className={`flex items-center justify-between p-3 rounded-2xl border transition-all text-left cursor-pointer ${
                    isSelected
                      ? 'bg-accent/25 border-accent/60 text-white shadow-md font-semibold'
                      : 'glass border-white/10 text-white/80 hover:text-white hover:bg-white/10'
                  }`}
                >
                  <div>
                    <p className="text-sm font-bold">{lang.native}</p>
                    <p className="text-xs text-white/50">{lang.name}</p>
                  </div>
                  {isSelected && <Check size={16} className="text-accent" />}
                </button>
              )
            })}
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  )
}

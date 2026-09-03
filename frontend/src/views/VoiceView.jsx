import { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { Mic, MicOff, Languages, Send, RotateCcw } from 'lucide-react'

// onSendVoice(text) — called instead of invoking sendMessage directly here.
// App.jsx stores the transcript and lets ChatView send it, so the response
// is properly displayed in the chat thread instead of being silently discarded.
export default function VoiceView({ onSendVoice, language }) {
  const [listening, setListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [supported, setSupported] = useState(true)
  const recognitionRef = useRef(null)

  const activeLangCode = language?.speechCode || 'en-IN'

  const isSecure =
    window.location.protocol === 'https:' ||
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1'

  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition || !isSecure) {
      setSupported(false)
      return
    }

    const recognition = new SpeechRecognition()
    recognition.lang = activeLangCode
    recognition.continuous = false
    recognition.interimResults = true

    recognition.onresult = (event) => {
      const result = Array.from(event.results)
        .map((r) => r[0].transcript)
        .join('')
      setTranscript(result)
    }

    recognition.onend = () => setListening(false)
    recognition.onerror = () => setListening(false)

    recognitionRef.current = recognition
  }, [activeLangCode])

  const toggleListening = () => {
    if (!recognitionRef.current) return
    if (listening) {
      recognitionRef.current.stop()
      setListening(false)
    } else {
      setTranscript('')
      recognitionRef.current.lang = lang
      recognitionRef.current.start()
      setListening(true)
    }
  }

  const handleSendToChat = () => {
    if (!transcript.trim()) return
    onSendVoice?.(transcript.trim())
    setTranscript('')
  }

  if (!supported) {
    return (
      <div className="flex-1 flex items-center justify-center px-6">
        <div className="glass rounded-3xl p-8 text-center max-w-sm">
          <p className="text-white/70 text-lg mb-4">
            Voice input requires Chrome browser on mobile or desktop.
          </p>
          <p className="text-white/50 text-sm mb-6">
            Please type your query in the Chat tab instead.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-6 sm:gap-8 p-6 pb-24 md:pb-6 overflow-y-auto no-scrollbar">
      {/* Title */}
      <div className="text-center">
        <h1 className="text-white text-xl sm:text-2xl font-display font-bold mb-2">Voice Assistant</h1>
        <p className="text-white/50 text-sm sm:text-base">Speak your weather query</p>
      </div>

      {/* Language Toggle */}
      <div className="flex items-center gap-2">
        <Languages className="text-white/40" size={18} />
        <button
          onClick={() => setLang('en-IN')}
          className={`px-4 py-2 rounded-full text-sm font-medium transition-colors touch-target ${
            lang === 'en-IN' ? 'bg-accent text-white' : 'glass text-white/60'
          }`}
        >
          EN
        </button>
        <button
          onClick={() => setLang('hi-IN')}
          className={`px-4 py-2 rounded-full text-sm font-medium transition-colors touch-target ${
            lang === 'hi-IN' ? 'bg-accent text-white' : 'glass text-white/60'
          }`}
        >
          HI
        </button>
      </div>

      {/* Microphone Button */}
      <div className="relative">
        {listening && (
          <motion.div
            className="absolute inset-0 rounded-full border-2 border-accent"
            animate={{ scale: [1, 1.3, 1], opacity: [0.6, 0, 0.6] }}
            transition={{ duration: 1.5, repeat: Infinity }}
          />
        )}
        <motion.button
          onClick={toggleListening}
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          aria-label={listening ? 'Stop listening' : 'Start listening'}
          className={`w-24 h-24 sm:w-32 sm:h-32 rounded-full flex items-center justify-center transition-colors touch-target ${
            listening ? 'border-2 border-accent glass' : 'glass'
          }`}
        >
          {listening ? (
            <MicOff className="text-red-400" size={44} />
          ) : (
            <Mic className="text-accent" size={44} />
          )}
        </motion.button>
      </div>

      {/* Transcript */}
      <div className="glass rounded-2xl px-6 py-4 mx-4 min-h-16 w-full max-w-md text-center">
        <p className={`text-base sm:text-lg ${transcript ? 'text-white' : 'text-white/30'}`}>
          {transcript || 'Tap the mic and speak...'}
        </p>
      </div>

      {/* Action Buttons */}
      {transcript && (
        <div className="flex gap-3">
          <button
            onClick={handleSendToChat}
            className="bg-accent rounded-xl px-6 py-3 text-white font-medium flex items-center gap-2 touch-target"
          >
            <Send size={16} /> Send to Chat
          </button>
          <button
            onClick={() => setTranscript('')}
            className="glass rounded-xl px-6 py-3 text-white/70 font-medium flex items-center gap-2 touch-target"
          >
            <RotateCcw size={16} /> Clear
          </button>
        </div>
      )}
    </div>
  )
}

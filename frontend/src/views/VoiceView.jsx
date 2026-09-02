import { useState, useEffect, useRef } from 'react'
import { motion } from 'framer-motion'
import { sendMessage } from '../api'

export default function VoiceView({ onNavigate }) {
  const [listening, setListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [supported, setSupported] = useState(true)
  const [lang, setLang] = useState('en-IN')
  const recognitionRef = useRef(null)

  useEffect(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    if (!SpeechRecognition) {
      setSupported(false)
      return
    }

    const recognition = new SpeechRecognition()
    recognition.lang = lang
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
  }, [lang])

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

  const handleSendToChat = async () => {
    if (!transcript.trim()) return
    try {
      await sendMessage(transcript.trim())
      onNavigate('chat')
    } catch (err) {
      console.error(err)
      onNavigate('chat')
    }
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
          <button
            onClick={() => onNavigate('chat')}
            className="bg-accent rounded-xl px-6 py-3 text-white font-medium"
          >
            Go to Chat
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col items-center justify-center gap-8 px-6">
      {/* Title */}
      <div className="text-center">
        <h1 className="text-white text-2xl font-display font-bold mb-2">Voice Assistant</h1>
        <p className="text-white/50">Speak your weather query</p>
      </div>

      {/* Language Toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setLang('en-IN')}
          className={`px-4 py-2 rounded-full text-sm font-medium transition-colors ${
            lang === 'en-IN' ? 'bg-accent text-white' : 'glass text-white/60'
          }`}
        >
          EN
        </button>
        <button
          onClick={() => setLang('hi-IN')}
          className={`px-4 py-2 rounded-full text-sm font-medium transition-colors ${
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
          className={`w-32 h-32 rounded-full flex items-center justify-center transition-colors ${
            listening ? 'border-2 border-accent glass' : 'glass'
          }`}
        >
          <span className="text-5xl">🎤</span>
        </motion.button>
      </div>

      {/* Transcript */}
      <div className="glass rounded-2xl px-6 py-4 mx-4 min-h-16 w-full max-w-md text-center">
        <p className={`text-lg ${transcript ? 'text-white' : 'text-white/30'}`}>
          {transcript || 'Tap the mic and speak...'}
        </p>
      </div>

      {/* Action Buttons */}
      {transcript && (
        <div className="flex gap-3">
          <button
            onClick={handleSendToChat}
            className="bg-accent rounded-xl px-6 py-3 text-white font-medium"
          >
            Send to Chat
          </button>
          <button
            onClick={() => setTranscript('')}
            className="glass rounded-xl px-6 py-3 text-white/70 font-medium"
          >
            Clear
          </button>
        </div>
      )}
    </div>
  )
}

import { useState, useRef, useEffect } from 'react'
import { sendMessage } from '../api'
import AnimatedContent from '../components/bits/AnimatedContent'

export default function ChatView() {
  const [messages, setMessages] = useState([])
  const [inputText, setInputText] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)
  const textareaRef = useRef(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSend = async () => {
    if (!inputText.trim() || loading) return
    const userMsg = inputText.trim()
    setInputText('')
    setMessages((prev) => [...prev, { text: userMsg, isUser: true }])
    setLoading(true)

    try {
      const response = await sendMessage(userMsg)
      setMessages((prev) => [...prev, { text: response, isUser: false }])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { text: 'Sorry, I encountered an error. Please try again.', isUser: false },
      ])
    } finally {
      setLoading(false)
    }
  }

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const examples = [
    'What is the weather in Mumbai today?',
    'Will it rain in Ahmedabad this week?',
    'आज दिल्ली में मौसम कैसा है?',
  ]

  return (
    <div className="flex-1 flex flex-col h-full">
      {/* Header */}
      <div className="glass border-b border-white/10 px-4 py-3 flex items-center justify-between flex-shrink-0">
        <h1 className="text-white text-lg font-display font-semibold">WeatherGPT Chat</h1>
        <span className="text-xl">🌤️</span>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto no-scrollbar px-4 py-4">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <p className="text-white/40 text-lg mb-6">Ask me about weather in India</p>
            <div className="flex flex-col gap-2 w-full max-w-sm">
              {examples.map((ex, i) => (
                <button
                  key={i}
                  onClick={() => setInputText(ex)}
                  className="glass rounded-2xl px-4 py-3 text-white/60 text-sm text-left hover:bg-white/10 transition-colors cursor-pointer"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4 max-w-2xl mx-auto">
            {messages.map((msg, i) => (
              <AnimatedContent key={i} delay={0} direction="up">
                <div className={`flex flex-col ${msg.isUser ? 'items-end' : 'items-start'}`}>
                  {!msg.isUser && (
                    <span className="text-accent text-xs font-semibold mb-1 ml-2">
                      🌤 WeatherGPT
                    </span>
                  )}
                  <div
                    className={`px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap max-w-[85%] ${
                      msg.isUser
                        ? 'bg-accent/20 backdrop-blur border border-accent/30 rounded-3xl rounded-br-sm text-white'
                        : 'glass rounded-3xl rounded-bl-sm text-white/90'
                    }`}
                  >
                    {msg.text}
                  </div>
                </div>
              </AnimatedContent>
            ))}

            {loading && (
              <div className="flex flex-col items-start">
                <span className="text-accent text-xs font-semibold mb-1 ml-2">
                  🌤 WeatherGPT
                </span>
                <div className="glass rounded-3xl rounded-bl-sm px-4 py-3 flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="text-white/50 animate-pulse"
                      style={{ animationDelay: `${i * 0.2}s` }}
                    >
                      ●
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Bar */}
      <div className="glass border-t border-white/10 px-4 py-3 flex gap-3 items-end flex-shrink-0">
        <textarea
          ref={textareaRef}
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about weather... (English या हिंदी में)"
          rows={1}
          className="flex-1 bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-white text-sm resize-none placeholder:text-white/30 focus:outline-none focus:ring-1 focus:ring-accent/50"
        />
        <button
          onClick={handleSend}
          disabled={!inputText.trim() || loading}
          className="bg-accent rounded-xl px-4 py-2.5 text-white text-sm font-medium disabled:opacity-40 transition-opacity"
        >
          Send
        </button>
      </div>
    </div>
  )
}

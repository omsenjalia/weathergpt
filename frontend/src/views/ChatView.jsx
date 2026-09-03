import { useState, useRef, useEffect } from 'react'
import { sendMessage } from '../api'
import AnimatedContent from '../components/bits/AnimatedContent'
import { Sun, Send } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function BotMessage({ text }) {
  return (
    <div className="prose-bot">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => (
            <a {...props} target="_blank" rel="noopener noreferrer" className="text-accent underline" />
          ),
          strong: ({ node, ...props }) => (
            <strong {...props} className="font-semibold text-white" />
          ),
          h1: ({ node, ...props }) => (
            <h1 {...props} className="text-lg font-display font-bold text-white my-2" />
          ),
          h2: ({ node, ...props }) => (
            <h2 {...props} className="text-base font-display font-bold text-white my-2" />
          ),
          h3: ({ node, ...props }) => (
            <h3 {...props} className="text-sm font-display font-bold text-white my-1" />
          ),
          ul: ({ node, ...props }) => (
            <ul {...props} className="list-disc pl-5 my-1.5 space-y-1" />
          ),
          ol: ({ node, ...props }) => (
            <ol {...props} className="list-decimal pl-5 my-1.5 space-y-1" />
          ),
          li: ({ node, ...props }) => (
            <li {...props} className="leading-relaxed my-0.5" />
          ),
          table: ({ node, ...props }) => (
            <div className="overflow-x-auto my-2">
              <table {...props} className="text-xs w-full border-collapse" />
            </div>
          ),
          th: ({ node, ...props }) => (
            <th {...props} className="border border-white/15 px-2 py-1 text-accent font-semibold text-left" />
          ),
          td: ({ node, ...props }) => (
            <td {...props} className="border border-white/15 px-2 py-1 align-top" />
          ),
          code: ({ node, inline, className, children, ...props }) =>
            inline ? (
              <code {...props} className="bg-white/10 rounded px-1 py-0.5 text-xs text-emerald-300">
                {children}
              </code>
            ) : (
              <pre className="my-2 bg-black/40 rounded-xl p-3 overflow-x-auto">
                <code {...props} className="text-xs text-emerald-200">{children}</code>
              </pre>
            ),
          blockquote: ({ node, ...props }) => (
            <blockquote {...props} className="border-l-2 border-accent/50 pl-3 my-2 text-white/80" />
          ),
          hr: ({ node, ...props }) => (
            <hr {...props} className="border-white/10 my-3" />
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
}

export default function ChatView({ messages, setMessages, initialMessage = '', onVoiceProcessed }) {
  const [inputText, setInputText] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)
  const voiceHandledRef = useRef('')

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // When a voice query arrives from VoiceView, auto-send it exactly once.
  useEffect(() => {
    if (!initialMessage || initialMessage === voiceHandledRef.current) return
    voiceHandledRef.current = initialMessage

    const voiceText = initialMessage
    setMessages((prev) => [...prev, { text: voiceText, isUser: true }])
    setLoading(true)

    sendMessage(voiceText)
      .then((response) => {
        setMessages((prev) => [...prev, { text: response, isUser: false }])
      })
      .catch(() => {
        setMessages((prev) => [
          ...prev,
          { text: 'Sorry, I encountered an error. Please try again.', isUser: false },
        ])
      })
      .finally(() => {
        setLoading(false)
        onVoiceProcessed?.()
      })
  }, [initialMessage, setMessages, onVoiceProcessed])

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
      <div
        className="glass border-b border-white/10 px-4 py-3 flex items-center justify-between flex-shrink-0"
        style={{ paddingTop: 'calc(env(safe-area-inset-top, 0px) + 0.75rem)' }}
      >
        <h1 className="text-white text-lg font-display font-semibold">WeatherGPT Chat</h1>
        <Sun className="text-accent" size={20} />
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
          <div className="flex flex-col gap-4 max-w-2xl mx-auto w-full">
            {messages.map((msg, i) => (
              <AnimatedContent key={i} delay={0} direction="up">
                <div className={`flex flex-col ${msg.isUser ? 'items-end' : 'items-start'}`}>
                  {!msg.isUser && (
                    <span className="text-accent text-xs font-semibold mb-1 ml-2 flex items-center gap-1">
                      <Sun size={12} /> WeatherGPT
                    </span>
                  )}
                  <div
                    className={`px-4 py-3 text-sm leading-relaxed max-w-[92%] sm:max-w-[85%] ${
                      msg.isUser
                        ? 'bg-accent/20 backdrop-blur border border-accent/30 rounded-3xl rounded-br-sm text-white whitespace-pre-wrap'
                        : 'glass rounded-3xl rounded-bl-sm text-white/90'
                    }`}
                  >
                    {msg.isUser ? msg.text : <BotMessage text={msg.text} />}
                  </div>
                </div>
              </AnimatedContent>
            ))}

            {loading && (
              <div className="flex flex-col items-start">
                <span className="text-accent text-xs font-semibold mb-1 ml-2 flex items-center gap-1">
                  <Sun size={12} /> WeatherGPT
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
      <div className="glass border-t border-white/10 px-3 py-3 flex gap-2 items-end flex-shrink-0 safe-bottom">
        <textarea
          value={inputText}
          onChange={(e) => setInputText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about weather... (English या हिंदी में)"
          rows={1}
          className="flex-1 bg-white/5 border border-white/10 rounded-2xl px-4 py-3 text-white text-sm resize-none placeholder:text-white/30 focus:outline-none focus:ring-1 focus:ring-accent/50 max-h-32 overflow-y-auto"
        />
        <button
          onClick={handleSend}
          disabled={!inputText.trim() || loading}
          aria-label="Send message"
          className="bg-accent rounded-xl h-11 px-4 text-white text-sm font-medium disabled:opacity-40 transition-opacity flex items-center gap-1.5 cursor-pointer"
        >
          <Send size={16} />
          <span className="hidden sm:inline">Send</span>
        </button>
      </div>
    </div>
  )
}

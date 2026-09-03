import { useState, useRef, useEffect } from 'react'
import { sendMessage } from '../api'
import AnimatedContent from '../components/bits/AnimatedContent'
import { Translations } from '../utils/translations'
import { Sun, Send, ShieldAlert } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function ChatAlertWidget({ data }) {
  if (!data) return null
  const { city, level, title, advisory, action } = data
  const isRed = level === 'RED'
  const isOrange = level === 'ORANGE'
  const isYellow = level === 'YELLOW'
  const badgeBg = isRed ? '#ef4444' : isOrange ? '#f97316' : isYellow ? '#f59e0b' : '#10b981'

  return (
    <div className="glass rounded-2xl p-4 my-3 border shadow-lg text-white max-w-full" style={{ borderColor: badgeBg, background: `${badgeBg}18` }}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <ShieldAlert size={18} style={{ color: badgeBg }} />
          <span className="font-bold font-display text-sm">{title || 'Official Weather Warning'}</span>
        </div>
        <span className="text-[10px] uppercase font-bold text-white px-2 py-0.5 rounded-full" style={{ background: badgeBg }}>
          {level || 'IMD'} ALERT
        </span>
      </div>

      {city && <p className="text-xs text-white/60 mb-2">Region: {city}</p>}
      {advisory && <p className="text-xs text-white/90 leading-relaxed mb-2 font-medium">{advisory}</p>}
      {action && (
        <div className="glass rounded-xl p-2.5 mt-2 text-xs font-semibold text-white/95 flex items-center gap-2 border border-white/10">
          <span>⚡ {action}</span>
        </div>
      )}
    </div>
  )
}

function ChatWeatherWidget({ data }) {
  if (!data) return null
  const { city, temp, feelsLike, condition, humidity, windSpeed, advisory } = data
  return (
    <div className="glass rounded-2xl p-4 my-3 border border-accent/40 bg-accent/10 shadow-lg text-white max-w-full">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <Sun className="text-accent" size={18} />
          <span className="font-bold font-display text-base">{city || 'Weather Telemetry'}</span>
        </div>
        <span className="text-[10px] uppercase font-bold text-accent bg-accent/20 px-2 py-0.5 rounded-full">
          Live Card
        </span>
      </div>

      <div className="flex items-baseline gap-3 my-2">
        <span className="text-3xl font-display font-extrabold">{temp != null ? `${temp}°C` : '--'}</span>
        {condition && <span className="text-white/80 text-sm font-medium">{condition}</span>}
      </div>

      <div className="grid grid-cols-3 gap-2 pt-2 border-t border-white/10 text-center">
        {feelsLike != null && (
          <div className="glass rounded-xl p-2">
            <span className="text-[10px] text-white/50 block">Feels</span>
            <span className="text-xs font-bold text-orange-300">{feelsLike}°C</span>
          </div>
        )}
        {humidity != null && (
          <div className="glass rounded-xl p-2">
            <span className="text-[10px] text-white/50 block">Humidity</span>
            <span className="text-xs font-bold text-sky-300">{humidity}%</span>
          </div>
        )}
        {windSpeed != null && (
          <div className="glass rounded-xl p-2">
            <span className="text-[10px] text-white/50 block">Wind</span>
            <span className="text-xs font-bold text-emerald-300">{windSpeed} km/h</span>
          </div>
        )}
      </div>

      {advisory && (
        <p className="text-xs text-accent/90 mt-2.5 pt-2 border-t border-white/10 font-medium">
          💡 {advisory}
        </p>
      )}
    </div>
  )
}

function ChatForecastWidget({ data }) {
  if (!data || !Array.isArray(data.days)) return null
  return (
    <div className="glass rounded-2xl p-4 my-3 border border-white/15 shadow-lg text-white max-w-full">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-bold uppercase tracking-wider text-accent flex items-center gap-1">
          <Sun size={14} /> {data.city ? `${data.city} Forecast` : 'Weather Forecast'}
        </span>
        <span className="text-[10px] text-white/40">{data.days.length} Days</span>
      </div>

      <div className="flex gap-2.5 overflow-x-auto no-scrollbar pb-1">
        {data.days.map((d, i) => (
          <div key={i} className="flex-shrink-0 glass rounded-xl p-2.5 text-center min-w-[75px] border border-white/10">
            <p className="text-[11px] text-white/60 font-semibold mb-1">{d.day}</p>
            <p className="text-sm font-bold text-white mb-0.5">{d.temp != null ? `${d.temp}°` : '--'}</p>
            <p className="text-[10px] text-white/70 truncate max-w-[70px]">{d.condition}</p>
            {d.rainProb > 0 && <p className="text-[9px] text-sky-300 font-semibold mt-1">{d.rainProb}% rain</p>}
          </div>
        ))}
      </div>
    </div>
  )
}

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
          code: ({ node, inline, className, children, ...props }) => {
            const rawStr = String(children).trim()
            const match = /widget:(weather|forecast|alert)/.exec(className || '') || /widget:(weather|forecast|alert)/.exec(rawStr)
            
            if (!inline && match) {
              try {
                const cleanedJson = rawStr.replace(/^widget:(weather|forecast|alert)/, '').trim()
                const parsedData = JSON.parse(cleanedJson)
                if (match[1] === 'weather') return <ChatWeatherWidget data={parsedData} />
                if (match[1] === 'forecast') return <ChatForecastWidget data={parsedData} />
                if (match[1] === 'alert') return <ChatAlertWidget data={parsedData} />
              } catch (err) {
                // Fall back if JSON parsing fails
              }
            }

            return inline ? (
              <code {...props} className="bg-white/10 rounded px-1 py-0.5 text-xs text-emerald-300">
                {children}
              </code>
            ) : (
              <pre className="my-2 bg-black/40 rounded-xl p-3 overflow-x-auto">
                <code {...props} className="text-xs text-emerald-200">{children}</code>
              </pre>
            )
          },
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

export default function ChatView({ messages, setMessages, initialMessage = '', onVoiceProcessed, location, language }) {
  const [inputText, setInputText] = useState('')
  const [loading, setLoading] = useState(false)
  const messagesEndRef = useRef(null)
  const voiceHandledRef = useRef('')

  const locationContext = location?.name ? `${location.name}${location.country ? `, ${location.country}` : ''}` : ''
  const languageName = language?.name || 'English'

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  // When a voice query arrives from VoiceView, auto-send it exactly once with full context
  useEffect(() => {
    if (!initialMessage || initialMessage === voiceHandledRef.current) return
    voiceHandledRef.current = initialMessage

    const voiceText = initialMessage
    const updatedMessages = [...messages, { text: voiceText, isUser: true }]
    setMessages(updatedMessages)
    setLoading(true)

    sendMessage(updatedMessages, locationContext, languageName)
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
  }, [initialMessage])

  const handleSend = async (overrideText = null) => {
    const textToSend = typeof overrideText === 'string' ? overrideText : inputText
    if (!textToSend.trim() || loading) return

    const userMsg = textToSend.trim()
    if (typeof overrideText !== 'string') {
      setInputText('')
    }
    const updatedHistory = [...messages, { text: userMsg, isUser: true }]
    setMessages(updatedHistory)
    setLoading(true)

    try {
      const response = await sendMessage(updatedHistory, locationContext, languageName)
      setMessages((prev) => [...prev, { text: response, isUser: false }])
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { text: 'Sorry, I encountered an error fetching weather context. Please try again.', isUser: false },
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
    { title: 'Mumbai Weather Today', text: 'What is the weather in Mumbai today?' },
    { title: 'Rain Prediction', text: 'Will it rain in Ahmedabad this week?' },
    { title: 'दिल्ली में मौसम (Hindi)', text: 'आज दिल्ली में मौसम कैसा है?' },
    { title: 'Travel Advice', text: 'Should I pack warm clothes for Shimla tomorrow?' },
  ]

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden">
      {/* Messages Scroll Area */}
      <div className="flex-1 overflow-y-auto no-scrollbar p-4 md:p-6">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center min-h-[70vh] text-center max-w-xl mx-auto">
            <div className="w-14 h-14 rounded-2xl bg-accent/20 border border-accent/40 flex items-center justify-center mb-4">
              <Sun className="text-accent" size={28} />
            </div>
            <h2 className="text-2xl md:text-3xl font-display font-bold text-white mb-2">
              Hello! Where are we checking the weather?
            </h2>
            <p className="text-white/60 text-sm md:text-base mb-8 max-w-md">
              Ask about current conditions, 7-day forecasts, rain predictions, or travel recommendations across India in any language.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full">
              {examples.map((ex, i) => (
                <button
                  key={i}
                  onClick={() => handleSend(ex.text)}
                  className="glass rounded-2xl p-4 text-left hover:bg-white/15 transition-all duration-200 cursor-pointer group border border-white/10"
                >
                  <p className="text-accent text-xs font-semibold mb-1 group-hover:underline">{ex.title}</p>
                  <p className="text-white/80 text-sm leading-snug">{ex.text}</p>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-5 max-w-3xl mx-auto w-full pb-4">
            {messages.map((msg, i) => (
              <AnimatedContent key={i} delay={0} direction="up">
                <div className={`flex flex-col ${msg.isUser ? 'items-end' : 'items-start'}`}>
                  {!msg.isUser && (
                    <div className="flex items-center gap-1.5 text-accent text-xs font-semibold mb-1.5 ml-1">
                      <div className="w-5 h-5 rounded-md bg-accent/20 flex items-center justify-center">
                        <Sun size={12} className="text-accent" />
                      </div>
                      <span>WeatherGPT</span>
                    </div>
                  )}
                  <div
                    className={`px-4 py-3 md:px-5 md:py-3.5 text-sm md:text-base leading-relaxed ${
                      msg.isUser
                        ? 'bg-accent/25 backdrop-blur border border-accent/40 rounded-3xl rounded-br-md text-white shadow-sm whitespace-pre-wrap max-w-[88%] sm:max-w-[80%]'
                        : 'glass rounded-3xl rounded-bl-md text-white/95 max-w-[95%] sm:max-w-[90%] shadow-lg'
                    }`}
                  >
                    {msg.isUser ? msg.text : <BotMessage text={msg.text} />}
                  </div>
                </div>
              </AnimatedContent>
            ))}

            {loading && (
              <div className="flex flex-col items-start">
                <div className="flex items-center gap-1.5 text-accent text-xs font-semibold mb-1.5 ml-1">
                  <div className="w-5 h-5 rounded-md bg-accent/20 flex items-center justify-center">
                    <Sun size={12} className="text-accent" />
                  </div>
                  <span>WeatherGPT is thinking...</span>
                </div>
                <div className="glass rounded-3xl rounded-bl-md px-5 py-3.5 flex gap-1.5 items-center">
                  {[0, 1, 2].map((i) => (
                    <span
                      key={i}
                      className="w-2 h-2 rounded-full bg-accent/80 animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Dock */}
      <div className="px-4 pb-4 pt-2 flex-shrink-0">
        <div className="max-w-3xl mx-auto glass rounded-3xl p-2 border border-white/15 shadow-2xl flex gap-2 items-center">
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={Translations.get(language?.code, 'chatPlaceholder')}
            rows={1}
            className="flex-1 bg-transparent px-4 py-2.5 text-white text-sm md:text-base resize-none placeholder:text-white/40 focus:outline-none max-h-32 overflow-y-auto"
          />
          <button
            onClick={() => handleSend()}
            disabled={!inputText.trim() || loading}
            aria-label="Send message"
            className="bg-accent hover:bg-accent/90 rounded-2xl h-11 px-5 text-white text-sm font-semibold disabled:opacity-30 transition-all flex items-center gap-2 cursor-pointer shadow-md flex-shrink-0"
          >
            <Send size={16} />
            <span className="hidden sm:inline">{Translations.get(language?.code, 'send')}</span>
          </button>
        </div>
      </div>
    </div>
  )
}

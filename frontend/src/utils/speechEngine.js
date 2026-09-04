// Browser Web Speech API Utility for Text-to-Speech (TTS)

let currentUtterance = null

const LOCALE_MAP = {
  en: 'en-IN',
  hi: 'hi-IN',
  gu: 'gu-IN',
  mr: 'mr-IN',
  ta: 'ta-IN',
  te: 'te-IN',
  bn: 'bn-IN',
  kn: 'kn-IN',
  ml: 'ml-IN',
  pa: 'pa-IN',
}

export function cleanTextForSpeech(rawMarkdown) {
  if (!rawMarkdown) return ''
  return rawMarkdown
    // Remove JSON widget blocks
    .replace(/```widget:(weather|forecast|alert)[\s\S]*?```/gi, '')
    // Remove general code blocks
    .replace(/```[\s\S]*?```/g, '')
    // Remove inline code ticks
    .replace(/`([^`]+)`/g, '$1')
    // Remove markdown headings
    .replace(/#+\s?/g, '')
    // Remove bold and italic formatting
    .replace(/[*_]{1,3}([^*_]+)[*_]{1,3}/g, '$1')
    // Remove markdown links
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    // Remove list bullet symbols
    .replace(/^[-*+]\s+/gm, '')
    .trim()
}

export function speakText(text, langCode = 'en', onStateChange) {
  if (!('speechSynthesis' in window)) {
    alert('Web Speech API is not supported in this browser.')
    return false
  }

  // If already speaking, stop and return
  if (window.speechSynthesis.speaking) {
    window.speechSynthesis.cancel()
    if (currentUtterance === text) {
      currentUtterance = null
      onStateChange?.(false)
      return false
    }
  }

  const printableText = cleanTextForSpeech(text)
  if (!printableText) return false

  const utterance = new SpeechSynthesisUtterance(printableText)
  const localeTag = LOCALE_MAP[langCode] || 'en-IN'
  utterance.lang = localeTag
  utterance.rate = 0.95
  utterance.pitch = 1.0

  currentUtterance = text

  utterance.onstart = () => {
    onStateChange?.(true)
  }

  utterance.onend = () => {
    currentUtterance = null
    onStateChange?.(false)
  }

  utterance.onerror = (e) => {
    console.warn('TTS error:', e)
    currentUtterance = null
    onStateChange?.(false)
  }

  window.speechSynthesis.speak(utterance)
  return true
}

export function stopSpeech() {
  if ('speechSynthesis' in window) {
    window.speechSynthesis.cancel()
  }
}

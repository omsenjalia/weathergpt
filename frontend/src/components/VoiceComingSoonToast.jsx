import { useState, useEffect } from 'react'
import { Mic } from 'lucide-react'

export default function VoiceComingSoonToast({ show, onClose }) {
  const [phase, setPhase] = useState('enter') // 'enter' | 'exit' | 'hidden'

  useEffect(() => {
    if (show) {
      setPhase('enter')
      const timer = setTimeout(() => {
        setPhase('exit')
        setTimeout(() => {
          onClose()
          setPhase('hidden')
        }, 250)
      }, 2500)
      return () => clearTimeout(timer)
    } else {
      setPhase('hidden')
    }
  }, [show, onClose])

  if (phase === 'hidden' && !show) return null

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center pointer-events-none">
      <div
        className={`pointer-events-auto ${phase === 'exit' ? 'toast-exit' : 'toast-enter'}`}
      >
        <div className="bg-neutral-900 border border-white/15 rounded-xl px-5 py-4 shadow-2xl flex items-center gap-3 max-w-xs">
          <div className="w-10 h-10 rounded-full bg-accent/20 border border-accent/30 flex items-center justify-center flex-shrink-0">
            <Mic size={20} className="text-accent" />
          </div>
          <div>
            <p className="text-white text-sm font-semibold">Voice Mode</p>
            <p className="text-white/50 text-xs">Coming soon! Stay tuned 🎙️</p>
          </div>
        </div>
      </div>
    </div>
  )
}

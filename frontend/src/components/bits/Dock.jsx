import { useRef } from 'react'
import { motion, useMotionValue, useTransform, useSpring } from 'framer-motion'

// Each item must be its own component so hooks run at the top level,
// not inside a .map() callback (which violates the Rules of Hooks).
function DockItem({ item, mouseX, activeId }) {
  const ref = useRef(null)
  const Icon = item.icon

  const distance = useTransform(mouseX, (val) => {
    if (!ref.current) return 150
    const rect = ref.current.getBoundingClientRect()
    const center = rect.left + rect.width / 2
    return Math.abs(val - center)
  })

  const widthSync = useTransform(distance, [0, 150], [64, 50])
  const width = useSpring(widthSync, { mass: 0.1, stiffness: 400, damping: 25 })

  const isActive = activeId === item.id

  return (
    <motion.button
      ref={ref}
      id={`dock-item-${item.id}`}
      onClick={() => item.onClick(item.id)}
      aria-label={item.label}
      className={`flex flex-col items-center justify-center rounded-2xl transition-colors touch-target ${
        isActive ? 'bg-accent/20 ring-2 ring-accent' : 'hover:bg-white/10'
      }`}
      style={{ width, height: width, minWidth: 44, minHeight: 44 }}
      whileTap={{ scale: 0.95 }}
    >
      <Icon className={isActive ? 'text-accent' : 'text-white/80'} size={22} />
      <span className="text-[9px] text-white/60 mt-1 leading-none">{item.label}</span>
    </motion.button>
  )
}

export default function Dock({ items, activeId }) {
  const mouseX = useMotionValue(Infinity)

  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 md:hidden safe-bottom">
      <motion.div
        className="glass rounded-full px-3 py-2.5 flex items-center gap-1.5"
        onMouseMove={(e) => mouseX.set(e.pageX)}
        onMouseLeave={() => mouseX.set(Infinity)}
      >
        {items.map((item) => (
          <DockItem key={item.id} item={item} mouseX={mouseX} activeId={activeId} />
        ))}
      </motion.div>
    </div>
  )
}

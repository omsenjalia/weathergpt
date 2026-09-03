import { useRef } from 'react'
import { motion, useMotionValue, useTransform, useSpring } from 'framer-motion'

// Each item must be its own component so hooks run at the top level,
// not inside a .map() callback (which violates the Rules of Hooks).
function DockItem({ item, mouseX, activeId }) {
  const ref = useRef(null)

  const distance = useTransform(mouseX, (val) => {
    if (!ref.current) return 150
    const rect = ref.current.getBoundingClientRect()
    const center = rect.left + rect.width / 2
    return Math.abs(val - center)
  })

  const widthSync = useTransform(distance, [0, 150], [56, 48])
  const width = useSpring(widthSync, { mass: 0.1, stiffness: 400, damping: 25 })

  const isActive = activeId === item.id

  return (
    <motion.button
      ref={ref}
      id={`dock-item-${item.id}`}
      onClick={() => item.onClick(item.id)}
      className={`flex flex-col items-center justify-center rounded-2xl transition-colors ${
        isActive ? 'bg-accent/20 ring-2 ring-accent' : 'hover:bg-white/10'
      }`}
      style={{ width, height: width }}
      whileTap={{ scale: 0.95 }}
    >
      <span className="text-2xl leading-none">{item.icon}</span>
      <span className="text-[9px] text-white/60 mt-1 leading-none">{item.label}</span>
    </motion.button>
  )
}

export default function Dock({ items, activeId }) {
  const mouseX = useMotionValue(Infinity)

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 md:hidden">
      <motion.div
        className="glass rounded-full px-4 py-3 flex items-center gap-2"
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

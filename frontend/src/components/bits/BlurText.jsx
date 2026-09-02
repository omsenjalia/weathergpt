import { motion, useInView } from 'framer-motion'
import { useRef } from 'react'

export default function BlurText({ text, className = '', delay = 0, once = true }) {
  const ref = useRef(null)
  const isInView = useInView(ref, { once })
  const words = text.split(' ')

  return (
    <span ref={ref} className={`inline-block ${className}`}>
      {words.map((word, i) => (
        <motion.span
          key={i}
          className="inline-block"
          initial={{ filter: 'blur(12px)', opacity: 0, y: 8 }}
          animate={isInView ? { filter: 'blur(0px)', opacity: 1, y: 0 } : {}}
          transition={{
            duration: 0.6,
            delay: i * 0.08 + delay / 1000,
            ease: [0.22, 1, 0.36, 1],
          }}
        >
          {word}
          {i < words.length - 1 && '\u00A0'}
        </motion.span>
      ))}
    </span>
  )
}

import { motion } from 'framer-motion'

export default function AnimatedContent({
  children,
  delay = 0,
  direction = 'up',
  distance = 24,
  className = '',
}) {
  const getInitial = () => {
    const base = { opacity: 0 }
    if (direction === 'up') base.y = distance
    else if (direction === 'down') base.y = -distance
    else if (direction === 'left') base.x = distance
    else if (direction === 'right') base.x = -distance
    return base
  }

  return (
    <motion.div
      initial={getInitial()}
      animate={{ opacity: 1, y: 0, x: 0 }}
      transition={{
        duration: 0.7,
        delay,
        ease: [0.22, 1, 0.36, 1],
      }}
      className={className}
    >
      {children}
    </motion.div>
  )
}

import { motion } from 'framer-motion'

export default function Aurora() {
  return (
    <div className="fixed inset-0 z-[-1] overflow-hidden">
      <div
        className="absolute inset-0"
        style={{
          background: 'radial-gradient(ellipse at 50% 50%, #2d1b69 0%, #1a0a2e 40%, #0d0b1a 100%)',
        }}
      />

      <motion.div
        className="absolute w-96 h-96 rounded-full"
        style={{
          top: '25%',
          left: '25%',
          background: 'radial-gradient(circle, #7c3aed 0%, transparent 70%)',
          opacity: 0.4,
        }}
        animate={{
          scale: [1, 1.2, 1],
          x: [0, 30, 0],
          opacity: [0.3, 0.5, 0.3],
        }}
        transition={{
          duration: 10,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      />

      <motion.div
        className="absolute w-80 h-80 rounded-full"
        style={{
          bottom: '25%',
          right: '25%',
          background: 'radial-gradient(circle, #4c1d95 0%, transparent 70%)',
          opacity: 0.3,
        }}
        animate={{
          scale: [1, 1.2, 1],
          x: [0, 30, 0],
          opacity: [0.3, 0.5, 0.3],
        }}
        transition={{
          duration: 12,
          repeat: Infinity,
          ease: 'easeInOut',
          delay: 2,
        }}
      />

      <motion.div
        className="absolute w-64 h-64 rounded-full"
        style={{
          top: '50%',
          right: '33%',
          background: 'radial-gradient(circle, #6d28d9 0%, transparent 70%)',
          opacity: 0.2,
        }}
        animate={{
          scale: [1, 1.2, 1],
          x: [0, 30, 0],
          opacity: [0.3, 0.5, 0.3],
        }}
        transition={{
          duration: 8,
          repeat: Infinity,
          ease: 'easeInOut',
          delay: 4,
        }}
      />

      <div
        className="absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`,
          backgroundRepeat: 'repeat',
          backgroundSize: '128px 128px',
        }}
      />
    </div>
  )
}

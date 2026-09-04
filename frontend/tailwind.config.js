export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        display: ['Playfair Display', 'Georgia', 'serif'],
        bricolage: ['Bricolage Grotesque', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        handwritten: ['Caveat', 'cursive', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        accent: '#f59e0b',
        'accent-dim': '#d97706',
        'accent-light': '#fbbf24',
      },
      backdropBlur: {
        glass: '20px',
      },
      backgroundColor: {
        'neutral-950': '#0a0a0c',
      },
    },
  },
  plugins: [],
}

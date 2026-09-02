export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ['Syne', 'sans-serif'],
        body: ['DM Sans', 'sans-serif'],
      },
      colors: {
        accent: '#a78bfa',
        'accent-dim': '#7c3aed',
      },
      backdropBlur: {
        glass: '20px',
      }
    },
  },
  plugins: [],
}

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      keyframes: {
        'toast-countdown': {
          from: { width: '100%' },
          to: { width: '0%' },
        },
      },
      animation: {
        'toast-countdown': 'toast-countdown 8s linear forwards',
      },
    },
  },
  plugins: [],
}

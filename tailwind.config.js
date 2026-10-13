/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        theme: {
          bg: '#080d0b',
          dark: '#0c1310',
          card: '#111a16',
          cardHover: '#16231d',
          border: '#1c2d25',
          borderLight: '#263d32',
          lime: '#b5f542',
          limeHover: '#c5fb5a',
          limeGlow: '#d4ff70',
          emerald: '#10b981',
          emeraldLight: '#34d399',
          rose: '#ff5c5c',
          textMain: '#ffffff',
          textMuted: '#7f9389',
          textDark: '#4b5b53',
        },
      },
      fontFamily: {
        sans: ['var(--font-sans)', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['var(--font-mono)', 'JetBrains Mono', 'Fira Code', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'ping-slow': 'ping 2s cubic-bezier(0, 0, 0.2, 1) infinite',
      },
    },
  },
  plugins: [],
};

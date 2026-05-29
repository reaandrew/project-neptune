/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Pulled verbatim from andrewreaassociates.com so this app
        // sits inside the consultancy's existing brand system.
        ink: {
          950: '#080c16',  // deepest page background
          900: '#0f172a',  // panel surface
          800: '#1e293b',  // panel border / inset
          700: '#334155',  // muted lines
        },
        brand: {
          DEFAULT: '#0891b2',  // primary cyan
          bright: '#22d3ee',   // hover / highlight
          dim:    '#0e7490',   // pressed / muted
        },
      },
      fontFamily: {
        sans: ['"Inter"', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        display: ['"Inter"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      letterSpacing: {
        widest2: '0.18em',
      },
    },
  },
  plugins: [],
};

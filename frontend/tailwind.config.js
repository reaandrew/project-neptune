/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Editorial palette — warm paper + muted ink, with a strong
        // accent. Aims for the same "brand book cover" feel as the PDF
        // (big display type on a coloured panel).
        paper: {
          DEFAULT: '#F5F2EC',  // cover-page neutral
          dark: '#EDE9DF',     // hover / inset surfaces
        },
        ink: {
          900: '#111111',      // primary text
          700: '#3A3A3A',
          500: '#6B6B6B',      // secondary text
          300: '#B5B0A5',      // tertiary / borders
        },
        accent: {
          DEFAULT: '#0F4C3A',  // deep forest — matches editorial feel
          soft: '#E8EFE9',     // pale accent wash
        },
      },
      fontFamily: {
        display: ['"Instrument Serif"', 'Georgia', 'ui-serif', 'serif'],
        sans: ['"Inter"', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      letterSpacing: {
        tightest: '-0.04em',
      },
    },
  },
  plugins: [],
};

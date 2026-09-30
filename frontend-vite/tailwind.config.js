/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Instrument Sans"', "Inter", "system-ui", "sans-serif"],
        serif: ['"Instrument Serif"', "Georgia", "serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        ink: {
          50: "#f4f5f7",
          100: "#e8eaee",
          400: "#8b93a7",
          500: "#6b7388",
          700: "#3a4052",
          800: "#1c2030",
          900: "#10131c",
          950: "#08090e",
        },
        gold: {
          50: "#fbf7ef",
          100: "#f3ead6",
          300: "#e2c890",
          400: "#d4b06a",
          500: "#c49a4a",
          600: "#a67d32",
        },
      },
      boxShadow: {
        panel:
          "0 1px 0 rgba(255,255,255,0.04) inset, 0 24px 80px -32px rgba(0,0,0,0.55)",
        "panel-light":
          "0 1px 0 rgba(255,255,255,0.8) inset, 0 18px 50px -28px rgba(16,19,28,0.18)",
        glow: "0 0 0 1px rgba(212,176,106,0.18), 0 12px 40px -18px rgba(196,154,74,0.45)",
      },
      letterSpacing: {
        kicker: "0.22em",
      },
      backgroundImage: {
        grain:
          "radial-gradient(1200px 600px at 12% -10%, rgba(212,176,106,0.09), transparent 50%), radial-gradient(900px 500px at 110% 110%, rgba(90,110,160,0.12), transparent 45%)",
      },
    },
  },
  plugins: [],
};

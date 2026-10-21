/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter"', '"Instrument Sans"', "ui-sans-serif", "system-ui", "sans-serif"],
        serif: ['"Instrument Serif"', "Georgia", "serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      colors: {
        /* Brand palette sampled from the Blupace Tech logo */
        brand: {
          indigo: "#3954A5",
          azure: "#0089CD",
          lime: "#B4D435",
        },
        /* Neutral ink scale (cool navy greys) */
        ink: {
          50: "#f4f7fb",
          100: "#e8eef6",
          200: "#d5dfec",
          400: "#8b97ab",
          500: "#5b6b82",
          600: "#46566c",
          700: "#33445c",
          800: "#1e2e44",
          900: "#122032",
          950: "#0a1626",
        },
        /* Former gold accent now carries the brand azure/indigo */
        gold: {
          50: "#eef7fd",
          100: "#d9edfa",
          200: "#b6ddf4",
          300: "#7cc4ea",
          400: "#39a6dc",
          500: "#0089CD",
          600: "#006fa8",
        },
      },
      boxShadow: {
        panel:
          "0 1px 0 rgba(255,255,255,0.04) inset, 0 20px 60px -28px rgba(0,0,0,0.5)",
        "panel-light":
          "0 1px 0 rgba(255,255,255,0.8) inset, 0 16px 44px -26px rgba(16,26,43,0.16)",
        glow: "0 0 0 1px rgba(0,137,205,0.18), 0 12px 40px -18px rgba(0,137,205,0.4)",
      },
      letterSpacing: {
        kicker: "0.2em",
      },
      backgroundImage: {
        grain:
          "radial-gradient(1200px 600px at 12% -10%, rgba(0,137,205,0.08), transparent 50%), radial-gradient(900px 500px at 110% 110%, rgba(57,84,165,0.10), transparent 45%)",
      },
    },
  },
  plugins: [],
};

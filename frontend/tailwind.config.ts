import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "Segoe UI",
          "sans-serif"
        ]
      },
      colors: {
        surface: {
          base: "#0f172a",
          sunken: "#0b1220",
          raised: "#16213b"
        },
        brand: {
          primary: "#38bdf8",
          secondary: "#818cf8"
        }
      },
      boxShadow: {
        inset: "inset 0 1px 0 0 rgba(255,255,255,0.04)",
        glow: "0 0 24px rgba(56,189,248,0.25)"
      },
      borderRadius: {
        xl: "1.25rem"
      }
    }
  },
  plugins: []
};

export default config;

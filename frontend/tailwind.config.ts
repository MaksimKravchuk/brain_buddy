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
          base: "#f8fafc",
          sunken: "#f1f5f9",
          raised: "#ffffff"
        },
        brand: {
          primary: "#0ea5e9",
          secondary: "#6366f1"
        }
      },
      boxShadow: {
        inset: "inset 0 1px 0 0 rgba(15,23,42,0.08)",
        glow: "0 16px 32px rgba(14,165,233,0.18)"
      },
      borderRadius: {
        xl: "1.25rem"
      },
      keyframes: {
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" }
        },
        "fade-out": {
          "0%": { opacity: "1" },
          "100%": { opacity: "0" }
        },
        "slide-down-fade-in": {
          "0%": { opacity: "0", transform: "translateY(-8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        },
        "slide-up-fade-out": {
          "0%": { opacity: "1", transform: "translateY(0)" },
          "100%": { opacity: "0", transform: "translateY(-8px)" }
        },
        "scale-fade-in": {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" }
        }
      },
      animation: {
        "fade-in": "fade-in 200ms ease-out",
        "fade-out": "fade-out 150ms ease-in forwards",
        "slide-down-fade-in": "slide-down-fade-in 250ms ease-out",
        "slide-up-fade-out": "slide-up-fade-out 200ms ease-in forwards",
        "scale-fade-in": "scale-fade-in 200ms ease-out"
      }
    }
  },
  plugins: []
};

export default config;

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
      }
    }
  },
  plugins: []
};

export default config;

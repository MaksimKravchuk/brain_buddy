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
      fontSize: {
        // Type scale (size, line-height, letter-spacing)
        display: ["1.75rem", { lineHeight: "1.15", letterSpacing: "-0.02em" }],
        title: ["1.25rem", { lineHeight: "1.3", letterSpacing: "-0.015em" }],
        subtitle: ["0.9375rem", { lineHeight: "1.4", letterSpacing: "-0.005em" }]
      },
      colors: {
        surface: {
          base: "#f8fafc",
          sunken: "#f1f5f9",
          raised: "#ffffff"
        },
        brand: {
          primary: "#0ea5e9",
          "primary-hover": "#38bdf8",
          secondary: "#6366f1"
        },
        node: {
          "leaf-bg": "#ef4444",
          "leaf-fg": "#ffffff",
          "root-bg": "#facc15",
          "root-fg": "#1f2937",
          "default-bg": "#ffffff",
          "default-fg": "#0f172a"
        },
        info: {
          DEFAULT: "#0ea5e9",
          bg: "#f0f9ff",
          border: "#bae6fd",
          fg: "#0369a1"
        },
        // AI & task-state aliases (post-pivot). emerald = AI executing a task
        // (Sparkles); sky = thinking canvas (Network). Never mix the two meanings.
        ai: {
          DEFAULT: "#10b981",
          bg: "#ecfdf5",
          border: "#a7f3d0",
          fg: "#047857"
        },
        agent: {
          "avatar-bg": "#ecfdf5",
          "avatar-fg": "#047857"
        },
        "needs-you": {
          DEFAULT: "#d97706",
          bg: "#fffbeb",
          border: "#fde68a",
          fg: "#92400e"
        },
        thinking: {
          DEFAULT: "#0ea5e9",
          bg: "#f0f9ff",
          border: "#bae6fd",
          fg: "#0369a1"
        },
        due: {
          bg: "#fff1f2",
          border: "#fecdd3",
          fg: "#be123c"
        },
        recording: "#e11d48",
        context: {
          bg: "#f1f5f9",
          fg: "#475569"
        }
      },
      boxShadow: {
        inset: "inset 0 1px 0 0 rgba(15,23,42,0.08)",
        soft: "0 1px 2px rgba(15,23,42,0.04), 0 1px 1px rgba(15,23,42,0.03)",
        raised:
          "0 1px 2px rgba(15,23,42,0.05), 0 8px 24px -12px rgba(15,23,42,0.12)",
        floating:
          "0 1px 2px rgba(15,23,42,0.04), 0 12px 32px -16px rgba(15,23,42,0.18)",
        glow: "0 16px 32px rgba(14,165,233,0.18)",
        "ring-focus":
          "0 0 0 2px #ffffff, 0 0 0 4px rgba(14,165,233,0.5)"
      },
      borderRadius: {
        xl: "1.25rem"
      },
      transitionTimingFunction: {
        smooth: "cubic-bezier(0.22, 1, 0.36, 1)"
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
        "fade-in-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        },
        "fade-in-down": {
          "0%": { opacity: "0", transform: "translateY(-6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        },
        "fade-out-down": {
          "0%": { opacity: "1", transform: "translateY(0)" },
          "100%": { opacity: "0", transform: "translateY(6px)" }
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
          "0%": { opacity: "0", transform: "scale(0.96)" },
          "100%": { opacity: "1", transform: "scale(1)" }
        },
        "scale-fade-out": {
          "0%": { opacity: "1", transform: "scale(1)" },
          "100%": { opacity: "0", transform: "scale(0.96)" }
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" }
        },
        "detail-enter": {
          "0%": { opacity: "0", transform: "translateY(-4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" }
        }
      },
      animation: {
        "fade-in": "fade-in 200ms cubic-bezier(0.22, 1, 0.36, 1)",
        "fade-out": "fade-out 150ms cubic-bezier(0.4, 0, 1, 1) forwards",
        "fade-in-up": "fade-in-up 220ms cubic-bezier(0.22, 1, 0.36, 1)",
        "fade-in-down": "fade-in-down 220ms cubic-bezier(0.22, 1, 0.36, 1)",
        "fade-out-down":
          "fade-out-down 180ms cubic-bezier(0.4, 0, 1, 1) forwards",
        "slide-down-fade-in":
          "slide-down-fade-in 250ms cubic-bezier(0.22, 1, 0.36, 1)",
        "slide-up-fade-out":
          "slide-up-fade-out 200ms cubic-bezier(0.4, 0, 1, 1) forwards",
        "scale-fade-in":
          "scale-fade-in 200ms cubic-bezier(0.22, 1, 0.36, 1)",
        "scale-fade-out":
          "scale-fade-out 180ms cubic-bezier(0.4, 0, 1, 1) forwards",
        shimmer: "shimmer 1500ms linear infinite",
        "detail-enter": "detail-enter 250ms cubic-bezier(0.22, 1, 0.36, 1)"
      }
    }
  },
  plugins: []
};

export default config;

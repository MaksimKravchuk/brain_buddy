/**
 * Brain Buddy design tokens.
 *
 * Direct translation of the design-system source of truth:
 * `.claude/skills/brain-buddy-design/colors_and_type.css`.
 * Do not invent values here — change the CSS source first, then mirror it.
 */

export const colors = {
  // Brand
  brandPrimary: "#0EA5E9", // sky-500 — interactive accents, mic, primary buttons
  brandPrimaryHover: "#38BDF8", // sky-400 — primary hovers lighter
  brandPrimarySoft: "rgba(14, 165, 233, 0.10)",
  brandSecondary: "#6366F1", // indigo-500 — sparing secondary accents

  // Surfaces
  surfaceBase: "#F8FAFC", // slate-50 — page background, always flat
  surfaceSunken: "#F1F5F9", // slate-100 — panel bg
  surfaceRaised: "#FFFFFF", // cards, dialogs

  // Foreground (slate scale)
  fg1: "#0F172A", // slate-900 — primary body
  fg2: "#1E293B", // slate-800
  fg3: "#334155", // slate-700
  fg4: "#475569", // slate-600
  fg5: "#64748B", // slate-500 — secondary/caption
  fg6: "#94A3B8", // slate-400 — placeholder
  fg7: "#CBD5E1", // slate-300

  // Borders
  border: "#E2E8F0", // slate-200 universal hairline
  borderHover: "#CBD5E1", // slate-300

  // Semantics
  success: "#10B981", // emerald-500
  successBg: "#ECFDF5",
  successBorder: "#A7F3D0",
  successFg: "#065F46",

  warning: "#D97706", // amber-600
  warningBg: "#FFFBEB",
  warningBorder: "#FDE68A",
  warningFg: "#92400E",

  danger: "#E11D48", // rose-600
  dangerBg: "#FFF1F2",
  dangerBorder: "#FECDD3",
  dangerFg: "#9F1239",

  info: "#0EA5E9",
  infoBg: "#F0F9FF",
  infoBorder: "#BAE6FD",
  infoFg: "#0369A1",

  // Due date chips (rose family, distinct fg from danger)
  dueBg: "#FFF1F2",
  dueBorder: "#FECDD3",
  dueFg: "#BE123C",

  // Recording indicator
  recording: "#E11D48",

  // Tag pills in task rows
  tagBg: "#F1F5F9",
  tagFg: "#475569",

  // Selection / focus
  selectionBg: "rgba(14, 165, 233, 0.22)",
  focusRing: "rgba(14, 165, 233, 0.5)",
} as const;

export const radii = {
  sm: 6, // inputs, menu items
  md: 8, // buttons, chips-as-buttons
  row: 12, // task rows (desktop reference)
  card: 14, // mobile task cards (per iOS design)
  lg: 16, // node shell, auth card
  xl: 20, // dialogs, panels, toasts
  full: 999,
} as const;

/** 4-pt spacing scale. */
export const space = {
  s1: 4,
  s2: 8,
  s3: 12,
  s4: 16,
  s5: 20,
  s6: 24,
  s8: 32,
} as const;

export const type = {
  label: 10, // UPPERCASE section labels only
  micro: 11, // inline metadata
  caption: 12,
  body: 14, // UI default
  subtitle: 15,
  bodyLg: 16,
  title: 20, // dialog + pane titles
  display: 28, // empty states
} as const;

export const tracking = {
  display: -0.02 * type.display,
  title: -0.015 * type.title,
  subtitle: -0.005 * type.subtitle,
  label: 0.06 * type.label,
} as const;

export const weights = {
  regular: "400",
  medium: "500",
  semibold: "600",
  bold: "700",
} as const;

/** Inter, loaded via @expo-google-fonts/inter in the root layout. */
export const fonts = {
  regular: "Inter_400Regular",
  medium: "Inter_500Medium",
  semibold: "Inter_600SemiBold",
  bold: "Inter_700Bold",
} as const;

export const durations = {
  quick: 150,
  base: 200,
  settle: 250,
} as const;

/** Signature easing — soft arrival, no overshoot: cubic-bezier(0.22, 1, 0.36, 1). */
export const easeSmoothBezier = [0.22, 1, 0.36, 1] as const;

/** Minimum hit target per the iOS design (44px+). */
export const minHitTarget = 44;

export const shadows = {
  soft: {
    shadowColor: "#0F172A",
    shadowOpacity: 0.04,
    shadowRadius: 2,
    shadowOffset: { width: 0, height: 1 },
    elevation: 1,
  },
  raised: {
    shadowColor: "#0F172A",
    shadowOpacity: 0.12,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 8 },
    elevation: 4,
  },
  floating: {
    shadowColor: "#0F172A",
    shadowOpacity: 0.18,
    shadowRadius: 32,
    shadowOffset: { width: 0, height: 12 },
    elevation: 8,
  },
} as const;

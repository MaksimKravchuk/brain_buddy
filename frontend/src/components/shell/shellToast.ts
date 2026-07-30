import { createContext, useContext } from "react";

/**
 * Prototype-style transient toast ("X isn't built yet — placeholder").
 * Lives outside AppShell.tsx so that file only exports components
 * (react-refresh constraint); AppShell provides the value.
 */
export const ShellToastContext = createContext<(message: string) => void>(() => undefined);

export function useShellToast(): (message: string) => void {
  return useContext(ShellToastContext);
}

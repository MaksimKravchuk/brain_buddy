/**
 * Carry On dark mode follows the operating system. The role values for both
 * schemes live in styles/carryOn.css; the dark ones apply under
 * `:root[data-theme="dark"]`, so this keeps that attribute in step with the
 * `prefers-color-scheme` media query. There is no in-app theme setting.
 */
const DARK_QUERY = "(prefers-color-scheme: dark)";

export function applySystemTheme(): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const query = window.matchMedia(DARK_QUERY);
  const root = document.documentElement;
  const apply = (dark: boolean): void => {
    root.dataset.theme = dark ? "dark" : "light";
  };
  apply(query.matches);
  const onChange = (event: MediaQueryListEvent): void => apply(event.matches);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

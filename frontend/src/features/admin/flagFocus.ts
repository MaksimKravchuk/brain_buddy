/**
 * Focus the first target that exists, in the order given.
 *
 * Its own module because the last link in `F-09`'s chain — the cohort-count
 * region, reached only when neither another cohort row nor the add-user input
 * is present — cannot be produced through the rendered UI, and a fallback
 * nothing exercises is a fallback nobody can trust.
 */
export function focusFirstAvailable(
  targets: Array<HTMLElement | null | undefined>
): HTMLElement | null {
  for (const target of targets) {
    if (target) {
      target.focus();
      return target;
    }
  }
  return null;
}

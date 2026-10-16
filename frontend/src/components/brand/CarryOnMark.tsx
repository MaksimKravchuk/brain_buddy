/**
 * The Carry On mark: a traveller climbing steps, with a terracotta head.
 * Shapes are the brand kit's `mark.svg`; the body follows the text colour so
 * the same mark reads as basalt on limestone and limestone on basalt.
 */
export function CarryOnMark({ className }: { className?: string }): React.JSX.Element {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true" focusable="false">
      <g transform="translate(0.8 5.4) scale(0.82)">
        <path d="M16 58H32V50H42V42H52V34H60" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <rect x="22" y="18.5" width="8.5" height="13" rx="3.5" fill="currentColor" transform="rotate(15 26.2 25)" />
        <path d="M30 34L26 45L23 55" stroke="currentColor" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <path d="M30 34L37 40L37 47" stroke="currentColor" strokeWidth="6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <path d="M33.2 22.5L30 34" stroke="currentColor" strokeWidth="7.5" strokeLinecap="round" />
        <path d="M33 24L39 29L43 26.5" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <path d="M43.5 20L44.6 40.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
        <circle cx="35.4" cy="13" r="4.8" fill="#C4472A" />
      </g>
    </svg>
  );
}

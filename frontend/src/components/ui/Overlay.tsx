import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";

const focusableSelector =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Modal dialog primitive: focus trap, Escape/scrim close, body scroll lock. */
export function Overlay({
  children,
  labelledBy,
  onClose,
  operationId,
  scrimTestId = "overlay-scrim",
  size = "wide"
}: {
  children: ReactNode;
  /** Id of the element naming the dialog. */
  labelledBy: string;
  /** Stamped on the panel as `data-operation-id` for end-to-end assertions. */
  operationId?: string;
  /**
   * Omitted when the overlay must not be dismissed — while a capture is live or
   * drafts are unreviewed the user has to make an explicit choice (Discard,
   * Stop & review, Confirm). Dismissing then would either abandon work or leave
   * the microphone open behind an invisible dialog.
   */
  onClose?: () => void;
  scrimTestId?: string;
  size?: "wide" | "narrow";
}): React.JSX.Element {
  const panelRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  // Keep the workspace from scrolling under the panel while it is open.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (onClose) {
          event.stopPropagation();
          onClose();
        }
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      // Cycle focus inside the panel: the workspace behind is inert to the user
      // but still in the tab order without this.
      const panel = panelRef.current;
      if (!panel) {
        return;
      }
      // No layout-based visibility filter here: the selector already drops
      // disabled and tabindex="-1" nodes, every panel unmounts inactive content
      // rather than hiding it, and `offsetParent`/`getClientRects` are always
      // empty under jsdom — which would collapse the cycle onto one element and
      // swallow the Tab that blurs a field.
      const focusable = Array.from(panel.querySelectorAll<HTMLElement>(focusableSelector));
      if (focusable.length === 0) {
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && (document.activeElement === first || document.activeElement === panel)) {
        event.preventDefault();
        last.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[100] flex items-stretch justify-center bg-slate-50/80 backdrop-blur-sm motion-safe:animate-fade-in sm:items-center sm:p-6">
      {/* Click-outside-to-close. Deliberately not a button: the header's X is the
          accessible close control, and a second one with the same name would just
          duplicate it in the accessibility tree and the tab order. */}
      {onClose ? <div aria-hidden data-testid={scrimTestId} className="absolute inset-0" onClick={onClose} /> : null}
      <section
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelledBy}
        data-operation-id={operationId}
        // The panel takes focus on mount so the dialog is where the keyboard
        // lands; `focus-visible:shadow-floating` keeps the global focus ring from
        // drawing a highlight around the whole dialog for that programmatic focus.
        className={`relative flex max-h-full w-full flex-col overflow-hidden bg-white shadow-floating outline-none focus-visible:shadow-floating motion-safe:sm:animate-fade-in-up sm:rounded-[20px] sm:border sm:border-slate-200 ${
          size === "wide" ? "sm:w-[880px]" : "sm:w-[480px]"
        }`}
      >
        {children}
      </section>
    </div>
  );
}

/** Header shared by overlay dialogs: title, optional meta, optional close. */
export function OverlayHeader({
  titleId,
  eyebrow,
  title,
  meta,
  status,
  closeLabel = "Close dialog",
  onClose
}: {
  titleId: string;
  eyebrow?: string;
  title: string;
  meta?: ReactNode;
  status?: ReactNode;
  closeLabel?: string;
  onClose?: () => void;
}): React.JSX.Element {
  return (
    <header className="flex shrink-0 items-start gap-3 border-b border-slate-100 px-5 pt-[max(16px,env(safe-area-inset-top))] pb-3 sm:px-6 sm:pt-5">
      <div className="min-w-0 flex-1">
        {eyebrow ? (
          <p className="text-[10px] font-semibold uppercase tracking-[0.06em] text-slate-500">{eyebrow}</p>
        ) : null}
        <h1 id={titleId} className="text-[20px] font-semibold leading-[1.3] tracking-[-0.015em] text-slate-900">
          {title}
        </h1>
        {meta ? <p className="mt-0.5 text-xs text-slate-500">{meta}</p> : null}
      </div>
      {status}
      {onClose ? (
        <button
          type="button"
          aria-label={closeLabel}
          className="-mr-1.5 -mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-500 transition-colors duration-200 ease-smooth hover:bg-surface-sunken hover:text-slate-900"
          onClick={onClose}
        >
          <X className="h-4 w-4" aria-hidden />
        </button>
      ) : null}
    </header>
  );
}

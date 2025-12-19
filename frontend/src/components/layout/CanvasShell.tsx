import type { ReactNode } from "react";

interface CanvasShellProps {
  children: ReactNode;
  overlay?: ReactNode;
  toolbar?: ReactNode;
}

export function CanvasShell({ children, overlay, toolbar }: CanvasShellProps): JSX.Element {
  return (
    <div className="relative flex flex-1 flex-col">
      {toolbar ? (
        <div className="pointer-events-none absolute left-1/2 top-4 z-20 flex -translate-x-1/2 gap-2">
          <div className="pointer-events-auto rounded-full border border-slate-200 bg-surface-raised/80 px-3 py-2 shadow-sm backdrop-blur">
            {toolbar}
          </div>
        </div>
      ) : null}
      <div className="relative flex flex-1 overflow-hidden rounded-tl-xl bg-surface-base">
        {children}
        {overlay ? <div className="pointer-events-none absolute inset-0 z-10">{overlay}</div> : null}
      </div>
    </div>
  );
}

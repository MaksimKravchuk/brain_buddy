import type { ReactNode } from "react";

interface SidePanelProps {
  children: ReactNode;
  footer?: ReactNode;
  title?: string;
  toolbar?: ReactNode;
}

export function SidePanel({ children, footer, title, toolbar }: SidePanelProps): JSX.Element {
  return (
    <div className="flex h-full flex-col gap-6">
      {title || toolbar ? (
        <div className="space-y-3">
          {title ? <h2 className="text-base font-semibold text-slate-900">{title}</h2> : null}
          {toolbar ? <div className="flex items-center gap-2 text-sm text-slate-600">{toolbar}</div> : null}
        </div>
      ) : null}

      <div className="flex-1 space-y-6">{children}</div>

      {footer ? <div className="border-t border-slate-200 pt-4 text-xs text-slate-500">{footer}</div> : null}
    </div>
  );
}

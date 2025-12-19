import type { ReactNode } from "react";

interface TopBarProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  rightSlot?: ReactNode;
}

export function TopBar({ title, subtitle, actions, rightSlot }: TopBarProps): JSX.Element {
  return (
    <div className="flex items-center justify-between gap-4">
      <div>
        <div className="flex items-center gap-3">
          <span className="text-lg font-semibold text-slate-900">{title}</span>
          {actions ? <div className="flex items-center gap-2 text-sm text-slate-600">{actions}</div> : null}
        </div>
        {subtitle ? <p className="mt-1 text-sm text-slate-500">{subtitle}</p> : null}
      </div>
      {rightSlot ? <div className="flex items-center gap-2">{rightSlot}</div> : null}
    </div>
  );
}

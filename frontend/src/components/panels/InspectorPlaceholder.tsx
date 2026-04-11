import { MousePointerClick, type LucideIcon } from "lucide-react";

interface InspectorPlaceholderProps {
  message: string;
  icon?: LucideIcon;
}

export function InspectorPlaceholder({
  message,
  icon: Icon = MousePointerClick
}: InspectorPlaceholderProps): JSX.Element {
  return (
    <div className="flex animate-fade-in flex-col items-center gap-3 rounded-xl border border-dashed border-slate-200 bg-surface-sunken/40 px-4 py-8 text-center text-sm text-slate-500">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white text-slate-400 shadow-soft">
        <Icon className="h-5 w-5" />
      </div>
      <p className="max-w-[220px] text-slate-500">{message}</p>
    </div>
  );
}

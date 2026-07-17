import { AlertCircle, AlertTriangle, CheckCircle2, Info, X, type LucideIcon } from "lucide-react";
import { twMerge } from "tailwind-merge";

import { useUiStore, type Toast } from "../../stores/uiStore";

const variantStyles: Record<Toast["variant"], string> = {
  info: "border-slate-200 bg-white/90 text-slate-800",
  success: "border-emerald-200 bg-emerald-50/95 text-emerald-900",
  warning: "border-amber-200 bg-amber-50/95 text-amber-900",
  error: "border-rose-200 bg-rose-50/95 text-rose-900"
};

const variantIcons: Record<Toast["variant"], { icon: LucideIcon; className: string }> = {
  info: { icon: Info, className: "bg-slate-100 text-slate-600" },
  success: { icon: CheckCircle2, className: "bg-emerald-100 text-emerald-700" },
  warning: { icon: AlertTriangle, className: "bg-amber-100 text-amber-700" },
  error: { icon: AlertCircle, className: "bg-rose-100 text-rose-700" }
};

export function ToastStack(): JSX.Element {
  const toasts = useUiStore((state) => state.toasts);
  const dismiss = useUiStore((state) => state.dismissToast);

  return (
    <div className="pointer-events-none fixed inset-x-0 top-4 z-50 flex justify-center">
      <div className="flex w-full max-w-md flex-col gap-3 px-4">
        {toasts.map((toast) => {
          const { icon: Icon, className: iconClassName } = variantIcons[toast.variant];

          return (
            <div
              key={toast.id}
              className={twMerge(
                "pointer-events-none rounded-xl border px-4 py-3 text-sm shadow-floating backdrop-blur",
                variantStyles[toast.variant],
                toast.dismissing
                  ? "animate-slide-up-fade-out"
                  : "animate-slide-down-fade-in"
              )}
            >
              <div className="flex items-start gap-3">
                <div
                  className={twMerge(
                    "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
                    iconClassName
                  )}
                >
                  <Icon className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="font-semibold">{toast.title}</p>
                  {toast.description ? (
                    <p className="mt-1 text-xs opacity-80">{toast.description}</p>
                  ) : null}
                  {toast.action ? (
                    <div className="mt-2">
                      <button
                        type="button"
                        onClick={() => {
                          toast.action?.onClick();
                          dismiss(toast.id);
                        }}
                        className="inline-flex h-7 items-center rounded-md px-2 text-xs font-semibold uppercase tracking-wide text-brand-primary transition-colors duration-200 ease-smooth hover:bg-brand-primary/10"
                      >
                        {toast.action.label}
                      </button>
                    </div>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={() => dismiss(toast.id)}
                  aria-label="Dismiss notification"
                  className="pointer-events-auto -mt-1 -mr-1 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-500 transition-colors duration-200 ease-smooth hover:bg-slate-100 hover:text-slate-700"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

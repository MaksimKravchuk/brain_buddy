import { useUiStore } from "../../stores/uiStore";

const variantStyles: Record<string, string> = {
  info: "border-slate-200 bg-white/80 text-slate-800",
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  error: "border-red-200 bg-red-50 text-red-800"
};

export function ToastStack(): JSX.Element | null {
  const toasts = useUiStore((state) => state.toasts);
  const dismiss = useUiStore((state) => state.dismissToast);

  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="pointer-events-none fixed inset-x-0 top-4 z-50 flex justify-center">
      <div className="flex w-full max-w-md flex-col gap-3 px-4">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`pointer-events-auto rounded-xl border px-4 py-3 text-sm shadow-lg backdrop-blur ${variantStyles[toast.variant]}`}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-semibold">{toast.title}</p>
                {toast.description ? <p className="mt-1 text-xs opacity-80">{toast.description}</p> : null}
              </div>
              <div className="flex gap-2">
                {toast.action ? (
                  <button
                    type="button"
                    onClick={() => {
                      toast.action?.onClick();
                      dismiss(toast.id);
                    }}
                    className="text-xs uppercase tracking-wide text-brand-primary transition hover:text-brand-primary/80"
                  >
                    {toast.action.label}
                  </button>
                ) : null}
                <button
                  type="button"
                  onClick={() => dismiss(toast.id)}
                  className="text-xs uppercase tracking-wide text-slate-500 transition hover:text-slate-700"
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

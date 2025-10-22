import { useUiStore } from "../../stores/uiStore";

const variantStyles: Record<string, string> = {
  info: "border-slate-600 bg-surface-sunken/80 text-slate-100",
  success: "border-emerald-600/60 bg-emerald-500/15 text-emerald-100",
  warning: "border-amber-600/60 bg-amber-500/15 text-amber-100",
  error: "border-red-600/60 bg-red-500/15 text-red-100"
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
              <button
                type="button"
                onClick={() => dismiss(toast.id)}
                className="text-xs uppercase tracking-wide text-slate-400 transition hover:text-slate-200"
              >
                Close
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const plannedWorkflowItems = [
  { id: "crt", label: "CRT" },
  { id: "weekly-review", label: "Weekly Review" }
] as const;

export function PlannedWorkflowNavigation(): JSX.Element {
  return (
    <nav
      aria-label="Planned workflows"
      className="order-last flex min-w-0 basis-full flex-wrap items-center gap-2 overflow-visible px-1 py-0.5 sm:order-none sm:flex-1 sm:basis-auto sm:flex-nowrap sm:overflow-x-auto"
    >
      {plannedWorkflowItems.map((item) => (
        <button
          key={item.id}
          type="button"
          disabled
          className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500 shadow-soft transition-[background-color,border-color,color,box-shadow,transform] duration-200 ease-smooth disabled:pointer-events-none disabled:opacity-100"
          aria-label={`${item.label} — Coming Later`}
        >
          <span className="text-slate-700">{item.label}</span>
          <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
            Coming Later
          </span>
        </button>
      ))}
    </nav>
  );
}

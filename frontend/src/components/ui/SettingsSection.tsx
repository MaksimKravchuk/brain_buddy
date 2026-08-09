import type { ReactNode } from "react";

/**
 * Settings-page primitives shared by account settings and connected agents.
 *
 * The `<section>` + `<h2>` shape is load-bearing: the Playwright suites locate a
 * settings block by filtering sections on their heading, so both pages must keep
 * emitting exactly one heading per card.
 */
export function SectionCard({
  title,
  description,
  children,
  tone = "default"
}: {
  title: string;
  description: string;
  children: ReactNode;
  tone?: "default" | "danger";
}): JSX.Element {
  const border = tone === "danger" ? "border-rose-200" : "border-slate-200";
  return (
    <section className={`rounded-2xl border ${border} bg-white p-5 shadow-soft`}>
      <h2 className="text-subtitle font-semibold text-slate-900">{title}</h2>
      <p className="mt-1 text-sm text-slate-500">{description}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function Field({
  label,
  type,
  value,
  onChange,
  autoComplete,
  name,
  placeholder,
  hint
}: {
  label: string;
  type: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
  name: string;
  placeholder?: string;
  /** Rendered under the input and wired to it, for policy the server enforces. */
  hint?: string;
}): JSX.Element {
  const hintId = hint ? `${name}-hint` : undefined;
  // The hint sits outside the <label> deliberately: inside, it would join the
  // field's accessible name and every `getByLabelText`/`getByLabel` lookup — in
  // tests and for screen-reader users — would have to spell out the whole hint.
  return (
    <div className="flex flex-col gap-1 text-sm">
      <label className="flex flex-col gap-1">
        <span className="font-medium text-slate-700">{label}</span>
        <input
          type={type}
          name={name}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="rounded-md border border-slate-200 bg-white px-3 py-2 text-slate-900 shadow-soft transition-colors duration-200 ease-smooth focus:border-brand-primary focus:outline-none"
          autoComplete={autoComplete}
          placeholder={placeholder}
          aria-describedby={hintId}
        />
      </label>
      {hint ? (
        <span id={hintId} className="text-xs text-slate-500">
          {hint}
        </span>
      ) : null}
    </div>
  );
}

export function Feedback({
  error,
  success
}: {
  error: string | null;
  success: string | null;
}): JSX.Element | null {
  if (error) {
    return (
      <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
        {error}
      </p>
    );
  }
  if (success) {
    return (
      <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
        {success}
      </p>
    );
  }
  return null;
}

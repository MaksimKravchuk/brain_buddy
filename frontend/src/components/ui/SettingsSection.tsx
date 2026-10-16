import { useId, type ReactNode } from "react";
import { NavLink } from "react-router-dom";

/**
 * Settings-page primitives shared by account settings and connected agents.
 *
 * The `<section>` + `<h2>` shape is load-bearing: the Playwright suites locate a
 * settings block by filtering sections on their heading, so both pages must keep
 * emitting exactly one heading per card.
 *
 * A `flat` section is a group of label-column rows (board M25): it draws no
 * card, keeps its heading and description for assistive technology, and is set
 * apart from the group above by the one rule the board draws.
 */
export function SectionCard({
  title,
  description,
  children,
  tone = "default",
  flat = false
}: {
  title: string;
  description: string;
  children: ReactNode;
  tone?: "default" | "danger";
  flat?: boolean;
}): React.JSX.Element {
  if (flat) {
    return (
      <section className="not-first:mt-2 not-first:border-t not-first:border-quiet not-first:pt-2">
        <h2 className="sr-only">{title}</h2>
        <p className="sr-only">{description}</p>
        {children}
      </section>
    );
  }
  return (
    <section className="rounded-card bg-card p-5">
      <h2 className={`text-co-body font-semibold ${tone === "danger" ? "text-danger" : "text-ink"}`}>{title}</h2>
      <p className="mt-1 text-co-meta text-ink-muted">{description}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

/** One label-column row: right-aligned label, the value, an optional action. */
export function SettingRow({
  label,
  htmlFor,
  action,
  children
}: {
  label?: string;
  htmlFor?: string;
  action?: ReactNode;
  children: ReactNode;
}): React.JSX.Element {
  return (
    <div className="grid grid-cols-1 items-center gap-x-3 gap-y-1 py-1.5 text-co-body sm:grid-cols-[150px_1fr_auto]">
      {label && htmlFor ? (
        <label htmlFor={htmlFor} className="text-ink-muted sm:text-right">
          {label}
        </label>
      ) : label ? (
        <span className="text-ink-muted sm:text-right">{label}</span>
      ) : (
        <span aria-hidden className="hidden sm:block" />
      )}
      <div className="min-w-0 text-ink">{children}</div>
      {action ? <div className="flex flex-wrap gap-2 sm:justify-end">{action}</div> : <span aria-hidden className="hidden sm:block" />}
    </div>
  );
}

/** Segmented Account / Agents switch at the top of the settings pages. */
export function SettingsTabs(): React.JSX.Element {
  const tab = ({ isActive }: { isActive: boolean }) =>
    `inline-flex min-h-9 items-center rounded-control px-4 text-co-meta ${
      isActive ? "bg-card font-semibold text-ink" : "text-ink-muted hover:text-ink"
    }`;
  return (
    <nav aria-label="Settings" className="inline-flex gap-0.5 self-start rounded-control bg-quiet p-[3px]">
      <NavLink to="/settings/account" className={tab} end>
        Account
      </NavLink>
      <NavLink to="/settings/agents" className={tab} end>
        Agents
      </NavLink>
    </nav>
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
  hint,
  disabled = false,
  row = false,
  action
}: {
  label: string;
  type: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
  name: string;
  placeholder?: string;
  disabled?: boolean;
  /** Rendered under the input and wired to it, for policy the server enforces. */
  hint?: string;
  /** Lay the label out in the label column of a settings row. */
  row?: boolean;
  /** Row layout only: the control that sits in the action column. */
  action?: ReactNode;
}): React.JSX.Element {
  const hintId = hint ? `${name}-hint` : undefined;
  const inputId = useId();
  const input = (
    <input
      id={inputId}
      type={type}
      name={name}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="min-h-11 w-full rounded-md bg-card px-3 py-2 text-co-body text-ink transition-colors duration-200 ease-smooth focus:outline-hidden disabled:opacity-60"
      autoComplete={autoComplete}
      placeholder={placeholder}
      disabled={disabled}
      aria-describedby={hintId}
    />
  );
  // The hint sits outside the <label> deliberately: inside, it would join the
  // field's accessible name and every `getByLabelText`/`getByLabel` lookup — in
  // tests and for screen-reader users — would have to spell out the whole hint.
  const hintNode = hint ? (
    <span id={hintId} className="text-co-meta text-ink-muted">
      {hint}
    </span>
  ) : null;
  if (row) {
    return (
      <SettingRow label={label} htmlFor={inputId} action={action}>
        <div className="flex max-w-[260px] flex-col gap-1">
          {input}
          {hintNode}
        </div>
      </SettingRow>
    );
  }
  return (
    <div className="flex flex-col gap-1 text-co-meta">
      <label htmlFor={inputId} className="text-ink-muted">
        {label}
      </label>
      {input}
      {hintNode}
    </div>
  );
}

export function Feedback({
  error,
  success
}: {
  error: string | null;
  success: string | null;
}): React.JSX.Element | null {
  if (error) {
    return (
      <p role="alert" className="rounded-card bg-quiet px-3 py-2 text-co-meta text-danger">
        {error}
      </p>
    );
  }
  if (success) {
    return (
      <p role="status" className="rounded-card bg-quiet px-3 py-2 text-co-meta text-ink">
        {success}
      </p>
    );
  }
  return null;
}

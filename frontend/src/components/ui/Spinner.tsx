import { twMerge } from "tailwind-merge";

interface SpinnerProps {
  size?: "sm" | "md" | "lg";
  className?: string;
  label?: string;
}

const sizeMap = {
  sm: "h-4 w-4 border-2",
  md: "h-6 w-6 border-2",
  lg: "h-8 w-8 border-[3px]",
};

export function Spinner({ size = "md", className, label }: SpinnerProps): React.JSX.Element {
  return (
    <div
      className={twMerge(
        "animate-spin rounded-full border-slate-200 border-t-brand-primary",
        sizeMap[size],
        className
      )}
      role="status"
      aria-label={label ?? "Loading"}
    >
      <span className="sr-only">{label ?? "Loading"}</span>
    </div>
  );
}

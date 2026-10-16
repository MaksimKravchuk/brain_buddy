import { cva, type VariantProps } from "class-variance-authority";

export const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 rounded-control font-semibold",
    "transition-[background-color,border-color,color,box-shadow,transform]",
    "duration-200 ease-smooth",
    "disabled:pointer-events-none disabled:opacity-60",
    "focus-visible:shadow-ring-focus"
  ].join(" "),
  {
    variants: {
      variant: {
        // Basalt: the default strong action. Terracotta is reserved for the
        // one next step on a screen, so it is opt-in through `accent`.
        primary:
          "bg-ink text-ground hover:bg-ink/85",
        accent:
          "bg-accent text-on-accent hover:bg-accent-pressed",
        secondary:
          "bg-quiet text-ink hover:bg-quiet-pressed",
        danger:
          "bg-quiet text-danger hover:bg-quiet-pressed",
        ghost:
          "bg-transparent text-ink-muted hover:bg-quiet hover:text-ink",
        icon:
          "bg-transparent text-ink-muted hover:bg-quiet hover:text-ink"
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4 text-sm",
        lg: "h-10 px-5 text-sm"
      }
    },
    compoundVariants: [
      {
        variant: "icon",
        size: "sm",
        className: "h-8 w-8 p-0"
      },
      {
        variant: "icon",
        size: "md",
        className: "h-9 w-9 p-0"
      },
      {
        variant: "icon",
        size: "lg",
        className: "h-10 w-10 p-0"
      }
    ],
    defaultVariants: {
      variant: "primary",
      size: "md"
    }
  }
);

export type ButtonVariantProps = VariantProps<typeof buttonVariants>;

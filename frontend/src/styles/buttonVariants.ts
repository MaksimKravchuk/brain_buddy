import { cva, type VariantProps } from "class-variance-authority";

export const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-2 rounded-lg font-medium",
    "transition-[background-color,border-color,color,box-shadow,transform]",
    "duration-200 ease-smooth",
    "active:scale-[0.98] disabled:pointer-events-none disabled:opacity-60"
  ].join(" "),
  {
    variants: {
      variant: {
        primary:
          "bg-brand-primary text-white shadow-soft hover:bg-sky-400 hover:shadow-raised",
        secondary:
          "border border-slate-200 bg-white text-slate-700 shadow-soft hover:border-slate-300 hover:text-slate-900 hover:shadow-raised",
        danger:
          "border border-rose-200 bg-rose-50 text-rose-700 shadow-soft hover:border-rose-300 hover:bg-rose-100 hover:text-rose-800",
        ghost:
          "border border-transparent bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900",
        icon:
          "border border-transparent bg-transparent text-slate-600 hover:bg-slate-100 hover:text-slate-900"
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

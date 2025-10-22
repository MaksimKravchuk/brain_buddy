import { cva } from "class-variance-authority";

type Intent = "primary" | "secondary";

type Size = "sm" | "md" | "lg";

export const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
  {
    variants: {
      intent: {
        primary: "bg-sky-500 text-white hover:bg-sky-400 focus-visible:outline-sky-300",
        secondary: "bg-slate-800 text-slate-100 hover:bg-slate-700 focus-visible:outline-slate-500"
      },
      size: {
        sm: "px-3 py-1.5 text-sm",
        md: "px-4 py-2 text-base",
        lg: "px-5 py-3 text-lg"
      }
    },
    defaultVariants: {
      intent: "primary",
      size: "md"
    }
  }
);

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { twMerge } from "tailwind-merge";

import { buttonVariants, type ButtonVariantProps } from "../../styles/buttonVariants";
import { Spinner } from "./Spinner";

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    ButtonVariantProps {
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  isLoading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    className,
    variant,
    size,
    leftIcon,
    rightIcon,
    isLoading = false,
    disabled,
    children,
    type = "button",
    ...rest
  },
  ref
) {
  const iconSlot = isLoading ? (
    <Spinner size="sm" className="border-current/30 border-t-current" />
  ) : (
    leftIcon
  );

  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || isLoading}
      data-loading={isLoading ? "true" : undefined}
      className={twMerge(buttonVariants({ variant, size }), className)}
      {...rest}
    >
      {iconSlot ? (
        <span className="inline-flex items-center justify-center [&>svg]:h-4 [&>svg]:w-4">
          {iconSlot}
        </span>
      ) : null}
      {children ? <span className="inline-flex items-center">{children}</span> : null}
      {!isLoading && rightIcon ? (
        <span className="inline-flex items-center justify-center [&>svg]:h-4 [&>svg]:w-4">
          {rightIcon}
        </span>
      ) : null}
    </button>
  );
});

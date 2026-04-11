import {
  cloneElement,
  createContext,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactElement,
  type ReactNode
} from "react";
import { twMerge } from "tailwind-merge";

import { useDelayedUnmount } from "../../hooks/useDelayedUnmount";

type Align = "start" | "end";

interface DropdownMenuContextValue {
  close: () => void;
}

const DropdownMenuContext = createContext<DropdownMenuContextValue | null>(null);

function useDropdownMenuContext(): DropdownMenuContextValue {
  const ctx = useContext(DropdownMenuContext);
  if (!ctx) {
    throw new Error("DropdownMenuItem must be used inside a DropdownMenu");
  }
  return ctx;
}

interface DropdownMenuProps {
  /**
   * Trigger element. Receives `ref`, `aria-haspopup`, `aria-expanded`,
   * `aria-controls`, and `onClick` via cloneElement.
   */
  trigger: ReactElement;
  children: ReactNode;
  align?: Align;
  menuClassName?: string;
  /** Minimum width of the menu panel. Defaults to `min-w-72`. */
  widthClassName?: string;
}

export function DropdownMenu({
  trigger,
  children,
  align = "start",
  menuClassName,
  widthClassName = "min-w-72"
}: DropdownMenuProps): JSX.Element {
  const [isOpen, setIsOpen] = useState(false);
  const menuId = useId();
  const triggerRef = useRef<HTMLElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const { shouldRender, isAnimatingOut } = useDelayedUnmount(isOpen, 160);

  const close = useCallback(() => setIsOpen(false), []);
  const contextValue = useMemo<DropdownMenuContextValue>(() => ({ close }), [close]);

  useEffect(() => {
    if (!isOpen) {
      return;
    }
    const handlePointerDown = (event: globalThis.MouseEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (menuRef.current?.contains(target)) return;
      if (triggerRef.current?.contains(target)) return;
      close();
    };
    const handleKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        close();
        triggerRef.current?.focus();
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKey);
    };
  }, [isOpen, close]);

  useLayoutEffect(() => {
    if (!isOpen) return;
    const firstItem = menuRef.current?.querySelector<HTMLElement>(
      '[role="menuitem"]:not([aria-disabled="true"])'
    );
    firstItem?.focus();
  }, [isOpen]);

  const handleMenuKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (
      event.key !== "ArrowDown" &&
      event.key !== "ArrowUp" &&
      event.key !== "Home" &&
      event.key !== "End"
    ) {
      return;
    }
    event.preventDefault();
    const items = Array.from(
      menuRef.current?.querySelectorAll<HTMLElement>(
        '[role="menuitem"]:not([aria-disabled="true"])'
      ) ?? []
    );
    if (items.length === 0) return;
    const active = document.activeElement as HTMLElement | null;
    const currentIndex = active ? items.indexOf(active) : -1;
    let nextIndex = currentIndex;
    if (event.key === "ArrowDown") {
      nextIndex = currentIndex < 0 ? 0 : (currentIndex + 1) % items.length;
    } else if (event.key === "ArrowUp") {
      nextIndex = currentIndex <= 0 ? items.length - 1 : currentIndex - 1;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = items.length - 1;
    }
    items[nextIndex]?.focus();
  };

  const triggerProps = {
    ref: (node: HTMLElement | null) => {
      triggerRef.current = node;
      const existingRef = (trigger as { ref?: unknown }).ref as
        | ((instance: HTMLElement | null) => void)
        | { current: HTMLElement | null }
        | null
        | undefined;
      if (typeof existingRef === "function") {
        existingRef(node);
      } else if (existingRef && typeof existingRef === "object") {
        (existingRef as { current: HTMLElement | null }).current = node;
      }
    },
    "aria-haspopup": "menu" as const,
    "aria-expanded": isOpen,
    "aria-controls": menuId,
    onClick: (event: MouseEvent<HTMLElement>) => {
      trigger.props.onClick?.(event);
      if (event.defaultPrevented) return;
      setIsOpen((prev) => !prev);
    }
  };

  const clonedTrigger = isValidElement(trigger)
    ? cloneElement(trigger, triggerProps)
    : trigger;

  return (
    <DropdownMenuContext.Provider value={contextValue}>
      <div className="relative inline-block text-left">
        {clonedTrigger}
        {shouldRender ? (
          <div
            ref={menuRef}
            id={menuId}
            role="menu"
            tabIndex={-1}
            onKeyDown={handleMenuKeyDown}
            className={twMerge(
              "absolute z-40 mt-2 origin-top rounded-xl border border-slate-200 bg-white/95 p-1 shadow-floating backdrop-blur",
              widthClassName,
              align === "end" ? "right-0" : "left-0",
              isAnimatingOut ? "animate-fade-out" : "animate-slide-down-fade-in",
              menuClassName
            )}
          >
            {children}
          </div>
        ) : null}
      </div>
    </DropdownMenuContext.Provider>
  );
}

interface DropdownMenuItemProps {
  onSelect?: () => void;
  disabled?: boolean;
  leftIcon?: ReactNode;
  children: ReactNode;
  variant?: "default" | "danger";
  className?: string;
  /** Close the parent menu on activation (default true). */
  closeOnSelect?: boolean;
}

/**
 * A focusable, keyboard-activatable item inside DropdownMenu.
 * The parent menu closes automatically on click/Enter/Space unless
 * `closeOnSelect` is false.
 */
export function DropdownMenuItem({
  onSelect,
  disabled = false,
  leftIcon,
  children,
  variant = "default",
  className,
  closeOnSelect = true
}: DropdownMenuItemProps): JSX.Element {
  const { close } = useDropdownMenuContext();

  const handleActivate = () => {
    if (disabled) return;
    onSelect?.();
    if (closeOnSelect) {
      close();
    }
  };

  const handleKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      handleActivate();
    }
  };

  return (
    <button
      type="button"
      role="menuitem"
      aria-disabled={disabled || undefined}
      disabled={disabled}
      onClick={handleActivate}
      onKeyDown={handleKey}
      className={twMerge(
        "flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors duration-150 ease-smooth",
        "focus:outline-none focus-visible:bg-slate-100",
        disabled
          ? "cursor-not-allowed text-slate-400"
          : variant === "danger"
            ? "text-rose-700 hover:bg-rose-50 focus:bg-rose-50"
            : "text-slate-700 hover:bg-slate-100 focus:bg-slate-100",
        className
      )}
    >
      {leftIcon ? (
        <span className="inline-flex h-4 w-4 items-center justify-center [&>svg]:h-4 [&>svg]:w-4">
          {leftIcon}
        </span>
      ) : null}
      <span className="flex-1 truncate">{children}</span>
    </button>
  );
}

export function DropdownMenuDivider(): JSX.Element {
  return <div role="separator" className="my-1 h-px bg-slate-200" />;
}

interface DropdownMenuSectionProps {
  label: string;
  children: ReactNode;
}

export function DropdownMenuSection({
  label,
  children
}: DropdownMenuSectionProps): JSX.Element {
  return (
    <div className="px-1 py-1">
      <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        {label}
      </div>
      {children}
    </div>
  );
}

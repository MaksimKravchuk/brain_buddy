import { useEffect } from "react";
import type { ReactNode } from "react";

import { useTreeStore } from "../../stores/treeStore";

interface LayoutProps {
  header: ReactNode;
  sidebar: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}

export function Layout({ header, sidebar, children, footer }: LayoutProps): JSX.Element {
  const hasPendingSync = useTreeStore((state) => state.pendingSync);

  useEffect(() => {
    if (!hasPendingSync) {
      return;
    }

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "You have unsynced changes.";
      return event.returnValue;
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasPendingSync]);

  return (
    <div className="flex min-h-screen bg-surface-base text-slate-100">
      <div className="flex flex-1 flex-col">
        <header className="border-b border-slate-800 bg-surface-sunken/80 px-6 py-4 shadow-inset backdrop-blur">
          {header}
        </header>

        <div className="flex flex-1 overflow-hidden">
          <aside className="w-80 shrink-0 border-r border-slate-800 bg-surface-sunken/70 backdrop-blur-sm">
            <div className="h-full overflow-y-auto px-4 py-6">{sidebar}</div>
          </aside>

          <main className="relative flex flex-1 flex-col overflow-hidden">{children}</main>
        </div>

        {footer ? (
          <footer className="border-t border-slate-800 bg-surface-sunken/70 px-6 py-3 text-sm text-slate-300">
            {footer}
          </footer>
        ) : null}
      </div>
    </div>
  );
}

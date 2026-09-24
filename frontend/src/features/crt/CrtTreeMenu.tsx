import { useCallback, useEffect, useRef, useState } from "react";

export type CrtTreeMenuItem = Readonly<{
  id: string;
  name: string;
  updated_at?: string;
}>;

export type CrtTreeMenuProps = Readonly<{
  currentTree: Readonly<{ id: string; name: string }> | null;
  trees: readonly CrtTreeMenuItem[];
  busy?: boolean;
  error?: string;
  onCreate: () => void | Promise<void>;
  onRename: () => void | Promise<void>;
  onImport: (file: File) => void | Promise<void>;
  onExport: () => void | Promise<void>;
  onDelete: () => void | Promise<void>;
  onSelectTree: (treeId: string) => void | Promise<void>;
}>;

type MenuAction = "create" | "rename" | "import" | "export" | "delete";

const focusableMenuSelector = "button[role=menuitem]:not([disabled])";

function actionLabel(action: MenuAction): string {
  if (action === "create") return "Create a new tree";
  if (action === "rename") return "Rename tree";
  if (action === "import") return "Import tree JSON";
  if (action === "export") return "Export saved server copy";
  return "Delete tree";
}

export function CrtTreeMenu({
  currentTree,
  trees,
  busy = false,
  error,
  onCreate,
  onRename,
  onImport,
  onExport,
  onDelete,
  onSelectTree
}: CrtTreeMenuProps): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const closeMenu = useCallback((restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) {
      triggerRef.current?.focus();
    }
  }, []);

  const focusItem = useCallback((index: number) => {
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>(focusableMenuSelector) ?? []);
    if (items.length === 0) return;
    const nextIndex = (index + items.length) % items.length;
    items[nextIndex]?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const first = menuRef.current?.querySelector<HTMLButtonElement>(focusableMenuSelector);
    first?.focus();

    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && !menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) {
        closeMenu();
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu();
        return;
      }
      if (event.key === "ArrowDown" || event.key === "ArrowUp" || event.key === "Home" || event.key === "End") {
        const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>(focusableMenuSelector) ?? []);
        const currentIndex = Math.max(0, items.indexOf(document.activeElement as HTMLButtonElement));
        const nextIndex = event.key === "Home"
          ? 0
          : event.key === "End"
            ? items.length - 1
            : event.key === "ArrowDown" ? currentIndex + 1 : currentIndex - 1;
        event.preventDefault();
        focusItem(nextIndex);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [closeMenu, focusItem, open]);

  const runAction = (action: MenuAction): void => {
    closeMenu();
    const callbacks: Record<MenuAction, () => void | Promise<void>> = {
      create: onCreate,
      rename: onRename,
      import: () => fileInputRef.current?.click(),
      export: onExport,
      delete: onDelete
    };
    void callbacks[action]();
  };

  const onFileChange = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    void onImport(file);
  };

  const treeActionDisabled = busy || currentTree === null;
  const triggerLabel = currentTree ? `Current tree: ${currentTree.name}` : "Choose a tree to continue";

  return (
    <div className="relative" data-crt-native="true">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="crt-tree-menu"
        disabled={busy}
        className="flex min-h-10 items-center gap-2 rounded-lg border border-sky-200 bg-sky-50 px-3 py-2 text-left text-sm font-semibold text-slate-900 shadow-sm disabled:cursor-wait disabled:opacity-70"
        onClick={() => setOpen((value) => !value)}
      >
        <span aria-hidden="true">▱</span>
        <span>{triggerLabel}</span>
        <span aria-hidden="true" className="text-sky-700">⌄</span>
      </button>
      <input
        ref={fileInputRef}
        className="sr-only"
        type="file"
        accept="application/json,.json"
        aria-label="Choose tree JSON file"
        onChange={onFileChange}
      />
      {!open && error ? <p role="alert" className="mt-2 rounded-md bg-rose-50 p-2 text-xs text-rose-800">{error}</p> : null}
      {open ? (
        <nav
          ref={menuRef}
          id="crt-tree-menu"
          role="menu"
          aria-label="Tree menu"
          aria-busy={busy}
          className="absolute left-0 top-[calc(100%+0.4rem)] z-50 min-w-64 rounded-xl border border-slate-200 bg-white p-1.5 shadow-floating"
        >
          {error ? <p role="alert" className="m-2 rounded-md bg-rose-50 p-2 text-xs text-rose-800">{error}</p> : null}
          {(["create", "rename", "import", "export", "delete"] as const).map((action) => {
            const disabled = action === "create" || action === "import" ? busy : treeActionDisabled;
            const danger = action === "delete";
            return (
              <button
                key={action}
                ref={(element) => { itemRefs.current[action === "create" ? 0 : action === "rename" ? 1 : action === "import" ? 2 : action === "export" ? 3 : 4] = element; }}
                type="button"
                role="menuitem"
                disabled={disabled}
                title={disabled && action !== "create" && action !== "import" ? "Create or choose a tree first" : undefined}
                className={`flex min-h-10 w-full items-center rounded-lg px-3 py-2 text-left text-sm font-medium hover:bg-slate-50 disabled:cursor-not-allowed disabled:text-slate-400 ${danger ? "text-rose-700 hover:bg-rose-50" : "text-slate-700"}`}
                onClick={() => runAction(action)}
              >
                {actionLabel(action)}
              </button>
            );
          })}
          <div className="my-1 border-t border-slate-100" />
          <p className="px-3 py-1 text-[0.68rem] font-bold uppercase tracking-[0.08em] text-slate-500">Switch tree</p>
          {trees.length === 0 ? (
            <p className="px-3 py-2 text-sm text-slate-500">No other trees yet</p>
          ) : (
            trees.map((tree) => {
              const isCurrent = tree.id === currentTree?.id;
              return (
                <button
                  key={tree.id}
                  type="button"
                  role="menuitem"
                  aria-current={isCurrent ? "true" : undefined}
                  disabled={busy || isCurrent}
                  className="flex min-h-10 w-full items-center rounded-lg px-3 py-2 text-left text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-default disabled:text-slate-500"
                  onClick={() => { closeMenu(); void onSelectTree(tree.id); }}
                >
                  {isCurrent ? `Current tree: ${tree.name}` : `Switch to ${tree.name}`}
                </button>
              );
            })
          )}
          {busy ? <p className="px-3 py-2 text-xs text-slate-500" role="status">Working…</p> : null}
        </nav>
      ) : null}
    </div>
  );
}

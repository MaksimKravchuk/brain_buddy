import { useMemo } from "react";
import {
  ChevronDown,
  Download,
  Pencil,
  Plus,
  Sprout,
  Trash2,
  Upload
} from "lucide-react";
import { twMerge } from "tailwind-merge";

import type { TreeListItem } from "../../api/types";
import {
  DropdownMenu,
  DropdownMenuDivider,
  DropdownMenuItem,
  DropdownMenuSection
} from "../ui/DropdownMenu";

interface TreeMenuProps {
  treeName: string;
  activeTreeId: string | null;
  trees: TreeListItem[] | undefined;
  isDownloading: boolean;
  isImporting: boolean;
  onCreateTree(): void;
  onRenameTree(): void;
  onDownload(): void;
  onImportClick(): void;
  onDeleteTree(): void;
  onSwitchTree(treeId: string): void;
}

export function TreeMenu({
  treeName,
  activeTreeId,
  trees,
  isDownloading,
  isImporting,
  onCreateTree,
  onRenameTree,
  onDownload,
  onImportClick,
  onDeleteTree,
  onSwitchTree
}: TreeMenuProps): JSX.Element {
  const otherTrees = useMemo(
    () => (trees ?? []).filter((tree) => tree.id !== activeTreeId),
    [trees, activeTreeId]
  );

  const hasActiveTree = Boolean(activeTreeId);

  const trigger = (
    <button
      type="button"
      className={twMerge(
        "group flex min-w-0 items-center gap-2 rounded-lg px-2 py-1.5 text-left",
        "transition-colors duration-200 ease-smooth hover:bg-slate-100",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-primary/40"
      )}
      aria-label="Tree menu"
    >
      <Sprout
        className="h-5 w-5 shrink-0 text-brand-primary"
        aria-hidden="true"
      />
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-title font-semibold text-slate-900">
          {treeName}
        </span>
      </span>
      <ChevronDown
        className="h-4 w-4 shrink-0 text-slate-500 transition-transform duration-200 ease-smooth group-aria-[expanded=true]:rotate-180"
        aria-hidden="true"
      />
    </button>
  );

  return (
    <DropdownMenu trigger={trigger} widthClassName="min-w-72" align="start">
      <div className="py-1">
        <DropdownMenuItem leftIcon={<Plus />} onSelect={onCreateTree}>
          New tree
        </DropdownMenuItem>
        <DropdownMenuItem
          leftIcon={<Pencil />}
          onSelect={onRenameTree}
          disabled={!hasActiveTree}
        >
          Rename tree
        </DropdownMenuItem>
        <DropdownMenuItem
          leftIcon={<Download />}
          onSelect={onDownload}
          disabled={!hasActiveTree || isDownloading}
        >
          {isDownloading ? "Exporting…" : "Export to file"}
        </DropdownMenuItem>
        <DropdownMenuItem
          leftIcon={<Upload />}
          onSelect={onImportClick}
          disabled={isImporting}
        >
          {isImporting ? "Importing…" : "Import from file"}
        </DropdownMenuItem>
        <DropdownMenuItem
          leftIcon={<Trash2 />}
          onSelect={onDeleteTree}
          disabled={!hasActiveTree}
          variant="danger"
        >
          Delete tree
        </DropdownMenuItem>
      </div>

      <DropdownMenuDivider />

      <DropdownMenuSection label="Switch tree">
        {otherTrees.length === 0 ? (
          <div className="px-3 py-2 text-xs text-slate-400">
            {trees && trees.length > 0 ? "No other trees" : "No other trees yet"}
          </div>
        ) : (
          <div className="max-h-64 overflow-y-auto">
            {otherTrees.map((tree) => (
              <DropdownMenuItem
                key={tree.id}
                onSelect={() => onSwitchTree(tree.id)}
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-sm text-slate-700">
                    {tree.name}
                  </span>
                  <span className="truncate text-[11px] text-slate-400">
                    Updated {formatRelativeTime(tree.updated_at)}
                  </span>
                </span>
              </DropdownMenuItem>
            ))}
          </div>
        )}
      </DropdownMenuSection>
    </DropdownMenu>
  );
}

function formatRelativeTime(isoString: string): string {
  const then = Date.parse(isoString);
  if (Number.isNaN(then)) {
    return isoString;
  }
  const diffMs = Date.now() - then;
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 30) return `${diffDay}d ago`;
  const diffMonth = Math.round(diffDay / 30);
  if (diffMonth < 12) return `${diffMonth}mo ago`;
  const diffYear = Math.round(diffMonth / 12);
  return `${diffYear}y ago`;
}

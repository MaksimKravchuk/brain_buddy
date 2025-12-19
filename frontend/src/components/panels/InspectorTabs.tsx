import { useTreeStore } from "../../stores/treeStore";
import { useUiStore } from "../../stores/uiStore";

const tabs: Array<{ id: "node" | "relation" | "versions"; label: string }> = [
  { id: "node", label: "Node" },
  { id: "relation", label: "Relation" },
  { id: "versions", label: "Versions" }
];

export function InspectorTabs(): JSX.Element {
  const inspectorTab = useUiStore((state) => state.inspectorTab);
  const setInspectorTab = useUiStore((state) => state.setInspectorTab);
  const selection = useTreeStore((state) => state.selection);

  return (
    <div className="flex rounded-full border border-slate-200 bg-surface-sunken/80 p-1 text-xs shadow-sm">
      {tabs.map((tab) => {
        const isActive = inspectorTab === tab.id;
        const isDisabled =
          (tab.id === "node" && selection.type !== "node") ||
          (tab.id === "relation" && selection.type !== "relation");

        return (
          <button
            key={tab.id}
            type="button"
            disabled={tab.id === "versions" ? false : isDisabled}
            onClick={() => setInspectorTab(tab.id)}
            className={`flex-1 rounded-full px-3 py-1 font-medium transition ${
              isActive ? "bg-brand-primary/20 text-slate-900" : "text-slate-600"
            } ${isDisabled && tab.id !== "versions" ? "cursor-not-allowed opacity-40" : ""}`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

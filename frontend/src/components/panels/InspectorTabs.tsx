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

  const activeIndex = tabs.findIndex((tab) => tab.id === inspectorTab);
  const indicatorWidth = 100 / tabs.length;
  const indicatorLeft = activeIndex * indicatorWidth;

  return (
    <div className="relative flex rounded-full border border-slate-200 bg-surface-sunken/80 p-1 text-xs shadow-soft">
      <span
        aria-hidden
        className="pointer-events-none absolute inset-y-1 rounded-full bg-white shadow-soft transition-[left,width] duration-300 ease-smooth"
        style={{
          left: `calc(${indicatorLeft}% + 4px)`,
          width: `calc(${indicatorWidth}% - 8px)`
        }}
      />
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
            className={`relative z-10 flex-1 rounded-full px-3 py-1.5 font-medium transition-colors duration-200 ease-smooth ${
              isActive ? "text-slate-900" : "text-slate-500 hover:text-slate-700"
            } ${isDisabled && tab.id !== "versions" ? "cursor-not-allowed opacity-40 hover:text-slate-500" : ""}`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

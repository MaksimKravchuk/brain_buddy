import { useEffect, useState } from "react";
import type { GraphRelation, GraphState } from "./graphModel";

type CrtInspectorProps = {
  graph: GraphState;
  onChange: (next: GraphState) => void;
  onDeleteRelation?: (relationId: string) => void;
};

function relationText(relation: GraphRelation, graph: GraphState): string {
  const source = graph.nodes.find((node) => node.id === relation.sourceId)?.label || "Untitled card";
  const target = graph.nodes.find((node) => node.id === relation.targetId)?.label || "Untitled card";
  return `Delete relation from ${source} to ${target}`;
}

export function CrtInspector({ graph, onChange, onDeleteRelation }: CrtInspectorProps): React.JSX.Element {
  const selected = graph.nodes.find((node) => node.id === graph.selectedNodeId);
  const selectedRelation = graph.relations.find((relation) => relation.id === graph.selectedRelationId);
  const [draftLabel, setDraftLabel] = useState(selected?.label ?? "");
  const [announcement, setAnnouncement] = useState("");

  useEffect(() => {
    setDraftLabel(selected?.label ?? "");
    setAnnouncement("");
  }, [selected?.id, selected?.label]);

  if (!selected) {
    return (
      <aside className="crt-inspector" aria-label="Card inspector">
        <p className="crt-inspector-eyebrow">Inspector</p>
        <h2 className="crt-inspector-title">{selectedRelation ? "Relation inspector" : "Select a card"}</h2>
        {selectedRelation ? (
          <>
            <p className="crt-inspector-empty">{relationText(selectedRelation, graph).replace("Delete ", "Selected ")}</p>
            <button
              type="button"
              data-crt-native="true"
              aria-label={relationText(selectedRelation, graph)}
              onClick={() => onDeleteRelation?.(selectedRelation.id)}
            >
              Delete relation
            </button>
          </>
        ) : (
          <p className="crt-inspector-empty">Choose a card to inspect its label and causal links.</p>
        )}
      </aside>
    );
  }

  const incoming = graph.relations
    .filter((relation) => relation.targetId === selected.id)
    .map((relation) => ({ relation, node: graph.nodes.find((node) => node.id === relation.sourceId) }))
    .filter((entry): entry is { relation: GraphRelation; node: NonNullable<typeof entry.node> } => entry.node !== undefined);
  const outgoing = graph.relations
    .filter((relation) => relation.sourceId === selected.id)
    .map((relation) => ({ relation, node: graph.nodes.find((node) => node.id === relation.targetId) }))
    .filter((entry): entry is { relation: GraphRelation; node: NonNullable<typeof entry.node> } => entry.node !== undefined);

  const updateLabel = (label: string) => {
    if (!label.trim()) {
      setDraftLabel(selected.label);
      setAnnouncement("Card label cannot be blank; existing value preserved.");
      return;
    }
    setDraftLabel(label);
    setAnnouncement("");
    onChange({
      ...graph,
      nodes: graph.nodes.map((node) => (node.id === selected.id ? { ...node, label } : node)),
      editingNodeId: selected.id
    });
  };

  const relationList = (heading: string, entries: typeof incoming) => (
    <section className="crt-inspector-relations" aria-labelledby={`crt-${heading.toLowerCase().replace(/ /g, "-")}`}>
      <h3 id={`crt-${heading.toLowerCase().replace(/ /g, "-")}`}>{heading}</h3>
      {entries.length > 0 ? (
        <ul>
          {entries.map(({ relation, node }) => (
            <li key={relation.id}>
              <button
                type="button"
                data-crt-native="true"
                onClick={() => onChange({ ...graph, selectedNodeId: node.id, editingNodeId: null, selectedRelationId: null })}
              >
                {node.label || "Untitled card"}
              </button>
              <button
                type="button"
                data-crt-native="true"
                aria-label={relationText(relation, graph)}
                onClick={() => onDeleteRelation?.(relation.id)}
              >
                Delete relation
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="crt-inspector-empty">No {heading.toLowerCase()}.</p>
      )}
    </section>
  );

  return (
    <aside className="crt-inspector" aria-label="Card inspector">
      <p className="crt-inspector-eyebrow">Selected card</p>
      <h2 className="crt-inspector-title">Card inspector</h2>
      <label className="crt-inspector-label">
        Card label
        <input
          aria-label="Card label"
          data-crt-native="true"
          value={draftLabel}
          onChange={(event) => updateLabel(event.currentTarget.value)}
          onFocus={() => onChange({ ...graph, editingNodeId: selected.id })}
        />
      </label>
      <p className="crt-canvas-announcement" role="status" aria-live="polite" aria-atomic="true">{announcement}</p>
      {relationList("Incoming causes", incoming)}
      {relationList("Outgoing effects", outgoing)}
    </aside>
  );
}

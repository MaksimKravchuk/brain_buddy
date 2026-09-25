import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { useEffect, useRef, useState } from "react";

export type CrtCardBadge = "Effect" | "Root cause" | "Intermediate";

export type CrtCardNodeData = {
  label: string;
  badge?: CrtCardBadge;
  selected: boolean;
  editing: boolean;
  connectionMode: boolean;
  onFocusCard?: (nodeId: string) => void;
  onEditCard?: (nodeId: string) => void;
  onCommitLabel?: (nodeId: string, label: string) => boolean;
  onCancelLabel?: (nodeId: string) => void;
  onConnectorActivate?: (nodeId: string, side: "source" | "target") => void;
  onConnectorPointerDown?: (nodeId: string, side: "source" | "target", event: React.PointerEvent<HTMLButtonElement>) => void;
};

export type CrtCard = Node<CrtCardNodeData, "crt-card">;

export function CrtCardNode({ id, data, selected }: NodeProps<CrtCard>): React.JSX.Element {
  const editorRef = useRef<HTMLInputElement>(null);
  const cardRef = useRef<HTMLButtonElement>(null);
  const restoreCardFocusRef = useRef(false);
  const [draftLabel, setDraftLabel] = useState(data.label);
  const isSelected = selected || data.selected;

  useEffect(() => {
    setDraftLabel(data.label);
  }, [data.editing, data.label]);

  useEffect(() => {
    if (data.editing) {
      editorRef.current?.focus();
      editorRef.current?.select();
      return;
    }
    if (!restoreCardFocusRef.current) return;
    restoreCardFocusRef.current = false;
    cardRef.current?.focus();
  }, [data.editing]);

  const commitLabel = (restoreCardFocus = false): void => {
    restoreCardFocusRef.current = restoreCardFocus;
    const committed = data.onCommitLabel?.(id, draftLabel) ?? true;
    if (!committed) {
      restoreCardFocusRef.current = false;
      setDraftLabel(data.label);
      window.requestAnimationFrame(() => editorRef.current?.focus());
    }
  };

  const activateConnector = (side: "source" | "target", event: React.MouseEvent<HTMLButtonElement>): void => {
    event.stopPropagation();
    data.onConnectorActivate?.(id, side);
  };

  const startConnectorPointer = (side: "source" | "target", event: React.PointerEvent<HTMLButtonElement>): void => {
    event.stopPropagation();
    data.onConnectorPointerDown?.(id, side, event);
  };

  return (
    <div className={`crt-card-node${isSelected ? " is-selected" : ""}`}>
      <Handle className={`crt-card-handle crt-card-handle-target${data.connectionMode ? " is-visible" : ""}`} type="target" position={Position.Bottom} aria-hidden="true" />
      {data.connectionMode ? (
        <button
          type="button"
          className="crt-card-connector crt-card-connector-target"
          data-crt-native="true"
          data-connector-node-id={id}
          data-connector-side="target"
          aria-label={`Connect into bottom of ${data.label || "Untitled card"}`}
          title={`Connect into bottom of ${data.label || "Untitled card"}`}
          onMouseDown={(event) => event.stopPropagation()}
          onPointerDown={(event) => startConnectorPointer("target", event)}
          onClick={(event) => activateConnector("target", event)}
        >
          ↧
        </button>
      ) : null}
      {data.editing ? (
        <input
          ref={editorRef}
          type="text"
          className="crt-card-editor"
          data-card-editor-id={id}
          data-crt-native="true"
          aria-label={`Edit card label${data.label ? ` for ${data.label}` : ""}`}
          value={draftLabel}
          onChange={(event) => {
            const nextLabel = event.currentTarget.value;
            setDraftLabel(nextLabel);
          }}
          onBlur={() => commitLabel()}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commitLabel(true);
            } else if (event.key === "Escape") {
              event.preventDefault();
              restoreCardFocusRef.current = true;
              data.onCancelLabel?.(id);
            }
          }}
        />
      ) : (
        <button
          ref={cardRef}
          type="button"
          className="crt-card-button"
          data-crt-card="true"
          data-node-id={id}
          aria-label={`${data.badge ? `${data.badge}: ` : ""}${data.label || "Untitled card"}`}
          title="Double-click to edit card label"
          aria-pressed={isSelected}
          tabIndex={isSelected ? 0 : -1}
          onFocus={() => data.onFocusCard?.(id)}
          onDoubleClick={() => data.onEditCard?.(id)}
        >
          {data.badge ? <span className="crt-card-badge">{data.badge}</span> : null}
          <span className="crt-card-label">{data.label || "Untitled card"}</span>
        </button>
      )}
      {data.connectionMode ? (
        <button
          type="button"
          className="crt-card-connector crt-card-connector-source"
          data-crt-native="true"
          data-connector-node-id={id}
          data-connector-side="source"
          aria-label={`Connect from top of ${data.label || "Untitled card"}`}
          title={`Connect from top of ${data.label || "Untitled card"}`}
          onMouseDown={(event) => event.stopPropagation()}
          onPointerDown={(event) => startConnectorPointer("source", event)}
          onClick={(event) => activateConnector("source", event)}
        >
          ↥
        </button>
      ) : null}
      <Handle className={`crt-card-handle crt-card-handle-source${data.connectionMode ? " is-visible" : ""}`} type="source" position={Position.Top} aria-hidden="true" />
    </div>
  );
}

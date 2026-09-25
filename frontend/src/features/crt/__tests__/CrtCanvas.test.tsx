import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createGraphState, type GraphState, type NewNodeIds } from "../graphModel";
import { ReactFlowProvider } from "@xyflow/react";
import { CrtCanvas } from "../CrtCanvas";
import { CrtCardNode } from "../CrtCardNode";
import { CrtInspector } from "../CrtInspector";

const flowHarness = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
  fitView: vi.fn(() => Promise.resolve()),
  setEdges: vi.fn(),
  zoomIn: vi.fn(),
  zoomOut: vi.fn(),
  getViewport: vi.fn(() => ({ x: 20, y: 30, zoom: 0.8 })),
  setViewport: vi.fn()
}));

vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  const FlowHarness = (props: Parameters<typeof actual.ReactFlow>[0]) => {
    flowHarness.props = props as unknown as Record<string, unknown>;
    return createElement(actual.ReactFlow, props);
  };
  return {
    ...actual,
    ReactFlow: FlowHarness,
    useReactFlow: () => ({
      fitView: flowHarness.fitView,
      setEdges: flowHarness.setEdges,
      zoomIn: flowHarness.zoomIn,
      zoomOut: flowHarness.zoomOut,
      getViewport: flowHarness.getViewport,
      setViewport: flowHarness.setViewport
    })
  };
});

const ids = (nodeId: string, relationId: string): (() => NewNodeIds) => () => ({ nodeId, relationId });

const initialGraph = (): GraphState =>
  createGraphState({
    nodes: [
      { id: "effect-1", label: "Server is unreliable", position: { x: 260, y: 40 } },
      { id: "cause-1", label: "Deployments are rushed", position: { x: 260, y: 260 } }
    ],
    relations: [{ id: "relation-1", sourceId: "cause-1", targetId: "effect-1" }],
    selectedNodeId: "cause-1",
    viewportCenter: { x: 260, y: 160 }
  });

function ControlledCanvas({ graph, onChange, createIds = ids("new-card", "new-relation") }: { graph: GraphState; onChange: (next: GraphState) => void; createIds?: () => NewNodeIds }) {
  const [current, setCurrent] = useState(graph);
  return (
    <CrtCanvas
      graph={current}
      onChange={(next) => {
        setCurrent(next);
        onChange(next);
      }}
      createIds={createIds}
    />
  );
}

function renderCanvas(
  graph: GraphState = initialGraph(),
  onChange = vi.fn(),
  createIds: () => NewNodeIds = ids("new-card", "new-relation")
) {
  return render(<ControlledCanvas graph={graph} onChange={onChange} createIds={createIds} />);
}

function cardButton(nodeId: string): HTMLButtonElement {
  const button = document.querySelector<HTMLButtonElement>(`[data-node-id="${nodeId}"]`);
  if (!button) throw new Error(`card ${nodeId} was not rendered`);
  return button;
}

function flowCallback(name: string): (...args: unknown[]) => unknown {
  const callback = flowHarness.props?.[name];
  if (typeof callback !== "function") throw new Error(`React Flow callback ${name} was not captured`);
  return callback as (...args: unknown[]) => unknown;
}

function currentFlowProps(): Record<string, unknown> {
  if (!flowHarness.props) throw new Error("React Flow props were not captured");
  return flowHarness.props;
}

beforeEach(() => {
  flowHarness.fitView.mockClear();
  flowHarness.setEdges.mockClear();
  flowHarness.zoomIn.mockClear();
  flowHarness.zoomOut.mockClear();
  flowHarness.getViewport.mockClear();
  flowHarness.setViewport.mockClear();
  flowHarness.props = null;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    () => new DOMRect(0, 0, 220, 100)
  );
});

afterEach(() => {
  vi.restoreAllMocks();
});

vi.stubGlobal("DOMMatrixReadOnly", class {
  readonly m22 = 1;
});

vi.stubGlobal("ResizeObserver", class {
  private readonly callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }

  observe(target: Element): void {
    this.callback([{ target, contentRect: { width: 220, height: 100 } } as ResizeObserverEntry], this as unknown as ResizeObserver);
  }

  unobserve(): void {}
  disconnect(): void {}
});

describe("CrtCanvas — 019-FR-005 through 019-FR-016", () => {
  it("019-FR-005 019-FR-006 019-FR-022 019-FR-023 019-FR-024 019-SC-007 renders native cards, semantic badges, a directed curved arrow, and the selected-card inspector", async () => {
    renderCanvas();

    expect(screen.getByRole("group", { name: "Current Reality Tree canvas" })).toBeInTheDocument();
    expect(cardButton("effect-1")).toHaveAttribute("aria-label", "Effect: Server is unreliable");
    expect(cardButton("cause-1")).toHaveAttribute("aria-label", "Root cause: Deployments are rushed");
    expect(cardButton("cause-1")).toHaveAttribute("aria-pressed", "true");
    const edge = await screen.findByTestId("crt-edge-relation-1");
    expect(edge).toHaveAttribute("aria-label", "Relation from Deployments are rushed to Server is unreliable");
    const relationPath = within(edge).getByRole("img", { name: "Directed relation" });
    const markerEnd = relationPath.getAttribute("marker-end");
    expect(markerEnd).toMatch(/^url\(['"]?#.+['"]?\)$/);
    const markerId = markerEnd?.match(/^url\(['"]?#([^'")]+)['"]?\)$/)?.[1];
    const markers = [...document.querySelectorAll("svg marker")];
    expect(markers.length).toBeGreaterThan(0);
    expect(markers.some((marker) => marker.id === markerId)).toBe(true);
    expect(relationPath.getAttribute("d")).toMatch(/C/);
    expect(document.querySelectorAll("[data-testid='crt-edge-relation-1']")).toHaveLength(1);
    expect(screen.getByRole("complementary", { name: "Card inspector" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Card label" })).toHaveValue("Deployments are rushed");
    expect(screen.getByRole("button", { name: "Fit all cards" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zoom out" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeInTheDocument();
  });

  it("does not show or expose a disconnected badge for an isolated card", () => {
    renderCanvas(createGraphState({
      nodes: [{ id: "isolated", label: "Unconnected idea", position: { x: 0, y: 0 } }],
      relations: [],
      selectedNodeId: "isolated",
      viewportCenter: { x: 0, y: 0 }
    }));

    const card = cardButton("isolated");
    expect(card).toHaveAccessibleName("Unconnected idea");
    expect(card).not.toHaveAccessibleName(/Disconnected/);
    expect(screen.queryByText("Disconnected")).not.toBeInTheDocument();
  });

  it("shows an accessible canvas toolbar for the selected relation and preserves its cause-to-effect direction", async () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);

    fireEvent.click(await screen.findByTestId("crt-edge-relation-1"));

    const toolbar = await screen.findByRole("toolbar", { name: "Selected relation actions" });
    expect(within(toolbar).getByRole("button", { name: "Go to Cause" })).toBeInTheDocument();
    expect(within(toolbar).getByRole("button", { name: "Go to Effect" })).toBeInTheDocument();
    expect(within(toolbar).getByRole("button", { name: "Delete relation" })).toBeInTheDocument();

    fireEvent.click(within(toolbar).getByRole("button", { name: "Go to Cause" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      selectedNodeId: "cause-1",
      selectedRelationId: null
    }));

    fireEvent.click(await screen.findByTestId("crt-edge-relation-1"));
    fireEvent.click(within(await screen.findByRole("toolbar", { name: "Selected relation actions" })).getByRole("button", { name: "Go to Effect" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      selectedNodeId: "effect-1",
      selectedRelationId: null
    }));
  });

  it("deletes a selected relation from the canvas toolbar", async () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);

    fireEvent.click(await screen.findByTestId("crt-edge-relation-1"));
    fireEvent.click(within(await screen.findByRole("toolbar", { name: "Selected relation actions" })).getByRole("button", { name: "Delete relation" }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      relations: [],
      selectedRelationId: null
    }));
  });

  it("keeps the canvas zoom at a legible maximum and leaves React Flow attribution visible", () => {
    renderCanvas();

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));

    expect(screen.getByLabelText("Zoom level")).toHaveTextContent("100%");
    expect(screen.getByText("React Flow")).toBeInTheDocument();
  });

  it("019-FR-014 reports pointer zoom changes in the graph state so autosave can retain the viewport", () => {
    const onChange = vi.fn();
    renderCanvas(createGraphState({ ...initialGraph(), viewportZoom: 0.75 }), onChange);

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ viewportZoom: 0.85 }));
  });

  it("keeps the 200-card render inputs stable when only persisted viewport state changes", () => {
    const graph = createGraphState({ ...initialGraph(), viewportZoom: 0.75 });
    renderCanvas(graph);
    const nodes = currentFlowProps().nodes;
    const edges = currentFlowProps().edges;
    flowHarness.setEdges.mockClear();

    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));

    expect(currentFlowProps().nodes).toBe(nodes);
    expect(currentFlowProps().edges).toBe(edges);
    expect(flowHarness.setEdges).not.toHaveBeenCalled();
  });

  it("renders live drag positions without committing durable graph state until drag stop", () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);

    const cause = (currentFlowProps().nodes as Array<{ id: string; position: { x: number; y: number } }>).find(
      (node) => node.id === "cause-1"
    );
    expect(cause).toBeDefined();

    act(() => {
      flowCallback("onNodesChange")([
        { id: "cause-1", type: "position", position: { x: 320, y: 300 }, dragging: true }
      ]);
    });

    expect((currentFlowProps().nodes as Array<{ id: string; position: { x: number; y: number } }>).find(
      (node) => node.id === "cause-1"
    )?.position).toEqual({ x: 320, y: 300 });
    expect(onChange).not.toHaveBeenCalled();

    act(() => {
      flowCallback("onNodeDragStop")({}, { id: "cause-1", position: { x: 320, y: 300 } });
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      nodes: expect.arrayContaining([expect.objectContaining({ id: "cause-1", position: { x: 320, y: 300 } })])
    }));
  });

  it("019-FR-010 hides native handles until Connect mode reveals them", () => {
    renderCanvas();

    const handles = () => [...document.querySelectorAll(".crt-card-handle")];
    expect(handles()).toHaveLength(4);
    expect(handles().every((handle) => !handle.classList.contains("is-visible"))).toBe(true);
    expect(handles().every((handle) => handle.getAttribute("aria-hidden") === "true")).toBe(true);
    expect(handles().every((handle) => !handle.hasAttribute("aria-label"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Connect cards" }));

    expect(handles().every((handle) => handle.classList.contains("is-visible"))).toBe(true);
  });

  it("019-FR-007 019-SC-001 fits the whole graph after keyboard creation without exceeding the canvas zoom cap", async () => {
    renderCanvas();
    flowHarness.fitView.mockClear();

    fireEvent.keyDown(cardButton("cause-1"), { key: "Enter" });

    await waitFor(() => {
      expect(flowHarness.fitView).toHaveBeenCalledWith({ duration: 160, padding: 0.2, maxZoom: 1 });
    });
  });

  it("keeps directed edge curves between their card endpoints", async () => {
    renderCanvas();

    const edge = await screen.findByTestId("crt-edge-relation-1");
    const path = within(edge).getByRole("img", { name: "Directed relation" });
    const coordinates = (path.getAttribute("d")?.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
    const yCoordinates = coordinates.filter((_, index) => index % 2 === 1);

    expect(Math.min(...yCoordinates)).toBeGreaterThanOrEqual(40);
    expect(Math.max(...yCoordinates)).toBeLessThanOrEqual(352);
  });

  it("019-SC-003 routes multiple incoming relations to distinct target-side endpoints so arrowheads stay traceable", async () => {
    renderCanvas(
      createGraphState({
        nodes: [
          { id: "effect-1", label: "Server is unreliable", position: { x: 260, y: 40 } },
          { id: "cause-1", label: "Deployments are rushed", position: { x: 120, y: 260 } },
          { id: "cause-2", label: "Checks are skipped", position: { x: 124, y: 400 } }
        ],
        relations: [
          { id: "relation-1", sourceId: "cause-1", targetId: "effect-1" },
          { id: "relation-2", sourceId: "cause-2", targetId: "effect-1" }
        ],
        selectedNodeId: "cause-1"
      })
    );

    const firstPath = within(await screen.findByTestId("crt-edge-relation-1")).getByRole("img", { name: "Directed relation" });
    const secondPath = within(await screen.findByTestId("crt-edge-relation-2")).getByRole("img", { name: "Directed relation" });
    const firstCoordinates = (firstPath.getAttribute("d")?.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
    const secondCoordinates = (secondPath.getAttribute("d")?.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);

    expect(Math.abs(firstCoordinates[4] - secondCoordinates[4])).toBeGreaterThanOrEqual(32);
    expect(firstPath).toHaveAttribute("marker-end");
    expect(secondPath).toHaveAttribute("marker-end");
    expect(Math.abs(firstCoordinates[6] - secondCoordinates[6])).toBeGreaterThanOrEqual(32);
  });

  it("019-FR-007 creates a cause below the selected card with Enter and reports the visible graph change", () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    const selected = cardButton("cause-1");

    fireEvent.keyDown(selected, { key: "Enter" });

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0]?.[0] as GraphState;
    expect(next.nodes).toContainEqual(expect.objectContaining({ id: "new-card", label: "" }));
    expect(next.relations).toContainEqual({ id: "new-relation", sourceId: "new-card", targetId: "cause-1" });
  });

  it("019-FR-008 creates a sibling with Tab while composite canvas mode is active", () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    const selected = cardButton("cause-1");

    fireEvent.click(selected);
    onChange.mockClear();
    fireEvent.keyDown(cardButton("cause-1"), { key: "Tab" });

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0]?.[0] as GraphState;
    expect(next.nodes).toContainEqual(expect.objectContaining({ id: "new-card", label: "" }));
    expect(next.relations).toContainEqual({ sourceId: "new-card", targetId: "effect-1", id: "new-relation" });
  });

  it("019-FR-013 preserves native inspector input keys instead of creating a card", () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    const input = screen.getByRole("textbox", { name: "Card label" });
    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });

    input.dispatchEvent(tab);
    fireEvent.keyDown(input, { key: "Enter" });

    expect(tab.defaultPrevented).toBe(false);
    expect(onChange).not.toHaveBeenCalled();
    expect(within(screen.getByRole("complementary", { name: "Card inspector" })).getByText("Incoming causes")).toBeInTheDocument();
  });

  it.each([
    ["ArrowUp", "cause-1", "effect-1"],
    ["ArrowDown", "effect-1", "cause-1"]
  ] as const)("019-FR-013 creates a sibling after %s traversal instead of exiting the canvas", async (direction, startId, destinationId) => {
    const onChange = vi.fn();
    renderCanvas(createGraphState({ ...initialGraph(), selectedNodeId: startId }), onChange);
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });

    fireEvent.focus(cardButton(startId));
    fireEvent.keyDown(canvas, { key: direction });
    await waitFor(() => expect(cardButton(destinationId)).toHaveFocus());
    onChange.mockClear();

    fireEvent.keyDown(canvas, { key: "Tab" });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0]?.[0]).toEqual(expect.objectContaining({
      nodes: expect.arrayContaining([expect.objectContaining({ id: "new-card" })])
    }));
  });

  it("019-FR-007 focuses a newly created card's inline editor and commits its label", async () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);

    fireEvent.keyDown(cardButton("cause-1"), { key: "Enter" });
    const editor = await waitFor(() => {
      const element = document.querySelector<HTMLInputElement>('[data-card-editor-id="new-card"]');
      if (!element) throw new Error("new card editor was not rendered");
      return element;
    });

    expect(editor).toHaveFocus();
    fireEvent.change(editor, { target: { value: "Cache misses are unbounded" } });
    fireEvent.keyDown(editor, { key: "Enter" });

    const next = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as GraphState;
    expect(next.nodes).toContainEqual(expect.objectContaining({ id: "new-card", label: "Cache misses are unbounded" }));
    expect(next.editingNodeId).toBeNull();
  });

  it("019-FR-015 rejects whitespace-only inline labels instead of committing them", async () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);

    fireEvent.keyDown(cardButton("cause-1"), { key: "Enter" });
    const editor = await waitFor(() => document.querySelector<HTMLInputElement>('[data-card-editor-id="new-card"]'));
    if (!editor) throw new Error("new card editor was not rendered");
    const callsBeforeInvalidCommit = onChange.mock.calls.length;

    fireEvent.change(editor, { target: { value: "   " } });
    fireEvent.keyDown(editor, { key: "Enter" });

    expect(onChange).toHaveBeenCalledTimes(callsBeforeInvalidCommit);
    expect(editor).toHaveFocus();
  });

  it("019-FR-010 deletes the selected relation with Delete and an accessible relation control", () => {
    const onChange = vi.fn();
    const graph = createGraphState({
      ...initialGraph(),
      selectedNodeId: null,
      selectedRelationId: "relation-1"
    });
    const firstRender = renderCanvas(graph, onChange);

    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.keyDown(canvas, { key: "Delete" });
    expect((onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as GraphState).relations).toEqual([]);

    onChange.mockClear();
    firstRender.unmount();
    renderCanvas(graph, onChange);
    fireEvent.click(within(screen.getByRole("toolbar", { name: "Selected relation actions" })).getByRole("button", { name: "Delete relation" }));
    expect((onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as GraphState).relations).toEqual([]);
  });

  it("019-FR-012 activates Space-held canvas panning without hijacking native inputs", () => {
    renderCanvas();
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    const space = new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true });
    act(() => canvas.dispatchEvent(space));
    expect(space.defaultPrevented).toBe(true);
    expect(screen.getByTestId("crt-flow-region")).toHaveAttribute("data-pan-active", "true");

    const input = screen.getByRole("textbox", { name: "Card label" });
    const nativeSpace = new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true });
    act(() => input.dispatchEvent(nativeSpace));
    expect(nativeSpace.defaultPrevented).toBe(false);

    act(() => canvas.dispatchEvent(new KeyboardEvent("keyup", { key: " ", bubbles: true })));
    expect(screen.getByTestId("crt-flow-region")).toHaveAttribute("data-pan-active", "false");
  });

  it("019-FR-013 019-SC-002 leaves ordinary Tab navigation intact when it first enters the canvas", () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });

    fireEvent.focus(canvas);
    fireEvent.keyDown(canvas, { key: "Tab" });

    expect(onChange).not.toHaveBeenCalled();
    expect(document.querySelector('[data-node-id="new-card"]')).not.toBeInTheDocument();
  });

  it("creates an unlinked root when Tab starts from an empty canvas", () => {
    const onChange = vi.fn();
    renderCanvas(createGraphState(), onChange);
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.keyDown(canvas, { key: "Tab" });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      nodes: [expect.objectContaining({ id: "new-card", label: "" })],
      relations: []
    }));
  });

  it("019-FR-010 exposes keyboard connector controls that preserve cause-to-effect direction", () => {
    const onChange = vi.fn();
    const graph = createGraphState({
      nodes: [
        { id: "cause-1", label: "Cause", position: { x: 100, y: 280 } },
        { id: "effect-1", label: "Effect", position: { x: 100, y: 100 } }
      ],
      selectedNodeId: "cause-1"
    });
    renderCanvas(graph, onChange);
    fireEvent.click(screen.getByRole("button", { name: "Connect cards" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect from top of Cause" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect into bottom of Effect" }));

    expect((onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as GraphState).relations).toEqual([
      { id: "new-relation", sourceId: "cause-1", targetId: "effect-1" }
    ]);
  });

  it("covers inline editor cancel, blur commit, card focus entry, and connector mouse handling", async () => {
    const onChange = vi.fn();
    const graph = createGraphState({
      ...initialGraph(),
      editingNodeId: "cause-1"
    });
    const firstView = renderCanvas(graph, onChange);

    const editor = await waitFor(() => document.querySelector<HTMLInputElement>('[data-card-editor-id="cause-1"]'));
    if (!editor) throw new Error("cause editor was not rendered");
    fireEvent.change(editor, { target: { value: "Updated cause" } });
    fireEvent.blur(editor);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ editingNodeId: null }));

    onChange.mockClear();
    firstView.unmount();
    const rerenderedGraph = createGraphState({ ...initialGraph(), editingNodeId: "cause-1" });
    const view = renderCanvas(rerenderedGraph, onChange);
    const editingAgain = await waitFor(() => document.querySelector<HTMLInputElement>('[data-card-editor-id="cause-1"]'));
    if (!editingAgain) throw new Error("cause editor was not rendered after rerender");
    fireEvent.keyDown(editingAgain, { key: "Escape" });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ editingNodeId: null }));
    await waitFor(() => expect(cardButton("cause-1")).toHaveFocus());
    view.unmount();

    renderCanvas();
    fireEvent.focus(cardButton("cause-1"));
    fireEvent.focus(cardButton("effect-1"));
    fireEvent.click(screen.getByRole("button", { name: "Connect cards" }));
    const source = screen.getByRole("button", { name: "Connect from top of Deployments are rushed" });
    const sourceMouseDown = new window.MouseEvent("mousedown", { bubbles: true });
    Object.defineProperty(sourceMouseDown, "view", { value: source.ownerDocument.defaultView });
    source.dispatchEvent(sourceMouseDown);
    fireEvent.click(source);
    const target = screen.getByRole("button", { name: "Connect into bottom of Server is unreliable" });
    const targetMouseDown = new window.MouseEvent("mousedown", { bubbles: true });
    Object.defineProperty(targetMouseDown, "view", { value: target.ownerDocument.defaultView });
    target.dispatchEvent(targetMouseDown);
    fireEvent.click(target);
    fireEvent.click(target);
    fireEvent.click(source);
  });

  it("covers card defaults when optional callbacks are absent", () => {
    const props = {
      id: "standalone",
      data: {
        label: "",
        badge: undefined,
        selected: false,
        editing: true,
        connectionMode: true
      },
      selected: false
    } as Parameters<typeof CrtCardNode>[0];
    const view = render(
      <ReactFlowProvider>
        <CrtCardNode {...props} />
      </ReactFlowProvider>
    );
    const editor = screen.getByRole("textbox", { name: "Edit card label" });
    fireEvent.keyDown(editor, { key: "Enter" });
    fireEvent.keyDown(editor, { key: "Escape" });
    view.rerender(
      <ReactFlowProvider>
        <CrtCardNode {...props} data={{ ...props.data, editing: false }} />
      </ReactFlowProvider>
    );
    fireEvent.focus(screen.getByRole("button", { name: "Untitled card" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect into bottom of Untitled card" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect from top of Untitled card" }));
  });

  it("returns focus to the card after committing its inline editor with Enter", async () => {
    function EditableCard(): React.JSX.Element {
      const [editing, setEditing] = useState(true);
      const props = {
        id: "focus-card",
        data: {
          label: "Focused card",
          badge: undefined,
          selected: true,
          editing,
          connectionMode: false,
          onCommitLabel: () => {
            setEditing(false);
            return true;
          }
        },
        selected: true
      } as unknown as Parameters<typeof CrtCardNode>[0];
      return <CrtCardNode {...props} />;
    }

    render(
      <ReactFlowProvider>
        <EditableCard />
      </ReactFlowProvider>
    );
    const editor = screen.getByRole("textbox", { name: "Edit card label for Focused card" });
    expect(editor).toHaveFocus();
    fireEvent.keyDown(editor, { key: "Enter" });

    await waitFor(() => expect(screen.getByRole("button", { name: "Focused card" })).toHaveFocus());
  });

  it("returns focus after a delayed controlled editor cancellation", async () => {
    function EditableCard(): React.JSX.Element {
      const [editing, setEditing] = useState(true);
      const props = {
        id: "delayed-focus-card",
        data: {
          label: "Delayed focus card",
          badge: undefined,
          selected: true,
          editing,
          connectionMode: false,
          onCancelLabel: () => {
            window.requestAnimationFrame(() => {
              window.requestAnimationFrame(() => setEditing(false));
            });
          }
        },
        selected: true
      } as unknown as Parameters<typeof CrtCardNode>[0];
      return <CrtCardNode {...props} />;
    }

    render(
      <ReactFlowProvider>
        <EditableCard />
      </ReactFlowProvider>
    );
    const editor = screen.getByRole("textbox", { name: "Edit card label for Delayed focus card" });
    expect(editor).toHaveFocus();
    fireEvent.keyDown(editor, { key: "Escape" });

    await waitFor(() => expect(screen.getByRole("button", { name: "Delayed focus card" })).toHaveFocus());
  });

  it("undoes keyboard card creation without exposing an invalid blank-label history step", async () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    fireEvent.keyDown(cardButton("cause-1"), { key: "Enter" });
    const editor = await waitFor(() => {
      const element = document.querySelector<HTMLInputElement>('[data-card-editor-id="new-card"]');
      if (!element) throw new Error("new card editor was not rendered");
      return element;
    });
    fireEvent.change(editor, { target: { value: "A durable cause" } });
    fireEvent.keyDown(editor, { key: "Enter" });
    await waitFor(() => expect(cardButton("new-card")).toHaveFocus());

    fireEvent.keyDown(cardButton("new-card"), { key: "z", ctrlKey: true });

    await waitFor(() => {
      const next = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as GraphState;
      expect(next.nodes).not.toContainEqual(expect.objectContaining({ id: "new-card" }));
    });
  });

  it("inspects incoming and outgoing lists, ignores blank labels, and selects related cards", () => {
    const onChange = vi.fn();
    renderCanvas(createGraphState({ ...initialGraph(), selectedNodeId: "effect-1" }), onChange);

    const inspector = screen.getByRole("complementary", { name: "Card inspector" });
    expect(within(inspector).getByText("Incoming causes")).toBeInTheDocument();
    expect(within(inspector).getByRole("button", { name: "Deployments are rushed" })).toBeInTheDocument();
    const label = within(inspector).getByRole("textbox", { name: "Card label" });
    fireEvent.focus(label);
    fireEvent.change(label, { target: { value: "   " } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ editingNodeId: "effect-1" }));
    onChange.mockClear();
    fireEvent.change(label, { target: { value: "Reliable service" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      nodes: expect.arrayContaining([expect.objectContaining({ id: "effect-1", label: "Reliable service" })])
    }));

    fireEvent.click(within(inspector).getByRole("button", { name: "Deployments are rushed" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ selectedNodeId: "cause-1", selectedRelationId: null }));

    cleanup();
    const deleteRelation = vi.fn();
    render(
      <CrtInspector
        graph={createGraphState({ ...initialGraph(), selectedNodeId: "effect-1" })}
        onChange={onChange}
        onDeleteRelation={deleteRelation}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Delete relation from Deployments are rushed to Server is unreliable" }));
    expect(deleteRelation).toHaveBeenCalledWith("relation-1");

    cleanup();
    render(
      <CrtInspector
        graph={createGraphState({
          relations: [{ id: "orphan", sourceId: "missing-source", targetId: "missing-target" }],
          selectedRelationId: "orphan"
        })}
        onChange={onChange}
        onDeleteRelation={deleteRelation}
      />
    );
    expect(screen.getByText("Selected relation from Untitled card to Untitled card")).toBeInTheDocument();
  });

  it("covers pending composite Tab exit, missing relation deletion, and generated IDs", async () => {
    const onChange = vi.fn();
    renderCanvas();
    fireEvent.focus(cardButton("cause-1"));
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Tab" });
    expect(onChange).not.toHaveBeenCalled();

    cleanup();
    render(
      <CrtCanvas
        graph={createGraphState({ ...initialGraph(), selectedNodeId: null, selectedRelationId: "missing" })}
        onChange={onChange}
      />
    );
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });
    expect(screen.getByText("The relation to delete no longer exists.")).toBeInTheDocument();

    cleanup();
    render(
      <CrtCanvas
        graph={createGraphState({ selectedNodeId: "missing" })}
        onChange={onChange}
      />
    );
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });

    cleanup();
    render(<CrtCanvas graph={createGraphState()} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "Add card" }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      nodes: [expect.objectContaining({ label: "" })],
      relations: []
    }));
  });

  it("exercises React Flow callbacks for selection, movement, connections, edges, panes, viewport, and initialization", async () => {
    const onChange = vi.fn();
    const graph = createGraphState({
      nodes: [
        { id: "cause", label: "Cause", position: { x: 80, y: 240 } },
        { id: "effect", label: "Effect", position: { x: 80, y: 60 } }
      ],
      relations: [{ id: "rel", sourceId: "cause", targetId: "effect" }],
      selectedNodeId: "cause"
    });
    const view = renderCanvas(graph, onChange);
    const props = currentFlowProps();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const edgeComponent = (props.edgeTypes as Record<string, unknown>)["crt-edge"] as (edgeProps: Record<string, unknown>) => React.JSX.Element;
    const fallbackEdge = render(createElement(edgeComponent, {
      id: "fallback",
      sourceX: 40,
      sourceY: 200,
      targetX: 40,
      targetY: 40,
      selected: true,
      data: undefined,
      markerEnd: undefined,
      style: undefined
    }));
    expect(screen.getByTestId("crt-edge-fallback")).toHaveAccessibleName("Relation from Untitled card to Untitled card");
    fallbackEdge.unmount();
    consoleError.mockRestore();
    fireEvent.keyDown(screen.getByRole("img", { name: "Directed relation" }), { key: "Escape" });

    act(() => {
      flowCallback("onNodeDragStop")({}, { id: "cause", position: { x: 80, y: 240 } });
      flowCallback("onNodeDragStop")({}, { id: "cause", position: { x: 120, y: 280 } });
      flowCallback("onNodeClick")(null, { id: "effect" });
    });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ selectedNodeId: "effect" }));

    act(() => {
      flowCallback("onEdgeClick")(null, { id: "rel" });
      flowCallback("onPaneClick")();
      flowCallback("onMove")({ type: "pointer" }, { x: 20, y: 30, zoom: 0.8 });
      flowCallback("onMove")(null, { x: 0, y: 0, zoom: 0.7 });
    });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ viewportZoom: 0.8, viewportCenter: { x: 112.5, y: 25 } }));
    expect(props.nodesConnectable).toBe(false);
    view.unmount();
    act(() => flowCallback("onMove")({ type: "pointer" }, { x: 0, y: 0, zoom: 0.9 }));

    const orphan = renderCanvas(createGraphState({
      relations: [{ id: "orphan", sourceId: "missing-source", targetId: "missing-target" }]
    }), onChange);
    orphan.unmount();

    const connectChange = vi.fn();
    renderCanvas(
      createGraphState({
        nodes: [
          { id: "cause", label: "Cause", position: { x: 80, y: 240 } },
          { id: "effect", label: "Effect", position: { x: 80, y: 60 } }
        ],
        selectedNodeId: "cause"
      }),
      connectChange
    );
    act(() => {
      flowCallback("onConnect")({ source: "", target: "effect" });
      flowCallback("onConnect")({ source: "cause", target: "" });
      flowCallback("onConnect")({ source: "cause", target: "effect" });
    });
    expect(connectChange).toHaveBeenCalledWith(expect.objectContaining({ relations: [{ id: "new-relation", sourceId: "cause", targetId: "effect" }] }));

    const initializedChange = vi.fn();
    const initialized = renderCanvas(
      createGraphState({
        nodes: [{ id: "card", label: "Card", position: { x: 0, y: 0 } }],
        viewportCenter: { x: 100, y: 60 },
        viewportZoom: 0.75
      }),
      initializedChange
    );
    expect(currentFlowProps().fitView).toBe(false);
    act(() => {
      flowCallback("onInit")({ setViewport: flowHarness.setViewport });
    });
    await waitFor(() => {
      expect(flowHarness.setViewport).toHaveBeenCalledWith(
        { x: 35, y: 5, zoom: 0.75 },
        { duration: 0 }
      );
    });
    initialized.unmount();
  });

  it("covers a relation route fallback when a target lookup changes during derivation", async () => {
    let targetReads = 0;
    const relation = {
      id: "volatile-relation",
      sourceId: "cause",
      get targetId(): string {
        targetReads += 1;
        return targetReads === 4 ? "missing-target" : "effect";
      }
    };
    renderCanvas(createGraphState({
      nodes: [
        { id: "cause", label: "Cause", position: { x: 0, y: 240 } },
        { id: "effect", label: "Effect", position: { x: 0, y: 0 } }
      ],
      relations: [relation]
    }));

    expect(await screen.findByTestId("crt-edge-volatile-relation")).toBeInTheDocument();
  });

  it("covers toolbar modes, shortcuts, zoom keys, fit persistence, and position callbacks", async () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.focus(cardButton("cause-1"));
    fireEvent.keyDown(canvas, { key: "ArrowUp" });
    await waitFor(() => expect(cardButton("effect-1")).toHaveFocus());

    fireEvent.click(screen.getByRole("button", { name: "Pan canvas" }));
    fireEvent.click(screen.getByRole("button", { name: "Pan canvas" }));
    fireEvent.click(screen.getByRole("button", { name: "Select tool" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect cards" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect cards" }));
    fireEvent.click(screen.getByRole("button", { name: "Shortcuts" }));
    expect(screen.getByText("Shortcuts: Enter adds a cause; Tab adds a sibling; Escape exits canvas mode.")).toBeInTheDocument();

    fireEvent.focus(cardButton("cause-1"));
    fireEvent.keyDown(canvas, { key: "+" });
    fireEvent.keyDown(canvas, { key: "=" });
    fireEvent.keyDown(canvas, { key: "-" });
    fireEvent.keyDown(canvas, { key: "0" });
    fireEvent.keyDown(canvas, { key: "q" });
    expect(flowHarness.zoomIn).toHaveBeenCalledTimes(2);
    expect(flowHarness.zoomOut).toHaveBeenCalledTimes(1);
    expect(flowHarness.fitView).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Fit all cards" }));
    await waitFor(() => expect(flowHarness.getViewport).toHaveBeenCalled());
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    const flowRegion = screen.getByTestId("crt-flow-region");
    vi.spyOn(flowRegion, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 0, 0));
    act(() => flowCallback("onMove")({ type: "pointer" }, { x: 0, y: 0, zoom: 0.9 }));
    vi.spyOn(flowRegion, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 220, 0));
    act(() => flowCallback("onMove")({ type: "pointer" }, { x: 0, y: 0, zoom: 0.95 }));
    flowHarness.fitView.mockImplementationOnce(() => undefined as unknown as Promise<void>);
    fireEvent.click(screen.getByRole("button", { name: "Fit all cards" }));
    fireEvent.keyUp(canvas, { key: "x" });

    act(() => {
      flowCallback("onNodeDragStop")({}, { id: "not-present", position: { x: 1, y: 1 } });
      flowCallback("onNodeDragStop")({}, { id: "cause-1", position: { x: 260, y: 260 } });
    });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({
      nodes: expect.arrayContaining([expect.objectContaining({ id: "cause-1", position: { x: 260, y: 260 } })])
    }));
  });

  it("covers node and relation delete confirmation plus duplicate and invalid connection feedback", async () => {
    const relationGraph = initialGraph();
    const defaultCancelled = render(<CrtCanvas graph={relationGraph} onChange={vi.fn()} />);
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });
    expect(await screen.findByRole("alertdialog", { name: "Delete Deployments are rushed?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    defaultCancelled.unmount();

    const cancelled = render(
      <CrtCanvas graph={relationGraph} onChange={vi.fn()} confirmDelete={() => false} />
    );
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });
    fireEvent.click(screen.getByRole("button", { name: "Delete card" }));
    await waitFor(() => expect(screen.getByText("Delete cancelled.")).toBeInTheDocument());
    cancelled.unmount();

    const confirmedChange = vi.fn();
    const confirmed = render(
      <CrtCanvas graph={relationGraph} onChange={confirmedChange} createIds={ids("new-card", "new-relation")} confirmDelete={() => true} />
    );
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });
    fireEvent.click(screen.getByRole("button", { name: "Delete card" }));
    await waitFor(() => expect(confirmedChange).toHaveBeenCalledWith(expect.objectContaining({ nodes: [{ id: "effect-1", label: "Server is unreliable", position: { x: 260, y: 40 } }] })));
    confirmed.unmount();

    const effectDeleteChange = vi.fn();
    const effectDelete = render(
      <CrtCanvas graph={createGraphState({ ...relationGraph, selectedNodeId: "effect-1" })} onChange={effectDeleteChange} confirmDelete={() => true} />
    );
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });
    fireEvent.click(screen.getByRole("button", { name: "Delete card" }));
    await waitFor(() => expect(effectDeleteChange).toHaveBeenCalledWith(expect.objectContaining({ nodes: [{ id: "cause-1", label: "Deployments are rushed", position: { x: 260, y: 260 } }] })));
    effectDelete.unmount();

    const isolatedChange = vi.fn();
    const isolated = renderCanvas(createGraphState({ nodes: [{ id: "isolated", label: "Isolated", position: { x: 0, y: 0 } }], selectedNodeId: "isolated" }), isolatedChange);
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });
    expect(isolatedChange).toHaveBeenCalledWith(expect.objectContaining({ nodes: [] }));
    isolated.unmount();

    const duplicateChange = vi.fn();
    renderCanvas(initialGraph(), duplicateChange, ids("cause-1", "new-relation"));
    fireEvent.click(screen.getByRole("button", { name: "Add card" }));
    expect(screen.getByText("The new card ID is already in use.")).toBeInTheDocument();

    act(() => {
      flowCallback("onConnect")({ source: "cause-1", target: "cause-1" });
      flowCallback("onConnect")({ source: "cause-1", target: "effect-1" });
    });
    expect(screen.getByText("That directed relation already exists.")).toBeInTheDocument();
  });

  it("supports undo, redo aliases, empty history, and canvas shortcut entry and exit", () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });

    fireEvent.focus(cardButton("cause-1"));
    fireEvent.keyDown(canvas, { key: "Enter" });
    expect(onChange).toHaveBeenCalled();
    onChange.mockClear();
    fireEvent.keyDown(canvas, { key: "z", ctrlKey: true });
    expect(onChange).toHaveBeenCalled();
    onChange.mockClear();
    fireEvent.keyDown(canvas, { key: "z", ctrlKey: true, shiftKey: true });
    expect(onChange).toHaveBeenCalled();
    onChange.mockClear();
    fireEvent.keyDown(canvas, { key: "z", ctrlKey: true });
    expect(onChange).toHaveBeenCalled();
    onChange.mockClear();
    fireEvent.keyDown(canvas, { key: "y", ctrlKey: true });
    expect(onChange).toHaveBeenCalled();
    onChange.mockClear();
    fireEvent.keyDown(canvas, { key: "z", ctrlKey: true, shiftKey: true });
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.keyDown(canvas, { key: "Escape" });
    fireEvent.keyDown(canvas, { key: "Tab" });

    fireEvent.focus(canvas);
    fireEvent.keyDown(canvas, { key: "Enter" });
    fireEvent.keyDown(canvas, { key: "ArrowUp" });
    fireEvent.keyDown(canvas, { key: "ArrowDown" });
    fireEvent.keyDown(canvas, { key: "ArrowLeft" });
    fireEvent.keyDown(canvas, { key: "ArrowRight" });
    fireEvent.keyDown(canvas, { key: "Escape" });
    expect(onChange).toHaveBeenCalled();
  });

  it("retains undo history after autosave installs an equivalent canonical graph", async () => {
    const onChange = vi.fn();
    const view = render(
      <CrtCanvas
        graph={initialGraph()}
        onChange={onChange}
        createIds={ids("controlled-new-card", "controlled-new-relation")}
      />
    );
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });

    fireEvent.focus(cardButton("cause-1"));
    fireEvent.keyDown(canvas, { key: "Enter" });
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      nodes: expect.arrayContaining([expect.objectContaining({ id: "controlled-new-card" })])
    })));
    const emitted = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as GraphState;
    const canonicalClone: GraphState = {
      ...emitted,
      nodes: emitted.nodes.map((node) => ({ ...node, position: { ...node.position } })),
      relations: emitted.relations.map((relation) => ({ ...relation })),
      viewportCenter: { ...emitted.viewportCenter }
    };
    view.rerender(
      <CrtCanvas
        graph={canonicalClone}
        onChange={onChange}
        createIds={ids("unused-card", "unused-relation")}
      />
    );
    await act(async () => { await Promise.resolve(); });
    fireEvent.keyDown(canvas, { key: "z", ctrlKey: true });

    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({
      nodes: expect.not.arrayContaining([expect.objectContaining({ id: "controlled-new-card" })])
    })));
  });

  it("clears undo history when an equivalent graph belongs to another tree", async () => {
    const onChange = vi.fn();
    const historyKeyProps = { historyKey: "tree-a" } as Record<string, string>;
    const view = render(
      <CrtCanvas
        {...historyKeyProps}
        graph={initialGraph()}
        onChange={onChange}
        createIds={ids("tree-a-new-card", "tree-a-new-relation")}
      />
    );
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.focus(cardButton("cause-1"));
    fireEvent.keyDown(canvas, { key: "Enter" });
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    const emitted = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0] as GraphState;

    onChange.mockClear();
    view.rerender(
      <CrtCanvas
        {...({ historyKey: "tree-b" } as Record<string, string>)}
        graph={emitted}
        onChange={onChange}
        createIds={ids("unused-card", "unused-relation")}
      />
    );
    await act(async () => { await Promise.resolve(); });
    fireEvent.keyDown(canvas, { key: "z", ctrlKey: true });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("covers missing focus targets, failed label commands, modifier aliases, and zoom floor", () => {
    const onChange = vi.fn();
    renderCanvas(createGraphState({
      nodes: [{ id: "cause", label: "Cause", position: { x: 0, y: 0 } }],
      selectedNodeId: "missing",
      viewportZoom: 0.25
    }), onChange);
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.keyDown(canvas, { key: "Enter" });
    fireEvent.keyDown(canvas, { key: "ArrowUp" });
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(screen.getByLabelText("Zoom level")).toHaveTextContent("25%");
    fireEvent.click(screen.getByRole("button", { name: "Fit all cards" }));

    cleanup();
    renderCanvas(createGraphState(), onChange);
    fireEvent.click(screen.getByRole("button", { name: "Fit all cards" }));

    cleanup();
    renderCanvas(createGraphState({
      nodes: [{ id: "cause", label: "Cause", position: { x: 0, y: 0 } }],
      selectedNodeId: "cause"
    }), onChange, ids("cause", "relation"));
    const selectedCanvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.focus(cardButton("cause"));
    fireEvent.keyDown(selectedCanvas, { key: "ArrowDown" });
    fireEvent.keyDown(selectedCanvas, { key: "ArrowRight" });
    fireEvent.keyDown(screen.getByRole("button", { name: "Shortcuts" }), { key: "Enter", metaKey: true });
    const nodeData = (currentFlowProps().nodes as Array<{ data: { onCommitLabel?: (id: string, label: string) => boolean; onCancelLabel?: (id: string) => void } }>)[0]?.data;
    let committed = false;
    act(() => { committed = nodeData?.onCommitLabel?.("missing", "No card") ?? false; });
    expect(committed).toBe(false);
    act(() => { nodeData?.onCancelLabel?.("missing"); });
    fireEvent.keyDown(selectedCanvas, { key: "z", metaKey: true });
  });

  it("covers card mouse-down propagation and non-Escape editor keys", () => {
    const props = {
      id: "standalone-mouse",
      data: {
        label: "Card",
        badge: undefined,
        selected: false,
        editing: true,
        connectionMode: true,
        onCancelLabel: vi.fn()
      },
      selected: false
    } as unknown as Parameters<typeof CrtCardNode>[0];
    render(
      <ReactFlowProvider>
        <CrtCardNode {...props} />
      </ReactFlowProvider>
    );
    const editor = screen.getByRole("textbox", { name: "Edit card label for Card" });
    fireEvent.keyDown(editor, { key: "ArrowLeft" });
    expect(props.data.onCancelLabel).not.toHaveBeenCalled();

    cleanup();
    render(
      <ReactFlowProvider>
        <CrtCardNode {...props} data={{ ...props.data, editing: false }} />
      </ReactFlowProvider>
    );
    fireEvent.mouseDown(screen.getByRole("button", { name: "Connect into bottom of Card" }));
    fireEvent.mouseDown(screen.getByRole("button", { name: "Connect from top of Card" }));
  });

  it("keeps empty redo history inert while shortcut mode is active", () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.click(cardButton("cause-1"));
    onChange.mockClear();
    fireEvent.keyDown(canvas, { key: "y", ctrlKey: true });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("uses named accessible consequences for a connected untitled card", async () => {
    renderCanvas(createGraphState({
      nodes: [
        { id: "blank", label: "", position: { x: 0, y: 0 } },
        { id: "effect", label: "Effect", position: { x: 0, y: 240 } }
      ],
      relations: [{ id: "relation", sourceId: "blank", targetId: "effect" }],
      selectedNodeId: "blank"
    }));

    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });

    const dialog = await screen.findByRole("alertdialog", { name: "Delete this card?" });
    expect(dialog).toHaveTextContent("Untitled card → Effect");
  });

  it("does not emit a deletion when an async confirmation resolves after the card disappeared", async () => {
    let resolveConfirmation!: (confirmed: boolean) => void;
    const confirmation = new Promise<boolean>((resolve) => { resolveConfirmation = resolve; });
    const onChange = vi.fn();
    const graph = createGraphState({
      nodes: [
        { id: "cause", label: "Cause", position: { x: 0, y: 0 } },
        { id: "effect", label: "Effect", position: { x: 0, y: 240 } }
      ],
      relations: [{ id: "relation", sourceId: "cause", targetId: "effect" }],
      selectedNodeId: "cause"
    });
    const view = render(<CrtCanvas graph={graph} onChange={onChange} confirmDelete={() => confirmation} />);
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });

    view.rerender(<CrtCanvas graph={createGraphState({ nodes: [] })} onChange={onChange} confirmDelete={() => confirmation} />);
    await act(async () => {
      resolveConfirmation(true);
      await confirmation;
      await Promise.resolve();
    });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("opens an accessible connected-card confirmation with named relation consequences and safe focus", async () => {
    const confirm = vi.spyOn(window, "confirm");
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    const card = cardButton("cause-1");
    act(() => card.focus());
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });

    const dialog = await screen.findByRole("alertdialog", { name: "Delete Deployments are rushed?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(dialog).toHaveTextContent("Server is unreliable");
    expect(dialog).toHaveTextContent("Deployments are rushed → Server is unreliable");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();

    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(card).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("blocks modal Escape while an injected connected-card confirmation is busy", async () => {
    let resolveConfirmation!: (confirmed: boolean) => void;
    const onChange = vi.fn();
    const confirmation = new Promise<boolean>((resolve) => { resolveConfirmation = resolve; });
    render(<CrtCanvas graph={initialGraph()} onChange={onChange} confirmDelete={() => confirmation} />);
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });

    const dialog = await screen.findByRole("alertdialog", { name: "Delete Deployments are rushed?" });
    await fireEvent.click(screen.getByRole("button", { name: "Delete card" }));
    expect(screen.getByRole("button", { name: "Deleting card…" })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();

    await act(async () => {
      resolveConfirmation(true);
      await confirmation;
    });
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ nodes: [{ id: "effect-1", label: "Server is unreliable", position: { x: 260, y: 40 } }] })));
  });

  it("keeps canvas hotkeys active after Escape without turning ordinary Tab into creation", async () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.focus(cardButton("cause-1"));
    fireEvent.keyDown(canvas, { key: "Escape" });
    onChange.mockClear();

    fireEvent.keyDown(canvas, { key: "z", ctrlKey: true });
    fireEvent.keyDown(canvas, { key: "+" });
    fireEvent.keyDown(canvas, { key: "-" });
    fireEvent.keyDown(canvas, { key: "0" });
    const tab = new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    canvas.dispatchEvent(tab);

    expect(tab.defaultPrevented).toBe(false);
    await waitFor(() => expect(flowHarness.fitView).toHaveBeenCalled());
    expect(flowHarness.zoomIn).toHaveBeenCalled();
    expect(flowHarness.zoomOut).toHaveBeenCalled();
    expect(flowHarness.fitView).toHaveBeenCalled();
    expect(document.querySelector('[data-node-id="new-card"]')).not.toBeInTheDocument();
  });

  it("moves ArrowLeft and ArrowRight to spatially matching related cards", async () => {
    renderCanvas(createGraphState({
      nodes: [
        { id: "left", label: "Left", position: { x: 0, y: 100 } },
        { id: "middle", label: "Middle", position: { x: 300, y: 100 } },
        { id: "right", label: "Right", position: { x: 600, y: 100 } }
      ],
      relations: [
        { id: "left-relation", sourceId: "left", targetId: "middle" },
        { id: "right-relation", sourceId: "middle", targetId: "right" }
      ],
      selectedNodeId: "middle"
    }));
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.focus(cardButton("middle"));
    fireEvent.keyDown(canvas, { key: "ArrowLeft" });
    await waitFor(() => expect(cardButton("left")).toHaveFocus());
    fireEvent.keyDown(canvas, { key: "ArrowRight" });
    await waitFor(() => expect(cardButton("middle")).toHaveFocus());
  });

  it("makes relations focusable, selectable, and deletable with semantic state", async () => {
    const onChange = vi.fn();
    renderCanvas(initialGraph(), onChange);
    const relation = await screen.findByRole("button", { name: "Relation from Deployments are rushed to Server is unreliable" });
    expect(relation).toHaveAttribute("aria-pressed", "false");
    fireEvent.focus(relation);
    fireEvent.click(relation);
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ selectedRelationId: "relation-1", selectedNodeId: null }));
    expect(relation).toHaveAttribute("aria-pressed", "true");
    fireEvent.keyDown(relation, { key: "Delete" });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ relations: [] }));
  });

  it("provides a nonmodal shortcut disclosure with every canvas key and native-control behavior", () => {
    renderCanvas(initialGraph());
    fireEvent.click(screen.getByRole("button", { name: "Shortcuts" }));
    const disclosure = screen.getByRole("region", { name: "Canvas keyboard shortcuts" });
    expect(disclosure).toHaveTextContent("Enter");
    expect(disclosure).toHaveTextContent("Tab");
    expect(disclosure).toHaveTextContent("Escape");
    expect(disclosure).toHaveTextContent("ArrowLeft");
    expect(disclosure).toHaveTextContent("ArrowRight");
    expect(disclosure).toHaveTextContent("Ctrl/Cmd+Z");
    expect(disclosure).toHaveTextContent("Ctrl/Cmd+Shift+Z");
    expect(disclosure).toHaveTextContent("Ctrl/Cmd+Y");
    expect(disclosure).toHaveTextContent("+");
    expect(disclosure).toHaveTextContent("-");
    expect(disclosure).toHaveTextContent("0");
    expect(disclosure).toHaveTextContent("Space");
    expect(disclosure).toHaveTextContent("Native controls");
    expect(disclosure).toHaveTextContent("Escape closes shortcut mode");
    expect(screen.getByRole("button", { name: "Shortcuts" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not fit an explicitly persisted default viewport", async () => {
    renderCanvas(createGraphState({
      nodes: [{ id: "card", label: "Card", position: { x: 0, y: 0 } }],
      viewportCenter: { x: 0, y: 0 },
      viewportZoom: 1
    }));
    expect(currentFlowProps().fitView).toBe(false);
    act(() => flowCallback("onInit")({ setViewport: flowHarness.setViewport }));
    await waitFor(() => expect(flowHarness.setViewport).toHaveBeenCalled());
  });

  it("announces and preserves the inspector label after whitespace-only rejection", () => {
    renderCanvas(initialGraph());
    const input = screen.getByRole("textbox", { name: "Card label" });
    fireEvent.change(input, { target: { value: "   " } });
    expect(input).toHaveValue("Deployments are rushed");
    expect(screen.getByText("Card label cannot be blank; existing value preserved.")).toBeInTheDocument();
  });

  it("resets undo history when a controlled graph changes node content", async () => {
    const onChange = vi.fn();
    const view = render(<CrtCanvas graph={initialGraph()} onChange={onChange} createIds={ids("unused-card", "unused-relation")} />);
    const changed = createGraphState({
      ...initialGraph(),
      nodes: [
        { id: "effect-1", label: "Server is stable", position: { x: 260, y: 40 } },
        { id: "cause-1", label: "Deployments are rushed", position: { x: 260, y: 260 } }
      ],
      selectedNodeId: "cause-1"
    });
    view.rerender(
      <CrtCanvas graph={changed} onChange={onChange} createIds={ids("unused-card", "unused-relation")} />
    );
    await act(async () => { await Promise.resolve(); });

    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "z", ctrlKey: true });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("moves to the nearest of multiple spatially related cards", async () => {
    renderCanvas(createGraphState({
      nodes: [
        { id: "near", label: "Near", position: { x: 180, y: 100 } },
        { id: "far", label: "Far", position: { x: -200, y: 100 } },
        { id: "center", label: "Center", position: { x: 400, y: 100 } }
      ],
      relations: [
        { id: "near-relation", sourceId: "near", targetId: "center" },
        { id: "far-relation", sourceId: "far", targetId: "center" }
      ],
      selectedNodeId: "center"
    }));
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.focus(cardButton("center"));
    fireEvent.keyDown(canvas, { key: "ArrowLeft" });

    await waitFor(() => expect(cardButton("near")).toHaveFocus());
  });

  it("fails closed when confirmation starts after the selected card disappears", async () => {
    const onChange = vi.fn();
    const view = render(<CrtCanvas graph={initialGraph()} onChange={onChange} confirmDelete={() => true} />);
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.keyDown(canvas, { key: "Delete" });
    await act(async () => {
      view.rerender(<CrtCanvas graph={createGraphState({ nodes: [] })} onChange={onChange} confirmDelete={() => true} />);
      await Promise.resolve();
    });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Root cause: Deployments are rushed" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Delete card" }));

    await waitFor(() => expect(screen.getByText("The card to delete no longer exists.")).toBeInTheDocument());
    expect(onChange).not.toHaveBeenCalled();
  });

  it("rejects deletion when the graph disappears during async confirmation", async () => {
    const onChange = vi.fn();
    const confirmDelete = vi.fn(() => {
      view.rerender(<CrtCanvas graph={createGraphState({ nodes: [] })} onChange={onChange} confirmDelete={() => true} />);
      return true;
    });
    const view = render(<CrtCanvas graph={initialGraph()} onChange={onChange} confirmDelete={confirmDelete} />);
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });
    fireEvent.click(screen.getByRole("button", { name: "Delete card" }));

    await waitFor(() => expect(screen.getByText("The card to delete no longer exists.")).toBeInTheDocument());
    expect(confirmDelete).toHaveBeenCalledOnce();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("ignores unrelated and missing related cards during spatial focus", () => {
    const onChange = vi.fn();
    renderCanvas(createGraphState({
      nodes: [
        { id: "selected", label: "Selected", position: { x: 200, y: 200 } },
        { id: "other", label: "Other", position: { x: 0, y: 0 } },
        { id: "below", label: "Below", position: { x: 200, y: 400 } }
      ],
      relations: [
        { id: "unrelated", sourceId: "other", targetId: "missing" },
        { id: "missing-target", sourceId: "selected", targetId: "missing" },
        { id: "below-relation", sourceId: "selected", targetId: "below" }
      ],
      selectedNodeId: "selected"
    }), onChange);
    const canvas = screen.getByRole("group", { name: "Current Reality Tree canvas" });
    fireEvent.focus(cardButton("selected"));
    fireEvent.keyDown(canvas, { key: "ArrowUp" });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("names missing relation endpoints in the delete confirmation", async () => {
    renderCanvas(createGraphState({
      nodes: [{ id: "cause", label: "Cause", position: { x: 0, y: 0 } }],
      relations: [{ id: "dangling", sourceId: "cause", targetId: "missing" }],
      selectedNodeId: "cause"
    }));
    fireEvent.keyDown(screen.getByRole("group", { name: "Current Reality Tree canvas" }), { key: "Delete" });

    const dialog = await screen.findByRole("alertdialog", { name: "Delete Cause?" });
    expect(dialog).toHaveTextContent("Cause → Untitled card");
  });

  it("announces duplicate connector attempts without changing the graph", () => {
    const onChange = vi.fn();
    renderCanvas(createGraphState({
      nodes: [
        { id: "cause", label: "Cause", position: { x: 100, y: 280 } },
        { id: "effect", label: "Effect", position: { x: 100, y: 100 } }
      ],
      relations: [{ id: "existing", sourceId: "cause", targetId: "effect" }],
      selectedNodeId: "cause"
    }), onChange);
    fireEvent.click(screen.getByRole("button", { name: "Connect cards" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect from top of Cause" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect into bottom of Effect" }));

    expect(screen.getByText("That directed relation already exists.")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalledWith(expect.objectContaining({ relations: expect.arrayContaining([expect.objectContaining({ id: "new-relation" })]) }));
  });
});

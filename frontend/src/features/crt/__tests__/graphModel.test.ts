import { describe, expect, it } from "vitest";

import {
  commitHistory,
  connectRelation,
  createGraphState,
  createHistory,
  buildCrtEdgePath,
  deleteNode,
  deleteRelation,
  enterCreate,
  redo,
  tabCreate,
  undo,
  type GraphState,
  type Point
} from "../graphModel";

const point = (x: number, y: number): Point => ({ x, y });

const graphWithEffect = (): GraphState =>
  createGraphState({
    nodes: [{ id: "effect-1", label: "Effect", position: point(100, 100) }],
    relations: [],
    selectedNodeId: "effect-1"
  });

describe("CRT graph command model", () => {
  it("uses defaults when creating an empty graph state", () => {
    expect(createGraphState()).toEqual({
      nodes: [],
      relations: [],
      selectedNodeId: null,
      editingNodeId: null,
      selectedRelationId: null,
      viewportCenter: point(0, 0),
      viewportZoom: 1
    });
  });

  it("builds a bounded upward route from a cause top to an effect bottom", () => {
    const path = buildCrtEdgePath({
      sourceX: 210,
      sourceY: 280,
      targetX: 210,
      targetY: 192,
      routeOffset: 0
    });
    const coordinates = (path.match(/-?\d+(?:\.\d+)?/g) ?? []).map(Number);
    const yCoordinates = coordinates.filter((_, index) => index % 2 === 1);

    expect(path).toMatch(/^M210,280 C/);
    expect(yCoordinates[yCoordinates.length - 1]).toBe(192);
    expect(Math.min(...yCoordinates)).toBeGreaterThanOrEqual(192);
    expect(Math.max(...yCoordinates)).toBeLessThanOrEqual(280);
  });

  it("019-FR-007 creates a cause below the selected effect and focuses it for editing", () => {
    const result = enterCreate(graphWithEffect(), {
      nodeId: "cause-1",
      relationId: "relation-1"
    });

    expect(result.error).toBeUndefined();
    expect(result.state.nodes).toContainEqual({
      id: "cause-1",
      label: "",
      position: point(100, 280)
    });
    expect(result.state.relations).toContainEqual({
      id: "relation-1",
      sourceId: "cause-1",
      targetId: "effect-1"
    });
    expect(result.state.selectedNodeId).toBe("cause-1");
    expect(result.state.editingNodeId).toBe("cause-1");
    expect(result.focusNodeId).toBe("cause-1");
  });

  it("019-FR-005 chooses a deterministic free grid slot when Enter's intended placement is occupied", () => {
    const state = createGraphState({
      nodes: [
        { id: "effect-1", label: "Effect", position: point(100, 100) },
        { id: "occupied", label: "Existing cause", position: point(100, 280) }
      ],
      selectedNodeId: "effect-1"
    });

    const result = enterCreate(state, { nodeId: "cause-1", relationId: "relation-1" });

    expect(result.error).toBeUndefined();
    expect(result.state.nodes.find((node) => node.id === "cause-1")?.position).toEqual(point(380, 280));
    expect(result.state.relations).toContainEqual({
      id: "relation-1",
      sourceId: "cause-1",
      targetId: "effect-1"
    });
  });

  it("019-FR-005 keeps a generated card outside the occupied card rectangle", () => {
    const state = createGraphState({
      nodes: [
        { id: "effect-1", label: "Effect", position: point(100, 100) },
        { id: "nearby", label: "Nearby cause", position: point(180, 280) }
      ],
      selectedNodeId: "effect-1"
    });

    const result = enterCreate(state, { nodeId: "cause-1", relationId: "relation-1" });
    const created = result.state.nodes.find((node) => node.id === "cause-1");

    expect(result.error).toBeUndefined();
    expect(created?.position).not.toEqual(point(100, 280));
    expect(
      created &&
        (created.position.x >= 180 + 220 || created.position.x + 220 <= 180 ||
          created.position.y >= 280 + 92 || created.position.y + 92 <= 280)
    ).toBe(true);
  });

  it("019-FR-008 creates a same-level sibling and preserves the original cause-to-effect relation", () => {
    const state = createGraphState({
      nodes: [
        { id: "effect-1", label: "Effect", position: point(100, 100) },
        { id: "cause-1", label: "First cause", position: point(100, 280) }
      ],
      relations: [{ id: "relation-1", sourceId: "cause-1", targetId: "effect-1" }],
      selectedNodeId: "cause-1"
    });

    const result = tabCreate(state, { nodeId: "cause-2", relationId: "relation-2" });

    expect(result.error).toBeUndefined();
    expect(result.state.nodes.find((node) => node.id === "cause-2")?.position.y).toBe(280);
    expect(result.state.relations).toContainEqual({
      id: "relation-2",
      sourceId: "cause-2",
      targetId: "effect-1"
    });
    expect(result.state.relations).toContainEqual({
      id: "relation-1",
      sourceId: "cause-1",
      targetId: "effect-1"
    });
    expect(result.state.selectedNodeId).toBe("cause-2");
    expect(result.state.editingNodeId).toBe("cause-2");
  });

  it("019-FR-008 keeps a crowded inherited sibling on its causal row and clears the upper card", () => {
    const state = createGraphState({
      nodes: [
        { id: "effect-1", label: "Top effect", position: point(700, 60) },
        { id: "cause-1", label: "Selected cause", position: point(250, 460) },
        { id: "blocking-card", label: "Upper card", position: point(590, 280) }
      ],
      relations: [{ id: "relation-1", sourceId: "cause-1", targetId: "effect-1" }],
      selectedNodeId: "cause-1"
    });

    const result = tabCreate(state, { nodeId: "cause-2", relationId: "relation-2" });
    const sibling = result.state.nodes.find((node) => node.id === "cause-2");

    expect(result.error).toBeUndefined();
    expect(sibling?.position).toEqual(point(1090, 460));
    expect(result.state.relations).toContainEqual({
      id: "relation-2",
      sourceId: "cause-2",
      targetId: "effect-1"
    });
    expect(
      sibling &&
        (sibling.position.x >= 590 + 220 || sibling.position.x + 220 <= 590 ||
          sibling.position.y >= 280 + 92 || sibling.position.y + 92 <= 280)
    ).toBe(true);
  });

  it("019-FR-008 creates an unlinked sibling with explicit feedback when no effect can be inherited", () => {
    const state = createGraphState({
      nodes: [{ id: "cause-1", label: "Root cause", position: point(100, 280) }],
      selectedNodeId: "cause-1"
    });

    const result = tabCreate(state, { nodeId: "cause-2", relationId: "unused-relation" });

    expect(result.error).toBeUndefined();
    expect(result.feedback).toEqual({
      code: "no-qualifying-effect",
      message: "No unique upward effect was available; the sibling was left unlinked."
    });
    expect(result.state.nodes.find((node) => node.id === "cause-2")?.position.y).toBe(280);
    expect(result.state.relations).toEqual([]);
  });

  it("019-FR-010 creates a manual relation with cause as source and effect as target", () => {
    const state = createGraphState({
      nodes: [
        { id: "cause-1", label: "Cause", position: point(100, 280) },
        { id: "effect-1", label: "Effect", position: point(100, 100) }
      ]
    });

    const result = connectRelation(state, {
      id: "relation-1",
      sourceId: "cause-1",
      targetId: "effect-1"
    });

    expect(result.error).toBeUndefined();
    expect(result.state.relations).toEqual([
      { id: "relation-1", sourceId: "cause-1", targetId: "effect-1" }
    ]);
    expect(result.state.selectedRelationId).toBe("relation-1");
    expect(result.state.selectedNodeId).toBeNull();

    const duplicateId = connectRelation(result.state, {
      id: "relation-1",
      sourceId: "cause-1",
      targetId: "effect-1"
    });
    expect(duplicateId.error?.code).toBe("duplicate-id");
  });

  it.each([
    ["self-link", { id: "self", sourceId: "cause-1", targetId: "cause-1" }],
    ["missing-endpoint", { id: "missing", sourceId: "cause-1", targetId: "missing-node" }],
    ["duplicate-relation", { id: "duplicate", sourceId: "cause-1", targetId: "effect-1" }]
  ] as const)("019-FR-011 rejects %s without mutating the graph", (code, relation) => {
    const state = createGraphState({
      nodes: [
        { id: "cause-1", label: "Cause", position: point(100, 280) },
        { id: "effect-1", label: "Effect", position: point(100, 100) }
      ],
      relations: [{ id: "relation-1", sourceId: "cause-1", targetId: "effect-1" }]
    });

    const result = connectRelation(state, relation);

    expect(result.error?.code).toBe(code);
    expect(result.changed).toBe(false);
    expect(result.state).toEqual(state);
  });

  it("019-FR-011 rejects a relation that would create a cycle without mutating the graph", () => {
    const state = createGraphState({
      nodes: [
        { id: "a", label: "A", position: point(0, 0) },
        { id: "b", label: "B", position: point(0, 180) },
        { id: "c", label: "C", position: point(0, 360) }
      ],
      relations: [
        { id: "ab", sourceId: "a", targetId: "b" },
        { id: "bc", sourceId: "b", targetId: "c" }
      ]
    });

    const result = connectRelation(state, { id: "ca", sourceId: "c", targetId: "a" });

    expect(result.error?.code).toBe("cycle");
    expect(result.changed).toBe(false);
    expect(result.state).toEqual(state);
  });

  it("019-FR-016 019-SC-005 supports immutable snapshot undo and redo around a graph command", () => {
    const initial = graphWithEffect();
    const created = enterCreate(initial, { nodeId: "cause-1", relationId: "relation-1" });
    const history = commitHistory(createHistory(initial), created.state);

    const undone = undo(history);
    const redone = redo(undone);

    expect(undone.present).toEqual(initial);
    expect(undone.present).not.toBe(created.state);
    expect(redone.present).toEqual(created.state);
    expect(initial.nodes).toHaveLength(1);
    expect(initial.relations).toEqual([]);
  });

  it("019-FR-010 cascades incident relations when a node deletion is confirmed", () => {
    const state = createGraphState({
      nodes: [
        { id: "cause-1", label: "Cause", position: point(100, 280) },
        { id: "effect-1", label: "Effect", position: point(100, 100) },
        { id: "other-1", label: "Other", position: point(400, 100) }
      ],
      relations: [
        { id: "relation-1", sourceId: "cause-1", targetId: "effect-1" },
        { id: "relation-2", sourceId: "other-1", targetId: "cause-1" },
        { id: "relation-3", sourceId: "other-1", targetId: "effect-1" }
      ],
      selectedNodeId: "cause-1",
      editingNodeId: "cause-1",
      selectedRelationId: "relation-1"
    });

    const result = deleteNode(state, "cause-1", { confirmed: true });

    expect(result.error).toBeUndefined();
    expect(result.deletedNodeId).toBe("cause-1");
    expect(result.state.nodes.map((node) => node.id)).toEqual(["effect-1", "other-1"]);
    expect(result.state.relations).toEqual([
      { id: "relation-3", sourceId: "other-1", targetId: "effect-1" }
    ]);
    expect(result.state.selectedNodeId).toBeNull();
  });

  it("019-FR-009 creates one unlinked card near the viewport center when Enter or Tab has no selection", () => {
    const empty = createGraphState({ viewportCenter: point(500, 300) });

    const enterResult = enterCreate(empty, { nodeId: "enter-card", relationId: "unused-enter-relation" });
    const tabResult = tabCreate(empty, { nodeId: "tab-card", relationId: "unused-tab-relation" });

    expect(enterResult.error).toBeUndefined();
    expect(enterResult.state.nodes).toHaveLength(1);
    expect(enterResult.state.nodes[0]).toMatchObject({ id: "enter-card", position: point(500, 300) });
    expect(enterResult.state.relations).toEqual([]);
    expect(enterResult.state.selectedNodeId).toBe("enter-card");
    expect(enterResult.state.editingNodeId).toBe("enter-card");
    expect(tabResult.error).toBeUndefined();
    expect(tabResult.state.nodes).toHaveLength(1);
    expect(tabResult.state.nodes[0]).toMatchObject({ id: "tab-card", position: point(500, 300) });
    expect(tabResult.state.relations).toEqual([]);
  });

  it("019-FR-010 deletes an isolated card without requiring cascade confirmation", () => {
    const state = createGraphState({
      nodes: [{ id: "isolated", label: "Standalone", position: point(0, 0) }],
      selectedNodeId: "isolated"
    });

    const result = deleteNode(state, "isolated", { confirmed: false });

    expect(result.error).toBeUndefined();
    expect(result.changed).toBe(true);
    expect(result.state.nodes).toEqual([]);
  });

  it("covers bounded edge geometry when the route runs right-to-left", () => {
    const path = buildCrtEdgePath({ sourceX: 300, sourceY: 180, targetX: 100, targetY: 0, routeOffset: 12 });

    expect(path).toBe("M300,180 C280,90 80,90 100,0");
  });

  it.each([
    ["Enter", enterCreate],
    ["Tab", tabCreate]
  ] as const)("rejects %s creation when the generated node ID is already used", (_name, create) => {
    const state = createGraphState({
      nodes: [{ id: "existing", label: "Existing", position: point(0, 0) }],
      selectedNodeId: null,
      viewportCenter: point(0, 0)
    });

    const result = create(state, { nodeId: "existing", relationId: "new-relation" });

    expect(result.error?.code).toBe("duplicate-id");
    expect(result.changed).toBe(false);
    expect(result.state).toBe(state);

    const selected = graphWithEffect();
    const selectedDuplicate = create(selected, { nodeId: "effect-1", relationId: "new-relation" });
    expect(selectedDuplicate.error?.code).toBe("duplicate-id");
  });

  it("rejects Enter when its selected effect is missing", () => {
    const state = createGraphState({ selectedNodeId: "gone" });
    const result = enterCreate(state, { nodeId: "cause", relationId: "relation" });

    expect(result.error?.code).toBe("missing-node");
    expect(result.changed).toBe(false);
    expect(result.state).toBe(state);
  });

  it("rejects Enter when its generated relation ID is already used", () => {
    const state = graphWithEffect();
    const withRelation = createGraphState({
      ...state,
      relations: [{ id: "relation", sourceId: "effect-1", targetId: "effect-1" }]
    });

    const result = enterCreate(withRelation, { nodeId: "cause", relationId: "relation" });

    expect(result.error?.code).toBe("duplicate-id");
    expect(result.state).toBe(withRelation);
  });

  it("rejects Tab when the selected node is missing or its node ID is duplicated", () => {
    const missing = createGraphState({ selectedNodeId: "gone" });
    expect(tabCreate(missing, { nodeId: "new", relationId: "relation" }).error?.code).toBe("missing-node");

    const state = createGraphState({
      nodes: [{ id: "selected", label: "Selected", position: point(0, 0) }],
      selectedNodeId: "selected"
    });
    const duplicate = tabCreate(state, { nodeId: "selected", relationId: "relation" });

    expect(duplicate.error?.code).toBe("duplicate-id");
    expect(duplicate.state).toBe(state);
  });

  it("rejects Tab when an inherited relation ID is already used", () => {
    const state = createGraphState({
      nodes: [
        { id: "effect", label: "Effect", position: point(0, 0) },
        { id: "selected", label: "Selected", position: point(0, 180) }
      ],
      relations: [
        { id: "relation", sourceId: "selected", targetId: "effect" }
      ],
      selectedNodeId: "selected"
    });

    const result = tabCreate(state, { nodeId: "sibling", relationId: "relation" });

    expect(result.error?.code).toBe("duplicate-id");
    expect(result.state).toBe(state);
  });

  it("leaves a Tab sibling unlinked when equally near upward effects make inheritance ambiguous", () => {
    const state = createGraphState({
      nodes: [
        { id: "left-effect", label: "Left", position: point(-100, 0) },
        { id: "right-effect", label: "Right", position: point(100, 0) },
        { id: "selected", label: "Selected", position: point(0, 180) }
      ],
      relations: [
        { id: "left-relation", sourceId: "selected", targetId: "left-effect" },
        { id: "right-relation", sourceId: "selected", targetId: "right-effect" }
      ],
      selectedNodeId: "selected"
    });

    const result = tabCreate(state, { nodeId: "sibling", relationId: "new-relation" });

    expect(result.error).toBeUndefined();
    expect(result.feedback?.code).toBe("no-qualifying-effect");
    expect(result.state.relations).toEqual(state.relations);
  });

  it("visits a shared descendant while checking a non-cyclic relation", () => {
    const state = createGraphState({
      nodes: ["a", "b", "c", "d", "x"].map((id, index) => ({
        id,
        label: id,
        position: point(index * 100, index * 100)
      })),
      relations: [
        { id: "ab", sourceId: "a", targetId: "b" },
        { id: "ac", sourceId: "a", targetId: "c" },
        { id: "bd", sourceId: "b", targetId: "d" },
        { id: "cd", sourceId: "c", targetId: "d" }
      ]
    });

    const result = connectRelation(state, { id: "xa", sourceId: "x", targetId: "a" });

    expect(result.error).toBeUndefined();
    expect(result.state.relations).toContainEqual({ id: "xa", sourceId: "x", targetId: "a" });
  });

  it("deletes an existing relation and clears only a matching relation selection", () => {
    const state = createGraphState({
      relations: [
        { id: "remove", sourceId: "a", targetId: "b" },
        { id: "keep", sourceId: "b", targetId: "c" }
      ],
      selectedRelationId: "keep"
    });
    const result = deleteRelation(state, "remove");

    expect(result.error).toBeUndefined();
    expect(result.deletedRelationId).toBe("remove");
    expect(result.state.relations).toEqual([{ id: "keep", sourceId: "b", targetId: "c" }]);
    expect(result.state.selectedRelationId).toBe("keep");
    const selectedResult = deleteRelation(createGraphState({
      relations: [{ id: "remove", sourceId: "a", targetId: "b" }],
      selectedRelationId: "remove"
    }), "remove");
    expect(selectedResult.state.selectedRelationId).toBeNull();
    expect(deleteRelation(state, "missing").error?.code).toBe("missing-endpoint");
  });

  it("requires confirmation before deleting a connected node and reports missing nodes", () => {
    const state = createGraphState({
      nodes: [
        { id: "cause", label: "Cause", position: point(0, 100) },
        { id: "effect", label: "Effect", position: point(0, 0) }
      ],
      relations: [{ id: "relation", sourceId: "cause", targetId: "effect" }]
    });

    expect(deleteNode(state, "missing", { confirmed: true }).error?.code).toBe("missing-node");
    const blocked = deleteNode(state, "cause", { confirmed: false });
    expect(blocked.error?.code).toBe("confirmation-required");
    expect(blocked.state).toBe(state);
  });

  it("preserves unrelated selection state during cascade deletion", () => {
    const state = createGraphState({
      nodes: [
        { id: "remove", label: "Remove", position: point(0, 100) },
        { id: "keep", label: "Keep", position: point(300, 100) },
        { id: "effect", label: "Effect", position: point(0, 0) }
      ],
      relations: [{ id: "relation", sourceId: "remove", targetId: "effect" }],
      selectedNodeId: "keep",
      editingNodeId: "keep",
      selectedRelationId: "unrelated"
    });

    const result = deleteNode(state, "remove", { confirmed: true });

    expect(result.state.selectedNodeId).toBe("keep");
    expect(result.state.editingNodeId).toBe("keep");
    expect(result.state.selectedRelationId).toBe("unrelated");
  });

  it("keeps no-op history operations immutable and clears redo after a new commit", () => {
    const initial = graphWithEffect();
    const history = createHistory(initial);

    expect(commitHistory(history, initial)).toBe(history);
    expect(undo(history)).toBe(history);
    expect(redo(history)).toBe(history);

    const next = enterCreate(initial, { nodeId: "cause", relationId: "relation" }).state;
    const committed = commitHistory(history, next);
    const undone = undo(committed);
    const changed = createGraphState({ ...initial, viewportZoom: 2 });
    const branched = commitHistory(undone, changed);

    expect(branched.future).toEqual([]);
  });
});

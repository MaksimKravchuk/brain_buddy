/// <reference types="node" />

import { mkdir, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { epic, feature, story } from "allure-js-commons";
import type { Locator, Page, Route } from "@playwright/test";
import { expect, test } from "../allure.fixtures";

const OWNER_ID = "00000000-0000-4000-8000-000000000019";
const SUPPORT_REFERENCE = "00000000-0000-4000-8000-000000000024";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
// Chromium CI can spend a few frames laying out a large React Flow surface. The
// budget is intentionally a readiness budget, not a wall-clock performance claim.
const LARGE_CANVAS_READY_BUDGET_MS = 5_000;
const FIXED_TIME = "2026-09-21T08:00:00.000Z";
const SUPPORTED_DESKTOP_WIDTHS = [1024, 1280] as const;

type Point = { x: number; y: number };
type NodeFixture = {
  id: string;
  label: string;
  type: "parent" | "child";
  position: Point;
  highlight_state: "none" | "cause_candidate" | "effect_spanning";
  relation_counts: { up_count: number; down_count: number };
};
type RelationFixture = {
  id: string;
  source_node_id: string;
  target_node_id: string;
  kind: "why";
  created_at: string;
};
type TreeFixture = {
  id: string;
  name: string;
  revision: number;
  schema_version: 1;
  metadata: {
    version: 1;
    created_at: string;
    updated_at: string;
    layout: { center: Point; zoom: number } | null;
    owner_id: string;
  };
  nodes: NodeFixture[];
  relations: RelationFixture[];
  owner_id: string;
};
type RequestRecord = {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
};
type WidthAudit = {
  inner_width: number;
  document_scroll_width: number;
  horizontal_overflow: boolean;
  clipped_shell: boolean;
};
type InteractionObservation =
  | { kind: "attribute"; selector: string; name: string; value: string }
  | { kind: "attribute-change"; selector: string; name: string; before: string | null }
  | { kind: "text-change"; selector: string; before: string | null }
  | { kind: "rect-change"; selector: string; before_x: number; before_y: number }
  | { kind: "focus"; selector: string };
type InteractionProbeConfig = {
  event_name: "click" | "pointermove" | "keydown";
  key?: string;
  input_selector?: string;
  observations: InteractionObservation[];
  timeout_ms?: number;
};
type InteractionProbeState = {
  status: "armed" | "observing" | "complete" | "error";
  duration_ms: number | null;
  error: string | null;
};
type FixtureOptions = {
  trees?: TreeFixture[];
  exposureStatus?: 204 | 404 | 503;
  rejectImport?: boolean;
  failNextPut?: boolean;
  conflictNextPut?: boolean;
};

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function node(id: string, label: string, position: Point, relationCounts = { up_count: 0, down_count: 0 }): NodeFixture {
  return {
    id,
    label,
    type: "child",
    position,
    highlight_state: "none",
    relation_counts: relationCounts
  };
}

function treeFixture(id: string, name: string, nodes: NodeFixture[] = [], relations: RelationFixture[] = [], revision = 1, zoom = 0.8): TreeFixture {
  return {
    id,
    name,
    revision,
    schema_version: 1,
    metadata: {
      version: 1,
      created_at: FIXED_TIME,
      updated_at: FIXED_TIME,
      layout: { center: { x: 0, y: 0 }, zoom },
      owner_id: OWNER_ID
    },
    nodes,
    relations,
    owner_id: OWNER_ID
  };
}

function oneCardTree(id = "tree-one", name = "Synthetic tree"): TreeFixture {
  return treeFixture(id, name, [node("node-effect", "Synthetic effect", { x: 0, y: 0 })]);
}

function tenCardSeed(): TreeFixture {
  return oneCardTree("tree-ten", "Ten card tree");
}

function twoHundredCardTree(): TreeFixture {
  const nodes = Array.from({ length: 200 }, (_, index) => node(
    `node-${String(index).padStart(3, "0")}`,
    `Synthetic card ${index + 1}`,
    { x: (index % 10) * 280, y: Math.floor(index / 10) * 150 }
  ));
  const relations: RelationFixture[] = [];
  for (let index = 1; index < nodes.length; index += 1) {
    relations.push({
      id: `relation-chain-${index}`,
      source_node_id: nodes[index].id,
      target_node_id: nodes[index - 1].id,
      kind: "why",
      created_at: FIXED_TIME
    });
  }
  for (let index = 2; index < 63; index += 1) {
    relations.push({
      id: `relation-branch-${index}`,
      source_node_id: nodes[index].id,
      target_node_id: nodes[index - 2].id,
      kind: "why",
      created_at: FIXED_TIME
    });
  }
  return treeFixture("tree-large", "Synthetic 200-card tree", nodes, relations, 7, 0.6);
}

function jsonHeaders(correlation = SUPPORT_REFERENCE): Record<string, string> {
  return { "content-type": "application/json", "x-correlation-id": correlation };
}

async function fulfill(route: Route, status: number, body?: unknown, correlation = SUPPORT_REFERENCE): Promise<void> {
  await route.fulfill({
    status,
    headers: body === undefined ? { "x-correlation-id": correlation } : jsonHeaders(correlation),
    body: body === undefined ? undefined : JSON.stringify(body)
  });
}

class CrtFixture {
  readonly requests: RequestRecord[] = [];
  private readonly trees: Map<string, TreeFixture>;
  private readonly options: FixtureOptions;
  private createdSequence = 0;
  private failedPut = false;
  private conflictedPut = false;

  constructor(options: FixtureOptions = {}) {
    this.options = options;
    this.trees = new Map((options.trees ?? []).map((tree) => [tree.id, clone(tree)]));
  }

  tree(id: string): TreeFixture {
    const value = this.trees.get(id);
    if (!value) throw new Error(`Fixture tree ${id} is missing`);
    return value;
  }

  private record(route: Route): { path: string; request: RequestRecord } {
    const request = route.request();
    const url = new URL(request.url());
    let body: unknown = undefined;
    try {
      body = request.postDataJSON();
    } catch {
      body = request.postData() ?? undefined;
    }
    const recorded: RequestRecord = {
      method: request.method(),
      path: `${url.pathname}${url.search}`,
      headers: request.headers(),
      body
    };
    this.requests.push(recorded);
    return { path: url.pathname, request: recorded };
  }

  async install(page: Page): Promise<void> {
    await page.route("**/api/**", async (route) => {
      if (!new URL(route.request().url()).pathname.startsWith("/api/")) {
        await route.continue();
        return;
      }
      const { path, request } = this.record(route);
      if (!path.startsWith("/api/")) {
        await route.continue();
        return;
      }
      if (path === "/api/auth/me") {
        await fulfill(route, 200, {
          id: OWNER_ID,
          email: "crt.synthetic@example.test",
          display_name: "CRT Synthetic User",
          feature_flags: { crt_canvas: true }
        });
        return;
      }
      if (path === "/api/crt/exposure") {
        if (this.options.exposureStatus === 404) {
          await fulfill(route, 404, { detail: { reason: "crt_canvas_disabled" } });
        } else if (this.options.exposureStatus === 503) {
          await fulfill(route, 503, { detail: { reason: "feature_flag_unavailable" } });
        } else {
          await fulfill(route, 204);
        }
        return;
      }
      if (path === "/api/crt/trees" && request.method === "GET") {
        await fulfill(route, 200, [...this.trees.values()].map((tree) => ({
          id: tree.id,
          name: tree.name,
          updated_at: tree.metadata.updated_at,
          owner_id: tree.owner_id
        })));
        return;
      }
      if (path === "/api/crt/trees" && request.method === "POST") {
        const payload = request.body as { name?: string };
        this.createdSequence += 1;
        const created = treeFixture(`tree-created-${this.createdSequence}`, payload.name ?? "Current Reality Tree");
        this.trees.set(created.id, created);
        await fulfill(route, 201, clone(created));
        return;
      }
      if (path === "/api/crt/trees/import" && request.method === "POST") {
        if (this.options.rejectImport) {
          await fulfill(route, 400, { detail: { reason: "cycle", message: "Import rejected: the graph contains a cycle." } });
          return;
        }
        const payload = request.body as { tree: TreeFixture };
        const imported = clone(payload.tree);
        imported.id = `tree-imported-${this.trees.size + 1}`;
        imported.revision = 1;
        imported.owner_id = OWNER_ID;
        this.trees.set(imported.id, imported);
        await fulfill(route, 201, imported);
        return;
      }
      const match = /^\/api\/crt\/trees\/([^/]+)(?:\/export)?$/.exec(path);
      if (match) {
        const treeId = decodeURIComponent(match[1]);
        const tree = this.trees.get(treeId);
        if (!tree) {
          await fulfill(route, 404, { detail: { reason: "not_found" } });
          return;
        }
        if (path.endsWith("/export") && request.method === "POST") {
          await fulfill(route, 200, { tree: clone(tree) });
          return;
        }
        if (request.method === "GET") {
          await fulfill(route, 200, clone(tree));
          return;
        }
        if (request.method === "DELETE") {
          this.trees.delete(treeId);
          await fulfill(route, 204);
          return;
        }
        if (request.method === "PUT") {
          const payload = request.body as TreeFixture & { expected_revision: number };
          if (this.options.failNextPut && !this.failedPut) {
            this.failedPut = true;
            await fulfill(route, 503, { detail: { reason: "temporary_failure" } });
            return;
          }
          if (this.options.conflictNextPut && !this.conflictedPut) {
            this.conflictedPut = true;
            tree.revision += 1;
            tree.nodes = tree.nodes.map((candidate) => candidate.id === "node-effect"
              ? { ...candidate, label: "Server copy label" }
              : candidate);
            tree.metadata.updated_at = "2026-09-21T08:01:00.000Z";
            await fulfill(route, 409, {
              message: "This tree has newer changes; review the conflict before saving.",
              detail: { reason: "stale_revision", tree_id: treeId, current_revision: tree.revision },
              reference_id: SUPPORT_REFERENCE
            });
            return;
          }
          if (payload.expected_revision !== tree.revision) {
            await fulfill(route, 409, {
              detail: { reason: "stale_revision", tree_id: treeId, current_revision: tree.revision },
              reference_id: SUPPORT_REFERENCE
            });
            return;
          }
          const next = clone(payload);
          next.id = treeId;
          next.revision = tree.revision + 1;
          next.metadata.updated_at = "2026-09-21T08:02:00.000Z";
          next.metadata.version = 1;
          next.schema_version = 1;
          next.owner_id = OWNER_ID;
          this.trees.set(treeId, next);
          await fulfill(route, 200, clone(next));
          return;
        }
      }
      await fulfill(route, 200, {});
    });
  }

  paths(suffix: string): string[] {
    return this.requests.filter((request) => request.path.endsWith(suffix)).map((request) => request.path);
  }

  enableNextConflict(): void {
    this.options.conflictNextPut = true;
  }

  mutation(path: string, method: string): RequestRecord[] {
    return this.requests.filter((request) => request.path === path && request.method === method);
  }
}

const pageErrors = new WeakMap<Page, Error[]>();
const evidenceArtifacts = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const errors: Error[] = [];
  pageErrors.set(page, errors);
  page.on("pageerror", (error) => errors.push(error));
});

test.afterEach(async ({ page }, testInfo) => {
  const errors = pageErrors.get(page) ?? [];
  if (errors.length > 0 || testInfo.status !== testInfo.expectedStatus) {
    await Promise.all(
      (evidenceArtifacts.get(page) ?? []).map((name) => removeEvidenceArtifact(name))
    );
  }
  expect(errors.map((error) => error.message), "The CRT page emitted a browser error").toEqual([]);
});

async function crtLabels(storyName: string): Promise<void> {
  await epic("Current Reality Tree");
  await feature("CRT canvas acceptance");
  await story(storyName);
}

async function openCrt(page: Page, fixture: CrtFixture): Promise<void> {
  await fixture.install(page);
  await page.goto("/crt");
}

function latestMutation(fixture: CrtFixture, path: string, method: string): RequestRecord {
  const matches = fixture.mutation(path, method);
  const latest = matches.at(-1);
  if (!latest) throw new Error(`Missing ${method} ${path}; observed ${JSON.stringify(fixture.requests.map((request) => `${request.method} ${request.path}`))}`);
  return latest;
}

function assertMutationHeaders(request: RequestRecord): void {
  expect(request.headers["idempotency-key"]).toMatch(UUID);
  expect(request.headers["x-correlation-id"]).toMatch(UUID);
}

function countContentRequests(fixture: CrtFixture): number {
  return fixture.requests.filter((request) => request.path.startsWith("/api/crt/trees")).length;
}

async function nextAnimationFrame(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
}

async function armInteractionProbe(page: Page, config: InteractionProbeConfig): Promise<void> {
  await page.evaluate((probeConfig) => {
    const probeWindow = window as typeof window & {
      __crtInteractionProbe?: InteractionProbeState;
      __crtInteractionProbeCleanup?: () => void;
    };
    const current = probeWindow.__crtInteractionProbe;
    if (current?.status === "armed" || current?.status === "observing") {
      throw new Error("A CRT interaction probe is already active");
    }

    const state: InteractionProbeState = {
      status: "armed",
      duration_ms: null,
      error: null
    };
    probeWindow.__crtInteractionProbe = state;
    const timeoutMs = probeConfig.timeout_ms ?? 2_000;

    const observationIsVisible = (observation: InteractionObservation): boolean => {
      if (observation.kind === "focus") {
        return document.activeElement instanceof Element &&
          document.activeElement.matches(observation.selector);
      }
      const element = document.querySelector<HTMLElement>(observation.selector);
      if (!element) return false;
      switch (observation.kind) {
        case "attribute":
          return element.getAttribute(observation.name) === observation.value;
        case "attribute-change":
          return element.getAttribute(observation.name) !== observation.before;
        case "text-change":
          return element.textContent !== observation.before;
        case "rect-change": {
          const box = element.getBoundingClientRect();
          return Math.abs(box.x - observation.before_x) > 0.5 ||
            Math.abs(box.y - observation.before_y) > 0.5;
        }
      }
    };

    let inputTimer = 0;
    let cancelled = false;
    const onInput = (event: Event): void => {
      if (!event.isTrusted) return;
      if (probeConfig.key !== undefined && (!(event instanceof KeyboardEvent) || event.key !== probeConfig.key)) {
        return;
      }
      if (probeConfig.input_selector !== undefined) {
        const target = event.target instanceof Element ? event.target : null;
        if (!target?.closest(probeConfig.input_selector)) return;
      }

      document.removeEventListener(probeConfig.event_name, onInput, true);
      window.clearTimeout(inputTimer);
      state.status = "observing";
      const started = performance.now();
      const deadline = started + timeoutMs;
      const observeFrame = (): void => {
        if (cancelled) return;
        if (probeConfig.observations.every(observationIsVisible)) {
          state.duration_ms = performance.now() - started;
          state.status = "complete";
          return;
        }
        if (performance.now() >= deadline) {
          state.status = "error";
          state.error = "Expected interaction state was not observable before the probe timeout";
          return;
        }
        requestAnimationFrame(observeFrame);
      };
      requestAnimationFrame(observeFrame);
    };

    document.addEventListener(probeConfig.event_name, onInput, true);
    probeWindow.__crtInteractionProbeCleanup = () => {
      cancelled = true;
      window.clearTimeout(inputTimer);
      document.removeEventListener(probeConfig.event_name, onInput, true);
    };
    inputTimer = window.setTimeout(() => {
      if (state.status !== "armed") return;
      document.removeEventListener(probeConfig.event_name, onInput, true);
      state.status = "error";
      state.error = `No ${probeConfig.event_name} input reached the interaction probe`;
    }, timeoutMs);
  }, config);
}

async function discardInteractionProbe(page: Page): Promise<void> {
  await page.evaluate(() => {
    const probeWindow = window as typeof window & {
      __crtInteractionProbe?: InteractionProbeState;
      __crtInteractionProbeCleanup?: () => void;
    };
    probeWindow.__crtInteractionProbeCleanup?.();
    delete probeWindow.__crtInteractionProbeCleanup;
    delete probeWindow.__crtInteractionProbe;
  });
}

async function collectInteractionProbe(page: Page): Promise<number> {
  await expect.poll(
    () => page.evaluate(() => {
      const probeWindow = window as typeof window & {
        __crtInteractionProbe?: InteractionProbeState;
      };
      return probeWindow.__crtInteractionProbe?.status ?? "missing";
    }),
    { timeout: 3_000, message: "Browser-side CRT interaction probe must settle" }
  ).toMatch(/^(complete|error)$/);

  const result = await page.evaluate(() => {
    const probeWindow = window as typeof window & {
      __crtInteractionProbe?: InteractionProbeState;
      __crtInteractionProbeCleanup?: () => void;
    };
    const probe = probeWindow.__crtInteractionProbe ?? null;
    probeWindow.__crtInteractionProbeCleanup?.();
    delete probeWindow.__crtInteractionProbeCleanup;
    delete probeWindow.__crtInteractionProbe;
    return probe;
  });
  if (result?.status !== "complete" || result.duration_ms === null) {
    throw new Error(result?.error ?? "CRT interaction probe did not return a duration");
  }
  return result.duration_ms;
}

async function writeEvidenceArtifact(name: string, value: unknown): Promise<void> {
  const directory = process.env.CRT_EVIDENCE_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await writeFile(join(directory, name), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

async function removeEvidenceArtifact(name: string): Promise<void> {
  const directory = process.env.CRT_EVIDENCE_DIR;
  if (!directory) return;
  await rm(join(directory, name), { force: true });
}

function p95(samples: number[]): number {
  const sorted = [...samples].sort((left, right) => left - right);
  return sorted[Math.max(0, Math.ceil(sorted.length * 0.95) - 1)] ?? 0;
}

async function loginThroughUi(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").click();
  await page.keyboard.type(email);
  await page.getByLabel("Password").click();
  await page.keyboard.type(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login$/);
}

async function addCardWithKeyboard(page: Page, card: Locator, key: "Enter" | "Tab", label: string): Promise<void> {
  await card.click();
  await page.keyboard.press(key);
  const editor = page.locator("input[data-card-editor-id]").last();
  await expect(editor).toBeFocused();
  await page.keyboard.type(label);
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: new RegExp(`: ${label}$`) })).toBeVisible();
}

test("T024 first run creates a truthful tree and exposes accessible tree menu actions", async ({ page }) => {
  await crtLabels("First run, create-first-tree, and tree menu accessibility");
  const fixture = new CrtFixture();
  await openCrt(page, fixture);

  await test.step("show the truthful empty state without demo cards", async () => {
    await expect(page.getByRole("heading", { name: "Start with your first undesired effect" })).toBeVisible();
    await expect(page.getByText("No demo content is added for you.")).toBeVisible();
    await expect(page.locator("[data-crt-card='true']")).toHaveCount(0);
    expect(fixture.paths("/api/crt/trees")).toEqual(["/api/crt/trees"]);
  });

  await test.step("create the first tree and inspect the keyboard-addressable menu", async () => {
    await page.getByRole("button", { name: "Create first tree" }).click();
    await expect(page.getByRole("heading", { name: "Current Reality Tree" })).toHaveClass(/sr-only/);
    const createRequest = await expect.poll(() => fixture.mutation("/api/crt/trees", "POST").length).toBe(1).then(() => latestMutation(fixture, "/api/crt/trees", "POST"));
    assertMutationHeaders(createRequest);
    expect(createRequest.body).toEqual({ name: "My first tree" });

    await page.getByRole("button", { name: /Current tree: My first tree/ }).click();
    const menu = page.getByRole("menu", { name: "Tree menu" });
    await expect(menu).toBeVisible();
    await expect(menu.getByRole("menuitem", { name: "Create a new tree" })).toBeEnabled();
    await expect(menu.getByRole("menuitem", { name: "Import tree JSON" })).toBeEnabled();
    await expect(menu.getByRole("menuitem", { name: "Rename tree" })).toBeEnabled();
    await expect(menu.getByRole("menuitem", { name: "Export saved server copy" })).toBeEnabled();
    await expect(menu.getByRole("menuitem", { name: "Delete tree" })).toBeEnabled();
    await expect(menu.getByText("No other trees yet")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: /Current tree: My first tree/ })).toBeFocused();
  });
});

test("T024 inline label editing cancels with Escape, persists on Enter, and undoes with Ctrl+Z", async ({ page }) => {
  await crtLabels("Inline label commit, cancellation, and undo");
  const fixture = new CrtFixture({ trees: [oneCardTree()] });
  await openCrt(page, fixture);
  await expect(page.getByRole("heading", { name: "Current Reality Tree", includeHidden: true })).toHaveClass(/sr-only/);

  const original = page.getByRole("button", { name: /Synthetic effect/ });
  await original.dblclick();
  const escapeEditor = page.locator("input[data-card-editor-id]").last();
  await expect(escapeEditor).toBeFocused();
  await escapeEditor.fill("Should not persist");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: /Synthetic effect/ })).toBeVisible();
  expect(fixture.mutation("/api/crt/trees/tree-one", "PUT")).toHaveLength(0);

  await page.getByRole("button", { name: /Synthetic effect/ }).dblclick();
  const enterEditor = page.locator("input[data-card-editor-id]").last();
  await enterEditor.fill("Persisted inline label");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: /Persisted inline label/ })).toBeVisible();
  await expect.poll(() => fixture.mutation("/api/crt/trees/tree-one", "PUT").length).toBe(1);
  expect(fixture.tree("tree-one").nodes.some((node) => node.label === "Persisted inline label")).toBe(true);

  await page.getByRole("group", { name: "Current Reality Tree canvas" }).click();
  await page.keyboard.press("Control+z");
  await expect(page.getByRole("button", { name: /Synthetic effect/ })).toBeVisible();
  await expect.poll(() => fixture.mutation("/api/crt/trees/tree-one", "PUT").length).toBe(2);
  expect(fixture.tree("tree-one").nodes.some((node) => node.label === "Synthetic effect")).toBe(true);
});

test("T024 keyboard-only bottom-up creation reaches a persisted branching ten-card graph under two minutes", async ({ page }) => {
  await crtLabels("Keyboard-only branching ten-card creation and persistence");
  const fixture = new CrtFixture({ trees: [tenCardSeed()] });
  await openCrt(page, fixture);
  const effect = page.locator("[data-node-id='node-effect']");
  await test.step("load the synthetic effect before keyboard creation", async () => {
    await expect(effect).toBeVisible();
  });

  const started = await page.evaluate(() => performance.now());
  await addCardWithKeyboard(page, effect, "Enter", "Cause A");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause A" }), "Tab", "Cause B");

  // Exercise the composite focus model with real arrow navigation before the
  // remaining branches are created. No locator.focus/fill shortcuts are used.
  const causeB = page.getByRole("button", { name: "Root cause: Cause B" });
  await causeB.click();
  await page.keyboard.press("ArrowUp");
  await expect(effect).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("ArrowDown");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause A" }), "Enter", "Cause A2");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause A2" }), "Tab", "Cause A3");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause A2" }), "Enter", "Cause A4");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause A4" }), "Tab", "Cause A5");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause B" }), "Enter", "Cause B2");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause B2" }), "Tab", "Cause B3");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause B2" }), "Enter", "Cause B4");

  await expect(page.locator("[data-crt-card='true']")).toHaveCount(10);
  await expect(page.locator("[data-testid^='crt-edge-']")).toHaveCount(9);
  const elapsed = await page.evaluate((start) => performance.now() - start, started);
  expect(elapsed).toBeLessThan(120_000);

  const cards = await page.locator("[data-crt-card='true']").allTextContents();
  for (const label of ["Synthetic effect", "Cause A", "Cause B", "Cause A2", "Cause A3", "Cause A4", "Cause A5", "Cause B2", "Cause B3", "Cause B4"]) {
    expect(cards.some((card) => card.includes(label))).toBe(true);
  }
  const requestsBeforeZoom = fixture.mutation("/api/crt/trees/tree-ten", "PUT").length;
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect.poll(() => fixture.mutation("/api/crt/trees/tree-ten", "PUT").length).toBeGreaterThan(requestsBeforeZoom);
  await expect(page.getByRole("status").filter({ hasText: "Saved" }).last()).toBeVisible();

  let previousSaveCount = -1;
  let stableSamples = 0;
  await expect.poll(() => {
    const currentSaveCount = fixture.mutation("/api/crt/trees/tree-ten", "PUT").length;
    stableSamples = currentSaveCount === previousSaveCount ? stableSamples + 1 : 0;
    previousSaveCount = currentSaveCount;
    return stableSamples;
  }, { intervals: [250, 250, 250, 250, 250, 250], timeout: 5_000 }).toBeGreaterThanOrEqual(4);
  const saves = fixture.mutation("/api/crt/trees/tree-ten", "PUT");
  expect(saves.length).toBeGreaterThan(0);
  const finalSave = saves.at(-1);
  if (!finalSave) throw new Error("Missing persisted branching graph save");
  const body = finalSave.body as { nodes: NodeFixture[]; relations: RelationFixture[]; metadata: TreeFixture["metadata"] };
  expect(body.nodes).toHaveLength(10);
  expect(body.relations).toHaveLength(9);
  const incomingCounts = new Map<string, number>();
  body.relations.forEach((relation) => incomingCounts.set(relation.target_node_id, (incomingCounts.get(relation.target_node_id) ?? 0) + 1));
  expect(Math.max(...incomingCounts.values())).toBeGreaterThan(1);
  expect(body.relations.every((relation) => body.nodes.findIndex((candidate) => candidate.id === relation.source_node_id) > body.nodes.findIndex((candidate) => candidate.id === relation.target_node_id))).toBe(true);

  const persistedZoom = fixture.tree("tree-ten").metadata.layout?.zoom;
  expect(persistedZoom).toBeDefined();
  expect(persistedZoom).not.toBe(0.8);
  await page.reload();
  await expect(page.locator("[data-crt-card='true']")).toHaveCount(10);
  await expect(page.locator("[aria-label='Zoom level']")).toContainText(`${Math.round((persistedZoom ?? 0) * 100)}%`);
  expect(fixture.tree("tree-ten").nodes).toHaveLength(10);
  expect(fixture.tree("tree-ten").relations).toHaveLength(9);
});

test("T024 failed PUT recovery replays the durable request exactly and revision conflict preserves local choice", async ({ page }) => {
  await crtLabels("Durable save recovery and revision conflict choices");
  const fixture = new CrtFixture({ trees: [oneCardTree()], failNextPut: true });
  await openCrt(page, fixture);
  const effect = page.getByRole("button", { name: "Synthetic effect" });
  await effect.focus();
  await page.keyboard.press("Enter");
  const editor = page.locator("input[data-card-editor-id]").last();
  await editor.fill("Local recovery label");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("button", { name: "Retry save" })).toBeVisible();

  const failed = latestMutation(fixture, "/api/crt/trees/tree-one", "PUT");
  assertMutationHeaders(failed);
  const durableDraft = await page.evaluate(() => Object.entries(localStorage)
    .filter(([key]) => key.startsWith("bb.crt.draft.v1."))
    .map(([key, value]) => ({ key, value })));
  expect(durableDraft.length).toBeGreaterThan(0);
  expect(durableDraft.some(({ value }) => value.includes(failed.headers["idempotency-key"]))).toBe(true);

  await test.step("reload, recover the durable draft, and replay the same PUT without changing its key or payload", async () => {
    await page.reload();
    await expect(page.getByRole("heading", { name: "Recover local draft" })).toBeVisible();
    await page.getByRole("button", { name: "Recover draft" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Saved" }).last()).toBeVisible();
    const replay = latestMutation(fixture, "/api/crt/trees/tree-one", "PUT");
    expect(replay.headers["idempotency-key"]).toBe(failed.headers["idempotency-key"]);
    expect(replay.body).toEqual(failed.body);
    await expect(page.getByRole("button", { name: "Root cause: Local recovery label" })).toBeVisible();
  });

  await test.step("surface a stale revision while retaining the local graph", async () => {
    fixture.enableNextConflict();
    const localCause = page.getByRole("button", { name: "Root cause: Local recovery label" });
    await localCause.click();
    await page.keyboard.press("Enter");
    const conflictEditor = page.locator("input[data-card-editor-id]").last();
    await conflictEditor.fill("Local-only choice");
    await page.keyboard.press("Enter");
    await expect(page.getByText("The server changed this tree. Your local graph is retained")).toBeVisible();
    await expect(page.getByRole("button", { name: "Intermediate: Local recovery label" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Root cause: Local-only choice" })).toBeVisible();
    await page.getByRole("button", { name: "Refresh server copy" }).click();
    await expect(page.getByRole("button", { name: "Save local changes" })).toBeVisible();
    await expect(page.getByText("Server copy label")).toHaveCount(0);
    expect(fixture.tree("tree-one").nodes.find((candidate) => candidate.id === "node-effect")?.label).toBe("Server copy label");
    const savesBeforeResolution = fixture.mutation("/api/crt/trees/tree-one", "PUT").length;
    await page.getByRole("button", { name: "Save local changes" }).click();
    await expect.poll(() => fixture.mutation("/api/crt/trees/tree-one", "PUT").length).toBeGreaterThan(savesBeforeResolution);
    await expect(page.getByRole("status").filter({ hasText: "Saved" }).last()).toBeVisible();
    const conflictSave = fixture.mutation("/api/crt/trees/tree-one", "PUT").at(-1);
    if (!conflictSave) throw new Error("Missing conflict resolution save");
    assertMutationHeaders(conflictSave);
    expect((conflictSave.body as { expected_revision: number }).expected_revision).toBe(3);
    expect(JSON.stringify(conflictSave.body)).toContain("Local-only choice");
  });
});

test("T024 server-rejected import leaves graph and local draft bytes unchanged", async ({ page }) => {
  await crtLabels("Atomic import rejection");
  const fixture = new CrtFixture({ trees: [oneCardTree()], rejectImport: true });
  await openCrt(page, fixture);
  await expect(page.getByRole("button", { name: "Synthetic effect" })).toBeVisible();
  const beforeGraph = await page.locator("[data-crt-card='true']").allTextContents();
  const beforeStorage = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage)));
  const validExport = { tree: clone(fixture.tree("tree-one")) };

  await test.step("reject the import atomically and retain the visible graph and draft bytes", async () => {
    await page.getByRole("button", { name: /Current tree: Synthetic tree/ }).click();
    await page.getByRole("menuitem", { name: "Import tree JSON" }).click();
    await page.getByLabel("Choose tree JSON file").setInputFiles({
      name: "server-rejected.json",
      mimeType: "application/json",
      buffer: Buffer.from(JSON.stringify(validExport))
    });
    await expect(page.getByRole("alert")).toContainText("couldn't import");
    await expect(page.locator("[data-crt-card='true']")).toHaveCount(1);
    expect(await page.locator("[data-crt-card='true']").allTextContents()).toEqual(beforeGraph);
    expect(await page.evaluate(() => Object.fromEntries(Object.entries(localStorage)))).toEqual(beforeStorage);
    const importRequest = latestMutation(fixture, "/api/crt/trees/import", "POST");
    assertMutationHeaders(importRequest);
  });
});

test("T024 normal OFF is a content-free 404 boundary", async ({ page }) => {
  await crtLabels("Normal feature-off boundary");
  const fixture = new CrtFixture({ exposureStatus: 404 });
  await openCrt(page, fixture);
  await test.step("verify the normal disabled boundary makes no content request", async () => {
    await expect(page.getByRole("heading", { name: "Thinking Mode isn't available for this account" })).toBeVisible();
    expect(countContentRequests(fixture)).toBe(0);
    expect(fixture.requests.filter((request) => request.path === "/api/crt/exposure")).toHaveLength(1);
  });
});

test("T024 degraded flag storage is a content-free 503 boundary with retry reference", async ({ page }) => {
  await crtLabels("Degraded flag-store boundary");
  const fixture = new CrtFixture({ exposureStatus: 503 });
  await openCrt(page, fixture);
  await test.step("verify the degraded boundary exposes retry support without content", async () => {
    await expect(page.getByRole("heading", { name: "Thinking Mode is temporarily unavailable" })).toBeVisible();
    await expect(page.getByLabel("Support reference")).toHaveValue(SUPPORT_REFERENCE);
    await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
    expect(countContentRequests(fixture)).toBe(0);
  });
});

test("T024 unsupported width is honest and does not mount or fetch tree content", async ({ page }) => {
  await crtLabels("Unsupported viewport boundary");
  const fixture = new CrtFixture({ trees: [oneCardTree()] });
  await page.setViewportSize({ width: 1000, height: 700 });
  await openCrt(page, fixture);
  await test.step("verify the honest narrow-width boundary is content-free", async () => {
    await expect(page.getByRole("heading", { name: "Thinking Mode needs a wider window" })).toBeVisible();
    await expect(page.getByText("Use a window at least 1024 px wide to edit this tree.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Back to Tasks" })).toBeVisible();
    await expect(page.locator("[data-testid='crt-flow-region']")).toHaveCount(0);
    expect(fixture.requests.filter((request) => request.path.startsWith("/api/crt/")).length).toBe(0);
  });
});

test("T027 bounded 200-card Chromium evidence records 20 samples per operation and passes the supported desktop audit", async ({ browser, page }, testInfo) => {
  // Setup, autosave settlement, and undo waits are intentionally outside the
  // measured operation samples and can vary on shared CI workers.
  test.setTimeout(180_000);
  await removeEvidenceArtifact("t027-200-card-performance.json");
  await crtLabels("Bounded 200-card performance and accessibility evidence");
  const performanceTree = twoHundredCardTree();
  const fixture = new CrtFixture({ trees: [performanceTree] });
  await fixture.install(page);
  const saveTelemetry: unknown[] = [];
  page.on("console", async (message) => {
    if (!message.text().startsWith("[telemetry]")) return;
    const payload = message.args()[1];
    if (!payload) return;
    try {
      const value = await payload.jsonValue();
      if (typeof value === "object" && value !== null && (value as { name?: unknown }).name === "crt.save") {
        saveTelemetry.push(value);
      }
    } catch {
      // A detached console handle is diagnostic-only and must not fail the journey.
    }
  });
  await page.goto("/crt");
  const cards = page.locator("[data-crt-card='true']");
  const flowRegion = page.locator("[data-testid='crt-flow-region']");
  const savedStatus = page.getByText("Saved", { exact: true });
  const expectSaved = async (): Promise<void> => {
    // Let the graph update publish its Unsaved/Saving state before accepting a
    // pre-existing Saved label from the previous operation.
    await nextAnimationFrame(page);
    try {
      await expect(savedStatus).toBeVisible({ timeout: 10_000 });
    } catch (error) {
      const visibleStatus = await page.getByRole("status").textContent().catch(() => null);
      throw new Error(
        `CRT did not stabilize as Saved; status=${JSON.stringify(visibleStatus)}; recent_save_telemetry=${JSON.stringify(saveTelemetry.slice(-3))}`,
        { cause: error }
      );
    }
  };
  await test.step("load the 200-card fixture before collecting bounded samples", async () => {
    await expect(cards).toHaveCount(200, { timeout: LARGE_CANVAS_READY_BUDGET_MS });
  });
  const visibleCardIndexes = await cards.evaluateAll((elements) => {
    const flow = document.querySelector<HTMLElement>("[data-testid='crt-flow-region']")?.getBoundingClientRect();
    if (!flow) return [];
    return elements.flatMap((element, index) => {
      const box = element.getBoundingClientRect();
      const visible = index > 0 && box.top >= flow.top + 80 && box.bottom <= flow.bottom - 80 &&
        box.left >= flow.left + 120 && box.right <= flow.right - 120;
      return visible ? [index] : [];
    }).slice(0, 2);
  });
  expect(visibleCardIndexes).toHaveLength(2);
  const anchorIndex = visibleCardIndexes[0] ?? -1;
  const alternateIndex = visibleCardIndexes[1] ?? -1;
  expect(anchorIndex).toBeGreaterThan(0);
  expect(alternateIndex).toBeGreaterThan(0);
  const anchorCard = cards.nth(anchorIndex);
  const alternateCard = cards.nth(alternateIndex);
  await expect(anchorCard).toBeVisible();
  await expect(alternateCard).toBeVisible();
  const anchorNodeId = await anchorCard.getAttribute("data-node-id");
  const alternateNodeId = await alternateCard.getAttribute("data-node-id");
  if (!anchorNodeId || !alternateNodeId) throw new Error("Visible performance cards need stable node identities");
  const anchorSelector = `[data-node-id="${anchorNodeId}"]`;
  const alternateSelector = `[data-node-id="${alternateNodeId}"]`;
  const anchorFlowNodeSelector = `.react-flow__node:has(${anchorSelector})`;

  const samples: Record<"selection" | "drag" | "enter" | "tab" | "pan" | "zoom", number[]> = {
    selection: [], drag: [], enter: [], tab: [], pan: [], zoom: []
  };
  const record = async (
    operation: keyof typeof samples,
    probe: InteractionProbeConfig,
    action: () => Promise<void>
  ): Promise<void> => {
    await armInteractionProbe(page, probe);
    try {
      await action();
      samples[operation].push(await collectInteractionProbe(page));
    } finally {
      await discardInteractionProbe(page);
    }
  };
  const selectVisibleCardForShortcut = async (): Promise<void> => {
    const findVisibleIndex = (): Promise<number> => cards.evaluateAll((elements) => {
      const flow = document.querySelector<HTMLElement>("[data-testid='crt-flow-region']")?.getBoundingClientRect();
      const header = document.querySelector<HTMLElement>(".crt-canvas-toolbar")?.getBoundingClientRect();
      if (!flow) return -1;
      const topBoundary = Math.max(flow.top + 16, (header?.bottom ?? flow.top) + 16);
      return elements.findIndex((element) => {
        const box = element.getBoundingClientRect();
        const nodeIndex = Number(element.getAttribute("data-node-id")?.replace("node-", ""));
        return Number.isInteger(nodeIndex) && nodeIndex > 0 && nodeIndex % 10 === 0 &&
          element.getAttribute("aria-pressed") !== "true" &&
          box.top >= topBoundary && box.bottom <= flow.bottom - 80 &&
          box.left >= flow.left + 80 && box.right <= flow.right - 80;
      });
    });
    let visibleIndex = await findVisibleIndex();
    if (visibleIndex < 0) {
      await page.getByRole("button", { name: "Fit all cards" }).click();
      await expect.poll(findVisibleIndex, { timeout: 5_000 }).toBeGreaterThanOrEqual(0);
      await page.waitForTimeout(550);
      await expectSaved();
      visibleIndex = await findVisibleIndex();
    }
    expect(visibleIndex).toBeGreaterThanOrEqual(0);
    const visibleCard = cards.nth(visibleIndex);
    await visibleCard.click();
    await expect(visibleCard).toHaveAttribute("aria-pressed", "true");
    await visibleCard.focus();
    await expect(visibleCard).toBeFocused();
  };

  for (let index = 0; index < 20; index += 1) {
    const targetCard = index % 2 === 0 ? anchorCard : alternateCard;
    const targetSelector = index % 2 === 0 ? anchorSelector : alternateSelector;
    await expect(targetCard).toHaveAttribute("aria-pressed", "false");
    await record(
      "selection",
      {
        event_name: "click",
        input_selector: targetSelector,
        observations: [{ kind: "attribute", selector: targetSelector, name: "aria-pressed", value: "true" }]
      },
      () => targetCard.click()
    );
    await expect(targetCard).toHaveAttribute("aria-pressed", "true");
  }

  // Pointerdown only arms React Flow's gesture; pointermove is the first input
  // that can move a card. Starting at pointerdown would include the Playwright
  // protocol gap before the real move and violate the browser-only interval.
  for (let index = 0; index < 20; index += 1) {
    const completedSaveCount = fixture.mutation("/api/crt/trees/tree-large", "PUT").length;
    const before = await anchorCard.boundingBox();
    if (!before) throw new Error("Visible card has no box for drag sample");
    const flowNode = page.locator(anchorFlowNodeSelector);
    const delta = index % 2 === 0 ? 24 : -24;
    await page.mouse.move(before.x + before.width / 2, before.y + before.height / 2);
    await page.mouse.down();
    try {
      // The first move crosses React Flow's gesture threshold and arms the
      // drag. The measured move below is the first one that can change the
      // already-active node transform.
      await page.mouse.move(
        before.x + before.width / 2 + delta / 6,
        before.y + before.height / 2
      );
      await expect(flowNode).toHaveClass(/dragging/);
      const beforeTransform = await flowNode.getAttribute("style");
      await record(
        "drag",
        {
          event_name: "pointermove",
          observations: [{
            kind: "attribute-change",
            selector: anchorFlowNodeSelector,
            name: "style",
            before: beforeTransform
          }]
        },
        () => page.mouse.move(
          before.x + before.width / 2 + delta,
          before.y + before.height / 2
        )
      );
    } finally {
      await page.mouse.up();
    }
    await expect.poll(async () => (await anchorCard.boundingBox())?.x ?? before.x).not.toBe(before.x);
    // Prove this drag dispatched its own save before accepting Saved. Merely
    // checking the label can false-pass on the previous operation's state.
    await expect.poll(
      () => fixture.mutation("/api/crt/trees/tree-large", "PUT").length,
      { timeout: 10_000 }
    ).toBeGreaterThan(completedSaveCount);
    await expectSaved();
  }

  for (let index = 0; index < 20; index += 1) {
    await selectVisibleCardForShortcut();
    const editors = page.locator("input[data-card-editor-id]");
    await expect(editors).toHaveCount(0);
    const editor = editors.last();
    await record(
      "enter",
      {
        event_name: "keydown",
        key: "Enter",
        observations: [{ kind: "focus", selector: "input[data-card-editor-id]" }]
      },
      () => page.keyboard.press("Enter")
    );
    await expect(editor).toBeVisible();
    await expect(editor).toBeFocused();
    const createdNodeId = await editor.getAttribute("data-card-editor-id") ?? "";
    if (!createdNodeId) throw new Error("Enter did not expose the created card identity");
    await page.keyboard.press("Escape");
    await expect(page.locator(`[data-node-id="${createdNodeId}"]`)).toBeFocused();
    await page.keyboard.press("Control+z");
    await expectSaved();
    expect(fixture.tree("tree-large").nodes).toHaveLength(200);
  }

  for (let index = 0; index < 20; index += 1) {
    await selectVisibleCardForShortcut();
    const editors = page.locator("input[data-card-editor-id]");
    await expect(editors).toHaveCount(0);
    const editor = editors.last();
    await record(
      "tab",
      {
        event_name: "keydown",
        key: "Tab",
        observations: [{ kind: "focus", selector: "input[data-card-editor-id]" }]
      },
      () => page.keyboard.press("Tab")
    );
    await expect(editor).toBeVisible();
    await expect(editor).toBeFocused();
    const createdNodeId = await editor.getAttribute("data-card-editor-id") ?? "";
    if (!createdNodeId) throw new Error("Tab did not expose the created card identity");
    await page.keyboard.press("Escape");
    await expect(page.locator(`[data-node-id="${createdNodeId}"]`)).toBeFocused();
    await page.keyboard.press("Control+z");
    await expectSaved();
    expect(fixture.tree("tree-large").nodes).toHaveLength(200);
  }

  const findOpenPanePoint = async (): Promise<{ x: number; y: number }> => flowRegion.evaluate((region) => {
    const bounds = region.getBoundingClientRect();
    for (let y = bounds.bottom - 24; y >= bounds.top + 96; y -= 16) {
      for (let x = bounds.right - 24; x >= bounds.left + 96; x -= 16) {
        const target = document.elementFromPoint(x, y);
        if (target instanceof HTMLElement && target.classList.contains("react-flow__pane")) {
          return { x, y };
        }
      }
    }
    throw new Error("Canvas has no unobstructed pane point for a real pan sample");
  });
  await page.getByRole("button", { name: "Pan canvas" }).click();
  try {
    await expect(flowRegion).toHaveAttribute("data-pan-active", "true");
    // Pointerdown only arms the gesture. Pointermove is the first input that
    // changes the viewport, and release happens after the measured frame.
    for (let index = 0; index < 20; index += 1) {
      await expect(flowRegion).toBeVisible();
      await expect(flowRegion).toHaveAttribute("data-pan-active", "true");
      const panPoint = await findOpenPanePoint();
      const beforeTransform = await page.locator(".react-flow__viewport").getAttribute("style");
      const delta = index % 2 === 0 ? 24 : -24;
      await page.mouse.move(panPoint.x, panPoint.y);
      await page.mouse.down();
      try {
        await record(
          "pan",
          {
            event_name: "pointermove",
            observations: [{
              kind: "attribute-change",
              selector: ".react-flow__viewport",
              name: "style",
              before: beforeTransform
            }]
          },
          () => page.mouse.move(panPoint.x + delta, panPoint.y + 16)
        );
      } finally {
        await page.mouse.up();
      }
      await expect.poll(() => page.locator(".react-flow__viewport").getAttribute("style")).not.toBe(beforeTransform);
    }
  } finally {
    if (await flowRegion.getAttribute("data-pan-active") === "true") {
      await page.getByRole("button", { name: "Pan canvas" }).click();
    }
  }

  await page.waitForTimeout(150);
  for (let index = 0; index < 20; index += 1) {
    const zoomLevel = page.locator("[aria-label='Zoom level']");
    const viewport = page.locator(".react-flow__viewport");
    const beforeZoom = await zoomLevel.textContent();
    const beforeTransform = await viewport.getAttribute("style");
    const beforePercent = Number.parseInt(beforeZoom ?? "", 10);
    const zoomAction = beforePercent <= 25
      ? "Zoom in"
      : beforePercent >= 100
        ? "Zoom out"
        : index % 2 === 0 ? "Zoom in" : "Zoom out";
    await record(
      "zoom",
      {
        event_name: "click",
        observations: [
          {
            kind: "attribute-change",
            selector: ".react-flow__viewport",
            name: "style",
            before: beforeTransform
          },
          { kind: "text-change", selector: "[aria-label='Zoom level']", before: beforeZoom }
        ]
      },
      () => page.getByRole("button", { name: zoomAction }).click()
    );
    await expect(zoomLevel).not.toHaveText(beforeZoom ?? "");
    await expect.poll(() => viewport.getAttribute("style")).not.toBe(beforeTransform);
    await page.waitForTimeout(150);
    await expectSaved();
  }

  const allSamples = Object.values(samples).flat();
  const withinBudget = allSamples.filter((sample) => sample <= 200).length;
  const axeResult = await new AxeBuilder({ page }).analyze();
  const seriousViolations = axeResult.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");

  const widthAudits: WidthAudit[] = [];
  for (const width of SUPPORTED_DESKTOP_WIDTHS) {
    await page.setViewportSize({ width, height: 768 });
    await page.getByRole("button", { name: "Fit all cards" }).click();
    await nextAnimationFrame(page);
    const widthAudit = await page.evaluate((): WidthAudit => ({
      inner_width: window.innerWidth,
      document_scroll_width: document.documentElement.scrollWidth,
      horizontal_overflow: document.documentElement.scrollWidth > window.innerWidth,
      clipped_shell: [...document.querySelectorAll<HTMLElement>("[data-testid='crt-flow-region'], .crt-canvas-shell")]
        .some((element) => element.scrollWidth > element.clientWidth)
    }));
    expect(widthAudit.inner_width, `width audit must run at ${width}px`).toBe(width);
    expect(widthAudit.horizontal_overflow, `${width}px must not horizontally overflow`).toBe(false);
    expect(widthAudit.clipped_shell, `${width}px must not clip the canvas shell`).toBe(false);
    widthAudits.push(widthAudit);
  }
  const operationStats = Object.fromEntries(Object.entries(samples).map(([operation, values]) => [operation, {
    sample_count: values.length,
    raw_ms: values,
    p95_ms: p95(values),
    within_200ms: values.filter((sample) => sample <= 200).length
  }]));
  const candidateSha = process.env.BRAIN_BUDDY_CANDIDATE_SHA ?? null;
  const exactShaRequired = process.env.CI === "true" ||
    process.env.BRAIN_BUDDY_REQUIRE_EXACT_SHA === "1";
  const evidence = {
    schema_version: 1,
    candidate_sha: candidateSha,
    candidate_state: candidateSha === null ? "uncommitted_worktree" : "exact_commit",
    fixture: {
      card_count_at_load: performanceTree.nodes.length,
      relation_count_at_load: performanceTree.relations.length,
      synthetic: true
    },
    browser: "Chromium",
    browser_version: browser.version(),
    measurement: "browser_event_to_first_observable_animation_frame",
    supported_widths: [...SUPPORTED_DESKTOP_WIDTHS],
    operations: operationStats,
    aggregate: { sample_count: allSamples.length, p95_ms: p95(allSamples), within_200ms: withinBudget, required_within_200ms: Math.ceil(allSamples.length * 0.95) },
    accessibility: {
      serious_or_critical_violations: seriousViolations.length,
      violations: seriousViolations.map((violation) => ({
        id: violation.id,
        impact: violation.impact,
        help: violation.help,
        node_count: violation.nodes.length
      }))
    },
    width_audit: widthAudits
  };
  if (exactShaRequired) {
    expect(candidateSha, "final T027 evidence must be bound to the exact candidate SHA")
      .toMatch(/^[0-9a-f]{40}$/);
  } else if (candidateSha !== null) {
    expect(candidateSha).toMatch(/^[0-9a-f]{40}$/);
  }
  expect(allSamples).toHaveLength(120);
  for (const [operation, values] of Object.entries(samples)) {
    expect(values, `${operation} must contain exactly 20 raw samples`).toHaveLength(20);
    expect(p95(values), `${operation} p95 must stay within 200ms`).toBeLessThanOrEqual(200);
  }
  expect(p95(allSamples)).toBeLessThanOrEqual(200);
  expect(withinBudget).toBeGreaterThanOrEqual(Math.ceil(allSamples.length * 0.95));
  expect(seriousViolations).toEqual([]);
  evidenceArtifacts.set(page, ["t027-200-card-performance.json"]);
  await writeEvidenceArtifact("t027-200-card-performance.json", evidence);
  await testInfo.attach("t027-200-card-performance.json", {
    body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
});

test("T024 tree management supports switch, rename, export, cancel, and revision-safe delete", async ({ page }) => {
  await crtLabels("Tree management and revision-safe deletion");
  const first = oneCardTree("tree-a", "Tree A");
  const second = oneCardTree("tree-b", "Tree B");
  const fixture = new CrtFixture({ trees: [first, second] });
  await openCrt(page, fixture);
  await test.step("load the first synthetic tree before managing the tree set", async () => {
    await expect(page.getByRole("button", { name: "Synthetic effect" })).toBeVisible();
  });

  await page.getByRole("button", { name: /Current tree: Tree A/ }).click();
  await page.getByRole("menuitem", { name: "Switch to Tree B" }).click();
  await expect(page.getByRole("button", { name: /Current tree: Tree B/ })).toBeVisible();
  await page.getByRole("button", { name: /Current tree: Tree B/ }).click();
  page.once("dialog", (dialog) => void dialog.accept("Renamed Tree B"));
  await page.getByRole("menuitem", { name: "Rename tree" }).click();
  await expect(page.getByRole("button", { name: /Current tree: Renamed Tree B/ })).toBeVisible();
  const rename = latestMutation(fixture, "/api/crt/trees/tree-b", "PUT");
  assertMutationHeaders(rename);
  expect((rename.body as { expected_revision: number }).expected_revision).toBe(1);

  await page.getByRole("button", { name: /Current tree: Renamed Tree B/ }).click();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("menuitem", { name: "Export saved server copy" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/Renamed-Tree-B\.json$/);
  expect(fixture.mutation("/api/crt/trees/tree-b/export", "POST")).toHaveLength(1);

  await page.getByRole("button", { name: /Current tree: Renamed Tree B/ }).click();
  await page.getByRole("menuitem", { name: "Delete tree" }).click();
  await expect(page.getByRole("alertdialog")).toContainText("Delete ‘Renamed Tree B’?");
  await page.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("button", { name: /Current tree: Renamed Tree B/ })).toBeVisible();
  expect(fixture.mutation("/api/crt/trees/tree-b", "DELETE")).toHaveLength(0);

  await page.getByRole("button", { name: /Current tree: Renamed Tree B/ }).click();
  await page.getByRole("menuitem", { name: "Delete tree" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete tree" }).click();
  await expect(page.getByRole("button", { name: /Current tree: Tree A/ })).toBeVisible();
  const deletion = latestMutation(fixture, "/api/crt/trees/tree-b?expected_revision=2", "DELETE");
  assertMutationHeaders(deletion);
  expect(fixture.tree("tree-a").id).toBe("tree-a");
});

test("T010 real connector drag links cause to effect without moving cards", async ({ page }) => {
  await crtLabels("Real pointer connector drag preserves cause-to-effect direction");
  const fixture = new CrtFixture({
    trees: [treeFixture("tree-connectors", "Connector tree", [
      node("node-cause", "Cause", { x: 0, y: 220 }),
      node("node-effect", "Effect", { x: 0, y: 0 })
    ])]
  });
  await openCrt(page, fixture);

  await test.step("drag the visible connector and verify persisted direction without card movement", async () => {
    await expect(page.locator('[data-node-id="node-cause"]')).toContainText("Cause");
  await page.getByRole("button", { name: "Connect cards" }).click();
  const target = page.getByRole("button", { name: "Connect into bottom of Effect" });
  const source = page.getByRole("button", { name: "Connect from top of Cause" });
  await expect(target).toBeVisible();
  await expect(source).toBeVisible();
  const causeCard = page.locator('[data-node-id="node-cause"]');
  const effectCard = page.locator('[data-node-id="node-effect"]');
  const causeBefore = await causeCard.boundingBox();
  const effectBefore = await effectCard.boundingBox();
  if (!causeBefore || !effectBefore) throw new Error("Connector cards must have visible bounds");
  const targetBox = await target.boundingBox();
  const sourceBox = await source.boundingBox();
  if (!targetBox || !sourceBox) throw new Error("Connector controls must have visible bounds");

  await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2);
  await page.mouse.down();
  await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2);
  await page.mouse.up();

  await expect.poll(() => fixture.tree("tree-connectors").relations.length).toBe(1);
  expect(fixture.tree("tree-connectors").relations[0]).toMatchObject({
    source_node_id: "node-cause",
    target_node_id: "node-effect"
  });
  const causeAfter = await causeCard.boundingBox();
  const effectAfter = await effectCard.boundingBox();
  expect(causeAfter?.y).toBeCloseTo(causeBefore.y, 1);
  expect(effectAfter?.y).toBeCloseTo(effectBefore.y, 1);
  });
});

test("T010 target-first visible connector click still adds a relation", async ({ page }) => {
  await crtLabels("Target-first connector click preserves the two-click path");
  await test.step("select the effect first and connect the cause", async () => {
  const fixture = new CrtFixture({ trees: [treeFixture("tree-click", "Click connectors", [
    node("node-cause", "Cause", { x: 0, y: 220 }),
    node("node-effect", "Effect", { x: 0, y: 0 })
  ])] });
  await openCrt(page, fixture);
  await page.getByRole("button", { name: "Connect cards" }).click();
  await page.getByRole("button", { name: "Connect into bottom of Effect" }).click();
  await page.getByRole("button", { name: "Connect from top of Cause" }).click();
  await expect.poll(() => fixture.tree("tree-click").relations.length).toBe(1);
  expect(fixture.tree("tree-click").relations[0]).toMatchObject({ source_node_id: "node-cause", target_node_id: "node-effect" });
  });
});

test("T024 Compose selected-user Chromium journey proves auth exposure, persistence, and second-account 404 isolation", async ({ page }, testInfo) => {
  await crtLabels("Unmocked Compose authentication, rollout, persistence, and isolation");
  await removeEvidenceArtifact("t024-compose-auth-isolation.json");
  const selectedEmail = process.env.BRAIN_BUDDY_E2E_SELECTED_EMAIL;
  const selectedPassword = process.env.BRAIN_BUDDY_E2E_SELECTED_PASSWORD;
  const secondEmail = process.env.BRAIN_BUDDY_E2E_SECOND_EMAIL;
  const secondPassword = process.env.BRAIN_BUDDY_E2E_SECOND_PASSWORD;
  if (!selectedEmail || !selectedPassword || !secondEmail || !secondPassword) {
    test.skip(true, "Compose operator setup is required for the unmocked CRT journey");
    return;
  }

  const contentRequests: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/crt/trees")) contentRequests.push(`${request.method()} ${url.pathname}`);
  });
  const selectedAuth = await test.step("authenticate the selected user and verify CRT exposure", async () => {
    await loginThroughUi(page, selectedEmail, selectedPassword);
    return page.evaluate(async () => {
      const me = await fetch("/api/auth/me");
      const exposure = await fetch("/api/crt/exposure");
      return { me: await me.json(), exposureStatus: exposure.status };
    });
  });
  expect(selectedAuth.me.feature_flags.crt_canvas).toBe(true);
  expect(selectedAuth.exposureStatus).toBe(204);

  const started = await page.evaluate(() => performance.now());
  await page.getByRole("link", { name: "Thinking Mode" }).click();
  await expect(page.getByRole("heading", { name: "Start with your first undesired effect" })).toBeVisible();
  await page.getByRole("button", { name: "Create first tree" }).click();
  await expect(page.getByRole("heading", { name: "Current Reality Tree" })).toHaveClass(/sr-only/);
  await page.getByRole("button", { name: "Add card" }).click();
  const effectEditor = page.locator("input[data-card-editor-id]").last();
  await expect(effectEditor).toBeFocused();
  await page.keyboard.type("Synthetic undesired effect");
  await page.keyboard.press("Enter");

  const effect = page.getByRole("button", { name: "Synthetic undesired effect" });
  await addCardWithKeyboard(page, effect, "Enter", "Cause A");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause A" }), "Tab", "Cause B");
  const effectButton = page.getByRole("button", { name: "Effect: Synthetic undesired effect" });
  await page.getByRole("button", { name: "Root cause: Cause B" }).click();
  await page.keyboard.press("ArrowUp");
  await expect(effectButton).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("ArrowDown");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause A" }), "Enter", "Cause A2");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause A2" }), "Tab", "Cause A3");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause A2" }), "Enter", "Cause A4");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause A4" }), "Tab", "Cause A5");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause B" }), "Enter", "Cause B2");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause B2" }), "Tab", "Cause B3");
  await addCardWithKeyboard(page, page.getByRole("button", { name: "Root cause: Cause B2" }), "Enter", "Cause B4");
  await expect(page.locator("[data-crt-card='true']")).toHaveCount(10);
  await expect(page.locator("[data-testid^='crt-edge-']")).toHaveCount(9);
  await expect.poll(async () => {
    if (await page.getByText("Save failed").isVisible()) return "failure";
    if (await page.getByText("Saved", { exact: true }).isVisible()) return "success";
    return "pending";
  }, { timeout: 10_000 }).toBe("success");
  const elapsed = await page.evaluate((start) => performance.now() - start, started);
  expect(elapsed).toBeLessThan(120_000);

  const readPersisted = async () => page.evaluate(async () => {
    const listResponse = await fetch("/api/crt/trees");
    const list = await listResponse.json() as Array<{ id: string; name: string }>;
    const tree = list.find((candidate) => candidate.name === "My first tree");
    if (!tree) return { found: false, id: "", nodeCount: 0, relationCount: 0, maxIncoming: 0 };
    const treeResponse = await fetch(`/api/crt/trees/${encodeURIComponent(tree.id)}`);
    const body = await treeResponse.json() as { nodes?: unknown[]; relations?: Array<{ target_node_id: string }> };
    const incoming = new Map<string, number>();
    for (const relation of body.relations ?? []) incoming.set(relation.target_node_id, (incoming.get(relation.target_node_id) ?? 0) + 1);
    return { found: true, id: tree.id, nodeCount: body.nodes?.length ?? 0, relationCount: body.relations?.length ?? 0, maxIncoming: Math.max(0, ...incoming.values()) };
  });
  let persisted = await readPersisted();
  await expect.poll(async () => {
    persisted = await readPersisted();
    return { found: persisted.found, nodeCount: persisted.nodeCount, relationCount: persisted.relationCount };
  }, { intervals: [250, 500, 1000, 1000], timeout: 15_000 }).toEqual({ found: true, nodeCount: 10, relationCount: 9 });
  expect(persisted.maxIncoming).toBeGreaterThan(1);
  await page.reload();
  await expect(page.locator("[data-crt-card='true']")).toHaveCount(10);
  await expect(page.getByRole("button", { name: "Effect: Synthetic undesired effect" })).toBeVisible();

  await page.evaluate(async () => { await fetch("/api/auth/logout", { method: "POST" }); });
  await page.reload();
  await expect(page).toHaveURL(/\/login$/);
  const contentBeforeSecond = contentRequests.length;
  await loginThroughUi(page, secondEmail, secondPassword);
  const secondAuth = await page.evaluate(async () => {
    const me = await fetch("/api/auth/me");
    const exposure = await fetch("/api/crt/exposure");
    return { me: await me.json(), exposureStatus: exposure.status };
  });
  expect(secondAuth.me.feature_flags.crt_canvas).toBe(false);
  expect(secondAuth.exposureStatus).toBe(404);
  await page.goto("/crt");
  await expect(page.getByRole("heading", { name: "Thinking Mode isn't available for this account" })).toBeVisible();
  const frontendContentRequestsSuppressed = contentRequests.slice(contentBeforeSecond).length === 0;
  expect(frontendContentRequestsSuppressed).toBe(true);
  const secondTrees = await page.evaluate(async () => {
    const response = await fetch("/api/crt/trees");
    return { status: response.status, body: await response.text() };
  });
  expect(secondTrees.status).toBe(404);
  expect(secondTrees.body).not.toContain("Synthetic undesired effect");
  expect(secondTrees.body).not.toContain(persisted.id);
  const secondTreesBody = JSON.parse(secondTrees.body) as { detail?: { reason?: string } };
  const secondResponseContentFree = secondTreesBody.detail?.reason === "crt_canvas_disabled";
  expect(secondResponseContentFree).toBe(true);

  const candidateSha = process.env.BRAIN_BUDDY_CANDIDATE_SHA ?? null;
  const exactShaRequired = process.env.CI === "true" ||
    process.env.BRAIN_BUDDY_REQUIRE_EXACT_SHA === "1";
  if (exactShaRequired) {
    expect(candidateSha, "final T024 evidence must be bound to the exact candidate SHA")
      .toMatch(/^[0-9a-f]{40}$/);
  } else if (candidateSha !== null) {
    expect(candidateSha).toMatch(/^[0-9a-f]{40}$/);
  }
  const evidence = {
    candidate_sha: candidateSha,
    candidate_state: candidateSha === null ? "uncommitted_worktree" : "exact_commit",
    schema_version: 1,
    synthetic: true,
    journey: "unmocked-compose-chromium",
    selected_user: { auth_me_crt_canvas: true, exposure_status: 204, persisted_node_count: persisted.nodeCount, persisted_relation_count: persisted.relationCount, persisted_after_reload: true },
    second_user: {
      auth_me_crt_canvas: false,
      exposure_status: 404,
      trees_status: secondTrees.status,
      content_free: secondResponseContentFree,
      frontend_content_requests_suppressed: frontendContentRequestsSuppressed
    },
    timed_keyboard_journey: { includes_thinking_mode_entry: true, includes_tab: true, includes_arrow_navigation: true, branching: true, card_count: 10, elapsed_ms: elapsed, budget_ms: 120000 }
  };
  evidenceArtifacts.set(page, ["t024-compose-auth-isolation.json"]);
  await writeEvidenceArtifact("t024-compose-auth-isolation.json", evidence);
  await testInfo.attach("t024-compose-auth-isolation.json", {
    body: Buffer.from(`${JSON.stringify(evidence, null, 2)}\n`, "utf8"),
    contentType: "application/json"
  });
});

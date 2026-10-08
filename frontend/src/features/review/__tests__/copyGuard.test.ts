/**
 * Copy and telemetry guard for the weekly review on the web (FR-004, FR-038,
 * FR-044; privacy checklist CHK022). It reads every review source as text and
 * renders the review surfaces, so a new string, a new colour or a new
 * telemetry field is checked without anyone remembering to add a case.
 */
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createElement, createRef } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { reviewApi } from "../../../api/review";
import type { ProjectResponse, TaskResponse } from "../../../api/taskTypes";
import { ShellToastContext } from "../../../components/shell/shellToast";
import { useAuthStore } from "../../../stores/authStore";
import { DecisionDialog } from "../DecisionDialog";
import { FormulationBlock } from "../FormulationBlock";

const featureSources = import.meta.glob(["../*.{ts,tsx}", "../steps/*.{ts,tsx}"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const apiSources = import.meta.glob(["../../../api/review.ts", "../../../api/reviewHooks.ts"], { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const sources = { ...featureSources, ...apiSources };

/** Error colouring the design reserves for real due dates and destructive controls. */
const ROSE_OR_RED = /\b(?:bg|text|border|ring|outline|fill|stroke|from|via|to|decoration|divide|shadow|accent)-(?:rose|red)-\d{2,3}\b/;
const OVERDUE = /overdue/i;
const STREAK = /streak/i;

const SENTINEL = {
  title: "SENTINEL-TITLE Renovate the bathroom",
  notes: "SENTINEL-NOTES call the landlord at home",
  reason: "SENTINEL-REASON waiting for the quote",
  ai: "SENTINEL-AI measure the walls"
};

const DAY = 86_400_000;
const iso = (offsetMs: number) => new Date(Date.now() + offsetMs).toISOString();

function task(overrides: Partial<TaskResponse> = {}, formulation: Partial<NonNullable<TaskResponse["formulation"]>> = {}): TaskResponse {
  return {
    id: "task_9f3c2a1b4d5e",
    title: SENTINEL.title,
    details: SENTINEL.notes,
    state: "next",
    project_id: null,
    tag_ids: [],
    due_date: null,
    priority: "none",
    waiting_for: null,
    waiting_since: null,
    order_key: 1,
    source_capture_ids: [],
    created_at: iso(-30 * DAY),
    updated_at: iso(-15 * DAY),
    completed_at: null,
    cancelled_at: null,
    revision: 7,
    formulation: {
      id: "form_a",
      started_at: iso(-15 * DAY),
      extended_at: null,
      extension_reason: null,
      park_floor_at: null,
      consecutive_stalled: 2,
      ageing_at: iso(-8 * DAY),
      ask_at: iso(-1 * DAY),
      park_due_at: iso(6 * DAY),
      paused_until: null,
      ...formulation
    },
    parked: null,
    ...overrides
  };
}

const projects: ProjectResponse[] = [];

function block(value: TaskResponse): React.ReactElement {
  const headingRef = createRef<HTMLHeadingElement>();
  return createElement("div", null, createElement("h2", { ref: headingRef, tabIndex: -1 }, "Task detail"),
    createElement(FormulationBlock, { task: value, projects, headingRef }));
}

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    createElement(QueryClientProvider, { client },
      createElement(ShellToastContext.Provider, { value: () => () => undefined },
        createElement(MemoryRouter, null, node)))
  );
}

function expectCalmMarkup(container: HTMLElement): void {
  for (const element of [container, ...Array.from(container.querySelectorAll<HTMLElement>("*"))]) {
    expect(element.getAttribute("class") ?? "").not.toMatch(ROSE_OR_RED);
  }
  expect(container.textContent).not.toMatch(OVERDUE);
  expect(container.textContent).not.toMatch(STREAK);
}

const infoSpy = vi.spyOn(console, "info");
const warnSpy = vi.spyOn(console, "warn");
const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  infoSpy.mockImplementation(() => undefined);
  warnSpy.mockImplementation(() => undefined);
  vi.stubGlobal("fetch", fetchMock);
  act(() => {
    useAuthStore.setState({ user: { id: "user-1", email: "max@example.test", feature_flags: { weekly_review: true, crt_canvas: true } }, status: "authed" });
  });
});

afterEach(async () => {
  cleanup();
  await act(() => new Promise<void>((resolve) => setTimeout(resolve, 20)));
  onlineManager.setOnline(true);
  vi.unstubAllGlobals();
  fetchMock.mockReset();
  infoSpy.mockReset();
  warnSpy.mockReset();
  window.localStorage.clear();
  act(() => {
    useAuthStore.setState({ user: null, status: "loading" });
  });
});

describe("020-FR-004 020-FR-038 review copy stays calm", () => {
  it("020-FR-038 reads the review sources it guards", () => {
    const names = Object.keys(sources).map((path) => path.split("/").pop());
    for (const expected of ["DecisionDialog.tsx", "FormulationBlock.tsx", "AutoParkExplainer.tsx", "WhileYouWereAway.tsx", "ReviewSettingsSection.tsx", "formulation.ts", "review.ts", "ReviewShell.tsx", "InboxStep.tsx", "SummaryStep.tsx"]) {
      expect(names).toContain(expected);
    }
  });

  it.each(Object.entries(sources).map(([path, text]) => [path.split("/").pop() as string, text] as const))(
    "020-FR-004 %s has no overdue, streak or rose/red wording",
    (_name, text) => {
      expect(text).not.toMatch(OVERDUE);
      expect(text).not.toMatch(STREAK);
      expect(text).not.toMatch(ROSE_OR_RED);
    }
  );

  it("020-FR-004 rendered markers and facts use no error colour and no overdue or streak wording", () => {
    const states: TaskResponse[] = [
      task(),
      task({}, { park_due_at: iso(6 * 60 * 60 * 1000) }),
      task({}, { started_at: iso(-9 * DAY), ageing_at: iso(-1 * DAY), ask_at: iso(5 * DAY), park_due_at: iso(12 * DAY) }),
      task({ due_date: "2026-10-16" }, { paused_until: iso(4 * DAY) }),
      task({}, { extended_at: iso(-4 * DAY), extension_reason: SENTINEL.reason, ask_at: iso(3 * DAY), park_due_at: iso(10 * DAY) }),
      task({ state: "someday", formulation: null, parked: { at: iso(-1 * DAY), formulation_id: "form_a" } })
    ];
    for (const state of states) {
      const { container, unmount } = wrap(block(state));
      expectCalmMarkup(container);
      unmount();
    }
  });

  it("020-FR-004 the decision dialog, its third-stall offer and its error banners use no error colour either", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ message: "nope", detail: { reason: "decision_not_allowed" } }), {
      status: 400,
      headers: { "Content-Type": "application/json", "X-Correlation-ID": "corr_7f3a2c91" }
    }));
    wrap(createElement(DecisionDialog, { task: task(), projectName: null, onClose: () => undefined }));

    expect(screen.getByRole("region", { name: "Third stalled wording" })).toBeInTheDocument();
    await user.click(within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name: /^Release to Someday/ }));
    await screen.findByRole("alert");

    expectCalmMarkup(document.body);
  });
});

describe("020-FR-044 review telemetry carries ids, codes, counts and timings only", () => {
  const ALLOWED_DETAIL_KEYS = new Set(["method", "route", "path", "status", "correlationId", "error"]);
  const SAFE_VALUE = /^(?:GET|POST|PUT|PATCH|DELETE|\d+|[A-Za-z]+Error|[A-Za-z0-9_\-/{}.]+)$/;

  function loggedEvents(): Array<{ name: string; durationMs?: number; ok?: boolean; details?: Record<string, unknown> }> {
    return [...infoSpy.mock.calls, ...warnSpy.mock.calls]
      .filter(([tag]) => tag === "[telemetry]")
      .map(([, payload]) => payload as { name: string; details?: Record<string, unknown> });
  }

  it("020-FR-044 a decision with a typed title and reason, and a failed read, log no content", async () => {
    const user = userEvent.setup();
    const decided = {
      decision: { id: "decision_1", type: "extend", task_id: "task_9f3c2a1b4d5e", session_id: null, decided_at: iso(0), substantive: null, stall_reason: null, ai_use: "none", yielded_auto_park: false },
      task: { ...task(), revision: 8, formulation: { ...task().formulation, extended_at: iso(0), extension_reason: SENTINEL.reason } },
      created_task: null,
      receipt: null,
      session_counts: null
    };
    fetchMock
      .mockResolvedValueOnce(new Response(JSON.stringify(decided), { status: 200, headers: { "Content-Type": "application/json", "X-Correlation-ID": "corr_ok" } }))
      .mockRejectedValueOnce(new TypeError(`${SENTINEL.ai} failed to fetch`));
    const onClose = vi.fn();
    wrap(createElement(DecisionDialog, { task: task({}, { consecutive_stalled: 0 }), projectName: null, onClose }));

    await user.click(within(screen.getByRole("group", { name: "Decisions" })).getByRole("button", { name: /^Keep 7 more days/ }));
    await user.type(screen.getByRole("textbox", { name: "Reason, required" }), SENTINEL.reason);
    await user.click(screen.getByRole("button", { name: /^Keep until/ }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    await reviewApi.getState().catch(() => undefined);

    const events = loggedEvents();
    expect(events.length).toBeGreaterThanOrEqual(2);
    const serialized = JSON.stringify(events);
    for (const sentinel of Object.values(SENTINEL)) {
      expect(serialized).not.toContain(sentinel);
    }
    for (const event of events) {
      expect(event.name).toMatch(/^(?:review|api)\.request$/);
      expect(typeof event.durationMs).toBe("number");
      for (const [key, value] of Object.entries(event.details ?? {})) {
        expect(ALLOWED_DETAIL_KEYS.has(key)).toBe(true);
        expect(String(value)).toMatch(SAFE_VALUE);
      }
    }
  });
});

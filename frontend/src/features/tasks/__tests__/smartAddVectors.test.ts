import { describe, expect, it } from "vitest";

import { applySmartAddSuggestion, parseSmartAdd, smartAddChips, smartAddSuggestions } from "../smartAdd";
import type { SmartAddKind, SmartAddRef, SmartAddSuggestion } from "../smartAdd";
import type { ProjectResponse, TagResponse } from "../../../api/taskTypes";

// Spec 026 (tasks.md T002): the web presentation helpers against the shared,
// versioned vectors that the Rust parity checks also consume. The file lives in
// specs/026-rust-core-sync/contracts/web-presentation-vectors.json.

interface RuntimeFileSystem {
  readFileSync(path: string, encoding: "utf8"): string;
}

interface RuntimeProcess {
  cwd(): string;
  getBuiltinModule(name: "fs"): RuntimeFileSystem;
}

interface Fixture {
  projects: Array<{ id: string; name: string; state: "active" }>;
  tags: Array<{ id: string; name: string; state: "active" }>;
}

interface Draft {
  clean_title: string;
  tags: SmartAddRef[];
  project: SmartAddRef | null;
  has_completed_tokens: boolean;
  is_valid: boolean;
}

interface Source {
  file: string;
  test: string;
}

interface Vectors {
  schema: string;
  rule_version: string;
  fixtures: Record<string, Fixture>;
  parse: Array<{
    id: string;
    source: Source;
    fixture?: string;
    context?: { project_id?: string; tag_id?: string };
    input: string;
    expect: Draft;
    chips: Array<{ kind: SmartAddKind; label: string }>;
    divergence?: { fields: Record<string, unknown>; reason: string };
  }>;
  suggestions: Array<{ id: string; source: Source; fixture?: string; input: string; caret: number; expect: SmartAddSuggestion[] }>;
  apply_suggestion: Array<{
    id: string;
    source: Source;
    input: string;
    caret: number;
    suggestion: SmartAddSuggestion;
    expect: { text: string; caret: number } | null;
  }>;
  name_collision_probes: Array<{ id: string; stored_tag: string; typed_tag: string; web_collides: boolean; server_collides: boolean; agrees: boolean }>;
}

function loadVectors(): Vectors {
  const runtime = globalThis as typeof globalThis & { process: RuntimeProcess };
  const path = `${runtime.process.cwd()}/../specs/026-rust-core-sync/contracts/web-presentation-vectors.json`;
  return JSON.parse(runtime.process.getBuiltinModule("fs").readFileSync(path, "utf8")) as Vectors;
}

const vectors = loadVectors();

function optionsFor(name: string | undefined, context?: { project_id?: string; tag_id?: string }) {
  const fixture = vectors.fixtures[name ?? "default"];
  const projects: ProjectResponse[] = fixture.projects.map((item) => ({ ...item, color: null, revision: 1, open_task_count: 0 }));
  const tags: TagResponse[] = fixture.tags.map((item) => ({ ...item, revision: 1, open_task_count: 0 }));
  return { projects, tags, contextProjectId: context?.project_id, contextTagId: context?.tag_id };
}

describe("web presentation vectors (026-FR-002, 026-SC-001)", () => {
  it("026-FR-002 names the rule version and carries every section", () => {
    expect(vectors.schema).toBe("brainbuddy-web-presentation-vectors/v1");
    expect(vectors.rule_version).toBe("smart-add-web/1");
    for (const section of [vectors.parse, vectors.suggestions, vectors.apply_suggestion, vectors.name_collision_probes]) {
      expect(section.length).toBeGreaterThan(0);
    }
    const ids = [...vectors.parse, ...vectors.suggestions, ...vectors.apply_suggestion, ...vectors.name_collision_probes].map((item) => item.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it.each(vectors.parse.map((item) => [item.id, item] as const))("026-FR-002 %s parses and previews as the shared vector says", (_id, vector) => {
    const options = optionsFor(vector.fixture, vector.context);
    const draft = parseSmartAdd(vector.input, options);

    expect({
      clean_title: draft.cleanTitle,
      tags: draft.tags,
      project: draft.project,
      has_completed_tokens: draft.hasCompletedTokens,
      is_valid: draft.isValid
    }).toEqual(vector.expect);
    expect(smartAddChips(draft, options)).toEqual(vector.chips);
  });

  it("026-FR-002 every recorded divergence differs from the web outcome in exactly its listed fields", () => {
    const diverging = vectors.parse.filter((item) => item.divergence !== undefined);
    expect(diverging.length).toBeGreaterThan(0);
    for (const vector of diverging) {
      const fields = vector.divergence?.fields ?? {};
      for (const [name, shared] of Object.entries(fields)) {
        expect(vector.expect[name as keyof Draft], `${vector.id} ${name}`).not.toEqual(shared);
      }
    }
  });

  it.each(vectors.suggestions.map((item) => [item.id, item] as const))("026-FR-002 %s suggests as the shared vector says", (_id, vector) => {
    expect(smartAddSuggestions(vector.input, vector.caret, optionsFor(vector.fixture))).toEqual(vector.expect);
  });

  it.each(vectors.apply_suggestion.map((item) => [item.id, item] as const))("026-FR-002 %s applies a suggestion as the shared vector says", (_id, vector) => {
    expect(applySmartAddSuggestion(vector.input, vector.caret, vector.suggestion)).toEqual(vector.expect);
  });

  it.each(vectors.name_collision_probes.map((item) => [item.id, item] as const))("026-FR-002 %s resolves a typed tag onto a stored one as recorded", (_id, probe) => {
    const draft = parseSmartAdd(`Plan #"${probe.typed_tag}"`, {
      projects: [],
      tags: [{ id: "tag-stored", name: probe.stored_tag, state: "active", revision: 1, open_task_count: 0 }]
    });

    expect(draft.tags.length === 1 && "id" in draft.tags[0]).toBe(probe.web_collides);
    expect(probe.agrees).toBe(probe.web_collides === probe.server_collides);
  });
});

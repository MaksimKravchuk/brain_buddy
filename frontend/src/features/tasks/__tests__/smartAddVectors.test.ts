import { describe, expect, it } from "vitest";

import { applySmartAddSuggestion, parseSmartAdd, smartAddChips, smartAddSuggestions } from "../smartAdd";
import type { SmartAddKind, SmartAddRef, SmartAddSuggestion } from "../smartAdd";
import type { ProjectResponse, TagResponse } from "../../../api/taskTypes";

// Spec 026 (tasks.md T002): the web presentation helpers against the shared,
// versioned vectors that the Rust parity checks also consume. The file lives in
// specs/026-rust-core-sync/contracts/web-presentation-vectors.json. The vectors
// keep the smart-add-web/1 outcomes as PR-02 measured them; the decision made for
// each disagreement (PR-53) is recorded in web-presentation-resolutions.json and
// this suite holds the helpers to it.

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

interface Resolution {
  id: string;
  decision: "resolved" | "accepted";
  reason: string;
}

interface Resolutions {
  schema: string;
  vectors: { path: string; schema: string; rule_version: string };
  adapter_revision: string;
  parse: Resolution[];
  name_collision_probes: Resolution[];
  server_whitespace: string[];
}

function loadContract<T>(file: string): T {
  const runtime = globalThis as typeof globalThis & { process: RuntimeProcess };
  const path = `${runtime.process.cwd()}/../specs/026-rust-core-sync/contracts/${file}`;
  return JSON.parse(runtime.process.getBuiltinModule("fs").readFileSync(path, "utf8")) as T;
}

const vectors = loadContract<Vectors>("web-presentation-vectors.json");
const resolutions = loadContract<Resolutions>("web-presentation-resolutions.json");

const decisionFor = (list: Resolution[], id: string): Resolution["decision"] | undefined => list.find((item) => item.id === id)?.decision;

// What the adapter must return now: the frozen web outcome, except where PR-53
// resolved the disagreement in favour of the shared rule.
function expectedDraft(vector: Vectors["parse"][number]): Draft {
  return decisionFor(resolutions.parse, vector.id) === "resolved"
    ? { ...vector.expect, ...(vector.divergence?.fields as Partial<Draft>) }
    : vector.expect;
}

function webCollides(storedTag: string, typedTag: string): boolean {
  const draft = parseSmartAdd(`Plan #"${typedTag}"`, {
    projects: [],
    tags: [{ id: "tag-stored", name: storedTag, state: "active", revision: 1, open_task_count: 0 }]
  });
  return draft.tags.length === 1 && "id" in draft.tags[0];
}

function parseRange(range: string): [number, number] {
  const [from, to] = range.split("-");
  return [Number.parseInt(from, 16), Number.parseInt(to ?? from, 16)];
}

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
    }).toEqual(expectedDraft(vector));
    expect(smartAddChips(draft, options)).toEqual(vector.chips);
  });

  it("026-FR-002 026-SC-001 the resolutions ledger names the rule version and decides every recorded disagreement exactly once", () => {
    expect(resolutions.schema).toBe("brainbuddy-web-presentation-resolutions/v1");
    expect(resolutions.vectors.schema).toBe(vectors.schema);
    expect(resolutions.vectors.rule_version).toBe(vectors.rule_version);
    expect(resolutions.adapter_revision).toBe(`${vectors.rule_version}+r1`);

    const diverging = vectors.parse.filter((item) => item.divergence !== undefined).map((item) => item.id);
    const disagreeing = vectors.name_collision_probes.filter((item) => !item.agrees).map((item) => item.id);
    expect(diverging.length).toBeGreaterThan(0);
    expect(disagreeing.length).toBeGreaterThan(0);
    expect(resolutions.parse.map((item) => item.id).sort()).toEqual([...diverging].sort());
    expect(resolutions.name_collision_probes.map((item) => item.id).sort()).toEqual([...disagreeing].sort());
    for (const item of [...resolutions.parse, ...resolutions.name_collision_probes]) {
      expect(item.reason.length, item.id).toBeGreaterThan(0);
    }
  });

  it("026-FR-002 a resolved divergence now yields the shared value and an accepted one still differs only in its listed fields", () => {
    let accepted = 0;
    let resolved = 0;
    for (const vector of vectors.parse.filter((item) => item.divergence !== undefined)) {
      const draft = parseSmartAdd(vector.input, optionsFor(vector.fixture, vector.context));
      const actual = {
        clean_title: draft.cleanTitle,
        tags: draft.tags,
        project: draft.project,
        has_completed_tokens: draft.hasCompletedTokens,
        is_valid: draft.isValid
      };
      for (const [name, shared] of Object.entries(vector.divergence?.fields ?? {})) {
        const value = actual[name as keyof Draft];
        if (decisionFor(resolutions.parse, vector.id) === "resolved") {
          expect(value, `${vector.id} ${name}`).toEqual(shared);
          resolved += 1;
        } else {
          expect(value, `${vector.id} ${name}`).not.toEqual(shared);
          accepted += 1;
        }
      }
    }
    expect(resolved).toBe(3);
    expect(accepted).toBe(1);
  });

  it.each(vectors.suggestions.map((item) => [item.id, item] as const))("026-FR-002 %s suggests as the shared vector says", (_id, vector) => {
    expect(smartAddSuggestions(vector.input, vector.caret, optionsFor(vector.fixture))).toEqual(vector.expect);
  });

  it.each(vectors.apply_suggestion.map((item) => [item.id, item] as const))("026-FR-002 %s applies a suggestion as the shared vector says", (_id, vector) => {
    expect(applySmartAddSuggestion(vector.input, vector.caret, vector.suggestion)).toEqual(vector.expect);
  });

  it.each(vectors.name_collision_probes.map((item) => [item.id, item] as const))("026-FR-002 %s resolves a typed tag onto a stored one as recorded", (_id, probe) => {
    // A resolved probe follows the server verdict now; an accepted one keeps the
    // frozen web verdict because the server resolves the submitted name anyway.
    const resolvedToServer = decisionFor(resolutions.name_collision_probes, probe.id) === "resolved";

    expect(webCollides(probe.stored_tag, probe.typed_tag)).toBe(resolvedToServer ? probe.server_collides : probe.web_collides);
    expect(probe.agrees).toBe(probe.web_collides === probe.server_collides);
    if (probe.agrees) {
      expect(webCollides(probe.stored_tag, probe.typed_tag)).toBe(probe.server_collides);
    }
  });

  it("026-FR-002 026-SC-001 the web strips and collapses exactly the whitespace the server does", () => {
    const serverSpace = new Set<number>();
    for (const range of resolutions.server_whitespace) {
      const [from, to] = parseRange(range);
      for (let code = from; code <= to; code += 1) serverSpace.add(code);
    }
    const disagreements: string[] = [];
    for (let code = 0; code <= 0xffff; code += 1) {
      const char = String.fromCharCode(code);
      // Surrogates are not scalars; a line break ends a quoted token; a sigil (or its
      // NFKC compatibility form) is stripped as the tag prefix, not as whitespace.
      if ((code >= 0xd800 && code <= 0xdfff) || code === 0x0a || code === 0x0d || /[#@]/u.test(char.normalize("NFKC"))) continue;
      const hit = webCollides("x", `${char}x`);
      if (hit !== serverSpace.has(code)) disagreements.push(code.toString(16).padStart(4, "0"));
    }
    expect(disagreements).toEqual([]);
  });
});

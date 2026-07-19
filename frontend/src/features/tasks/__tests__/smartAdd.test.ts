import { describe, expect, it } from "vitest";

import {
  applySmartAddSuggestion,
  parseSmartAdd,
  smartAddChips,
  smartAddSuggestions,
  stripLegacyProjectSigil,
  stripLegacySigil
} from "../smartAdd";
import type { ProjectResponse, TagResponse } from "../../../api/taskTypes";

const projects: ProjectResponse[] = [
  { id: "project-launch", name: "Launch v2", color: null, state: "active", revision: 1, open_task_count: 1 },
  { id: "project-vendor", name: "Vendor launch", color: null, state: "active", revision: 1, open_task_count: 0 },
  { id: "project-admin", name: "Admin", color: null, state: "active", revision: 1, open_task_count: 0 }
];

const tags: TagResponse[] = [
  { id: "tag-work", name: "work", state: "active", revision: 1, open_task_count: 2 },
  { id: "tag-deep", name: "deep work", state: "active", revision: 1, open_task_count: 1 },
  { id: "tag-calls", name: "calls", state: "active", revision: 1, open_task_count: 0 }
];

describe("smartAdd", () => {
  it.each([
    ["Draft update #work @\"Launch v2\"", "Draft update", [{ id: "tag-work" }], { id: "project-launch" }],
    ["Draft #work #WORK", "Draft", [{ id: "tag-work" }], null],
    ["Draft @old @new", "Draft", [], { name: "new" }],
    ["Draft (#work) today", "Draft today", [{ id: "tag-work" }], null],
    ["Draft #work, today", "Draft, today", [{ id: "tag-work" }], null],
    ["Discuss C# and max@example.com", "Discuss C# and max@example.com", [], null],
    ["Use \\#literal marker", "Use #literal marker", [], null],
    ["Plan #", "Plan #", [], null],
    ["Plan @\"Launch v2", "Plan @\"Launch v2", [], null]
  ])("parses %s into a clean task create draft", (raw, cleanTitle, expectedTags, expectedProject) => {
    const parsed = parseSmartAdd(raw, { projects, tags });

    expect(parsed.cleanTitle).toBe(cleanTitle);
    expect(parsed.tags).toEqual(expectedTags);
    expect(parsed.project).toEqual(expectedProject);
    expect(parsed.hasCompletedTokens).toBe(expectedTags.length > 0 || expectedProject !== null);
  });

  it("merges contextual defaults, deduplicates tags, and lets the final project win", () => {
    const parsed = parseSmartAdd("Plan #calls @Admin @\"Vendor launch\" #work", {
      projects,
      tags,
      contextProjectId: "project-launch",
      contextTagId: "tag-work"
    });

    expect(parsed.cleanTitle).toBe("Plan");
    expect(parsed.tags).toEqual([{ id: "tag-work" }, { id: "tag-calls" }]);
    expect(parsed.project).toEqual({ id: "project-vendor" });
  });

  it("rejects completed classifications when the clean title is empty", () => {
    const parsed = parseSmartAdd("#work @launch", { projects, tags });

    expect(parsed.cleanTitle).toBe("");
    expect(parsed.hasCompletedTokens).toBe(true);
    expect(parsed.isValid).toBe(false);
  });

  it("builds preview chip models with project and tag sigils", () => {
    const parsed = parseSmartAdd("Call partner #calls @\"Vendor launch\" #new", { projects, tags });

    expect(smartAddChips(parsed, { projects, tags })).toEqual([
      { kind: "project", label: "Vendor launch" },
      { kind: "tag", label: "calls" },
      { kind: "tag", label: "new" }
    ]);
  });

  it("ranks local suggestions and appends a non-durable create option", () => {
    const suggestions = smartAddSuggestions("Plan @la", 8, { projects, tags });

    expect(suggestions.map((item) => item.label)).toEqual(["Launch v2", "Vendor launch", "Create @la"]);
    expect(suggestions[0]).toMatchObject({ kind: "project", ref: { id: "project-launch" }, create: false });
    expect(suggestions[2]).toMatchObject({ kind: "project", ref: { name: "la" }, create: true });
  });

  it("offers deterministic local choices for bare sigils without creating an option", () => {
    const suggestions = smartAddSuggestions("Plan #", 6, { projects, tags });

    expect(suggestions.map((item) => item.label)).toEqual(["calls", "deep work", "work"]);
    expect(suggestions.every((item) => !item.create)).toBe(true);
  });

  it("does not activate invalid or completed classification positions", () => {
    expect(smartAddSuggestions("Plan word,#work", "Plan word,#work".length, { projects, tags })).toEqual([]);
    expect(smartAddSuggestions("Plan @launch, next", "Plan @launch, next".length, { projects, tags })).toEqual([]);
  });

  it("decodes quoted escapes and leaves malformed forms as literal title text", () => {
    expect(parseSmartAdd('Plan #"deep \\"work\\""', { projects, tags })).toMatchObject({
      cleanTitle: "Plan",
      tags: [{ name: 'deep "work"' }]
    });
    expect(parseSmartAdd("Plan #-work @\"broken\nproject\"", { projects, tags })).toMatchObject({
      cleanTitle: "Plan #-work @\"broken project\"",
      hasCompletedTokens: false
    });
  });

  it("parses punctuation names and wrapper cleanup while preserving unsupported quote escapes", () => {
    expect(parseSmartAdd("Plan [#a-b] {#a.b}", { projects, tags })).toMatchObject({
      cleanTitle: "Plan",
      tags: [{ name: "a-b" }, { name: "a.b" }]
    });
    expect(parseSmartAdd('Plan #"literal \\q"', { projects, tags })).toMatchObject({
      tags: [{ name: "literal \\q" }]
    });
  });

  it("validates smart add draft bounds and skips preview labels for unloaded ids", () => {
    const overlongTitle = parseSmartAdd(`${"x".repeat(501)} #work`, { projects, tags });
    const overlongTag = parseSmartAdd(`Plan #${"x".repeat(501)}`, { projects, tags });

    expect(overlongTitle.isValid).toBe(false);
    expect(overlongTag.isValid).toBe(false);
    expect(smartAddChips({
      cleanTitle: "Plan",
      tags: [{ id: "missing-tag" }],
      project: { id: "missing-project" },
      hasCompletedTokens: true,
      isValid: true
    }, { projects, tags })).toEqual([]);
  });

  it("ranks exact, word-prefix, and substring matches without a duplicate create choice", () => {
    expect(smartAddSuggestions("Plan #work", 10, { projects, tags }).map((item) => item.label)).toEqual(["work", "deep work"]);
    expect(smartAddSuggestions("Plan @ven", 9, { projects, tags }).map((item) => item.label)).toEqual(["Vendor launch", "Create @ven"]);
    expect(smartAddSuggestions("Plan @dor", 9, { projects, tags }).map((item) => item.label)).toEqual(["Vendor launch", "Create @dor"]);
  });

  it("keeps incomplete quoted queries active but stops at a completed token boundary", () => {
    expect(smartAddSuggestions('Plan @"Ven', 10, { projects, tags }).map((item) => item.label)).toEqual(["Vendor launch", "Create @Ven"]);
    expect(smartAddSuggestions("Plan @launch,", 13, { projects, tags })).toEqual([]);
    expect(smartAddSuggestions("Plan #nomatch", 13, { projects, tags }).map((item) => item.label)).toEqual(["Create #nomatch"]);
  });

  it("serializes selected suggestions back into the active token span", () => {
    const replacement = applySmartAddSuggestion("Plan @la tomorrow", 8, {
      kind: "project",
      label: "Launch v2",
      ref: { id: "project-launch" },
      create: false
    });

    expect(replacement?.text).toBe("Plan @\"Launch v2\" tomorrow");
    expect(replacement?.caret).toBe("Plan @\"Launch v2\" ".length);
  });

  it("replaces the whole completed token when a suggestion is selected mid-token", () => {
    const replacement = applySmartAddSuggestion("Plan @launc tomorrow", 8, {
      kind: "project",
      label: "Launch v2",
      ref: { id: "project-launch" },
      create: false
    });

    expect(replacement?.text).toBe("Plan @\"Launch v2\" tomorrow");
  });

  it("preserves delimiters and rejects a suggestion of the wrong classification kind", () => {
    const replacement = applySmartAddSuggestion("Plan #ca, tomorrow", 8, {
      kind: "tag",
      label: "calls",
      ref: { id: "tag-calls" },
      create: false
    });

    expect(replacement).toEqual({ text: "Plan #calls, tomorrow", caret: "Plan #calls".length });
    expect(applySmartAddSuggestion("Plan #ca", 8, {
      kind: "project",
      label: "Launch v2",
      ref: { id: "project-launch" },
      create: false
    })).toBeNull();
  });

  it("serializes legacy labels, quoted punctuation, and terminal whitespace correctly", () => {
    const replacement = applySmartAddSuggestion("Plan #de", 8, {
      kind: "tag",
      label: "@deep work",
      ref: { id: "tag-deep" },
      create: false
    });

    expect(replacement).toEqual({ text: 'Plan #"deep work" ', caret: 'Plan #"deep work" '.length });
    expect(stripLegacySigil("#work")).toBe("work");
    expect(stripLegacySigil("@legacy")).toBe("legacy");
    expect(stripLegacyProjectSigil("@launch")).toBe("launch");
    expect(stripLegacyProjectSigil("#not-project")).toBe("#not-project");
  });

  it("retains an existing separator after accepting a suggestion and ignores plain text", () => {
    expect(applySmartAddSuggestion("Plan #ca tomorrow", 8, {
      kind: "tag",
      label: "calls",
      ref: { id: "tag-calls" },
      create: false
    })).toEqual({ text: "Plan #calls tomorrow", caret: "Plan #calls ".length });
    expect(applySmartAddSuggestion("Plan calls", 10, {
      kind: "tag",
      label: "calls",
      ref: { id: "tag-calls" },
      create: false
    })).toBeNull();
  });
});

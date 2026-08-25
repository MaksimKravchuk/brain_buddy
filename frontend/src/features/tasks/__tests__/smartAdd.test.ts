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

  it("uses stable ids to order duplicate local suggestion names", () => {
    const duplicateTags = [
      { id: "tag-z", name: "duplicate", state: "active" as const, revision: 1, open_task_count: 0 },
      { id: "tag-a", name: "duplicate", state: "active" as const, revision: 1, open_task_count: 0 }
    ];

    const suggestions = smartAddSuggestions("Plan #dup", 9, { projects: [], tags: duplicateTags });

    expect(suggestions.slice(0, 2).map((item) => item.ref)).toEqual([{ id: "tag-a" }, { id: "tag-z" }]);
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

  it("matches a stored name whose own spacing and case are untidy", () => {
    const untidy = [
      { id: "tag-untidy", name: "  Deep   Work  ", state: "active" as const, revision: 1, open_task_count: 0 }
    ];

    expect(parseSmartAdd('Plan #"deep work"', { projects, tags: untidy })).toMatchObject({
      tags: [{ id: "tag-untidy" }]
    });
  });

  it("strips a legacy sigil only from the front of a name", () => {
    expect(stripLegacySigil("c#sharp")).toBe("c#sharp");
    expect(stripLegacyProjectSigil("mail@example.com")).toBe("mail@example.com");
    expect(parseSmartAdd('Plan #"c#sharp"', { projects, tags })).toMatchObject({
      tags: [{ name: "c#sharp" }]
    });
  });

  it("leaves a lone backslash alone when no sigil follows it", () => {
    expect(parseSmartAdd("Copy from C:\\ drive", { projects, tags })).toMatchObject({
      cleanTitle: "Copy from C:\\ drive",
      hasCompletedTokens: false
    });
  });

  it("ignores a quoted token with an empty name instead of classifying it", () => {
    expect(parseSmartAdd('Plan #"" today', { projects, tags })).toMatchObject({
      cleanTitle: 'Plan #"" today',
      tags: [],
      hasCompletedTokens: false
    });
  });

  it("treats a backslash-escaped sigil as literal text for both kinds", () => {
    expect(parseSmartAdd("Ping \\@nobody today", { projects, tags })).toMatchObject({
      cleanTitle: "Ping @nobody today",
      project: null,
      hasCompletedTokens: false
    });
    expect(parseSmartAdd("Mail \\#one and \\@two", { projects, tags })).toMatchObject({
      cleanTitle: "Mail #one and @two",
      tags: [],
      project: null
    });
  });

  it("only honours an escape that stands at a token boundary", () => {
    // Mid-word the backslash is ordinary text, and the sigil behind it is not a
    // token either, so the whole run survives into the title verbatim.
    expect(parseSmartAdd("id\\#42 wins", { projects, tags })).toMatchObject({
      cleanTitle: "id\\#42 wins",
      tags: [],
      hasCompletedTokens: false
    });
  });

  it("matches an existing name regardless of case and inner spacing", () => {
    expect(parseSmartAdd('Plan #"DEEP   WORK"', { projects, tags })).toMatchObject({
      cleanTitle: "Plan",
      tags: [{ id: "tag-deep" }]
    });
    expect(parseSmartAdd('Plan @"  vendor   LAUNCH  "', { projects, tags })).toMatchObject({
      project: { id: "project-vendor" }
    });
  });

  it("normalises the display name of a tag or project it is about to create", () => {
    expect(parseSmartAdd('Plan #"  New   Tag  "', { projects, tags })).toMatchObject({
      tags: [{ name: "New Tag" }]
    });
    expect(parseSmartAdd('Plan @"  Fresh   Project  "', { projects, tags })).toMatchObject({
      project: { name: "Fresh Project" }
    });
  });

  it("decodes an escaped backslash inside a quoted name", () => {
    expect(parseSmartAdd('Plan #"back\\\\slash"', { projects, tags })).toMatchObject({
      cleanTitle: "Plan",
      tags: [{ name: "back\\slash" }]
    });
  });

  it("abandons a quoted name broken by a carriage return, as it does for a newline", () => {
    expect(parseSmartAdd('Plan #"broken\rname"', { projects, tags })).toMatchObject({
      // The token is abandoned, and the stray control character collapses into
      // ordinary spacing the way any other whitespace run does.
      cleanTitle: 'Plan #"broken name"',
      hasCompletedTokens: false
    });
  });

  it("stops an unquoted name at a trailing separator instead of swallowing it", () => {
    expect(parseSmartAdd("Ping #a- now", { projects, tags })).toMatchObject({
      cleanTitle: "Ping - now",
      tags: [{ name: "a" }]
    });
    expect(parseSmartAdd("Ping #a. now", { projects, tags })).toMatchObject({
      cleanTitle: "Ping. now",
      tags: [{ name: "a" }]
    });
  });

  it("removes a bracket pair only when the token is the whole of it", () => {
    expect(parseSmartAdd("Draft ( #work ) today", { projects, tags })).toMatchObject({
      cleanTitle: "Draft today",
      tags: [{ id: "tag-work" }]
    });
    expect(parseSmartAdd("( #work ) alone", { projects, tags })).toMatchObject({
      cleanTitle: "alone"
    });
    expect(parseSmartAdd("Draft (see #work) today", { projects, tags })).toMatchObject({
      cleanTitle: "Draft (see) today",
      tags: [{ id: "tag-work" }]
    });
    expect(parseSmartAdd("Draft (#work extra) today", { projects, tags })).toMatchObject({
      cleanTitle: "Draft ( extra) today",
      tags: [{ id: "tag-work" }]
    });
  });

  it("deduplicates a tag written with and without its legacy sigil", () => {
    expect(parseSmartAdd('Plan #work #"#work"', { projects, tags })).toMatchObject({
      tags: [{ id: "tag-work" }]
    });
    expect(parseSmartAdd('Plan #"brand new" #"BRAND   NEW"', { projects, tags })).toMatchObject({
      tags: [{ name: "brand new" }]
    });
  });

  it("accepts a draft at the length limit and rejects the one past it", () => {
    const atLimit = parseSmartAdd(`${"x".repeat(500)} #work`, { projects, tags });
    const overLimit = parseSmartAdd(`${"x".repeat(501)} #work`, { projects, tags });
    const tagAtLimit = parseSmartAdd(`Plan #${"x".repeat(500)}`, { projects, tags });
    const projectAtLimit = parseSmartAdd(`Plan @${"x".repeat(500)}`, { projects, tags });
    const projectOverLimit = parseSmartAdd(`Plan @${"x".repeat(501)}`, { projects, tags });

    expect(atLimit.isValid).toBe(true);
    expect(overLimit.isValid).toBe(false);
    expect(tagAtLimit.isValid).toBe(true);
    expect(projectAtLimit.isValid).toBe(true);
    expect(projectOverLimit.isValid).toBe(false);
  });

  it("ranks an exact name above a prefix, a word prefix, and a bare substring", () => {
    const ranked = smartAddSuggestions("Plan #work", 10, {
      projects,
      tags: [
        ...tags,
        { id: "tag-workshop", name: "workshop", state: "active", revision: 1, open_task_count: 0 },
        { id: "tag-homework", name: "homework", state: "active", revision: 1, open_task_count: 0 }
      ]
    });

    expect(ranked.map((item) => item.label)).toEqual(["work", "workshop", "deep work", "homework"]);
  });

  it("treats a hyphen as a word break when matching a query to a name", () => {
    const hyphenated = [
      { id: "tag-deep-focus", name: "deep-focus", state: "active" as const, revision: 1, open_task_count: 0 }
    ];

    expect(smartAddSuggestions("Plan #focus", 11, { projects, tags: hyphenated }).map((item) => item.label)).toEqual([
      "deep-focus",
      "Create #focus"
    ]);
  });

  it("ranks a whole-name prefix above a word prefix, and both above a bare substring", () => {
    // "coworking" sorts before "deep work" alphabetically, so the two orderings
    // this could collapse into are distinguishable: only real word-prefix
    // scoring keeps "deep work" second.
    const ranked = smartAddSuggestions("Plan #work", 10, {
      projects,
      tags: [
        { id: "tag-workshop", name: "workshop", state: "active" as const, revision: 1, open_task_count: 0 },
        { id: "tag-deep", name: "deep work", state: "active" as const, revision: 1, open_task_count: 0 },
        { id: "tag-coworking", name: "coworking", state: "active" as const, revision: 1, open_task_count: 0 },
        { id: "tag-rework", name: "rework", state: "active" as const, revision: 1, open_task_count: 0 },
        { id: "tag-zebra", name: "zebra-rework", state: "active" as const, revision: 1, open_task_count: 0 }
      ]
    });

    expect(ranked.map((item) => item.label)).toEqual([
      "workshop",
      "deep work",
      "coworking",
      "rework",
      "zebra-rework",
      "Create #work"
    ]);
  });

  it("decodes escapes inside an in-progress quoted query", () => {
    const quoted = [
      { id: "tag-quote", name: 'a"b', state: "active" as const, revision: 1, open_task_count: 0 }
    ];
    const input = 'Plan #"a\\"b';

    expect(smartAddSuggestions(input, input.length, { projects, tags: quoted }).map((item) => item.label)).toEqual([
      'a"b'
    ]);
  });

  it("stops looking for an active token at the nearest whitespace", () => {
    expect(smartAddSuggestions("Plan #work more", "Plan #work more".length, { projects, tags })).toEqual([]);
  });

  it("quotes and escapes a serialized name that is not a bare identifier", () => {
    expect(
      applySmartAddSuggestion("Plan #q", 7, {
        kind: "tag",
        label: 'say "hi"',
        ref: { name: 'say "hi"' },
        create: true
      })?.text
    ).toBe('Plan #"say \\"hi\\"" ');

    expect(
      applySmartAddSuggestion("Plan #q", 7, {
        kind: "tag",
        label: "back\\slash",
        ref: { name: "back\\slash" },
        create: true
      })?.text
    ).toBe('Plan #"back\\\\slash" ');
  });

  it("sheds either legacy sigil from a tag label before serializing it", () => {
    expect(
      applySmartAddSuggestion("Plan #w", 7, {
        kind: "tag",
        label: "#work",
        ref: { id: "tag-work" },
        create: false
      })?.text
    ).toBe("Plan #work ");
  });

  it("keeps a digit after a separator inside a bare name", () => {
    expect(
      applySmartAddSuggestion("Plan #a", 7, {
        kind: "tag",
        label: "a-1",
        ref: { name: "a-1" },
        create: true
      })?.text
    ).toBe("Plan #a-1 ");
  });

  it("separates the token from whatever text runs straight into it", () => {
    expect(
      applySmartAddSuggestion("Plan #ca/path", 8, {
        kind: "tag",
        label: "calls",
        ref: { id: "tag-calls" },
        create: false
      })
    ).toEqual({ text: "Plan #calls /path", caret: "Plan #calls ".length });
  });

  it("keeps a project label's own leading sigil out of the serialized token", () => {
    expect(
      applySmartAddSuggestion("Plan @l", 7, {
        kind: "project",
        label: "@Launch",
        ref: { id: "project-launch" },
        create: false
      })?.text
    ).toBe("Plan @Launch ");

    // A tag label may carry either legacy sigil; a project label only sheds @.
    expect(
      applySmartAddSuggestion("Plan @l", 7, {
        kind: "project",
        label: "#Hashed",
        ref: { id: "project-launch" },
        create: false
      })?.text
    ).toBe('Plan @"#Hashed" ');
  });

  it("adds no separator when the token already runs into one", () => {
    expect(
      applySmartAddSuggestion("Plan #ca]", 8, {
        kind: "tag",
        label: "calls",
        ref: { id: "tag-calls" },
        create: false
      })
    ).toEqual({ text: "Plan #calls]", caret: "Plan #calls".length });
  });

  it("accepts every name-char class in a bare unquoted name", () => {
    // contracts/smart-add.md: name-char = Unicode Letter | Number | Mark | "_",
    // with "-" and "." allowed between two name-chars.
    expect(parseSmartAdd("Ping #q3_a-b.c now", { projects, tags })).toMatchObject({
      cleanTitle: "Ping now",
      tags: [{ name: "q3_a-b.c" }]
    });
    // A combining mark continues the name, and NFKC then composes the display
    // spelling: "cafe" + U+0301 is stored as "café".
    expect(parseSmartAdd("Ping #café now", { projects, tags })).toMatchObject({
      cleanTitle: "Ping now",
      tags: [{ name: "café" }]
    });
  });

  it("folds case downwards, so a name only equal when upper-cased stays distinct", () => {
    // "ß".toLocaleUpperCase() is "SS". Canonicalising upwards would silently
    // resolve #ß onto an existing "ss" tag; lower-casing keeps them apart.
    const sharp: TagResponse[] = [
      { id: "tag-ss", name: "ss", state: "active", revision: 1, open_task_count: 0 }
    ];

    expect(parseSmartAdd("Plan #ß", { projects, tags: sharp })).toMatchObject({
      tags: [{ name: "ß" }]
    });
  });

  it("escapes only a sigil, leaving a boundary backslash before anything else", () => {
    expect(parseSmartAdd("Copy \\ drive", { projects, tags })).toMatchObject({
      cleanTitle: "Copy \\ drive",
      hasCompletedTokens: false
    });
  });

  it("keeps the contextual project when no inline project token supersedes it", () => {
    expect(parseSmartAdd("Plan #work", { projects, tags, contextProjectId: "project-launch" })).toMatchObject({
      cleanTitle: "Plan",
      tags: [{ id: "tag-work" }],
      project: { id: "project-launch" }
    });
  });

  it("activates a token that opens the input, where start-of-input is the boundary", () => {
    expect(smartAddSuggestions("#wo", 3, { projects, tags }).map((item) => item.label)).toEqual([
      "work",
      "deep work",
      "Create #wo"
    ]);
  });

  it("stops at a completed quoted token even when punctuation runs into it", () => {
    // The quoted body closes before the caret, so the token is committed rather
    // than active and the popup stays shut.
    const input = 'Plan #"work",';

    expect(smartAddSuggestions(input, input.length, { projects, tags })).toEqual([]);
  });

  it("closes the popup once whitespace separates the caret from an unclosed quote", () => {
    // The active-token scan stops at the nearest whitespace, so a quoted query
    // that has grown past a space is no longer caret-local. The contract permits
    // this: unclosed quoted bodies *may* be active, they are not required to be.
    const input = 'Plan #"deep wo';

    expect(smartAddSuggestions(input, input.length, { projects, tags })).toEqual([]);
  });

  it("caps the ranked entities at eight before appending the create option", () => {
    // contracts/smart-add.md: "Show at most eight entities", and separately
    // "append one" Create option when the query has no exact match -- so the
    // cap bounds the entities, and nine rows is the intended shape, not eight.
    // 003-FR-004 words the same rule as "capped at eight visible results".
    const many: TagResponse[] = "abcdefghijk".split("").map((suffix) => ({
      id: `tag-${suffix}`,
      name: `work${suffix}`,
      state: "active" as const,
      revision: 1,
      open_task_count: 0
    }));

    const suggestions = smartAddSuggestions("Plan #work", 10, { projects, tags: many });

    expect(suggestions.filter((item) => !item.create)).toHaveLength(8);
    expect(suggestions.map((item) => item.label)).toEqual([
      "worka",
      "workb",
      "workc",
      "workd",
      "worke",
      "workf",
      "workg",
      "workh",
      "Create #work"
    ]);
  });

  it("keeps a name bare when a combining mark follows an internal separator", () => {
    // "-" is internal punctuation when a name-char follows, and a Mark is a
    // name-char, so this label serializes unquoted.
    expect(
      applySmartAddSuggestion("Plan #a", 7, {
        kind: "tag",
        label: "a-́b",
        ref: { name: "a-́b" },
        create: true
      })?.text
    ).toBe("Plan #a-́b ");
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

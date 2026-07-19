import type { ProjectResponse, TagResponse } from "../../api/taskTypes";

export type SmartAddKind = "tag" | "project";
export type SmartAddRef = { id: string } | { name: string };

export interface SmartAddParseOptions {
  projects: ProjectResponse[];
  tags: TagResponse[];
  contextProjectId?: string;
  contextTagId?: string;
}

export interface SmartAddDraft {
  cleanTitle: string;
  tags: SmartAddRef[];
  project: SmartAddRef | null;
  hasCompletedTokens: boolean;
  isValid: boolean;
}

export interface SmartAddSuggestion {
  kind: SmartAddKind;
  label: string;
  ref: SmartAddRef;
  create: boolean;
}

export interface SmartAddChip {
  kind: SmartAddKind;
  label: string;
}

interface TokenSpan {
  kind: SmartAddKind;
  start: number;
  end: number;
  name: string;
}

interface EscapeSpan {
  start: number;
  end: number;
}

interface ActiveToken {
  kind: SmartAddKind;
  start: number;
  end: number;
  query: string;
}

const nameCharPattern = /^[\p{L}\p{N}\p{M}_]$/u;
const leftBoundaryPattern = /^[\s([{]$/u;
const whitespacePattern = /\s/u;
const wrapperPairs = new Map([
  ["(", ")"],
  ["[", "]"],
  ["{", "}"]
]);

const normalize = (value: string): string => value.normalize("NFKC").trim().replace(/\s+/gu, " ").toLocaleLowerCase();
const displayName = (value: string): string => value.normalize("NFKC").trim().replace(/\s+/gu, " ");
export const stripLegacySigil = (value: string): string => value.replace(/^[#@]/u, "");
export const stripLegacyProjectSigil = (value: string): string => value.replace(/^@/u, "");

function isNameChar(char: string | undefined): boolean {
  return Boolean(char && nameCharPattern.test(char));
}

function hasLeftBoundary(input: string, index: number): boolean {
  return index === 0 || leftBoundaryPattern.test(input[index - 1] ?? "");
}

function parseQuoted(input: string, bodyStart: number): { name: string; end: number } | null {
  let name = "";
  for (let index = bodyStart + 1; index < input.length; index += 1) {
    const char = input[index];
    if (char === "\n" || char === "\r") {
      return null;
    }
    if (char === "\\") {
      const next = input[index + 1];
      if (next === '"' || next === "\\") {
        name += next;
        index += 1;
        continue;
      }
      name += char;
      continue;
    }
    if (char === '"') {
      return { name, end: index + 1 };
    }
    name += char;
  }
  return null;
}

function parseUnquoted(input: string, bodyStart: number): { name: string; end: number } | null {
  if (!isNameChar(input[bodyStart])) {
    return null;
  }
  let end = bodyStart + 1;
  while (end < input.length) {
    const char = input[end];
    const next = input[end + 1];
    if (isNameChar(char)) {
      end += 1;
      continue;
    }
    if ((char === "-" || char === ".") && isNameChar(next)) {
      end += 1;
      continue;
    }
    break;
  }
  return { name: input.slice(bodyStart, end), end };
}

function scanCompleted(input: string): { tokens: TokenSpan[]; escapes: EscapeSpan[] } {
  const tokens: TokenSpan[] = [];
  const escapes: EscapeSpan[] = [];
  for (let index = 0; index < input.length; index += 1) {
    const char = input[index];
    const next = input[index + 1];
    if (char === "\\" && (next === "#" || next === "@") && hasLeftBoundary(input, index)) {
      escapes.push({ start: index, end: index + 1 });
      index += 1;
      continue;
    }
    if ((char !== "#" && char !== "@") || !hasLeftBoundary(input, index)) {
      continue;
    }
    const parsed = next === '"' ? parseQuoted(input, index + 1) : parseUnquoted(input, index + 1);
    if (!parsed || displayName(parsed.name).length === 0) {
      continue;
    }
    tokens.push({ kind: char === "#" ? "tag" : "project", start: index, end: parsed.end, name: displayName(parsed.name) });
    index = parsed.end - 1;
  }
  return { tokens, escapes };
}

function expandedRemovalSpans(input: string, tokens: TokenSpan[]): Array<{ start: number; end: number }> {
  return tokens.map((token) => {
    let left = token.start - 1;
    while (left >= 0 && whitespacePattern.test(input[left])) {
      left -= 1;
    }
    let right = token.end;
    while (right < input.length && whitespacePattern.test(input[right])) {
      right += 1;
    }
    const close = wrapperPairs.get(input[left] ?? "");
    if (close && input[right] === close) {
      const before = input.slice(left + 1, token.start);
      const after = input.slice(token.end, right);
      if (!before.trim() && !after.trim()) {
        return { start: left, end: right + 1 };
      }
    }
    return { start: token.start, end: token.end };
  });
}

function cleanTitle(input: string, tokens: TokenSpan[], escapes: EscapeSpan[]): string {
  const remove = new Array<boolean>(input.length).fill(false);
  for (const span of expandedRemovalSpans(input, tokens)) {
    for (let index = span.start; index < span.end; index += 1) {
      remove[index] = true;
    }
  }
  for (const span of escapes) {
    for (let index = span.start; index < span.end; index += 1) {
      remove[index] = true;
    }
  }
  const kept = Array.from(input).filter((_, index) => !remove[index]).join("");
  return kept.replace(/\s+/gu, " ").replace(/\s+([,.;:!?\])}])/gu, "$1").trim();
}

function tagKeyForName(name: string): string {
  return normalize(stripLegacySigil(name));
}

function projectKeyForName(name: string): string {
  return normalize(stripLegacyProjectSigil(name));
}

function refKey(ref: SmartAddRef, kind: SmartAddKind): string {
  if ("id" in ref) {
    return `id:${ref.id}`;
  }
  return `name:${kind === "tag" ? tagKeyForName(ref.name) : projectKeyForName(ref.name)}`;
}

function resolveTag(name: string, tags: TagResponse[]): SmartAddRef {
  const key = tagKeyForName(name);
  const existing = tags.find((tag) => tagKeyForName(tag.name) === key);
  return existing ? { id: existing.id } : { name: displayName(stripLegacySigil(name)) };
}

function resolveProject(name: string, projects: ProjectResponse[]): SmartAddRef {
  const key = projectKeyForName(name);
  const existing = projects.find((project) => projectKeyForName(project.name) === key);
  return existing ? { id: existing.id } : { name: displayName(stripLegacyProjectSigil(name)) };
}

export function parseSmartAdd(input: string, options: SmartAddParseOptions): SmartAddDraft {
  const { tokens, escapes } = scanCompleted(input);
  const tags: SmartAddRef[] = [];
  const seenTags = new Set<string>();
  const appendTag = (ref: SmartAddRef) => {
    const key = refKey(ref, "tag");
    if (!seenTags.has(key)) {
      seenTags.add(key);
      tags.push(ref);
    }
  };
  if (options.contextTagId) {
    appendTag({ id: options.contextTagId });
  }
  let project: SmartAddRef | null = options.contextProjectId ? { id: options.contextProjectId } : null;
  for (const token of tokens) {
    if (token.kind === "tag") {
      appendTag(resolveTag(token.name, options.tags));
    } else {
      project = resolveProject(token.name, options.projects);
    }
  }
  const title = cleanTitle(input, tokens, escapes);
  const hasCompletedTokens = tokens.length > 0;
  return {
    cleanTitle: title,
    tags,
    project,
    hasCompletedTokens,
    isValid: title.length > 0 && title.length <= 500 && tags.every((tag) => !("name" in tag) || tag.name.length <= 500) && (!(project && "name" in project) || project.name.length <= 500)
  };
}

function labelForRef(ref: SmartAddRef, kind: SmartAddKind, options: SmartAddParseOptions): string | null {
  if ("name" in ref) {
    return ref.name;
  }
  const entity = kind === "tag"
    ? options.tags.find((tag) => tag.id === ref.id)
    : options.projects.find((project) => project.id === ref.id);
  return entity?.name ?? null;
}

export function smartAddChips(draft: SmartAddDraft, options: SmartAddParseOptions): SmartAddChip[] {
  const chips: SmartAddChip[] = [];
  if (draft.project) {
    const label = labelForRef(draft.project, "project", options);
    if (label) {
      chips.push({ kind: "project", label });
    }
  }
  for (const tagRef of draft.tags) {
    const label = labelForRef(tagRef, "tag", options);
    if (label) {
      chips.push({ kind: "tag", label });
    }
  }
  return chips;
}

function findActiveToken(input: string, caret: number): ActiveToken | null {
  for (let index = Math.min(caret, input.length) - 1; index >= 0; index -= 1) {
    const char = input[index];
    if ((char === "#" || char === "@") && hasLeftBoundary(input, index)) {
      const parsed = input[index + 1] === '"'
        ? parseQuoted(input, index + 1)
        : parseUnquoted(input, index + 1);
      if (parsed && caret > parsed.end) {
        continue;
      }
      const end = parsed?.end ?? caret;
      const raw = input.slice(index + 1, caret);
      const query = raw.startsWith('"') ? raw.slice(1).replace(/\\(["\\])/gu, "$1") : raw;
      return { kind: char === "#" ? "tag" : "project", start: index, end, query };
    }
    if (whitespacePattern.test(char)) {
      break;
    }
  }
  return null;
}

function scoreEntity(query: string, name: string): number | null {
  const normalizedQuery = normalize(query);
  const normalizedName = normalize(name);
  if (!normalizedQuery) {
    return 4;
  }
  if (normalizedName === normalizedQuery) {
    return 0;
  }
  if (normalizedName.startsWith(normalizedQuery)) {
    return 1;
  }
  if (normalizedName.split(/[\s-]+/u).some((part) => part.startsWith(normalizedQuery))) {
    return 2;
  }
  if (normalizedName.includes(normalizedQuery)) {
    return 3;
  }
  return null;
}

export function smartAddSuggestions(input: string, caret: number, options: SmartAddParseOptions): SmartAddSuggestion[] {
  const active = findActiveToken(input, caret);
  if (!active) {
    return [];
  }
  const entities = active.kind === "tag" ? options.tags : options.projects;
  const ranked = entities
    .map((entity) => ({ entity, score: scoreEntity(active.query, entity.name) }))
    .filter((item): item is { entity: TagResponse | ProjectResponse; score: number } => item.score !== null)
    .sort((left, right) => left.score - right.score || normalize(left.entity.name).localeCompare(normalize(right.entity.name)) || left.entity.id.localeCompare(right.entity.id))
    .slice(0, 8)
    .map<SmartAddSuggestion>(({ entity }) => ({ kind: active.kind, label: entity.name, ref: { id: entity.id }, create: false }));
  const query = displayName(active.query);
  const exact = entities.some((entity) => normalize(entity.name) === normalize(query));
  if (query && !exact) {
    ranked.push({ kind: active.kind, label: `Create ${active.kind === "tag" ? "#" : "@"}${query}`, ref: { name: query }, create: true });
  }
  return ranked;
}

function serializeToken(kind: SmartAddKind, label: string): string {
  const sigil = kind === "tag" ? "#" : "@";
  const clean = kind === "tag" ? stripLegacySigil(label) : stripLegacyProjectSigil(label);
  if (/^[\p{L}\p{N}\p{M}_](?:[\p{L}\p{N}\p{M}_]|[-.](?=[\p{L}\p{N}\p{M}_]))*$/u.test(clean)) {
    return `${sigil}${clean}`;
  }
  return `${sigil}"${clean.replace(/\\/gu, "\\\\").replace(/"/gu, '\\"')}"`;
}

export function applySmartAddSuggestion(input: string, caret: number, suggestion: SmartAddSuggestion): { text: string; caret: number } | null {
  const active = findActiveToken(input, caret);
  if (!active || active.kind !== suggestion.kind) {
    return null;
  }
  const label = "name" in suggestion.ref ? suggestion.ref.name : suggestion.label;
  const token = serializeToken(suggestion.kind, label);
  const needsSpace = !input[active.end] || (!whitespacePattern.test(input[active.end]) && !/[,.;:!?\])}]/u.test(input[active.end]));
  const replacement = `${token}${needsSpace ? " " : ""}`;
  const text = `${input.slice(0, active.start)}${replacement}${input.slice(active.end)}`;
  const caretOffset = replacement.length + (!needsSpace && whitespacePattern.test(input[active.end] ?? "") ? 1 : 0);
  return { text, caret: active.start + caretOffset };
}

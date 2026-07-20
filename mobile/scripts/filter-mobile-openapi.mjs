#!/usr/bin/env node
// Explicit mobile operation allowlist (ADR-0002 / ADR-0008 / spec 004 tasks.md T013).
//
// The full backend OpenAPI contract stays committed at api/openapi.json (a
// copy of the repo-root pinned `openapi/brainbuddy-v1.json` snapshot) for
// audit/drift review, including deprecated web-compatibility aliases (direct
// proposal PATCH, `/finish`, `/commit`, and the untyped `/{action}` bare
// path) and every non-mobile domain (Reality Tree/CRT, Smart Add, Project/
// Tag mutation, Subtasks, Comments, browser session/signup).
//
// This filter is an ALLOWLIST, not "drop everything marked deprecated": an
// operation is kept only when its (method, path) pair is explicitly listed
// below as part of the bounded first mobile slice. A backend author adding
// a new non-deprecated route does NOT automatically expose it to mobile --
// they must add it here deliberately. This also means the untyped
// `/brain-dump-operations/{operation_id}/{action}` dispatcher is excluded
// even though nothing about the OpenAPI document itself forces that (it
// happens to also be marked `deprecated: true`, but exclusion here does not
// depend on that flag).

import { readFileSync, writeFileSync } from "node:fs";

const HTTP_METHODS = ["get", "put", "post", "delete", "patch", "options", "head", "trace"];

// (method, path) pairs the first mobile slice is allowed to consume.
// Keep in sync with specs/004-expo-mobile-first-slice/contracts/mobile-api.md.
export const MOBILE_ALLOWED_OPERATIONS = [
  // Mobile session establishment (ADR-0008) -- never /auth/login or
  // /auth/signup, which are browser-cookie/web-only.
  ["post", "/api/auth/mobile/sessions"],
  ["get", "/api/auth/me"],
  ["post", "/api/auth/logout"],

  // Task subset (mobile-api.md "Task subset"): read/create/transition only,
  // never Smart Add, Subtasks, or Comments.
  ["get", "/api/tasks"],
  ["get", "/api/tasks/{task_id}"],
  ["post", "/api/tasks"],
  ["post", "/api/tasks/{task_id}/transitions"],
  ["get", "/api/projects"],
  ["get", "/api/projects/{project_id}"],
  ["get", "/api/tags"],
  ["get", "/api/tags/{tag_id}"],

  // Voice Brain Dump canonical operation substrate (mobile-api.md "Voice
  // Brain Dump subset"): never the deprecated /transcript, /commit,
  // /finish, direct proposal PATCH, or untyped /{action} dispatcher.
  ["get", "/api/brain-dump-processing-policy"],
  ["post", "/api/brain-dump-operations"],
  ["get", "/api/brain-dump-operations/{operation_id}"],
  ["put", "/api/brain-dump-operations/{operation_id}/audio/{chunk_number}"],
  ["post", "/api/brain-dump-operations/{operation_id}/seal"],
  ["post", "/api/brain-dump-operations/{operation_id}/consent-decisions"],
  ["post", "/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}/patches"],
  ["post", "/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}/conflicts/resolve"],
  ["post", "/api/brain-dump-operations/{operation_id}/proposal-batches"],
  ["post", "/api/brain-dump-operations/{operation_id}/confirm"],
  ["post", "/api/brain-dump-operations/{operation_id}/audio/delete"],
  ["post", "/api/brain-dump-operations/{operation_id}/commands/{action}"],
];

const ALLOWED_SET = new Set(
  MOBILE_ALLOWED_OPERATIONS.map(([method, path]) => `${method}:${path}`),
);

// Belt-and-suspenders: even if a future edit accidentally allowlisted one of
// these, they are hard-excluded. Every deprecated web-compatibility alias
// and the untyped action dispatcher must never reach mobile generation.
const HARD_EXCLUDED = new Set([
  "post:/api/brain-dump-operations/{operation_id}/{action}",
  "post:/api/brain-dump-operations/{operation_id}/commit",
  "post:/api/brain-dump-operations/{operation_id}/finish",
  "patch:/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}",
  "post:/api/brain-dump-operations/{operation_id}/transcript",
  "post:/api/tasks/smart-add",
]);

export function filterToMobileAllowlist(schema) {
  const filtered = JSON.parse(JSON.stringify(schema));
  const excludedOperationIds = [];
  const keptOperationIds = [];
  const paths = filtered.paths ?? {};

  for (const [path, pathItem] of Object.entries(paths)) {
    for (const method of HTTP_METHODS) {
      const operation = pathItem[method];
      if (!operation) {
        continue;
      }
      const key = `${method}:${path}`;
      const allowed = ALLOWED_SET.has(key) && !HARD_EXCLUDED.has(key);
      if (operation.deprecated === true && allowed) {
        // An allowlisted path must never also be the deprecated alias it is
        // meant to replace -- fail loudly instead of silently shipping a
        // deprecated operation to mobile.
        throw new Error(
          `Mobile allowlist entry '${key}' is marked deprecated in the OpenAPI ` +
            "document; remove it from MOBILE_ALLOWED_OPERATIONS or fix the backend route.",
        );
      }
      if (!allowed) {
        excludedOperationIds.push(operation.operationId ?? key);
        delete pathItem[method];
        continue;
      }
      keptOperationIds.push(operation.operationId ?? key);
    }
    if (Object.keys(pathItem).length === 0) {
      delete paths[path];
    }
  }

  const missing = MOBILE_ALLOWED_OPERATIONS.filter(
    ([method, path]) => !(schema.paths?.[path]?.[method]),
  );
  if (missing.length > 0) {
    throw new Error(
      "Mobile allowlist references operation(s) absent from the OpenAPI document: " +
        missing.map(([method, path]) => `${method.toUpperCase()} ${path}`).join(", "),
    );
  }

  return { schema: filtered, excludedOperationIds, keptOperationIds };
}

// Retained for callers/tests that still import the old drop-deprecated-only
// name; behavior is now the explicit allowlist above.
export function filterDeprecatedOperations(schema) {
  return filterToMobileAllowlist(schema);
}

function main() {
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) {
    console.error("usage: filter-mobile-openapi.mjs <input-openapi.json> <output-openapi.json>");
    process.exit(1);
  }

  const schema = JSON.parse(readFileSync(inputPath, "utf8"));
  const { schema: filtered, excludedOperationIds, keptOperationIds } =
    filterToMobileAllowlist(schema);
  writeFileSync(outputPath, `${JSON.stringify(filtered, null, 2)}\n`);
  console.error(
    `mobile openapi allowlist: kept ${keptOperationIds.length} operation(s), ` +
      `excluded ${excludedOperationIds.length}: ${excludedOperationIds.join(", ")}`,
  );
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}

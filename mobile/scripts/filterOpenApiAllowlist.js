#!/usr/bin/env node
"use strict";

// ADR-0008 (docs/decisions/0008-add-one-expo-mobile-client-over-opaque-sessions.md,
// lines 132-141) and specs/004-expo-mobile-first-slice/contracts/mobile-api.md fix
// an explicit mobile operation allowlist: mobile client generation must never pass
// the full backend OpenAPI snapshot to openapi-typescript. The committed snapshot
// may keep describing deprecated web-compatibility aliases and unrelated web
// surface (tree canvas, project/tag mutations, subtasks/comments) during their
// bounded overlap window, but the mobile client must never receive typed request/
// response signatures for operations it must not call.
//
// Keyed by exact "<method> <path>" as they appear in the OpenAPI document's
// `paths` object (method lowercase, path exactly as written, including the `/api`
// prefix). An allowlist entry for an operation the current backend does not yet
// expose as a distinct route (e.g. the canonical proposal-batches/confirm/
// consent-decisions/audio-delete/processing-policy routes mobile-api.md names,
// which this PR's backend still serves through the generic
// `/brain-dump-operations/{operation_id}/{action}` command dispatcher) is
// harmless: filtering is a lookup against whatever paths are actually present in
// the input document, so an unmatched allowlist entry simply contributes nothing.
const ALLOWED_OPERATIONS = new Set([
  // Mobile session establishment (mobile-api.md "Mobile session establishment").
  "post /api/auth/mobile/sessions",
  "get /api/auth/me",
  "post /api/auth/logout",

  // Task subset (mobile-api.md "Task subset").
  "get /api/tasks",
  "get /api/tasks/{task_id}",
  "post /api/tasks",
  "post /api/tasks/{task_id}/transitions",
  "get /api/projects",
  "get /api/projects/{project_id}",
  "get /api/tags",
  "get /api/tags/{tag_id}",

  // Voice Brain Dump subset (mobile-api.md "Voice Brain Dump subset").
  "get /api/brain-dump-processing-policy",
  "post /api/brain-dump-operations",
  "get /api/brain-dump-operations/{operation_id}",
  "put /api/brain-dump-operations/{operation_id}/audio/{chunk_number}",
  "post /api/brain-dump-operations/{operation_id}/seal",
  "post /api/brain-dump-operations/{operation_id}/proposals/{proposal_id}/patches",
  "post /api/brain-dump-operations/{operation_id}/proposal-batches",
  "post /api/brain-dump-operations/{operation_id}/confirm",
  "post /api/brain-dump-operations/{operation_id}/consent-decisions",
  "post /api/brain-dump-operations/{operation_id}/audio/delete",
  // The canonical cancel/retry/review-provisional commands are dispatched
  // through this generic action-command substrate on the current backend (the
  // canonical routes named above do not exist as separate paths yet). It must
  // stay allowed so mobile can generate types for the commands it is already
  // allowed to send; mobile-api.md's excluded `/finish` and `/commit`
  // compatibility aliases are literal, separate legacy routes this dispatcher
  // does not expose, not action values carried through it.
  "post /api/brain-dump-operations/{operation_id}/{action}",
]);

const HTTP_METHODS = new Set([
  "get",
  "put",
  "post",
  "delete",
  "options",
  "head",
  "patch",
  "trace",
]);

function filterOpenApiDocument(document) {
  const filteredPaths = {};
  for (const [requestPath, pathItem] of Object.entries(document.paths || {})) {
    const keptPathItem = {};
    for (const [key, value] of Object.entries(pathItem)) {
      const isOperation = HTTP_METHODS.has(key);
      if (!isOperation) {
        // Preserve path-item-level fields (e.g. a shared "parameters" array)
        // verbatim; they are not operations to allowlist.
        keptPathItem[key] = value;
        continue;
      }
      if (ALLOWED_OPERATIONS.has(`${key} ${requestPath}`)) {
        keptPathItem[key] = value;
      }
    }
    const hasOperation = Object.keys(keptPathItem).some((key) => HTTP_METHODS.has(key));
    if (hasOperation) {
      filteredPaths[requestPath] = keptPathItem;
    }
  }
  return { ...document, paths: filteredPaths };
}

module.exports = { ALLOWED_OPERATIONS, filterOpenApiDocument };

if (require.main === module) {
  const fs = require("fs");
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) {
    console.error(
      "usage: filterOpenApiAllowlist.js <input-openapi.json> <output-filtered.json>",
    );
    process.exit(1);
  }
  const document = JSON.parse(fs.readFileSync(inputPath, "utf8"));
  const filtered = filterOpenApiDocument(document);
  fs.writeFileSync(outputPath, `${JSON.stringify(filtered, null, 2)}\n`, "utf8");
}

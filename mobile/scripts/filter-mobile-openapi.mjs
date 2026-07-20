#!/usr/bin/env node
// Deterministic mobile operation allowlist (ADR-0002 / ADR-0008).
//
// The full backend OpenAPI contract stays committed at api/openapi.json for
// audit/drift review, including deprecated web-compatibility aliases (direct
// proposal PATCH, `/finish`, `/commit`). Mobile client generation must never
// see those aliases: this filter keeps every operation except one the
// backend explicitly marks `deprecated: true`, and writes the allowlisted
// subset to a separate file that is the only input to openapi-typescript.

import { readFileSync, writeFileSync } from "node:fs";

const HTTP_METHODS = ["get", "put", "post", "delete", "patch", "options", "head", "trace"];

export function filterDeprecatedOperations(schema) {
  const filtered = JSON.parse(JSON.stringify(schema));
  const excludedOperationIds = [];
  const paths = filtered.paths ?? {};

  for (const [path, pathItem] of Object.entries(paths)) {
    for (const method of HTTP_METHODS) {
      const operation = pathItem[method];
      if (operation && operation.deprecated === true) {
        excludedOperationIds.push(operation.operationId ?? `${method.toUpperCase()} ${path}`);
        delete pathItem[method];
      }
    }
    if (Object.keys(pathItem).length === 0) {
      delete paths[path];
    }
  }

  return { schema: filtered, excludedOperationIds };
}

function main() {
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) {
    console.error("usage: filter-mobile-openapi.mjs <input-openapi.json> <output-openapi.json>");
    process.exit(1);
  }

  const schema = JSON.parse(readFileSync(inputPath, "utf8"));
  const { schema: filtered, excludedOperationIds } = filterDeprecatedOperations(schema);
  writeFileSync(outputPath, `${JSON.stringify(filtered, null, 2)}\n`);
  console.error(
    `mobile openapi allowlist: excluded ${excludedOperationIds.length} deprecated operation(s): ` +
      excludedOperationIds.join(", "),
  );
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}

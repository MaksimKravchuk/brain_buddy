import * as fs from "fs";
import * as path from "path";

import { mobileAllure, withAllure } from "@/test/allureTaxonomy";

import { ALLOWED_OPERATIONS, filterOpenApiDocument } from "../filterOpenApiAllowlist";

function op(summary: string) {
  return {
    summary,
    operationId: summary.replace(/[^a-zA-Z0-9]+/g, "_"),
    responses: { "200": { description: "ok" } },
  };
}

describe("mobile OpenAPI operation allowlist", () => {
  it(
    mobileAllure.contract(
      "keeps only the mobile-api.md first-slice operations and drops the rest",
    ).title,
    async () => {
      await withAllure(
        mobileAllure.contract(
          "keeps only the mobile-api.md first-slice operations and drops the rest",
        ),
        async () => {
          const fixture = {
            openapi: "3.1.0",
            info: { title: "fixture", version: "1.0.0" },
            paths: {
              // Included: mobile session establishment (specs/004 "Mobile session establishment").
              "/api/auth/mobile/sessions": { post: op("create mobile session") },
              "/api/auth/me": { get: op("me") },
              "/api/auth/logout": { post: op("logout") },

              // Included: task subset (specs/004 "Task subset").
              "/api/tasks": { get: op("list tasks"), post: op("create task") },
              "/api/tasks/{task_id}": { get: op("get task") },
              "/api/tasks/{task_id}/transitions": { post: op("transition task") },
              "/api/projects": { get: op("list projects") },
              "/api/projects/{project_id}": { get: op("get project") },
              "/api/tags": { get: op("list tags") },
              "/api/tags/{tag_id}": {
                get: op("get tag"),
                patch: op("update tag"),
                delete: op("delete tag"),
              },

              // Included: Voice Brain Dump subset (specs/004 "Voice Brain Dump subset").
              "/api/brain-dump-processing-policy": { get: op("processing policy") },
              "/api/brain-dump-operations": { post: op("start operation") },
              "/api/brain-dump-operations/{operation_id}": { get: op("get operation") },
              "/api/brain-dump-operations/{operation_id}/audio/{chunk_number}": {
                put: op("upload audio chunk"),
              },
              "/api/brain-dump-operations/{operation_id}/seal": { post: op("seal operation") },
              "/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}/patches": {
                post: op("canonical proposal patches"),
              },
              "/api/brain-dump-operations/{operation_id}/proposal-batches": {
                post: op("freeze proposal batch"),
              },
              "/api/brain-dump-operations/{operation_id}/confirm": { post: op("confirm batch") },
              "/api/brain-dump-operations/{operation_id}/consent-decisions": {
                post: op("consent decision"),
              },
              "/api/brain-dump-operations/{operation_id}/audio/delete": {
                post: op("delete raw audio"),
              },
              "/api/brain-dump-operations/{operation_id}/{action}": {
                post: op("cancel/retry/review-provisional command"),
              },

              // Excluded: web-only auth (mobile never uses cookie login/signup).
              "/api/auth/login": { post: op("web login") },
              "/api/auth/signup": { post: op("web signup") },

              // Excluded: deprecated direct proposal PATCH alias (mobile-api.md
              // "API version ownership" / ADR-0008 lines 132-141), even though its
              // sibling canonical POST .../patches route above is kept.
              "/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}": {
                patch: op("deprecated direct proposal patch"),
              },

              // Excluded: deprecated /finish and /commit compatibility aliases.
              "/api/brain-dump-operations/{operation_id}/finish": {
                post: op("deprecated finish alias"),
              },
              "/api/brain-dump-operations/{operation_id}/commit": {
                post: op("deprecated commit alias"),
              },

              // Excluded: explicitly out of the first slice (mobile-api.md "Task subset").
              "/api/tasks/smart-add": { post: op("smart add") },
              "/api/tasks/{task_id}/comments": { post: op("create comment") },
              "/api/projects/{project_id}/archive": { post: op("archive project") },

              // Excluded: unrelated web/tree mutation operations.
              "/api/trees": { get: op("list trees"), post: op("create tree") },
              "/api/trees/{tree_id}": {
                get: op("get tree"),
                put: op("update tree"),
                delete: op("delete tree"),
              },
              "/api/trees/{tree_id}/nodes": { post: op("create node") },
              "/health": { get: op("health check") },
            },
            components: { schemas: { Placeholder: { type: "object" } } },
          };

          const filtered = filterOpenApiDocument(fixture);

          const includedOperations: [string, string][] = [
            ["post", "/api/auth/mobile/sessions"],
            ["get", "/api/auth/me"],
            ["post", "/api/auth/logout"],
            ["get", "/api/tasks"],
            ["post", "/api/tasks"],
            ["get", "/api/tasks/{task_id}"],
            ["post", "/api/tasks/{task_id}/transitions"],
            ["get", "/api/projects"],
            ["get", "/api/projects/{project_id}"],
            ["get", "/api/tags"],
            ["get", "/api/tags/{tag_id}"],
            ["get", "/api/brain-dump-processing-policy"],
            ["post", "/api/brain-dump-operations"],
            ["get", "/api/brain-dump-operations/{operation_id}"],
            ["put", "/api/brain-dump-operations/{operation_id}/audio/{chunk_number}"],
            ["post", "/api/brain-dump-operations/{operation_id}/seal"],
            ["post", "/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}/patches"],
            ["post", "/api/brain-dump-operations/{operation_id}/proposal-batches"],
            ["post", "/api/brain-dump-operations/{operation_id}/confirm"],
            ["post", "/api/brain-dump-operations/{operation_id}/consent-decisions"],
            ["post", "/api/brain-dump-operations/{operation_id}/audio/delete"],
            ["post", "/api/brain-dump-operations/{operation_id}/{action}"],
          ];
          for (const [method, requestPath] of includedOperations) {
            expect(filtered.paths[requestPath]?.[method]).toBeDefined();
          }

          // Mutation methods on an otherwise-kept path are dropped individually.
          expect(filtered.paths["/api/tags/{tag_id}"].patch).toBeUndefined();
          expect(filtered.paths["/api/tags/{tag_id}"].delete).toBeUndefined();

          const excludedPaths = [
            "/api/auth/login",
            "/api/auth/signup",
            "/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}",
            "/api/brain-dump-operations/{operation_id}/finish",
            "/api/brain-dump-operations/{operation_id}/commit",
            "/api/tasks/smart-add",
            "/api/tasks/{task_id}/comments",
            "/api/projects/{project_id}/archive",
            "/api/trees",
            "/api/trees/{tree_id}",
            "/api/trees/{tree_id}/nodes",
            "/health",
          ];
          for (const requestPath of excludedPaths) {
            expect(filtered.paths[requestPath]).toBeUndefined();
          }

          // components are preserved verbatim so referenced schemas keep resolving.
          expect(filtered.components).toEqual(fixture.components);
        },
      );
    },
  );

  it(
    mobileAllure.contract(
      "excludes deprecated and unrelated operations from the committed snapshot",
    ).title,
    async () => {
      await withAllure(
        mobileAllure.contract(
          "excludes deprecated and unrelated operations from the committed snapshot",
        ),
        async () => {
          const snapshotPath = path.resolve(__dirname, "..", "..", "api", "openapi.json");
          const document = JSON.parse(fs.readFileSync(snapshotPath, "utf8"));
          const filtered = filterOpenApiDocument(document);

          expect(filtered.paths["/api/auth/mobile/sessions"]?.post).toBeDefined();
          expect(filtered.paths["/api/auth/me"]?.get).toBeDefined();
          expect(filtered.paths["/api/auth/logout"]?.post).toBeDefined();
          expect(filtered.paths["/api/tasks"]?.get).toBeDefined();
          expect(filtered.paths["/api/tasks"]?.post).toBeDefined();
          expect(filtered.paths["/api/brain-dump-operations"]?.post).toBeDefined();
          expect(filtered.paths["/api/brain-dump-operations/{operation_id}"]?.get).toBeDefined();
          expect(
            filtered.paths["/api/brain-dump-operations/{operation_id}/seal"]?.post,
          ).toBeDefined();
          expect(
            filtered.paths["/api/brain-dump-operations/{operation_id}/{action}"]?.post,
          ).toBeDefined();

          // Deprecated direct proposal PATCH alias is excluded even though it exists today.
          expect(
            filtered.paths["/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}"],
          ).toBeUndefined();

          // Unrelated web-only and tree canvas operations are excluded.
          expect(filtered.paths["/api/auth/login"]).toBeUndefined();
          expect(filtered.paths["/api/auth/signup"]).toBeUndefined();
          expect(filtered.paths["/api/tasks/smart-add"]).toBeUndefined();
          expect(filtered.paths["/health"]).toBeUndefined();
          for (const requestPath of Object.keys(document.paths)) {
            if (requestPath.startsWith("/api/trees")) {
              expect(filtered.paths[requestPath]).toBeUndefined();
            }
          }

          // Every operation actually kept is a declared allowlist member.
          for (const [requestPath, methods] of Object.entries(filtered.paths)) {
            for (const method of Object.keys(methods as Record<string, unknown>)) {
              expect(ALLOWED_OPERATIONS.has(`${method} ${requestPath}`)).toBe(true);
            }
          }
        },
      );
    },
  );
});

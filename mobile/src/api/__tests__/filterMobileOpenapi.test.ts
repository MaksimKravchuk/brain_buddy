import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { mobileAllure, withAllure } from "@/test/allureTaxonomy";

const SCRIPT_PATH = join(__dirname, "..", "..", "..", "scripts", "filter-mobile-openapi.mjs");

function fixtureSchema() {
  return {
    openapi: "3.1.0",
    info: { title: "Brain Buddy API", version: "1.0.0" },
    paths: {
      "/api/tasks": {
        get: { operationId: "list_tasks" },
        post: { operationId: "create_task" },
      },
      "/api/tasks/smart-add": {
        post: { operationId: "smart_add_task" },
      },
      "/api/brain-dump-operations/{operation_id}/commands/{action}": {
        post: { operationId: "command_brain_dump_operation_canonical" },
      },
      "/api/brain-dump-operations/{operation_id}/{action}": {
        post: { operationId: "command_brain_dump_operation", deprecated: true },
      },
      "/api/brain-dump-operations/{operation_id}/commit": {
        post: { operationId: "commit_brain_dump_operation_deprecated", deprecated: true },
      },
      "/api/trees": {
        get: { operationId: "list_trees" },
      },
      // Every path referenced by MOBILE_ALLOWED_OPERATIONS must exist for
      // the script's own completeness check to pass.
      "/api/auth/mobile/sessions": { post: { operationId: "mobile_login" } },
      "/api/auth/me": { get: { operationId: "me" } },
      "/api/auth/logout": { post: { operationId: "logout" } },
      "/api/tasks/{task_id}": { get: { operationId: "get_task" } },
      "/api/tasks/{task_id}/transitions": { post: { operationId: "transition_task" } },
      "/api/projects": { get: { operationId: "list_projects" } },
      "/api/projects/{project_id}": { get: { operationId: "get_project" } },
      "/api/tags": { get: { operationId: "list_tags" } },
      "/api/tags/{tag_id}": { get: { operationId: "get_tag" } },
      "/api/brain-dump-processing-policy": { get: { operationId: "policy" } },
      "/api/brain-dump-operations": { post: { operationId: "start_brain_dump" } },
      "/api/brain-dump-operations/{operation_id}": { get: { operationId: "get_brain_dump" } },
      "/api/brain-dump-operations/{operation_id}/audio/{chunk_number}": {
        put: { operationId: "upload_chunk" },
      },
      "/api/brain-dump-operations/{operation_id}/seal": { post: { operationId: "seal" } },
      "/api/brain-dump-operations/{operation_id}/consent-decisions": {
        post: { operationId: "consent_decision" },
      },
      "/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}/patches": {
        post: { operationId: "proposal_patch" },
      },
      "/api/brain-dump-operations/{operation_id}/proposals/{proposal_id}/conflicts/resolve": {
        post: { operationId: "resolve_conflict" },
      },
      "/api/brain-dump-operations/{operation_id}/proposal-batches": {
        post: { operationId: "freeze_batch" },
      },
      "/api/brain-dump-operations/{operation_id}/confirm": { post: { operationId: "confirm" } },
      "/api/brain-dump-operations/{operation_id}/audio/delete": {
        post: { operationId: "delete_audio" },
      },
    },
  };
}

describe("mobile OpenAPI allowlist filter", () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "mobile-openapi-allowlist-"));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it(
    mobileAllure.contract(
      "excludes deprecated aliases and the arbitrary action path, keeps the canonical route",
    ).title,
    async () => {
      await withAllure(
        mobileAllure.contract(
          "excludes deprecated aliases and the arbitrary action path, keeps the canonical route",
        ),
        async () => {
          const inputPath = join(dir, "input.json");
          const outputPath = join(dir, "output.json");
          writeFileSync(inputPath, JSON.stringify(fixtureSchema()));

          execFileSync("node", [SCRIPT_PATH, inputPath, outputPath], { stdio: "pipe" });

          const filtered = JSON.parse(readFileSync(outputPath, "utf8"));
          const paths = filtered.paths;

          // Kept: explicit allowlist entries.
          expect(paths["/api/tasks"].get).toBeDefined();
          expect(paths["/api/tasks"].post).toBeDefined();
          expect(
            paths["/api/brain-dump-operations/{operation_id}/commands/{action}"].post,
          ).toBeDefined();

          // Excluded: deprecated aliases, the arbitrary action path, Smart
          // Add, and the entire non-mobile Reality Tree domain.
          expect(paths["/api/tasks/smart-add"]).toBeUndefined();
          expect(
            paths["/api/brain-dump-operations/{operation_id}/{action}"],
          ).toBeUndefined();
          expect(
            paths["/api/brain-dump-operations/{operation_id}/commit"],
          ).toBeUndefined();
          expect(paths["/api/trees"]).toBeUndefined();
        },
      );
    },
  );

  it(
    mobileAllure.contract("fails loudly when an allowlisted operation is also marked deprecated")
      .title,
    async () => {
      await withAllure(
        mobileAllure.contract(
          "fails loudly when an allowlisted operation is also marked deprecated",
        ),
        async () => {
          const schema = fixtureSchema();
          (schema.paths["/api/tasks"] as { get: { deprecated?: boolean } }).get.deprecated = true;
          const inputPath = join(dir, "input.json");
          const outputPath = join(dir, "output.json");
          writeFileSync(inputPath, JSON.stringify(schema));

          // stdio: "pipe" keeps the deliberately-triggered child-process
          // error trace out of the test runner's own console/CI log --
          // this test asserts the *throw*, not the printed trace.
          expect(() =>
            execFileSync("node", [SCRIPT_PATH, inputPath, outputPath], { stdio: "pipe" }),
          ).toThrow();
        },
      );
    },
  );

  it(
    mobileAllure.contract("fails loudly when an allowlisted operation is missing from the schema")
      .title,
    async () => {
      await withAllure(
        mobileAllure.contract(
          "fails loudly when an allowlisted operation is missing from the schema",
        ),
        async () => {
          const schema = fixtureSchema();
          delete (schema.paths as Record<string, unknown>)["/api/tags"];
          const inputPath = join(dir, "input.json");
          const outputPath = join(dir, "output.json");
          writeFileSync(inputPath, JSON.stringify(schema));

          // See stdio note above -- suppress the deliberate child error trace.
          expect(() =>
            execFileSync("node", [SCRIPT_PATH, inputPath, outputPath], { stdio: "pipe" }),
          ).toThrow();
        },
      );
    },
  );
});

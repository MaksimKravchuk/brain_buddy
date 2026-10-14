# Spec 026 pilot rehearsal, 2026-10-14 (automated; not reference-device evidence)

Automated rehearsal of the Apple pilot (quickstart.md Q01–Q12, SC-003/SC-004, cutover drill) run by agents on a MacBook Air M4 (macOS 26) and the iOS Simulator against a **local** backend. None of these results fill a cell of `apple-pilot.md`, `apple-ux.md`, `mac-ux.md`, `iphone-ai.md`, `mac-ai.md` or `ai-consent.md`: those need the reference devices (iPhone 11 / iOS 26, MacBook Air M1). NOT_AUTOMATED is never a pass.

How to rerun: S1 `python3 scripts/rehearsal/run.py --target local`; S2 see below; S3 `BB_REHEARSAL_TARGET=local BB_BACKEND_PYTHON=… swift test --package-path ios/BrainBuddyKit --filter Rehearsal` (and `--package-path macos --filter MacRehearsal`); S4 `sh scripts/rehearsal/run_ios_ui.sh "iPhone 17"`.

## S1 API driver

| Field | Value |
| --- | --- |
| target | `local` |
| git_sha | `cf28db8d541e2ba3c409fa3116b5aafcda6bbd8f` |
| machine | `MacBook Air M4 (not reference)` |
| timestamp | `2026-10-13T23:16:28+00:00` |
| run_id | `ef17a3f9` |
| requests | `83` |

| Scenario | Status | Summary |
| --- | --- | --- |
| CLEANUP rehearsal data removed | PASS | {'task:200': 4, 'project:200': 2} |
| CUTOVER cutover and rollback drill (local copy, flag off -> on -> restore) | PASS | flag OFF: scope_enabled false=True, flag OFF: feed refused=True, flag ON: scope_enabled true=True, ON: snapshot lists both tasks=True, restore: record set equals pre-enable copy=True, restore: flag OFF again=True |
| Q01 offline capture | NOT_AUTOMATED | needs real phone/Mac clients (airplane mode, kill/reopen) |
| Q02 concurrent edits | NOT_AUTOMATED | needs two native devices and the conflict UI |
| Q03 delivery faults | NOT_AUTOMATED | needs process-kill fault injection in a native client; covered by cargo/pytest suites |
| Q04 reset with live edits | NOT_AUTOMATED | needs a native client capturing during snapshot paging |
| Q05 isolation (REST + sync, API part) | PASS | 20 probes, all foreign == unknown 404 |
| Q06 import | NOT_AUTOMATED | needs the legacy Apple stores and the native import path |
| Q07 REST writers visible in A's sync feed (create/edit/move) | PASS | 3 transactions for the task; checks: feed answered 200=True, at least 3 transactions name the task=True, edited title appears=True, moved state appears=True; shared fields that differ from REST: none |
| Q08 restore drill (control-plane replay, revoked session, old cursor) | PASS | replay CLI exit 0=True, reopen CLI exit 0=True, session revoked after backup stays rejected=True, pre-backup task present=True, post-backup task absent (reported lost commit)=True, pre-restore cursor not accepted as-is=True, fresh snapshot works=True |
| Q09 AI | NOT_AUTOMATED | needs on-device models; paid providers are out of scope |
| Q10 retention | NOT_AUTOMATED | Q10 needs a controlled server clock across the 24-hour response and seven-day Review content expiry, then receipt/feed/snapshot reads, export and purge. The test CLI only seeds an aged formulation and runs the Review sweep; no seam advances the clock that governs sync receipts. Partial seed+sweep observed: seed exit 0, sweep exit 0. |
| Q11 read-light web regression smoke | PASS | 13 requests; mismatches: none |
| Q12 user recovery | NOT_AUTOMATED | needs human participants and VoiceOver |

### CLEANUP rehearsal data removed - PASS


### CUTOVER cutover and rollback drill (local copy, flag off -> on -> restore) - PASS

Correlation IDs: 0264e015-f1e4-43be-80bc-347019baaf12, ae9c7cd1-af23-4ab4-b4db-6ebbcd215e1d, 09669db9-0490-4216-bd5e-94c799e49668, 75fc061e-833d-4dd3-9004-cd1b0f488823

```json
{
  "checks": {
    "flag OFF: scope_enabled false": true,
    "flag OFF: feed refused": true,
    "flag ON: scope_enabled true": true,
    "ON: snapshot lists both tasks": true,
    "restore: record set equals pre-enable copy": true,
    "restore: flag OFF again": true
  },
  "pre_enable_task": "task_58a86bf8f81e",
  "statuses": {
    "off_capabilities": 200,
    "off_changes": 403,
    "on_capabilities": 200,
    "on_snapshot": 200
  },
  "restored_equals_pre_enable": true,
  "drill_step_4_note": "the post-enable write is absent after restore: a lossy rollback, as documented",
  "not_automated": "PostgreSQL staging import (separate ASK authorization)"
}
```

### Q01 offline capture - NOT_AUTOMATED

Reason: needs real phone/Mac clients (airplane mode, kill/reopen)


### Q02 concurrent edits - NOT_AUTOMATED

Reason: needs two native devices and the conflict UI


### Q03 delivery faults - NOT_AUTOMATED

Reason: needs process-kill fault injection in a native client; covered by cargo/pytest suites


### Q04 reset with live edits - NOT_AUTOMATED

Reason: needs a native client capturing during snapshot paging


### Q05 isolation (REST + sync, API part) - PASS

Correlation IDs: ff0ec94d-c851-4c78-9e43-5d130b9c372d, 282f13dd-41ec-4a6c-8504-74c2efce5c0d, 5a5dafe6-cf7d-4f15-bee5-2ba3e224cf99, cd52f75c-f3fb-4bc9-87c1-e4663e6c946c, 4e713c0d-f38d-4d13-b77c-1702f3fa7900, 833f8d73-4614-4ec8-8d2e-334bf4518d09, 45f0b4a8-7901-4831-8c24-b6ceb71f4970, 8d09f225-308d-44bf-9254-284278609a9d, a8d99e20-2898-463e-9db5-b7aec404d6a4, 8a3c08db-2a4c-4682-8a53-0042f39f8d62, a4067ebd-87ea-4c61-9801-fee85d2f6cb6, 411f624e-6fc8-4f9c-8a94-a1b3ab4ed9bf, 70ab0484-330d-4a38-b101-9882df5dbec9, 4ed31bf9-d4fe-435a-b443-b0933d3c728f, 6ed9e600-f768-4511-8680-d92d38d503f7, 02042a0c-b469-41da-be64-3e6eecf437a2, b3a6cfac-377f-41c9-94b8-c9f9adaf4544, a2b68f19-f673-4e51-90af-11350149bdd2, a481a509-1c2b-442b-839f-a70fdc09682f, 78c7677f-1167-4a09-8371-17aebe113b14, c3177d7b-580c-4a57-816c-e7f575a2378f, ad31ac62-2509-499a-a9eb-3f78fbfb8718, d421fe5e-e698-4c3e-b8e5-fc49b9447914, 5f29a40d-60f5-4602-9524-76bef638683b, 5b96abcc-4c5d-499f-87a2-01032a031313, d22291eb-de13-439a-9c4a-240871e7c1b0, a3fcc1ef-dc4a-422f-b622-77cecdad497f, b5c3ca5c-68f2-4cb7-8d1c-81a2e8c1409f, a27ba9fb-2c57-43c6-a5b6-84ca263c6734, 94152e86-76c0-466a-ade5-fd9eeed8f346, 3dfee88a-354b-435f-acca-d5c479cd1bba, 4e05d2c2-8fb5-49e7-b782-3cbfb6efd69e, bf2e7887-aba4-4faf-9157-664cfda977fd, ed639b5e-4c8a-4bb9-8729-23f83a9f94cf, 764febb8-7f5b-4edd-82af-481cc973030a, 73934384-ce36-44a9-a6f2-308b6ca51d6e, 89fcd2c0-c380-4717-b269-f160a8445d6e, 9cb4bdc4-cc5c-4751-81ee-0f8447db7917, 2456b7d0-9f2d-44ca-868d-e6ddf08baee8, f07b5705-7cdb-4f82-8810-da664e501a1b, 666d0b14-97bb-47da-b8bf-c0cec52665ac, 308e895d-cea7-45f7-8563-075b78d2d7bd, 88b933dc-8ae4-4e5e-9f13-7f8675446df3, a547804f-7883-4679-a2fa-65f06369360d, 5e443fb8-23ec-44b0-9b11-2df972a4654a, 3bfd26ef-20eb-4372-8ff8-a56a0ded3be7, 6557ebdf-2f65-43a0-b5ae-e8aba6092e3f, 093ecc44-8721-4c54-85a5-f6484a23eb4e

```json
{
  "probes": [
    {
      "direction": "B->A",
      "probe": "GET task",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "cd52f75c-f3fb-4bc9-87c1-e4663e6c946c"
    },
    {
      "direction": "B->A",
      "probe": "PATCH task",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "833f8d73-4614-4ec8-8d2e-334bf4518d09"
    },
    {
      "direction": "B->A",
      "probe": "transition task",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "8d09f225-308d-44bf-9254-284278609a9d"
    },
    {
      "direction": "B->A",
      "probe": "GET project",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "8a3c08db-2a4c-4682-8a53-0042f39f8d62"
    },
    {
      "direction": "B->A",
      "probe": "sync capabilities (scope)",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "411f624e-6fc8-4f9c-8a94-a1b3ab4ed9bf"
    },
    {
      "direction": "B->A",
      "probe": "sync changes (scope)",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "4ed31bf9-d4fe-435a-b443-b0933d3c728f"
    },
    {
      "direction": "B->A",
      "probe": "sync snapshot create (scope)",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "02042a0c-b469-41da-be64-3e6eecf437a2"
    },
    {
      "direction": "B->A",
      "probe": "sync device command lookup (scope)",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "a2b68f19-f673-4e51-90af-11350149bdd2"
    },
    {
      "direction": "B->A",
      "probe": "sync SSE hints (scope)",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "78c7677f-1167-4a09-8371-17aebe113b14"
    },
    {
      "direction": "B->A",
      "probe": "sync foreign snapshot id",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "d421fe5e-e698-4c3e-b8e5-fc49b9447914"
    },
    {
      "direction": "A->B",
      "probe": "GET task",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "b5c3ca5c-68f2-4cb7-8d1c-81a2e8c1409f"
    },
    {
      "direction": "A->B",
      "probe": "PATCH task",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "94152e86-76c0-466a-ade5-fd9eeed8f346"
    },
    {
      "direction": "A->B",
      "probe": "transition task",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "4e05d2c2-8fb5-49e7-b782-3cbfb6efd69e"
    },
    {
      "direction": "A->B",
      "probe": "GET project",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "ed639b5e-4c8a-4bb9-8729-23f83a9f94cf"
    },
    {
      "direction": "A->B",
      "probe": "sync capabilities (scope)",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "73934384-ce36-44a9-a6f2-308b6ca51d6e"
    },
    {
      "direction": "A->B",
      "probe": "sync changes (scope)",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "9cb4bdc4-cc5c-4751-81ee-0f8447db7917"
    },
    {
      "direction": "A->B",
      "probe": "sync snapshot create (scope)",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "f07b5705-7cdb-4f82-8810-da664e501a1b"
    },
    {
      "direction": "A->B",
      "probe": "sync device command lookup (scope)",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "308e895d-cea7-45f7-8563-075b78d2d7bd"
    },
    {
      "direction": "A->B",
      "probe": "sync SSE hints (scope)",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "a547804f-7883-4679-a2fa-65f06369360d"
    },
    {
      "direction": "A->B",
      "probe": "sync foreign snapshot id",
      "foreign_status": 404,
      "unknown_status": 404,
      "identical_body": true,
      "id_echoed": false,
      "foreign_cid": "6557ebdf-2f65-43a0-b5ae-e8aba6092e3f"
    }
  ],
  "not_covered": "foreign sync command ID needs a device-protocol command; not exercised"
}
```

### Q06 import - NOT_AUTOMATED

Reason: needs the legacy Apple stores and the native import path


### Q07 REST writers visible in A's sync feed (create/edit/move) - PASS

Correlation IDs: 53af7a3b-084c-4fd5-9c5b-0102b0d0213b, 87898b5b-8bd9-4957-bae7-0c1c93d9b329, 1dcd2532-f52d-4cce-a0b2-a2f4d81ded37, a6af525c-c765-4398-9e36-173672b7694f, 1d6797e7-7ae6-4e8f-aa36-490ee08c1022

```json
{
  "checks": {
    "feed answered 200": true,
    "at least 3 transactions name the task": true,
    "edited title appears": true,
    "moved state appears": true
  },
  "feed_statuses": [
    200
  ],
  "transactions_total": 3,
  "transaction_keys": [
    "changes",
    "commit_seq",
    "source_command_id",
    "transaction_id"
  ],
  "shape_compare": {
    "last_record_keys": [
      "edit_revision",
      "entity_type",
      "operation",
      "record_key",
      "record_version",
      "value"
    ],
    "rest_only_fields": [
      "comments",
      "subtasks"
    ],
    "feed_only_fields": [
      "consecutive_stalled_formulations"
    ],
    "shared_fields_equal": {
      "cancelled_at": true,
      "completed_at": true,
      "created_at": true,
      "details": true,
      "due_date": true,
      "formulation": true,
      "id": true,
      "order_key": true,
      "parked": true,
      "priority": true,
      "project_id": true,
      "revision": true,
      "source_capture_ids": true,
      "state": true,
      "tag_ids": true,
      "title": true,
      "updated_at": true,
      "waiting_for": true,
      "waiting_since": true
    }
  }
}
```

### Q08 restore drill (control-plane replay, revoked session, old cursor) - PASS

Correlation IDs: 8c8964f8-81cb-47aa-95b0-0bfc967e36cb, 330e7664-164f-4662-8123-894d5028fca2, fd1809a8-86b1-47d4-a1e4-c7bd92ef773c, cb25e2bd-5197-43f2-9c48-5fbb9cf668e7, ee654ffb-23f1-4ea6-9c02-1b310823c6a0, 05014808-de02-4d61-a994-b7ae9901fa8f

```json
{
  "checks": {
    "replay CLI exit 0": true,
    "reopen CLI exit 0": true,
    "session revoked after backup stays rejected": true,
    "pre-backup task present": true,
    "post-backup task absent (reported lost commit)": true,
    "pre-restore cursor not accepted as-is": true,
    "fresh snapshot works": true
  },
  "tasks": {
    "before_backup": "task_b2480f7e-70e3-5940-a141-eaccf52dd0cc",
    "after_backup_lost": "task_19a2e0d4-5bd5-53fe-8a29-723196513886"
  },
  "session_before_restore_status": 401,
  "session_after_restore_status": 401,
  "old_cursor_feed": {
    "status": 409,
    "body": {
      "correlation_id": "<CID>",
      "error": {
        "code": "RESET_REQUIRED",
        "details": {
          "epoch_status": "active",
          "reset_reason": "feed_changed"
        },
        "message": "The local base must be recovered.",
        "retryable": false
      }
    }
  },
  "cli_replay": {
    "exit": 0,
    "output": "{\"closed_epochs\": 0, \"outcome\": \"INCIDENT_RECONCILIATION_REQUIRED\", \"purged\": [], \"revoked\": []}"
  },
  "cli_reopen": {
    "exit": 0,
    "output": "Access reopened."
  },
  "not_automated": "worker lease expiry/fences and external-effect reconciliation",
  "finding": "a restored WAL-flagged auth.sqlite3 without -shm makes startup fail with 'Authentication migration operation failed' (read-only open); the drill ships backup copies in rollback journal mode"
}
```

### Q09 AI - NOT_AUTOMATED

Reason: needs on-device models; paid providers are out of scope


### Q10 retention - NOT_AUTOMATED

Reason: Q10 needs a controlled server clock across the 24-hour response and seven-day Review content expiry, then receipt/feed/snapshot reads, export and purge. The test CLI only seeds an aged formulation and runs the Review sweep; no seam advances the clock that governs sync receipts. Partial seed+sweep observed: seed exit 0, sweep exit 0.

```json
{
  "seed": {
    "exit": 0,
    "output": "task_4f8e650f-800e-5833-ba57-12b448a15690"
  },
  "sweep": {
    "exit": 0,
    "output": "owners=1 parked=0 repaired=0 closed=0 gap_floors=0 snapshots_nulled=0"
  }
}
```

### Q11 read-light web regression smoke - PASS

Correlation IDs: 3efe88d9-db70-4fc5-b8fe-b4b2d1c7a9a8, cd43a17c-82b4-4869-b3ab-855f66c173f7, bac891fa-b5d9-487d-a50c-591b8fbed539, 6e0a5359-e28a-4a5d-88b1-1d9e6f51afc3, 1c5886ea-b689-42bb-8d50-9bdd1608e2ad, f5a5820f-f12b-43a3-955c-3956f3ebbfa5, 8f341a82-2ddf-42b6-b2e4-e0cb6a8eaea3, 9c5ba90a-a8fd-44f2-9c9c-5c6eb34de3fb, 3a7a8f01-f5cd-45f1-949b-cad3f274b033, 75d1e3c8-a18b-493e-b0fe-9c73753bcfdb, 3f147059-b132-48aa-bbb6-6432be99dbe0, e5fc2d7d-1f37-4bb3-a4ae-7780730dc411, 0bc7db1d-445d-4be6-bc22-d78610a26ea9, 72391957-06b9-4e0c-877d-cf227df307e8

```json
{
  "rows": [
    {
      "request": "GET /api/health",
      "status": 200,
      "expected": 200,
      "body_keys": [
        "environment",
        "schema_version",
        "status"
      ],
      "cid": "3efe88d9-db70-4fc5-b8fe-b4b2d1c7a9a8"
    },
    {
      "request": "GET /api/auth/me",
      "status": 200,
      "expected": 200,
      "body_keys": [
        "deletion_cancelled",
        "display_name",
        "email",
        "feature_flags",
        "id"
      ],
      "cid": "cd43a17c-82b4-4869-b3ab-855f66c173f7"
    },
    {
      "request": "GET /api/tasks",
      "status": 200,
      "expected": 200,
      "body_keys": [
        "counts_by_state",
        "has_more",
        "items",
        "next_cursor"
      ],
      "cid": "bac891fa-b5d9-487d-a50c-591b8fbed539"
    },
    {
      "request": "GET /api/tasks?state=next",
      "status": 200,
      "expected": 200,
      "body_keys": [
        "counts_by_state",
        "has_more",
        "items",
        "next_cursor"
      ],
      "cid": "6e0a5359-e28a-4a5d-88b1-1d9e6f51afc3"
    },
    {
      "request": "GET /api/projects",
      "status": 200,
      "expected": 200,
      "body_keys": "list",
      "cid": "1c5886ea-b689-42bb-8d50-9bdd1608e2ad"
    },
    {
      "request": "GET /api/tags",
      "status": 200,
      "expected": 200,
      "body_keys": "list",
      "cid": "f5a5820f-f12b-43a3-955c-3956f3ebbfa5"
    },
    {
      "request": "GET /api/review/state",
      "status": 200,
      "expected": 200,
      "body_keys": [
        "counts",
        "explainer_seen",
        "grace_until",
        "last_counted_review",
        "last_counted_review_at",
        "next_review_at",
        "open_session",
        "receipts",
        "restart_mode",
        "server_now",
        "settings",
        "unseen_parks"
      ],
      "cid": "8f341a82-2ddf-42b6-b2e4-e0cb6a8eaea3"
    },
    {
      "request": "GET /api/sync/v1/capabilities?scope_id=",
      "status": 200,
      "expected": 200,
      "body_keys": [
        "command_versions",
        "correlation_id",
        "feed_generation",
        "limits",
        "projection_schema_version",
        "protocol_versions",
        "recovery",
        "rule_version",
        "scope_enabled",
        "scope_id",
        "server_generation",
        "server_now"
      ],
      "cid": "9c5ba90a-a8fd-44f2-9c9c-5c6eb34de3fb"
    },
    {
      "request": "GET /api/tasks/not-a-task",
      "status": 404,
      "expected": 404,
      "body_keys": [
        "detail",
        "message",
        "reference_id"
      ],
      "cid": "3a7a8f01-f5cd-45f1-949b-cad3f274b033"
    },
    {
      "request": "GET /api/tasks",
      "status": 401,
      "expected": 401,
      "body_keys": [
        "detail",
        "message",
        "reference_id"
      ],
      "cid": "75d1e3c8-a18b-493e-b0fe-9c73753bcfdb"
    },
    {
      "request": "stale revision write",
      "status": 409,
      "expected": 409,
      "cid": "e5fc2d7d-1f37-4bb3-a4ae-7780730dc411"
    },
    {
      "request": "empty title write",
      "status": 422,
      "expected": 422,
      "cid": "0bc7db1d-445d-4be6-bc22-d78610a26ea9"
    },
    {
      "request": "missing Idempotency-Key write",
      "status": 400,
      "expected": 400,
      "cid": "72391957-06b9-4e0c-877d-cf227df307e8"
    }
  ],
  "shape_note": "key lists are response top-level keys"
}
```

### Q12 user recovery - NOT_AUTOMATED

Reason: needs human participants and VoiceOver

## S2 Rust real-backend replay

Revision cf28db8d, `BB_REQUIRE_BACKEND=1 cargo test -p bb-client --test protocol_faults --test e2e_backend --test hints_backend -- --include-ignored` on MacBook Air M4 (not a reference device), local backend. Result: 25 passed, 0 failed, 0 ignored (protocol_faults 15, e2e_backend 7, hints_backend 3). A precondition for the pilot, not a substitute for any apple-pilot.md row.

- `e2e_026_fr_004_a_web_write_is_pulled_and_the_local_query_sees_it` — PASS
- `e2e_026_fr_007_a_conflict_the_feed_reveals_holds_the_edit_back_as_an_issue` — PASS
- `e2e_026_fr_007_a_conflict_the_server_decides_becomes_an_issue_not_data_loss` — PASS
- `e2e_026_fr_006_an_oversized_transaction_arrives_whole_through_the_transfer_path` — PASS
- `e2e_026_fr_010_reset_required_recovers_through_a_snapshot_and_keeps_pending_work` — PASS
- `e2e_026_fr_001_local_commands_reach_the_real_server_and_receipts_replay` — PASS
- `e2e_026_fr_003_the_first_sign_in_merge_reaches_the_real_server_once` — PASS
- `hints_026_fr_011_a_refused_stream_wakes_nothing_and_backs_off` — PASS
- `hints_026_fr_004_the_real_stream_wakes_on_committed_writes_only` — PASS
- `hints_026_sc_004_real_hints_wake_pulls_without_moving_the_poll_deadline` — PASS
- `faults_026_fr_004_a_replayed_feed_page_changes_nothing_and_the_next_pull_converges` — PASS
- `faults_026_fr_005_a_command_stuck_unknown_blocks_only_its_dependants` — PASS
- `faults_026_fr_005_a_dependent_that_overtakes_its_create_is_not_applied_early` — PASS
- `faults_026_fr_005_a_lost_ack_then_a_crash_settles_by_receipt_without_a_second_effect` — PASS
- `faults_026_fr_005_a_snapshot_that_expires_mid_bootstrap_restarts_without_a_partial_base` — PASS
- `faults_026_fr_005_duplicate_delivery_of_a_command_chain_takes_effect_once` — PASS
- `faults_026_fr_006_lost_transfer_pages_are_refetched_and_the_transaction_applies_once` — PASS
- `faults_026_fr_010_a_generation_change_with_an_active_epoch_closes_it_instead_of_looping` — PASS
- `faults_026_fr_010_a_restore_that_forgot_the_device_epoch_does_not_block_new_work` — PASS
- `faults_026_fr_010_a_server_rolled_back_to_a_backup_is_rebuilt_from_a_snapshot` — PASS
- `faults_026_fr_011_an_epoch_closed_mid_send_holds_the_command_and_new_work_proceeds` — PASS
- `faults_026_sc_001_two_devices_with_lost_and_duplicated_deliveries_converge` — PASS
- `faults_026_sc_002_a_crash_between_the_local_commit_and_the_send_loses_nothing` — PASS
- `faults_026_sc_002_a_lost_smart_add_ack_survives_a_rename_and_24_hours` — PASS
- `faults_026_sc_004_a_lost_hint_is_covered_by_the_poll_within_sixty_seconds` — PASS

## S3 Swift driver

Automated rehearsal (headless Swift driver), not reference-device evidence. Sources: `ios/BrainBuddyKit/Tests/BrainBuddyWorkspaceTests/Rehearsal`, `macos/Tests/BrainBuddyMacTests/MacRehearsalTests.swift`.

| Target | Scenario | Verdict | Config | Observed | Correlation IDs | Note |
| --- | --- | --- | --- | --- | --- | --- |
| local | Mac-host Mac launch: WorkspaceHost selection, sign-in and Rust host against a local backend | PASS | debug | clientIdentity=brainbuddy-macos; pendingAfterSync=0; syncStatus=idle(lastSyncedAt: Optional(2026-10-14 01:08:17 +0000)) | fc091018-e3ce-4cd4-b314-61a654524514 |  |
| local | Q01 offline capture, kill/reopen, converge once | PASS | debug | accountlessRequests=0; macCounts=oat=1 plumber=1; pendingAfterReopen=4; pendingWhileOffline=4; serverCounts=oat=1 plumber=1 stale=0; serverStates=["buy oat milk=inbox", "call plumber=someday"] | f206ee70-433b-4786-9ba8-dcdd7ff84b99 |  |
| local | Q01-device Q01 on an iPhone and a Mac with real airplane mode and process kill | NOT_AUTOMATED | - |  |  | Offline is simulated by the host's network flag and a refusing transport, and the kill by closing and reopening the runtime; a real device kill, airplane mode and the second physical Mac are reference-device work. |
| local | Q01b capture into Next reaches the server | FAIL | debug | serverState=absent; settleFailed.phone=status=failing(message: "Syncing stopped. Your changes are saved on this device.", referenceID: Optional("INVALID_REQUEST"), lastSyncedAt: nil) pending=1 issues=0 transportUnavailable=false events=[/capabilities sent:200x37,/changes sent:200x37,/commands sent:422 INVALID_REQUESTx37,/commands/a8550ff1-7ed1-4676-a730-dc1faa71e7b5 sent:200x36,/devices sent:200x1,/snapshots sent:200x1,/snapshots/f19114f9-6a7d-4568-aa74-d7b4771a432e sent:200x1]; settled=false | bc641c48-a2c7-4b7c-96d1-e51af4c337bf, 7e80502a-a4c7-461e-b217-239fb6c45085, c46f76ca-a3f6-46b7-9952-e0343b8237e7 | KNOWN DEFECT: task.smart_add into Next carries new_formulation_id=null while the review is hidden; sync-v1 answers 422 INVALID_REQUEST, the queue wedges (status failing, no issue) FAILED: a task captured into Next did not reach the server |
| local | Q02 concurrent edits, conflict issue, stale resolve | PASS | debug | Q02a.bothVersionsAvailable=true; Q02a.issueCount=1; Q02a.issueReason=REVISION_CONFLICT; Q02a.unrelatedSynced=true; Q02b.bothVersionsAvailable=true; Q02b.issueCount=1; Q02b.issueReason=REVISION_CONFLICT; Q02b.unrelatedSynced=true; freshResolve=resolved; staleResolve=changedAgain, current=true | 914123b0-312f-4596-a215-dd0bef3e0b7a |  |
| local | Q02-tag-and-descendants delete/edit of a Tag; blocked descendants (preserve, reapprove, discard); interrupted choices | NOT_AUTOMATED | - |  |  | Needs descendant/Tag fixtures and the sheet's discard confirmation; the shipped Swift and Rust unit suites cover the decisions, the rehearsal drives only the single-task conflict. |
| local | Q03 client-side delivery faults, no duplicate effect | PASS | debug | crashAfterCommit=faultFired=true server=1 pending=0; macCounts=1/1/1/1; requestDropped=events=2 server=1; responseLost=dropped=1 sentAfter=2 server=1 | 84653e4f-c8ac-40be-8ee7-43ff41745b79 |  |
| local | Q03-hints Q03 hint-only fault: drop the hint, retry retired-version envelopes, reorder ACK/feed | NOT_AUTOMATED | - |  |  | The wrapper faults the request/response transport; the hint stream and server-side reordering are covered by the bb-client and backend suites. |
| local | Q04 Q04 reset with live edits: expired cursor, snapshot paging while capturing, lost registration ACK | NOT_AUTOMATED | - |  |  | Needs server-side cursor expiry and oversized atomic operations (BB_E2E_PAGE_LIMITS); the bb-client e2e suite drives these, not the Swift host. |
| local | Q05 A to B switch isolation | PASS | debug | aServer=mine=1 pending=0 inflight=0 leakedB=0; bServer=B=1 leakedA=0; localAfterSignOut=0; reauthShows=mine=true B=false | fc805a1d-40d3-4b7b-9a26-e540d686787f |  |
| local | Q05-ids identical 404 for unknown vs foreign scope/device/snapshot/transfer IDs, including SSE registration | NOT_AUTOMATED | - |  |  | Server-side oracle assertions (backend and bb-client suites); the Swift driver only exercises the client-visible isolation. |
| local | Q06-faults low disk and a competing widget writer during the import | NOT_AUTOMATED | debug |  |  | Needs a full volume and a second process holding the document lock mid-import; covered by the kit's RustStoreImporter tests and bb-client import.rs, not driven from this headless run. |
| local | Q06-import legacy-populated and legacy-awkward import, field by field | PASS | debug | legacy-awkward.projects=expected=5 actual=5; legacy-awkward.tags=expected=3 actual=3; legacy-awkward.taskMismatches=missing=0 extra=0; legacy-awkward.tasks=expected=8 actual=8; legacy-populated.projects=expected=6 actual=6; legacy-populated.tags=expected=3 actual=3; legacy-populated.taskMismatches=missing=0 extra=0; legacy-populated.tasks=expected=18 actual=18 |  |  |
| local | Q06-merge first-sign-in merge into a populated account | PASS | debug | localBeforeMerge=3; serverCounts=1/1/1/1; serverCountsAfterRelaunch=1/1/1/1; states=inbox,inbox,inbox,someday | b31c81e3-6640-4bfa-b588-784e5fbcf0f1 |  |
| local | Q06-unreadable legacy-corrupt and legacy-newer: failure leaves the original intact | PASS | debug | legacy-corrupt.phase=ready; legacy-corrupt.tasksShown=0; legacy-newer.phase=ready; legacy-newer.tasksShown=0 |  |  |
| local | Q07 Q07 parity and writers across Rust, PyO3 and Swift; every command-catalog writer | NOT_AUTOMATED | - |  |  | Parity vectors and writer coverage belong to the Rust, backend and kit parity suites. |
| local | Q08 Q08 jobs and restore: worker lease expiry, consistent backup restore, fencing | NOT_AUTOMATED | - |  |  | Server-side job and restore drills; no client involvement. |
| local | Q09 Q09 AI: suitable/absent/failed local model, consent, cancel, kill/reopen mid-request | NOT_AUTOMATED | - |  |  | AI paths are out of scope for the free rehearsal (no provider calls); only on-device availability is probed on the Mac. |
| local | Q09-probe on-device model availability (no request) | PASS | debug | systemLanguageModel=unavailable: appleIntelligenceNotEnabled |  | Availability only: no prompt was sent. Suitable/absent/failed local-model paths of Q09 need a reference device. |
| local | Q10 Q10 retention: 24-hour response and seven-day Review expiry, export, purge | NOT_AUTOMATED | - |  |  | Needs controlled server time and the retention workers; backend suites. |
| local | Q11 Q11 web regression through unchanged public routes | NOT_AUTOMATED | - |  |  | The web client and its Playwright suites; not an Apple-driver concern. |
| local | Q12 waiting, failure, conflict and rebuild states on the Workspace model | FAIL | debug | Q12c.bothVersionsAvailable=true; Q12c.issueCount=1; Q12c.issueReason=REVISION_CONFLICT; Q12c.unrelatedSynced=true; conflictIssueCount=1; conflictLine=1 change couldn't sync; failureLine=Synced just now; failureStatus=failing(message: "Syncing stopped. Your changes are saved on this device.", referenceID: Optional("INVALID_REQUEST"), la; rebuildInterrupted=failed(referenceID: Optional("OFFLINE")) recovery=failed(referenceID: Optional("OFFLINE")); rebuildResumed=rebuilt recovery=idle; waitingLine=Offline · 1 change waiting; waitingStatus=idle(lastSyncedAt: Optional(2026-10-14 01:07:51 +0000)) | 19f28d6a-48b1-4bf3-be17-75079eda97da | FAILED: the status line does not show the persistent failure (reads: Synced just now) |
| local | Q12-people keyboard/VoiceOver reach, representative-user comprehension, timing comparison against M-/D- states | NOT_AUTOMATED | - |  |  | Human judgement on a reference device (SC-008); this driver asserts model state only. |
| local | SC-003 durable local success latency, 10k-task store | FAIL | release | afterSaveListQueryP50ms=237.5; afterSaveStatusRefreshP50ms=0.3; build=release build; failures=0; fixtureTasks=10000; fixtureTasksShown=inbox=200 (first page); hardware=Apple M4, 10 cores, 16 GiB: indicative only, not a reference device; importAndOpenSeconds=3.9; lowPowerMode=false; operations=1000; pendingAtEnd=1300; pendingAtStart=100; perRunP95ms=322.1 / 377.0 / 447.9 / 517.1 / 595.0; pooledMaxMs=628.7; pooledP50ms=395.9; pooledP95ms=560.4; residentMB=179; thermalState=0 |  | FAILED: pooled p95 560.350375 ms exceeds 50 ms |
| local | SC-003-stall no main-thread stall >= 100 ms while scrolling/editing during background replay | NOT_AUTOMATED | - |  |  | Needs the UI run loop on a reference device with Instruments; the headless driver has no scrolling view. |
| local | SC-004 two-device convergence over SSE | PASS | debug | batches=100; maxS=1.513; method=writer commit seen as pending==0 (polled ~5 ms), reader shows title; one process clock; loopback without RTT shaping; the final writer is the other device in this process, not a separate writer process; p50s=0.196; p95s=0.256; timeouts=0 | b32c80e1-fde8-4ad3-9756-8542de6c8d67 |  |
| local | SC-004-fallback all hints dropped: poll starts <= 30 s apart, update visible within 60 s; RTT <= 100 ms shaping; final writer in a separate server process | NOT_AUTOMATED | - |  |  | The wrapper faults the request/response transport, not the hint stream, and the harness has no network shaper; the bb-client hint tests cover the 30 s poll fallback. |

## S4 iOS Simulator UI

XCUITest drives the real app on an iOS Simulator against a **local** backend only (no deployed server,
no paid provider, no `/verify-live`). Synthetic accounts A and B (`rehearsal-a@example.com`, local-only
passwords in `scripts/rehearsal/ui_backend.py`), a throw-away data directory, and the backend's
deterministic review navigator (`BRAIN_BUDDY_REVIEW_NAVIGATOR_PROVIDER=deterministic`, test environment).

### Run identity

| Field | Value |
|---|---|
| Date | 2026-10-14 (local time) |
| Source | worktree on top of `cf28db8d` plus the uncommitted S4 files (no SHA of its own) |
| Simulator | iPhone 17, iOS 26.5 (Simulator, arm64, Debug, ad-hoc signed: `CODE_SIGN_IDENTITY=-`) |
| Runtime | Rust runtime reached the supported way: legacy sign-in, then `-BBRustRuntimePilot YES` (see Finding 1) |
| Server | `app.main` in `BRAIN_BUDDY_ENV=test`, `rust_core_sync` and `weekly_review` ON, behind a fault proxy |
| Rust bridge | `BB_APPLE_TARGETS=aarch64-apple-ios-sim sh ios/scripts/build-rust-bridge.sh apple` with toolchain 1.99.0 |
| Result | 12 test methods; 9 passed, 3 failed (two timing flakes and one test that raced the on-device model, see "Reliability") |

### How to run

```bash
BB_APPLE_TARGETS=aarch64-apple-ios-sim RUSTUP_TOOLCHAIN=1.99.0-aarch64-apple-darwin \
  sh ios/scripts/build-rust-bridge.sh apple                     # once; arm64 simulator slice only
BB_BACKEND_PYTHON=<venv python 3.14 with the backend deps and bb_core> \
  sh scripts/rehearsal/run_ios_ui.sh "iPhone 17"
```

Output goes to `.rehearsal-build/out/`: `results.tsv` (one line per item), `screens/`, `xcodebuild.log`,
`backend.log`. The script starts the backend (`scripts/rehearsal/ui_backend.py`: proxy on port P, server on
P+1, control on P+2), uninstalls the app between its two phases, and runs the `BrainBuddyRehearsal` scheme
(target `BrainBuddyUITests`, `ios/BrainBuddyUITests/`). The `BrainBuddy` scheme and CI are unchanged;
`xcodebuild build -scheme BrainBuddy` for the simulator still succeeds (arm64 only, because the bridge
above has only the arm64 simulator slice).

The server address is typed in the sign-in sheet (Advanced) as `http://localhost:18700/api`. A literal
`127.0.0.1` is refused by ATS and by the app's own check; `localhost` works.

### Results by item

PASS = observed as stated. FAIL = checked and not as expected. FINDING = reproduced a defect.
NOT_AUTOMATED = not driven, reason given. "Row" is the row of `apple-ux.md`.

| Item | Row / source | Result | What was observed |
|---|---|---|---|
| Pilot switch, fresh install | pilot | PASS | `-BBRustRuntimePilot YES`: Settings > Pilot footer "This device uses the shared runtime. Your tasks were carried over once."; switch locked on |
| Legacy sign-in, then the switch | pilot | PASS | Signed in on the legacy runtime, relaunched with the switch: shared runtime selected, account A still linked, the carried-over task is on the server |
| Sign in A on a fresh Rust-selected install | pilot | **FINDING 1** | Sign-in is refused: "This account change isn't available yet. Your work is kept." |
| Create, edit, complete | pilot | PASS | Capture, a title edit and Complete all reached the server over REST (`Rehearsal alpha` > `Rehearsal alpha v2` > completed) |
| 1 Fully synced | UX-01 | PASS | "Synced just now", Waiting to sync "Nothing" (legacy and Rust runtime) |
| 2 Account-less | UX-02 | PASS (partly) | Inbox header "1 open task · On this iPhone". No "Sign in to sync" in that line; Settings footer says "Sign in to sync with Brain Buddy on the web." |
| 3 Offline, three edits, relaunch | UX-03 | PASS (partly) | Header "5 open tasks · Offline — 3 changes waiting", unchanged after a relaunch with the server still down; replay after reconnect: all three tasks once each. **Differs:** Settings > Sync said "Synced 1 min ago · 3 changes waiting" at the same time, "Sync now" enabled with no "off" explanation, and the "Your changes are saved on this device." line was not seen (Finding 3) |
| 4 Online, changes not yet acknowledged | UX-04 | NOT_AUTOMATED | Not driven. The Settings text above matches row 4's wording but was seen while offline |
| 5 One change rejected | UX-05 | PASS (as a conflict) | Settings > Sync "1 change couldn't sync, Other changes synced. This change is saved here."; Sync issues row reachable. Produced by a same-title edit, not by a server rejection |
| 6 Session expired | UX-06 | PASS | Proxy answering 401: status "Sign in again to sync" (Finding 2 is what happens next) |
| 7 Store from a newer app | UX-07 | NOT_AUTOMATED | Needs a store written by a newer build |
| 8 Two-version conflict | UX-08 | PASS | "This item changed on your account after you edited it. Both versions are saved."; "Your saved edit" `title: Conflict base phone`, "Current account version" `title: Conflict base laptop`, reference ID; "Apply choice" disabled until "Use my version" / "Use account version" is chosen; applying stored the chosen title once |
| 9 Task changed again | UX-09 | NOT_AUTOMATED | Needs a second server edit while the detail is open |
| 10 Tag deleted elsewhere | UX-10 | NOT_AUTOMATED | Not driven |
| 11 Later actions | UX-11 | NOT_AUTOMATED | Needs queued dependent edits |
| 12 Discard confirmation | UX-12 | NOT_AUTOMATED | Same |
| 13 Force-quit with an unsent draft | UX-13 | NOT_AUTOMATED | Not driven |
| 14 VoiceOver, Dynamic Type, Reduce Motion | a11y | NOT_AUTOMATED | Judgement on a device |
| 15 Sync recovery row / rebuild | M-03 | NOT_AUTOMATED | The row appears only for a newer store or a failed rebuild; no way to cause either from outside |
| Q12 user recovery | quickstart | partly | Waiting (3), persistent failure (5) and a two-version conflict (8) shown and applied. Blocked-descendant decisions, an interrupted rebuild, a representative user and keyboard/VoiceOver: NOT_AUTOMATED |
| Q09 sheet copy | iphone-ai | PASS | First open: "Brain Buddy tries a model on this device first. Task content stays here unless you allow cloud suggestions." with Request suggestions / Continue without AI |
| Q09 local request | iphone-ai | PASS | "Preparing suggestions…" with Cancel; then "Review suggestion / Nothing changes until you apply." with proposals; **0 requests reached the navigator**; the task on the server is unchanged; closing the sheet changes nothing. The model is the host Mac's Apple Intelligence on the Simulator, not the device |
| Q09 cancel before send | iphone-ai | PASS in 2 of 3 runs | "Suggestions cancelled" / "Nothing was sent."; Request again offered; 0 navigator requests. FAIL in the last run: the model answered first (race) |
| Q09 consent prompt, decline, accept, proposal | ai-consent | NOT_AUTOMATED | The sheet reaches the cloud only after the on-device attempt fails; the host model answers, and the failure cannot be forced without changing the app |
| Q09 clarifying question (`navigator-test:question`) | iphone-ai | NOT_AUTOMATED | Same reason (the backend side is ready) |
| Q09 cancel after send | iphone-ai | NOT_AUTOMATED | Same reason |
| Q09 kill, relaunch, "Suggestions were interrupted" | iphone-ai | INCONCLUSIVE | Killed while "Preparing suggestions…" was showing (1 s): the reopened sheet showed the initial state, not the interrupted one. In the other run the model had answered before the kill. See Finding 4. The test now records NOT_AUTOMATED when the request is no longer live |
| Q09 no automatic resend | iphone-ai | INCONCLUSIVE | Depends on the item above; 0 navigator requests were seen throughout |
| Q09 Apply suggestion, undo | iphone-ai | NOT_AUTOMATED | Would rewrite the review task; covered by `ReviewSuggestionModelTests` |
| Real on-device Apple Intelligence; availability states | iphone-ai | NOT_AUTOMATED | Needs the reference iPhone |
| VoiceOver announcements, Dynamic Type AX5, 44 pt targets | iphone-ai | NOT_AUTOMATED | Judgement on a device |

### Findings

1. **Sign-in is impossible on an install that is already on the Rust runtime.** `SignInSheet` calls
   `Workspace.beginSignIn` / `completeSignIn`, and both begin with `guard !isRustSelected else { throw … "This account
   change isn't available yet. Your work is kept." }` (`Workspace.swift`). Only the older `Workspace.signIn(serverURL:email:password:)`
   has a Rust path (`signInRust`), and nothing in the app calls it. Repro: fresh install, launch with
   `-BBRustRuntimePilot YES`, Settings > Sign in > Advanced > server `http://localhost:<port>/api` > Use your password
   > correct credentials > Sign in. Screenshot `rehearsal-screens/s4-02-pilot-fresh-signin-refused.png`. The only working order is
   legacy sign-in first, switch second, which is how the rest of this run proceeds. A pilot tester on a fresh install cannot sign in.
2. **Renewing an expired session is expected to be refused for the same reason.** After the proxy's 401s the status reads "Sign in again to
   sync" and Settings offers "Sign in again", which opens the sheet. The password step could not be driven here (the field took no input
   under automation), so the refusal was not observed; by the code in Finding 1 it should be refused. Confirm by hand.
3. **Status disagreement while offline.** Server unreachable: the Inbox header said "Offline — 3 changes waiting", Settings > Sync said
   "Synced 1 min ago · 3 changes waiting" with "Sync now" enabled and no explanation (row 3 expects "Sync now explained as off" and the line
   "Your changes are saved on this device."). Repro: sign in, switch on the pilot, stop the server, capture three tasks, open Settings.
   Screenshot `s4-51-offline-settings.png`.
4. **Possible: a request killed mid-flight is not shown as interrupted.** Start "Request suggestions", kill the app while "Preparing
   suggestions…" shows (about 1 s), relaunch, open the same decision card and "Suggest new wording": the sheet shows the initial
   "Suggestions" state, where `ReviewSuggestionModel.recover()` should give "Suggestions were interrupted". Seen once; the other attempts
   lost the race to the model. Not confirmed; the request was local (nothing transmitted), which may be intended.
5. **Fast typing into the capture field loses characters on the Rust runtime, not on the legacy one.** `typeText("Rehearsal fast rust")`
   produced titles such as "Rl st" / "Rl f" on the Rust runtime; the same input on the legacy runtime (`TYPING-LEGACY`) arrived intact,
   and keystroke-by-keystroke typing is intact on both. Screenshot `s4-45-fast-typing-rust.png`. Could be a Simulator/XCUITest
   artefact of a slower per-keystroke path; type quickly on a device to settle it. The suite types slowly everywhere it needs an exact title.

### Reliability of this run

Three full runs were made. The same 9 methods passed in all of them. In the last (the run the table and screenshots come from)
`testS4_50` failed its final step (Settings status did not read "Synced" within 30 s after the queue drained; it did in the two earlier
runs) and `testS4_70` failed (cancel raced the on-device model; it passed in the two earlier runs); `testS4_80` could not kill a live
request because the warm host model answered first. These are timing-dependent, not deterministic, and the cloud half of Q09 is
untested. Do not read the table as a green run.

### Screenshots

`rehearsal-screens/` (24 files, scaled to 520 px wide, synthetic accounts only): `s4-01`/`s4-02` fresh pilot and the sign-in refusal,
`s4-10`/`s4-20`/`s4-30` account-less, signed in, shared runtime selected, `s4-40`-`s4-42` create/edit/complete, `s4-45` typing,
`s4-50`-`s4-52` offline, `s4-55`-`s4-59` conflict list, detail, choice and result, `s4-60`-`s4-63` decision card and suggestion sheet,
`s4-70` cancel, `s4-80` request in flight, `s4-90` session expired.

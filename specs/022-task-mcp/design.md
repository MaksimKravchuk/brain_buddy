# MCP interaction states

The interaction surface is the tool schema and structured response. The existing
generic Admin Portal lists `task_mcp` with its unchanged OFF/selected-users/ON
controls. The Privacy Policy's managed-flag count becomes six; no navigation or
native-client interaction changes.

| State | Trigger | Observable result |
| --- | --- | --- |
| D-01 OFF | Exposure setting absent/disabled | Endpoint 404; existing task API works |
| D-02 Unauthorized | Missing/invalid/expired/revoked bearer; cookie only | 401 with Bearer challenge |
| D-10 Audience excluded | Valid bearer outside task_mcp cohort, flag OFF or degraded store | 403 before discovery/commands; task data preserved |
| D-03 Discovery | Authenticated initialization/tools list | Four tools and read/write/destructive hints |
| D-04 Read | Search/list/get, including empty and paginated lists | Native structured task projection and cursor |
| D-05 Create | Valid title/key and native optional fields | Inbox by default; canonical task response |
| D-06 Remove | Open task/current revision/key | Cancelled response; absent from active lists |
| D-07 Reconcile | Stale revision or changed payload/same key | Tool error; requested change not applied |
| D-08 Retry | Identical key and arguments after lost response | Stored response, no second mutation |
| D-09 Invalid/failed | Validation, transport rejection or storage failure | Safe tool/HTTP error with correlated operation log |

Clients use the tool descriptions to find IDs before deletion and preserve retry
identity. Soft deletion is explicit in discovery and user documentation; recovery
uses the already-existing reopen command.

# MCP interaction states

The interaction surface is the tool schema and structured response; no rendered
screens, navigation or native clients change.

| State | Trigger | Observable result |
| --- | --- | --- |
| D-01 OFF | Exposure setting absent/disabled | Endpoint 404; existing task API works |
| D-02 Unauthorized | Missing/invalid/expired/revoked bearer; cookie only | 401 with Bearer challenge |
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

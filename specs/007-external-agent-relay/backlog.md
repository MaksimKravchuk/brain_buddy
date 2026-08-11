# External-agent relay v1 backlog

These items are intentionally outside the minimum web+iOS production slice. None may be used to defer a release-critical defect in connection setup, hand-off review, owner-scoped run state, blocked replies, security, or honest completion reporting.

Connection update is not backlog: FR-001 requires the connection-update endpoint and its web/iOS UI in the minimum production slice. The backlog contains only optional extensions beyond that required update flow.

- Connector-specific cancellation UX beyond capability-gated request cancellation.
- More reference connectors and provider-specific prompt optimization.
- Multi-agent fan-out, routing, delegation chains, and workflow builders.
- Agent marketplace, billing, quotas, and managed-agent hosting.
- Rich progress visualization when a connector supplies structured progress.
- Push notifications for blocked/completed runs; v1 shows state in the task.
- Long-term run analytics, quality scoring, and result acceptance automation.
- Connection templates, sharing, organization policy, and bulk administration.
- Extended device cleanup and account-deletion UX beyond current server-side cleanup.
- Draft hand-offs and reusable context bundles.

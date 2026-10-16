# Approved component snapshots

`CarryOnCatalogSnapshotTests` compares each catalog section, light and dark, with the
PNG of the same name here (2x, 390 pt wide). A PNG lands here only after it was
compared with the design canvas and approved.

To re-record after an approved change, on a Mac:

```bash
cd ios/BrainBuddyKit && CARRY_ON_SNAPSHOT_RECORD=1 swift test --filter CarryOnCatalogSnapshotTests
```

Without a Mac, a failing run prints each render as base64 between
`CARRY_ON_SNAPSHOT_BEGIN <name>` and `CARRY_ON_SNAPSHOT_END <name>` in the CI log.

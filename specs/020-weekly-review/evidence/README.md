# Feature 020 evidence

Evidence rule (constitution I; plan "Evidence rule"):

- Every screenshot, recording, trace or Allure attachment kept here or in a slice PR
  comes from a seeded synthetic account that uses the design's example data (the
  Playwright seed in `frontend/tests/e2e/weekly-review.spec.ts`). Never real account data.
- Results from the owner's real use (SC-001, SC-003, SC-004, SC-005) are recorded only
  as the numbers `python -m app.cli review-metrics` prints, with their sample sizes.
  Never titles, notes, reasons, summaries or ids.
- A file whose result cells say `PENDING` is a template. It is not evidence until someone
  runs the steps and fills the cells in.

| file | what it holds |
|---|---|
| `manual-ios-increment1.md`, `manual-ios-increment3.md` | manual iOS device runs (slices PR-04, PR-12) |
| `macos-host-run.md` | the macOS-host run for 020-FR-041 (slice PR-06); `make check-specs` requires the file |
| `real-use-readout.md` | the weekly real-use numbers |
| `rollout-decisions.md` | the owner's flag stages and the `BBWeeklyReviewLocal` decision |

# The aggregate Allure quality gate

The `allure-report` job in `.github/workflows/ci.yml` used to publish the
aggregate report without ever judging it: a failed test could reach the artifact
while the run stayed green. Its last step now runs Allure Report 3's native
quality gate, so the report is graded.

## The rule

`allurerc.mjs` declares one rule — `maxFailures: 0`. Any failed or broken result
in the aggregate fails the job, and `full-ci` with it.

That file is **ASK class** (`scripts/classify_path_risk.py`): it decides what
"passing" means, so a change to it cannot land through automatic trunk
promotion. The response to a failing gate is to fix the test, never to raise the
number.

The CLI is invoked with an explicit `--config ../allurerc.mjs`. Allure's own
defaults declare no quality gate at all, so an implicit lookup would turn a
deleted config into a silent pass. Gate-replacing flags (`--max-failures`,
`--known-issues`, `--rerun`, …) are rejected by
`scripts/validate_ci_artifacts.py workflow`, because passing one discards the
config's ruleset rather than adjusting it.

## The two report artifacts

| Artifact | What it is | How to read it |
| --- | --- | --- |
| `allure-report-single-file` | one self-contained HTML file | unzip GitHub's artifact envelope, open the single `index.html` — no local server |
| `allure-report-html` | the complete multi-file report, including attachments | unzip and serve the directory locally |

Both are uploaded, and the pull-request comment is posted, **before** the
verdict step and with `if: always()`. A red gate therefore still leaves behind
the report that explains it. Retention is unchanged: 7 days on a pull request,
30 days on a push.

## The canary

`scripts/allure_quality_gate_selftest.sh` runs the same CLI and the same
`allurerc.mjs` over two committed fixtures in
`scripts/fixtures/allure-quality-gate/` that differ in exactly one `status`
field, and asserts the clean one exits 0 and the dirty one does not. It runs in
CI immediately before the verdict, so every run re-earns the right to believe
that verdict. Run it locally the same way:

```bash
cd frontend && npm ci      # once, to install the Allure 3 CLI
./scripts/allure_quality_gate_selftest.sh
```

## Out of scope

Report hosting/history storage, rerun policy, environment labels, per-lane
evidence floors, freshness and duplicate detection. The gate judges the
aggregate this run produced; making a lane's *absence* detectable is a separate
problem and is not claimed here.

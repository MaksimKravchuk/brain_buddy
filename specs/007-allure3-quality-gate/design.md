# Design: Allure 3 aggregate Quality Gate and single-file report

## Screen and state inventory

**None.** This feature has no product UI, adds no screen, and changes no
existing one. Constitution Principle V requires that to be stated rather than
assumed, so it is stated here: the acceptance auditor should expect zero screens.

## The only human-facing surfaces

| # | Surface | State | Copy contract |
| --- | --- | --- | --- |
| 1 | Pull-request comment (updated in place, one per PR) | always posted, even when the gate is red | names both artifacts, marks `allure-report-single-file` as the starting point, says to unzip GitHub's envelope and open the single `index.html`, and states 7-day PR / 30-day push retention (007-FR-008) |
| 2 | The `allure-report` job log | green: silent · red: Allure prints which rule failed and by how much | the failure names `maxFailures`, so the reader is told the aggregate contained a failed or broken result |
| 3 | Canary log line | pass: one line · fail: an explicit "THE GATE IS BROKEN" warning not to trust the run's verdict | 007-FR-005 |

Accessibility is inherited: the comment is plain Markdown, and the reports are
Allure's own HTML output, which this feature does not restyle.

See [spec.md](spec.md) for the requirements these surfaces serve.

# CI timing and completeness

Compare merge-group runs using the same source inputs and a warm Rust bridge.
Measure from the CI run creation to the `Full CI` verdict, including the closing
Allure report; record queue wait separately. Job durations overlap, so their sum
is not the time a pull request waits. Keep test counts, coverage and mutation
scope alongside timings so a faster partial run cannot look like an improvement.


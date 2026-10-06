# BrainBuddySyncTests resources

Byte-identical copies of backend golden fixtures that the sync tests replay
against `BrainBuddyFakeServer` (spec 020, plan "Test strategy").

- `review_traces_tasks.json` arrives with slice PR-15 (tasks.md T086) and is
  replayed in Swift by PR-04 (tasks.md T173). Edit the canonical file in
  `backend/tests/fixtures/` and its copies in one commit; the drift guard in
  `backend/tests/test_review_formulation_vectors.py` fails otherwise.

`Package.swift` declares this directory as a `.copy` resource of the test
target, so the declaration holds before the trace copies arrive.

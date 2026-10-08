import BrainBuddyCore
import Foundation
import Testing

/// The golden run traces of slice PR-11 (`review_traces_runs.json`, a
/// byte-identical copy of `backend/tests/fixtures/review_traces_runs.json`)
/// replayed against `BrainBuddyFakeServer` with the recorded statuses and
/// responses, so the fake cannot drift from the backend on a review started
/// offline, replaced, moved on by two clients, retried after the 24 h
/// idempotency retention, and finished (tasks.md T136; 020-FR-029,
/// 020-SC-007). The replay is the one `ReviewTaskTraceReplayTests` runs.
@Suite("Review run trace replay (spec 020)")
struct ReviewTraceReplayTests {
    static let file = ReviewTaskTraceReplayTests.file("review_traces_runs")
    static let traces = ReviewTaskTraceReplayTests.traces(in: file)

    @Test("020-SC-007: the run trace file declares its schema and five traces naming feature-qualified ids")
    func traceFileDeclaresItsSchema() {
        #expect(Self.file["schema"]?.stringValue == "brainbuddy-review-traces/v1")
        #expect(Self.traces.map(\.id) == ["TR-R01", "TR-R02", "TR-R03", "TR-R04", "TR-R05"])
        for trace in Self.traces {
            #expect(trace.requirements.allSatisfy { $0.hasPrefix("020-") }, "\(trace.id) names a bare id")
        }
    }

    @Test(
        "020-FR-029 020-SC-007: each golden run trace replays against the fake server with the recorded statuses and responses",
        arguments: traces
    )
    func traceReplaysAgainstTheFakeServer(_ trace: ReviewTaskTraceReplayTests.Trace) throws {
        let replay = try Replay(trace)
        for (index, step) in trace.steps.enumerated() {
            replay.run(step, index: index)
        }
    }
}

import Testing

/// The pilot scenarios this driver cannot run, written into the result set with the reason, so the
/// evidence file never reads as if they had been rehearsed (quickstart.md Q01-Q12).
@Suite("Pilot rehearsal: scenarios not automated by this driver", .rehearsal)
struct RehearsalNotAutomatedTests {
    @Test("the not-automated scenarios are recorded with their reasons")
    func recordNotAutomated() {
        let rows: [(String, String, String)] = [
            ("Q01-device", "Q01 on an iPhone and a Mac with real airplane mode and process kill",
             "Offline is simulated by the host's network flag and a refusing transport, and the kill by closing and reopening the runtime; a real device kill, airplane mode and the second physical Mac are reference-device work."),
            ("Q03-hints", "Q03 hint-only fault: drop the hint, retry retired-version envelopes, reorder ACK/feed",
             "The wrapper faults the request/response transport; the hint stream and server-side reordering are covered by the bb-client and backend suites."),
            ("Q04", "Q04 reset with live edits: expired cursor, snapshot paging while capturing, lost registration ACK",
             "Needs server-side cursor expiry and oversized atomic operations (BB_E2E_PAGE_LIMITS); the bb-client e2e suite drives these, not the Swift host."),
            ("Q07", "Q07 parity and writers across Rust, PyO3 and Swift; every command-catalog writer",
             "Parity vectors and writer coverage belong to the Rust, backend and kit parity suites."),
            ("Q08", "Q08 jobs and restore: worker lease expiry, consistent backup restore, fencing",
             "Server-side job and restore drills; no client involvement."),
            ("Q09", "Q09 AI: suitable/absent/failed local model, consent, cancel, kill/reopen mid-request",
             "AI paths are out of scope for the free rehearsal (no provider calls); only on-device availability is probed on the Mac."),
            ("Q10", "Q10 retention: 24-hour response and seven-day Review expiry, export, purge",
             "Needs controlled server time and the retention workers; backend suites."),
            ("Q11", "Q11 web regression through unchanged public routes",
             "The web client and its Playwright suites; not an Apple-driver concern."),
        ]
        for (id, title, reason) in rows { RehearsalReport.notAutomated(id, title, reason: reason) }
    }
}

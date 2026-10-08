import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("Sync activity indicator")
struct SyncActivityIndicatorTests {
    let t0 = Date(timeIntervalSince1970: 1_790_000_000)

    private func at(_ seconds: TimeInterval) -> Date { t0.addingTimeInterval(seconds) }

    /// Whether the indicator shows at each tenth of a second of `range`.
    private func visible(_ indicator: SyncActivityIndicator, from start: Double, to end: Double) -> [Double] {
        stride(from: start, through: end, by: 0.1).map { ($0 * 10).rounded() / 10 }.filter {
            indicator.isVisible(at: at($0))
        }
    }

    @Test("021-FR-013 a sync under a second shows nothing")
    func shortSyncIsInvisible() {
        var indicator = SyncActivityIndicator()
        indicator.started(at: at(0))
        #expect(indicator.isVisible(at: at(0.9)) == false)
        indicator.finished(at: at(0.9))
        #expect(visible(indicator, from: 0, to: 3).isEmpty)
        #expect(indicator.nextChange(after: at(0.9)) == nil)
    }

    @Test("021-FR-013 a sync of 1.1 s shows from the first second and for at least half a second")
    func longerSyncIsShownForAtLeastHalfASecond() {
        var indicator = SyncActivityIndicator()
        indicator.started(at: at(0))
        #expect(indicator.nextChange(after: at(0)) == at(1), "the app re-evaluates when it would appear")
        #expect(indicator.isVisible(at: at(0.99)) == false)
        #expect(indicator.isVisible(at: at(1.05)))
        indicator.finished(at: at(1.1))
        #expect(visible(indicator, from: 0, to: 3) == [1.0, 1.1, 1.2, 1.3, 1.4])
        #expect(indicator.nextChange(after: at(1.1)) == at(1.5), "it stays until half a second after it appeared")
        #expect(indicator.nextChange(after: at(1.5)) == nil)
    }

    @Test("021-FR-013 a long sync is shown until it ends")
    func longSyncIsShownUntilItEnds() {
        var indicator = SyncActivityIndicator()
        indicator.started(at: at(0))
        #expect(indicator.nextChange(after: at(2)) == nil, "nothing changes until it finishes")
        indicator.finished(at: at(4))
        #expect(indicator.isVisible(at: at(3.9)))
        #expect(indicator.isVisible(at: at(4)) == false)
    }

    @Test("021-FR-013 cycles back to back, or starting while it shows, make one unbroken span")
    func backToBackCyclesAreOneSpan() {
        var indicator = SyncActivityIndicator()
        indicator.started(at: at(0))
        indicator.finished(at: at(1.2))
        indicator.started(at: at(1.3))  // still showing (until 1.5): no flicker, however short the cycle
        indicator.finished(at: at(1.35))
        #expect(visible(indicator, from: 1, to: 3) == [1.0, 1.1, 1.2, 1.3, 1.4])
        indicator.started(at: at(1.4))
        indicator.finished(at: at(2.0))
        #expect(visible(indicator, from: 1, to: 3).last == 1.9)

        // A cycle that begins after it went away starts counting afresh.
        indicator.started(at: at(5))
        #expect(indicator.isVisible(at: at(5.5)) == false)
        indicator.finished(at: at(5.5))
        #expect(indicator.isVisible(at: at(5.6)) == false)
    }
}

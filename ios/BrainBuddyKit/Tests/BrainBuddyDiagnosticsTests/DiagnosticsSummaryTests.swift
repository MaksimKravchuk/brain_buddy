import BrainBuddyDiagnostics
import Foundation
import Testing

@Suite("DiagnosticsSummary")
struct DiagnosticsSummaryTests {
    let now = Date(timeIntervalSince1970: 100_000)

    func sample(secondsAgo: Double, seconds: Double = 10, cpu: Double, screen: String, thermal: ThermalLevel = .nominal)
        -> CPUSample
    {
        CPUSample(
            at: now.addingTimeInterval(-secondsAgo), seconds: seconds, cpuPercent: cpu, screen: screen,
            thermal: thermal, lowPowerMode: false)
    }

    @Test("Averages are weighted by each sample's length, per window and per screen")
    func weightedAverages() throws {
        let log = DiagnosticsLog(samples: [
            sample(secondsAgo: 300, seconds: 30, cpu: 10, screen: "inbox"),
            sample(secondsAgo: 200, seconds: 10, cpu: 90, screen: "inbox"),
            sample(secondsAgo: 100, seconds: 10, cpu: 50, screen: "task"),
        ])
        let summary = DiagnosticsSummary(log: log, now: now, windowSeconds: 3_600)

        #expect(summary.sampledSeconds == 50)
        // (10 × 30 + 90 × 10 + 50 × 10) / 50
        #expect(summary.averageCPUPercent == 34)
        #expect(summary.peak?.cpuPercent == 90)
        // inbox: (300 + 900) / 40 = 30; task: 50. Busiest first.
        let expected = [
            DiagnosticsSummary.ScreenLoad(screen: "task", averageCPUPercent: 50, sampledSeconds: 10),
            DiagnosticsSummary.ScreenLoad(screen: "inbox", averageCPUPercent: 30, sampledSeconds: 40),
        ]
        #expect(summary.byScreen == expected)
    }

    @Test("Only entries inside the window count")
    func window() {
        let log = DiagnosticsLog(
            samples: [
                sample(secondsAgo: 4_000, cpu: 99, screen: "inbox", thermal: .critical),
                sample(secondsAgo: 60, cpu: 5, screen: "today", thermal: .fair),
            ],
            thermalEvents: [
                ThermalEvent(at: now.addingTimeInterval(-5_000), level: .critical, screen: "inbox"),
                ThermalEvent(at: now.addingTimeInterval(-30), level: .serious, screen: "today"),
                ThermalEvent(at: now.addingTimeInterval(-20), level: .fair, screen: "today"),
            ])
        let summary = DiagnosticsSummary(log: log, now: now, windowSeconds: 3_600)

        #expect(summary.averageCPUPercent == 5)
        #expect(summary.peak?.screen == "today")
        #expect(summary.hottestThermal == .serious)
        #expect(summary.seriousThermalEvents == 1)
    }

    @Test("An empty window has no average, peak or thermal state")
    func empty() {
        let summary = DiagnosticsSummary(log: DiagnosticsLog(), now: now, windowSeconds: 3_600)
        #expect(summary.averageCPUPercent == nil)
        #expect(summary.peak == nil)
        #expect(summary.byScreen.isEmpty)
        #expect(summary.hottestThermal == nil)
        #expect(summary.seriousThermalEvents == 0)
    }
}

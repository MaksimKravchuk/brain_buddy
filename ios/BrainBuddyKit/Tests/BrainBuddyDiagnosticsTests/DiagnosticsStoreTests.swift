import BrainBuddyDiagnostics
import Foundation
import Testing

@Suite("DiagnosticsStore")
struct DiagnosticsStoreTests {
    let store = DiagnosticsStore(
        directory: FileManager.default.temporaryDirectory.appendingPathComponent("diagnostics-\(UUID().uuidString)"))

    @Test("The log round-trips; a missing or damaged file reads as an empty log")
    func logRoundTrip() throws {
        defer { try? store.clear() }
        #expect(store.loadLog() == DiagnosticsLog())

        var log = DiagnosticsLog()
        log.recordLaunch(at: Date(timeIntervalSince1970: 1_000))
        log.append(
            CPUSample(
                at: Date(timeIntervalSince1970: 1_010), seconds: 10, cpuPercent: 42.5, screen: "inbox",
                thermal: .serious, lowPowerMode: true))
        log.append(ThermalEvent(at: Date(timeIntervalSince1970: 1_020), level: .critical, screen: "capture"))
        try store.saveLog(log)
        #expect(store.loadLog() == log)

        try Data("not json".utf8).write(to: store.directory.appendingPathComponent("log.json"))
        #expect(store.loadLog() == DiagnosticsLog())
    }

    @Test("A report delivered twice is kept once; the oldest go beyond the limit")
    func reports() throws {
        defer { try? store.clear() }
        let first = Data(#"{"n":0}"#.utf8)
        try store.saveReport(first, kind: .metrics, periodEnd: Date(timeIntervalSince1970: 0))
        try store.saveReport(first, kind: .metrics, periodEnd: Date(timeIntervalSince1970: 0))
        #expect(store.reportCount(.metrics) == 1)
        // A different report ending in the same second is kept too.
        try store.saveReport(Data(#"{"n":-1}"#.utf8), kind: .metrics, periodEnd: Date(timeIntervalSince1970: 0.5))
        #expect(store.reportCount(.metrics) == 2)

        for day in 1...DiagnosticsStore.reportLimit {
            try store.saveReport(
                Data(#"{"n":\#(day)}"#.utf8), kind: .metrics, periodEnd: Date(timeIntervalSince1970: Double(day) * 86_400))
        }
        try store.saveReport(Data(#"{"d":1}"#.utf8), kind: .diagnostics, periodEnd: Date(timeIntervalSince1970: 5))

        #expect(store.reportCount(.metrics) == DiagnosticsStore.reportLimit)
        #expect(store.reportCount(.diagnostics) == 1)
        let reports = store.reports()
        // Oldest kept first (day 0 was dropped), metrics before diagnostics.
        #expect(reports.first == SystemReport(kind: .metrics, json: Data(#"{"n":1}"#.utf8)))
        #expect(reports.last == SystemReport(kind: .diagnostics, json: Data(#"{"d":1}"#.utf8)))
    }

    @Test("Clearing removes the log and every report")
    func clear() throws {
        try store.saveLog(DiagnosticsLog(launches: [Date(timeIntervalSince1970: 1)]))
        try store.saveReport(Data("{}".utf8), kind: .diagnostics, periodEnd: Date(timeIntervalSince1970: 1))
        try store.clear()

        #expect(store.loadLog().isEmpty)
        #expect(store.reports().isEmpty)
        try store.clear()  // nothing left to remove is fine
    }
}

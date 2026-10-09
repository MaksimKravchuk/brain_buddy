import BrainBuddyDiagnostics
import Foundation
import Testing

@Suite("DiagnosticsExport")
struct DiagnosticsExportTests {
    let now = Date(timeIntervalSince1970: 1_760_000_000)
    let device = DiagnosticsDeviceInfo(
        appVersion: "0.1.0 (412)", buildLabel: "main @ abc1234", osVersion: "iOS 26.1", deviceModel: "iPhone17,1",
        thermal: .fair, lowPowerMode: false)

    private struct NotAnObject: Error {}

    private func object(_ value: Any?) throws -> [String: Any] {
        guard let object = value as? [String: Any] else { throw NotAnObject() }
        return object
    }

    private func objects(_ value: Any?) throws -> [[String: Any]] {
        guard let objects = value as? [[String: Any]] else { throw NotAnObject() }
        return objects
    }

    @Test("One JSON file: summaries, raw entries and the system reports embedded as JSON")
    func shape() throws {
        var log = DiagnosticsLog()
        log.recordLaunch(at: now.addingTimeInterval(-7_200))
        log.append(
            CPUSample(
                at: now.addingTimeInterval(-5_000), seconds: 10, cpuPercent: 80, screen: "inbox", thermal: .serious,
                lowPowerMode: false))
        log.append(
            CPUSample(
                at: now.addingTimeInterval(-60), seconds: 10, cpuPercent: 4, screen: "today", thermal: .fair,
                lowPowerMode: false))
        log.append(ThermalEvent(at: now.addingTimeInterval(-5_000), level: .serious, screen: "inbox"))
        let reports = [
            SystemReport(kind: .metrics, json: Data(#"{"cpuMetrics":{"cumulativeCPUTime":"12 sec"}}"#.utf8)),
            SystemReport(kind: .diagnostics, json: Data("not json".utf8)),
        ]

        let data = try DiagnosticsExport.make(log: log, reports: reports, device: device, now: now)
        let export = try object(JSONSerialization.jsonObject(with: data))

        #expect(export["format"] as? String == DiagnosticsExport.format)
        #expect(try object(export["device"])["deviceModel"] as? String == "iPhone17,1")
        #expect(try objects(export["samples"]).count == 2)
        #expect(try objects(export["thermalEvents"]).count == 1)
        // The last hour sees only the recent sample; everything recorded sees both.
        #expect(try object(export["lastHour"])["averageCPUPercent"] as? Double == 4)
        let allRecorded = try object(export["allRecorded"])
        #expect(allRecorded["averageCPUPercent"] as? Double == 42)
        #expect(allRecorded["seriousThermalEvents"] as? Int == 1)

        let embedded = try objects(export["systemReports"])
        #expect(embedded.map { $0["kind"] as? String } == ["metrics", "diagnostics"])
        let cpuMetrics = try object(object(embedded[0]["payload"])["cpuMetrics"])
        #expect(cpuMetrics["cumulativeCPUTime"] as? String == "12 sec")
        // Kept as text rather than dropped.
        #expect(embedded[1]["payload"] as? String == "not json")
    }

    @Test("An empty log still exports")
    func emptyLog() throws {
        let data = try DiagnosticsExport.make(log: DiagnosticsLog(), reports: [], device: device, now: now)
        let export = try object(JSONSerialization.jsonObject(with: data))
        #expect(try objects(export["samples"]).isEmpty)
        #expect(try objects(export["systemReports"]).isEmpty)
    }

    @Test("The file is named after the export time in UTC")
    func fileName() {
        // 1_760_000_000 is 2025-10-09 08:53:20 UTC.
        #expect(DiagnosticsExport.fileName(for: now) == "BrainBuddy-diagnostics-20251009-085320.json")
    }
}

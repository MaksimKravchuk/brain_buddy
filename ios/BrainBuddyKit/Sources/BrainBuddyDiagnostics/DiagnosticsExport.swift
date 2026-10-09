import Foundation

/// What the export says about the build and the device, so a report can be
/// read without asking. No identifiers: the model is the hardware family
/// ("iPhone17,1"), not the device.
public struct DiagnosticsDeviceInfo: Codable, Sendable, Equatable {
    public var appVersion: String
    public var buildLabel: String?
    public var osVersion: String
    public var deviceModel: String
    public var thermal: ThermalLevel
    public var lowPowerMode: Bool

    public init(
        appVersion: String, buildLabel: String?, osVersion: String, deviceModel: String, thermal: ThermalLevel,
        lowPowerMode: Bool
    ) {
        self.appVersion = appVersion
        self.buildLabel = buildLabel
        self.osVersion = osVersion
        self.deviceModel = deviceModel
        self.thermal = thermal
        self.lowPowerMode = lowPowerMode
    }
}

/// The single JSON file the Performance screen shares: a summary first, then
/// the raw samples, thermal events and the system's own reports, embedded as
/// the JSON they arrived as.
public enum DiagnosticsExport {
    public static let format = "brainbuddy-diagnostics/v1"

    private struct Body: Encodable {
        var format: String
        var exportedAt: Date
        var device: DiagnosticsDeviceInfo
        var lastHour: DiagnosticsSummary
        var allRecorded: DiagnosticsSummary
        var samples: [CPUSample]
        var thermalEvents: [ThermalEvent]
        var launches: [Date]
    }

    public static func make(log: DiagnosticsLog, reports: [SystemReport], device: DiagnosticsDeviceInfo, now: Date)
        throws -> Data
    {
        let body = Body(
            format: format,
            exportedAt: now,
            device: device,
            lastHour: DiagnosticsSummary(log: log, now: now, windowSeconds: 3_600),
            allRecorded: DiagnosticsSummary(log: log, now: now, windowSeconds: secondsSinceEarliestEntry(log, now: now)),
            samples: log.samples,
            thermalEvents: log.thermalEvents,
            launches: log.launches
        )
        guard var object = try JSONSerialization.jsonObject(with: DiagnosticsStore.encoder.encode(body)) as? [String: Any]
        else { throw CocoaError(.coderInvalidValue) }
        object["systemReports"] = reports.map { report -> [String: Any] in
            // A payload that is not JSON is kept as text rather than dropped.
            let payload =
                (try? JSONSerialization.jsonObject(with: report.json))
                ?? String(decoding: report.json, as: UTF8.self)
            return ["kind": report.kind.rawValue, "payload": payload]
        }
        return try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
    }

    /// "BrainBuddy-diagnostics-20261009-153000.json", in UTC.
    public static func fileName(for date: Date) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "UTC")!
        let parts = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: date)
        let stamp = String(
            format: "%04d%02d%02d-%02d%02d%02d", parts.year!, parts.month!, parts.day!, parts.hour!, parts.minute!,
            parts.second!)
        return "BrainBuddy-diagnostics-\(stamp).json"
    }

    /// A window that takes in every entry (the summary's window excludes its start).
    private static func secondsSinceEarliestEntry(_ log: DiagnosticsLog, now: Date) -> Double {
        let earliest = [log.launches.first, log.samples.first?.at, log.thermalEvents.first?.at].compactMap { $0 }.min()
        return earliest.map { now.timeIntervalSince($0) + 1 } ?? 0
    }
}

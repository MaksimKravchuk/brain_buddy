import Foundation

/// A report the system delivered (MetricKit on iOS), kept as the JSON it came as.
public struct SystemReport: Sendable, Equatable {
    public enum Kind: String, Sendable, CaseIterable {
        /// A daily `MXMetricPayload`.
        case metrics
        /// An `MXDiagnosticPayload`: CPU exceptions, hangs, excessive disk writes, crashes.
        case diagnostics
    }

    public var kind: Kind
    public var json: Data

    public init(kind: Kind, json: Data) {
        self.kind = kind
        self.json = json
    }
}

/// The diagnostics directory: the log as one JSON file and each system report
/// as its own file. Everything stays on the device; only an export the person
/// shares leaves it.
public struct DiagnosticsStore: Sendable {
    /// System reports kept per kind; the oldest go first.
    public static let reportLimit = 30

    public let directory: URL

    public init(directory: URL) {
        self.directory = directory
    }

    private var logURL: URL { directory.appendingPathComponent("log.json") }

    /// The stored log; empty when there is none or it cannot be read
    /// (diagnostics never block the app, so a damaged file is started over).
    public func loadLog() -> DiagnosticsLog {
        guard let data = try? Data(contentsOf: logURL),
            let log = try? Self.decoder.decode(DiagnosticsLog.self, from: data)
        else { return DiagnosticsLog() }
        return log
    }

    public func saveLog(_ log: DiagnosticsLog) throws {
        try createDirectory()
        try Self.encoder.encode(log).write(to: logURL, options: .atomic)
    }

    /// Stores a report under its period's end, so the same report delivered
    /// twice is kept once, and drops the oldest beyond `reportLimit`.
    public func saveReport(_ json: Data, kind: SystemReport.Kind, periodEnd: Date) throws {
        try createDirectory()
        let stamp = String(format: "%012lld", Int64(periodEnd.timeIntervalSince1970.rounded(.down)))
        try json.write(to: directory.appendingPathComponent("\(kind.rawValue)-\(stamp).json"), options: .atomic)
        for name in reportFileNames(kind).dropLast(Self.reportLimit) {
            try? FileManager.default.removeItem(at: directory.appendingPathComponent(name))
        }
    }

    /// Oldest first within each kind, metrics before diagnostics.
    public func reports() -> [SystemReport] {
        SystemReport.Kind.allCases.flatMap { kind in
            reportFileNames(kind).compactMap { name in
                (try? Data(contentsOf: directory.appendingPathComponent(name))).map { SystemReport(kind: kind, json: $0) }
            }
        }
    }

    public func reportCount(_ kind: SystemReport.Kind) -> Int { reportFileNames(kind).count }

    /// Removes the log and every report.
    public func clear() throws {
        guard FileManager.default.fileExists(atPath: directory.path) else { return }
        try FileManager.default.removeItem(at: directory)
    }

    /// Names sort by period end because the stamp is zero-padded.
    private func reportFileNames(_ kind: SystemReport.Kind) -> [String] {
        let names = (try? FileManager.default.contentsOfDirectory(atPath: directory.path)) ?? []
        return names.filter { $0.hasPrefix("\(kind.rawValue)-") && $0.hasSuffix(".json") }.sorted()
    }

    private func createDirectory() throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    }

    static var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }

    static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}

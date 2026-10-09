import BrainBuddyCore
import BrainBuddyDiagnostics
import Foundation
import MetricKit
import Observation
import SwiftUI
import UIKit

/// Beta performance diagnostics (Settings → About → Performance), on while the
/// Info.plist key `BBPerformanceDiagnostics` (`BB_PERFORMANCE_DIAGNOSTICS` in
/// project.yml) is YES.
///
/// In the foreground it samples the process's CPU use every 10 s, with the
/// screen on top, the thermal state and Low Power Mode; it logs every thermal
/// state change; and it keeps the reports MetricKit delivers. Everything stays
/// in Caches/PerformanceDiagnostics until the person shares an export. Screens
/// are named by kind ("task", "list next"), never by content.
@MainActor
@Observable
final class PerformanceDiagnostics {
    static let infoKey = "BBPerformanceDiagnostics"
    static let sampleInterval: Duration = .seconds(10)
    /// About five minutes of foreground time between saves of the log.
    static let samplesPerSave = 30

    private(set) var log = DiagnosticsLog()
    private(set) var metricReportCount = 0
    private(set) var diagnosticReportCount = 0
    /// The screen on top, set by `diagnosticsScreen(_:)`. Not observed:
    /// nothing shows it live, and it changes on every navigation.
    @ObservationIgnored var screen = "launch"

    private let store: DiagnosticsStore
    @ObservationIgnored private var meter = CPUMeter()
    @ObservationIgnored private var isStarted = false
    @ObservationIgnored private var isLoaded = false
    @ObservationIgnored private var isForeground = false
    @ObservationIgnored private var sampling: Task<Void, Never>?
    @ObservationIgnored private var saving: Task<Void, Never>?
    @ObservationIgnored private var unsavedSamples = 0
    @ObservationIgnored private var thermalObserver: (any NSObjectProtocol)?
    @ObservationIgnored private var metricKitSubscriber: MetricKitSubscriber?

    init(store: DiagnosticsStore) {
        self.store = store
    }

    /// Nil when the build turns diagnostics off; then nothing is recorded and
    /// Settings shows no Performance row.
    static func live() -> PerformanceDiagnostics? {
        guard isEnabled else { return nil }
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        return PerformanceDiagnostics(
            store: DiagnosticsStore(directory: caches.appendingPathComponent("PerformanceDiagnostics")))
    }

    static var isEnabled: Bool {
        let value = Bundle.main.object(forInfoDictionaryKey: infoKey)
        if let flag = value as? Bool { return flag }
        // A `$(SETTING)` in the plist arrives as the string "YES" or "NO".
        if let text = value as? String {
            return ["yes", "true", "1"].contains(text.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
        }
        return false
    }

    // MARK: Lifecycle

    /// Once per process (every window's root calls it): reads the stored log
    /// off the main thread, then records the launch, the current thermal
    /// state and subscribes to thermal changes and MetricKit.
    func start() async {
        guard !isStarted else { return }
        isStarted = true
        let store = store
        let stored = await Task.detached(priority: .utility) { store.loadLog() }.value
        log = stored
        isLoaded = true
        // The scene may have become active before this ran.
        if UIApplication.shared.applicationState != .background { isForeground = true }
        log.recordLaunch(at: Date())
        recordThermalState()

        thermalObserver = NotificationCenter.default.addObserver(
            forName: ProcessInfo.thermalStateDidChangeNotification, object: nil, queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.recordThermalState() }
        }

        let subscriber = MetricKitSubscriber(store: store) { [weak self] in
            Task { @MainActor in self?.refreshReportCounts() }
        }
        metricKitSubscriber = subscriber
        MXMetricManager.shared.add(subscriber)
        // Reports the system kept from earlier deliveries. Each is stored
        // under its period, so reading one again changes nothing.
        Task.detached(priority: .utility) {
            subscriber.didReceive(MXMetricManager.shared.pastPayloads)
            subscriber.didReceive(MXMetricManager.shared.pastDiagnosticPayloads)
        }
        refreshReportCounts()
        startSamplingIfReady()
    }

    func sceneBecameActive() {
        isForeground = true
        startSamplingIfReady()
    }

    /// Stops sampling (a suspended app uses no CPU, and the gap must not
    /// count as one long idle sample) and saves the log.
    func sceneEnteredBackground() {
        isForeground = false
        sampling?.cancel()
        sampling = nil
        Task { await save() }
    }

    // MARK: Recording

    private func startSamplingIfReady() {
        guard isLoaded, isForeground, sampling == nil else { return }
        meter = CPUMeter()
        takeSample()  // the baseline
        sampling = Task { [weak self] in
            while !Task.isCancelled {
                do { try await Task.sleep(for: Self.sampleInterval) } catch { return }
                self?.takeSample()
            }
        }
    }

    private func takeSample() {
        guard let cpuSeconds = ProcessCPUTime.seconds(),
            let measurement = meter.reading(cpuSeconds: cpuSeconds, at: .now)
        else { return }
        log.append(
            CPUSample(
                at: Date(), seconds: measurement.seconds, cpuPercent: measurement.cpuPercent, screen: screen,
                thermal: Self.currentThermal, lowPowerMode: ProcessInfo.processInfo.isLowPowerModeEnabled))
        unsavedSamples += 1
        if unsavedSamples >= Self.samplesPerSave { Task { await save() } }
    }

    private func recordThermalState() {
        log.append(ThermalEvent(at: Date(), level: Self.currentThermal, screen: screen))
        // Rare and the reason this exists: kept on disk at once.
        Task { await save() }
    }

    /// Writes a snapshot off the main thread, one write at a time and in order.
    private func save() async {
        guard isLoaded else { return }
        unsavedSamples = 0
        let snapshot = log
        let store = store
        let previous = saving
        let current = Task.detached(priority: .utility) {
            await previous?.value
            // Diagnostics never get in the app's way: a failed write is
            // retried with the next save.
            try? store.saveLog(snapshot)
        }
        saving = current
        await current.value
    }

    private func refreshReportCounts() {
        metricReportCount = store.reportCount(.metrics)
        diagnosticReportCount = store.reportCount(.diagnostics)
    }

    // MARK: Actions

    /// Removes the log and the stored reports; recording carries on.
    func clear() async {
        log = DiagnosticsLog()
        unsavedSamples = 0
        await saving?.value
        // Best effort, like every diagnostics write.
        try? store.clear()
        // Queued after any save still running, so the cleared log is what stays.
        await save()
        refreshReportCounts()
    }

    /// Writes the export to a temporary file named after the moment it was
    /// made, for the share sheet.
    func exportFile() async throws -> URL {
        let snapshot = log
        let device = deviceInfo()
        let store = store
        return try await Task.detached(priority: .userInitiated) {
            let now = Date()
            let data = try DiagnosticsExport.make(log: snapshot, reports: store.reports(), device: device, now: now)
            let url = FileManager.default.temporaryDirectory.appendingPathComponent(
                DiagnosticsExport.fileName(for: now))
            try data.write(to: url, options: .atomic)
            return url
        }.value
    }

    // MARK: Device

    static var currentThermal: ThermalLevel {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: .nominal
        case .fair: .fair
        case .serious: .serious
        case .critical: .critical
        // A state added later reads as hot rather than hidden.
        @unknown default: .serious
        }
    }

    private func deviceInfo() -> DiagnosticsDeviceInfo {
        DiagnosticsDeviceInfo(
            appVersion: SettingsScreen.versionDescription,
            buildLabel: SettingsScreen.buildLabel,
            osVersion: "\(UIDevice.current.systemName) \(UIDevice.current.systemVersion)",
            deviceModel: Self.hardwareModel,
            thermal: Self.currentThermal,
            lowPowerMode: ProcessInfo.processInfo.isLowPowerModeEnabled
        )
    }

    /// The hardware family, such as "iPhone17,1" (thermal behaviour differs
    /// by model); not an identifier of the device.
    private static var hardwareModel: String {
        var info = utsname()
        uname(&info)
        return withUnsafeBytes(of: &info.machine) { bytes in
            String(decoding: bytes.prefix { $0 != 0 }, as: UTF8.self)
        }
    }
}

/// Stores what MetricKit delivers, on whatever queue it delivers on.
private final class MetricKitSubscriber: NSObject, MXMetricManagerSubscriber, Sendable {
    private let store: DiagnosticsStore
    private let didSave: @Sendable () -> Void

    init(store: DiagnosticsStore, didSave: @escaping @Sendable () -> Void) {
        self.store = store
        self.didSave = didSave
    }

    func didReceive(_ payloads: [MXMetricPayload]) {
        guard !payloads.isEmpty else { return }
        for payload in payloads {
            try? store.saveReport(payload.jsonRepresentation(), kind: .metrics, periodEnd: payload.timeStampEnd)
        }
        didSave()
    }

    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        guard !payloads.isEmpty else { return }
        for payload in payloads {
            try? store.saveReport(payload.jsonRepresentation(), kind: .diagnostics, periodEnd: payload.timeStampEnd)
        }
        didSave()
    }
}

// MARK: - Screen names

extension View {
    /// Names this screen in performance diagnostics while it is on top. When
    /// it goes, the screen it covered is named again.
    func diagnosticsScreen(_ name: String) -> some View {
        modifier(DiagnosticsScreenName(name: name))
    }
}

private struct DiagnosticsScreenName: ViewModifier {
    let name: String
    @Environment(PerformanceDiagnostics.self) private var diagnostics: PerformanceDiagnostics?
    @State private var covered: String?

    func body(content: Content) -> some View {
        content
            .onAppear {
                guard let diagnostics else { return }
                covered = diagnostics.screen
                diagnostics.screen = name
            }
            .onDisappear {
                guard let diagnostics, diagnostics.screen == name, let covered else { return }
                diagnostics.screen = covered
            }
    }
}

extension AppRoute {
    /// The route's kind for performance diagnostics: never a name, a search
    /// query or any other content.
    var diagnosticsName: String {
        switch self {
        case .task: "task"
        case .destination(let destination):
            switch destination {
            case .list(let list): "list \(list.rawValue)"
            case .agenda: "agenda"
            case .dateView: "date view"
            case .project: "project"
            case .tag: "tag"
            case .history: "history"
            case .search: "search results"
            }
        case .projects: "projects"
        case .archivedProjects: "archived projects"
        case .tags: "tags"
        case .settings: "settings"
        case .syncIssues: "sync issues"
        case .review: "review"
        case .performance: "performance"
        }
    }
}

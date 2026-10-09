import BrainBuddyDiagnostics
import CoreTransferable
import SwiftUI
import UniformTypeIdentifiers

/// Settings → About → Performance (beta builds): what `PerformanceDiagnostics`
/// recorded, and the export to share when something runs hot.
struct PerformanceScreen: View {
    @Environment(PerformanceDiagnostics.self) private var diagnostics: PerformanceDiagnostics?
    @State private var isConfirmingClear = false

    init() {}

    var body: some View {
        Group {
            if let diagnostics {
                content(diagnostics)
            } else {
                EmptyStateView(
                    title: "Diagnostics are off",
                    message: "This build doesn't record performance diagnostics.",
                    systemImage: "gauge.with.dots.needle.0percent"
                )
            }
        }
        .navigationTitle("Performance")
    }

    private func content(_ diagnostics: PerformanceDiagnostics) -> some View {
        // Recomputed with every sample (every 10 s while this screen is open).
        let summary = DiagnosticsSummary(log: diagnostics.log, now: Date(), windowSeconds: 3_600)
        return List {
            Section {
                LabeledContent("Thermal state", value: Self.thermalDescription(PerformanceDiagnostics.currentThermal))
                LabeledContent(
                    "Low Power Mode", value: ProcessInfo.processInfo.isLowPowerModeEnabled ? "On" : "Off")
                if let latest = diagnostics.log.samples.last {
                    LabeledContent("Latest sample", value: Self.percent(latest.cpuPercent))
                }
            } header: {
                Text("Now")
            }

            Section {
                LabeledContent("Average CPU", value: summary.averageCPUPercent.map(Self.percent) ?? "No samples yet")
                if let peak = summary.peak {
                    LabeledContent("Peak", value: "\(Self.percent(peak.cpuPercent)) · \(Self.screenTitle(peak.screen))")
                }
                LabeledContent("Hottest state", value: summary.hottestThermal.map(Self.thermalDescription) ?? "—")
                LabeledContent("Serious or critical", value: Self.events(summary.seriousThermalEvents))
                LabeledContent("In the foreground", value: Self.duration(summary.sampledSeconds))
            } header: {
                Text("Last hour")
            } footer: {
                // Verbatim: a localized key would read "% i" as a format specifier.
                Text(
                    verbatim:
                        "100 % is one processor core busy the whole time. Resting on a list, the app should stay close to 0 %."
                )
            }

            if !summary.byScreen.isEmpty {
                Section {
                    ForEach(summary.byScreen.prefix(6), id: \.screen) { load in
                        LabeledContent(
                            Self.screenTitle(load.screen),
                            value: "\(Self.percent(load.averageCPUPercent)) · \(Self.duration(load.sampledSeconds))")
                    }
                } header: {
                    Text("By screen, last hour")
                }
            }

            Section {
                LabeledContent("Daily reports", value: diagnostics.metricReportCount.formatted())
                LabeledContent("Diagnostic reports", value: diagnostics.diagnosticReportCount.formatted())
            } header: {
                Text("From iOS")
            } footer: {
                Text(
                    "iOS sends a daily report about once a day and a diagnostic report after a CPU exception, a hang or heavy disk writing. If none arrive after a couple of days, turn on Share With App Developers in Settings › Privacy & Security › Analytics & Improvements."
                )
            }

            Section {
                ShareLink(
                    item: DiagnosticsExportFile(diagnostics: diagnostics),
                    preview: SharePreview("Brain Buddy performance diagnostics")
                ) {
                    Label("Export diagnostics", systemImage: "square.and.arrow.up")
                }
                Button("Clear diagnostics", role: .destructive) { isConfirmingClear = true }
            } footer: {
                Text(
                    "One JSON file with timings and system figures. It never includes your tasks, and it leaves this \(ThisDevice.name) only when you share it."
                )
            }
        }
        .confirmationDialog(
            "Clear performance diagnostics?", isPresented: $isConfirmingClear, titleVisibility: .visible
        ) {
            Button("Clear", role: .destructive) { Task { await diagnostics.clear() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Recording starts again from now.")
        }
    }

    // MARK: Formatting

    static func percent(_ value: Double) -> String { "\(Int(value.rounded())) %" }

    static func events(_ count: Int) -> String {
        switch count {
        case 0: "None"
        case 1: "1 time"
        default: "\(count) times"
        }
    }

    static func duration(_ seconds: Double) -> String {
        guard seconds >= 60 else { return "Under a minute" }
        return Duration.seconds(seconds).formatted(.units(allowed: [.hours, .minutes], width: .abbreviated))
    }

    static func thermalDescription(_ level: ThermalLevel) -> String {
        switch level {
        case .nominal: "Normal"
        case .fair: "Fair"
        case .serious: "Serious"
        case .critical: "Critical"
        }
    }

    /// "list next" → "List next".
    static func screenTitle(_ name: String) -> String {
        name.prefix(1).uppercased() + name.dropFirst()
    }
}

/// The export, written only when the share sheet asks for it.
private struct DiagnosticsExportFile: Transferable {
    let diagnostics: PerformanceDiagnostics

    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(exportedContentType: .json) { file in
            SentTransferredFile(try await file.diagnostics.exportFile())
        }
    }
}

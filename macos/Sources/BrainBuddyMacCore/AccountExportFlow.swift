import BrainBuddyAPI
import Foundation
import Observation

/// What the export flow reads from the server: `BrainBuddyAPIClient` in the app, a fake in tests.
package protocol AccountExportRemote: Sendable {
    func exportAccount() async throws(APIError) -> AccountExport
}

extension BrainBuddyAPIClient: AccountExportRemote {}

/// The Account tab's export (spec 028, design S-02.08 – S-02.12), with no view. The server's file name
/// is known only from the response, so the flow downloads first (cancellable), then waits for the
/// person to choose a location, then writes once. 028-FR-013: nothing is left behind. The bytes live
/// in memory only until the write or a cancel; `Data.write(options: .atomic)` writes a temporary file
/// and renames it, so the destination never holds a partial export. Logs carry the stage, outcome,
/// duration and reference only (028-FR-018).
@MainActor
@Observable
package final class AccountExportFlow {
    package enum FailureKind: Equatable, Sendable {
        case offline, cannotSave, server

        package var message: String {
            switch self {
            case .offline: "Couldn't export. Check your connection."
            case .cannotSave: "Couldn't save the file there."
            case .server: "Couldn't export."
            }
        }
    }

    package enum State: Equatable, Sendable {
        case idle
        case exporting
        case choosingLocation(suggestedName: String)
        case saved
        case failed(kind: FailureKind, reference: String?)
    }

    package typealias Writer = @Sendable (Data, URL) throws -> Void
    package static let atomicWriter: Writer = { data, url in try data.write(to: url, options: .atomic) }

    package private(set) var state: State = .idle
    package var holdsExportBytes: Bool { pending != nil }

    @ObservationIgnored private let remote: any AccountExportRemote
    @ObservationIgnored private let log: any MacLogSink
    @ObservationIgnored private let writer: Writer
    @ObservationIgnored private var pending: Data?
    @ObservationIgnored private var downloadTask: Task<Void, Never>?
    /// Bumped by start and cancel: a download finishing after a cancel is ignored.
    @ObservationIgnored private var generation = 0

    package init(remote: any AccountExportRemote, log: any MacLogSink = SystemMacLog(), writer: @escaping Writer = AccountExportFlow.atomicWriter) {
        self.remote = remote
        self.log = log
        self.writer = writer
    }

    private var isWorking: Bool {
        switch state {
        case .exporting, .choosingLocation: true
        case .idle, .saved, .failed: false
        }
    }

    /// Export… / Try again; ignored while working.
    package func start() {
        guard !isWorking else { return }
        generation += 1
        let mine = generation
        state = .exporting
        downloadTask = Task { [weak self] in await self?.download(generation: mine) }
    }

    package func waitUntilSettled() async { await downloadTask?.value }

    /// The person confirmed a location. Writes once; an error leaves nothing new at `url`.
    package func save(to url: URL) {
        guard case .choosingLocation = state, let data = pending else { return }
        pending = nil
        let started = ContinuousClock.now
        do {
            try writer(data, url)
            state = .saved
            record("write", "ok", since: started)
        } catch {
            state = .failed(kind: .cannotSave, reference: nil)
            record("write", "failed", since: started)
        }
    }

    /// Cancel, panel cancelled, window closed: stops the download, drops the bytes, writes nothing.
    package func cancel() {
        generation += 1
        downloadTask?.cancel()
        downloadTask = nil
        pending = nil
        state = .idle
    }

    private func download(generation mine: Int) async {
        let started = ContinuousClock.now
        let result: Result<AccountExport, APIError>
        do throws(APIError) {
            result = .success(try await remote.exportAccount())
        } catch {
            result = .failure(error)
        }
        guard mine == generation, state == .exporting else { return }
        downloadTask = nil
        switch result {
        case .success(let export):
            pending = export.data
            state = .choosingLocation(suggestedName: export.suggestedFileName)
            record("download", "ok", since: started)
        case .failure(let error):
            var kind = FailureKind.server
            if case .network = error.kind { kind = .offline }
            if case .cancelled = error.kind { state = .idle } else { state = .failed(kind: kind, reference: error.referenceID) }
            record("download", state == .idle ? "cancelled" : "\(kind)", since: started, reference: error.referenceID)
        }
    }

    private func record(_ stage: String, _ outcome: String, since started: ContinuousClock.Instant, reference: String? = nil) {
        let parts = started.duration(to: .now).components
        var line = "account export stage=\(stage) outcome=\(outcome) duration_ms=\(parts.seconds * 1000 + parts.attoseconds / 1_000_000_000_000_000)"
        if let reference { line += " reference=\(reference)" }
        log.log(.sync, line)
    }
}

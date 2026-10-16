import BrainBuddyAPI
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyMacCore

/// Spec 028 T010: the account export flow (design S-02.08 – S-02.12). The no-partial-file cases come
/// first: they pin 028-FR-013 before the state and message cases. No network and no panel: a fake
/// remote answers, and the person's choice in the panel is a call to `save(to:)` or `cancel()`.
@Suite("Account export flow")
@MainActor
struct AccountExportFlowTests {
    private static let archive = Data("PK-fixture-archive".utf8)

    /// A remote that answers once per call, or waits until the calling task is cancelled.
    private final class FakeRemote: AccountExportRemote {
        enum Behavior: Sendable {
            case succeed(AccountExport)
            case fail(APIError)
            case waitForCancel
        }

        private struct State {
            var calls = 0
            var sawCancellation = false
        }

        private let behavior: Behavior
        private let state = Mutex(State())

        init(_ behavior: Behavior) { self.behavior = behavior }

        var calls: Int { state.withLock { $0.calls } }
        var sawCancellation: Bool { state.withLock { $0.sawCancellation } }

        func exportAccount() async throws(APIError) -> AccountExport {
            state.withLock { $0.calls += 1 }
            switch behavior {
            case .succeed(let export): return export
            case .fail(let error): throw error
            case .waitForCancel:
                while !Task.isCancelled { await Task.yield() }
                state.withLock { $0.sawCancellation = true }
                throw APIError(kind: .cancelled, message: "The request was cancelled.")
            }
        }
    }

    private func export(_ name: String = "brainbuddy-export-2026-10-16.zip") -> AccountExport {
        AccountExport(suggestedFileName: name, data: Self.archive)
    }

    private func makeFlow(
        _ remote: FakeRemote, log: CapturingMacLog = CapturingMacLog(),
        writer: @escaping AccountExportFlow.Writer = AccountExportFlow.atomicWriter
    ) -> AccountExportFlow {
        AccountExportFlow(remote: remote, log: log, writer: writer)
    }

    /// Starts and waits until the flow is asking where to save.
    private func downloaded(_ flow: AccountExportFlow) async {
        flow.start()
        await flow.waitUntilSettled()
    }

    private func error(_ kind: APIError.Kind, status: Int? = nil, reference: String? = "ref-1") -> APIError {
        APIError(kind: kind, message: "Server words that are not shown.", referenceID: reference, statusCode: status)
    }

    // MARK: No partial file (028-FR-013, 028-SC-005)

    @Test("028-FR-013 028-SC-005 cancel during the download writes nothing and holds no bytes")
    func cancelDuringDownloadLeavesNothing() async {
        let folder = TemporaryFolder()
        let remote = FakeRemote(.waitForCancel)
        let flow = makeFlow(remote)

        flow.start()
        #expect(flow.state == .exporting)
        flow.cancel()
        await flow.waitUntilSettled()
        // The remote task is cancelled and unwinds on its own; give it a turn to notice.
        while !remote.sawCancellation { await Task.yield() }

        #expect(flow.state == .idle)
        #expect(!flow.holdsExportBytes)
        #expect(folder.names.isEmpty)
    }

    @Test("028-FR-013 028-SC-005 cancel at the panel drops the bytes and writes nothing")
    func cancelAtPanelLeavesNothing() async {
        let folder = TemporaryFolder()
        let flow = makeFlow(FakeRemote(.succeed(export())))

        await downloaded(flow)
        #expect(flow.state == .choosingLocation(suggestedName: "brainbuddy-export-2026-10-16.zip"))
        #expect(flow.holdsExportBytes)
        flow.cancel()
        // A late confirmation after the panel was cancelled has nothing to write.
        flow.save(to: folder.file("late.zip"))

        #expect(flow.state == .idle)
        #expect(!flow.holdsExportBytes)
        #expect(folder.names.isEmpty)
    }

    @Test("028-FR-013 028-SC-005 a write into a folder that does not exist fails and leaves nothing")
    func writeToMissingFolderLeavesNothing() async {
        let folder = TemporaryFolder()
        let target = folder.url.appendingPathComponent("missing", isDirectory: true).appendingPathComponent("out.zip")
        let flow = makeFlow(FakeRemote(.succeed(export())))

        await downloaded(flow)
        flow.save(to: target)

        #expect(flow.state == .failed(kind: .cannotSave, reference: nil))
        #expect(!flow.holdsExportBytes)
        #expect(folder.names.isEmpty)
    }

    @Test(
        "028-FR-013 028-SC-005 a write into a read-only folder fails and leaves nothing",
        .enabled(if: getuid() != 0, "root can write into a read-only folder"))
    func writeToReadOnlyFolderLeavesNothing() async throws {
        let folder = TemporaryFolder()
        try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: folder.url.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: folder.url.path) }
        let flow = makeFlow(FakeRemote(.succeed(export())))

        await downloaded(flow)
        flow.save(to: folder.file("out.zip"))

        #expect(flow.state == .failed(kind: .cannotSave, reference: nil))
        #expect(!flow.holdsExportBytes)
        #expect(folder.names.isEmpty)
    }

    @Test(
        "028-FR-013 028-SC-005 a write that fails over an existing file leaves that file as it was",
        .enabled(if: getuid() != 0, "root can write into a read-only folder"))
    func failedReplaceKeepsTheOldFile() async throws {
        let folder = TemporaryFolder()
        let existing = folder.file("out.zip")
        try Data("old".utf8).write(to: existing)
        try FileManager.default.setAttributes([.posixPermissions: 0o555], ofItemAtPath: folder.url.path)
        defer { try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: folder.url.path) }
        let flow = makeFlow(FakeRemote(.succeed(export())))

        await downloaded(flow)
        flow.save(to: existing)

        #expect(flow.state == .failed(kind: .cannotSave, reference: nil))
        #expect(folder.bytes("out.zip") == Data("old".utf8))
        #expect(folder.names == ["out.zip"])
    }

    @Test("028-FR-013 028-SC-005 a writer that fails after part of a write is a failed save with the bytes dropped")
    func failureAfterPartialWrite() async {
        struct DiskFull: Error {}
        let folder = TemporaryFolder()
        let target = folder.file("out.zip")
        // Stands in for a disk filling up mid-write: the flow must not keep the bytes or claim success.
        let writer: AccountExportFlow.Writer = { data, _ in
            _ = data.prefix(4)
            throw DiskFull()
        }
        let flow = makeFlow(FakeRemote(.succeed(export())), writer: writer)

        await downloaded(flow)
        flow.save(to: target)

        #expect(flow.state == .failed(kind: .cannotSave, reference: nil))
        #expect(!flow.holdsExportBytes)
        #expect(!FileManager.default.fileExists(atPath: target.path))
        #expect(folder.names.isEmpty)
    }

    @Test("028-FR-013 the default writer is atomic: the confirmed file holds exactly the archive and no temporary file remains")
    func successWritesExactlyTheArchive() async {
        let folder = TemporaryFolder()
        let flow = makeFlow(FakeRemote(.succeed(export())))

        await downloaded(flow)
        flow.save(to: folder.file("chosen.zip"))

        #expect(flow.state == .saved)
        #expect(!flow.holdsExportBytes)
        #expect(folder.names == ["chosen.zip"])
        #expect(folder.bytes("chosen.zip") == Self.archive)
    }

    // MARK: States and messages (028-FR-012, 028-FR-013, 028-FR-017)

    @Test("028-FR-012 the panel is offered the server's file name once the download is done")
    func suggestedNameComesFromTheServer() async {
        let remote = FakeRemote(.succeed(export("my-data.zip")))
        let flow = makeFlow(remote)

        #expect(flow.state == .idle)
        flow.start()
        #expect(flow.state == .exporting)
        await flow.waitUntilSettled()

        #expect(flow.state == .choosingLocation(suggestedName: "my-data.zip"))
        #expect(remote.calls == 1)
    }

    @Test("028-FR-012 starting again while exporting or choosing a location does not download twice")
    func startIsIgnoredWhileWorking() async {
        let remote = FakeRemote(.succeed(export()))
        let flow = makeFlow(remote)

        flow.start()
        flow.start()
        await flow.waitUntilSettled()
        flow.start()

        #expect(remote.calls == 1)
        #expect(flow.state == .choosingLocation(suggestedName: "brainbuddy-export-2026-10-16.zip"))
    }

    @Test("028-FR-017 an offline failure reads \"Couldn't export. Check your connection.\" with its reference")
    func offlineFailure() async {
        let flow = makeFlow(FakeRemote(.fail(error(.network("offline")))))

        await downloaded(flow)

        #expect(flow.state == .failed(kind: .offline, reference: "ref-1"))
        #expect(AccountExportFlow.FailureKind.offline.message == "Couldn't export. Check your connection.")
    }

    @Test("028-FR-017 a server failure reads \"Couldn't export.\" with its reference, whatever the status")
    func serverFailures() async {
        let kinds: [APIError.Kind] = [.server, .rateLimited, .unauthorized, .rejected, .decoding("x")]
        for kind in kinds {
            let flow = makeFlow(FakeRemote(.fail(error(kind, status: 500))))
            await downloaded(flow)
            #expect(flow.state == .failed(kind: .server, reference: "ref-1"), "028-FR-017 \(kind)")
        }
        #expect(AccountExportFlow.FailureKind.server.message == "Couldn't export.")
    }

    @Test("028-FR-017 a failure without a reference id shows none")
    func failureWithoutReference() async {
        let flow = makeFlow(FakeRemote(.fail(error(.server, reference: nil))))

        await downloaded(flow)

        #expect(flow.state == .failed(kind: .server, reference: nil))
    }

    @Test("028-FR-013 a write failure reads \"Couldn't save the file there.\"")
    func cannotSaveMessage() {
        #expect(AccountExportFlow.FailureKind.cannotSave.message == "Couldn't save the file there.")
    }

    @Test("028-FR-017 Try again after a failure downloads again")
    func tryAgainAfterFailure() async {
        let remote = FakeRemote(.fail(error(.server)))
        let flow = makeFlow(remote)

        await downloaded(flow)
        #expect(flow.state == .failed(kind: .server, reference: "ref-1"))
        await downloaded(flow)

        #expect(remote.calls == 2)
    }

    @Test("028-FR-012 after Saved the flow can export again, and cancel returns to idle")
    func exportAgainAfterSaved() async {
        let folder = TemporaryFolder()
        let remote = FakeRemote(.succeed(export()))
        let flow = makeFlow(remote)

        await downloaded(flow)
        flow.save(to: folder.file("one.zip"))
        #expect(flow.state == .saved)
        await downloaded(flow)
        #expect(flow.state == .choosingLocation(suggestedName: "brainbuddy-export-2026-10-16.zip"))
        flow.cancel()

        #expect(flow.state == .idle)
        #expect(remote.calls == 2)
    }

    @Test("028-FR-013 a server answer that arrives after Cancel is ignored")
    func lateAnswerAfterCancelIsIgnored() async {
        let remote = FakeRemote(.succeed(export()))
        let flow = makeFlow(remote)

        flow.start()
        flow.cancel()
        await flow.waitUntilSettled()
        // Let the already-started download finish; it must not reopen the panel.
        for _ in 0..<20 { await Task.yield() }

        #expect(flow.state == .idle)
        #expect(!flow.holdsExportBytes)
    }

    // MARK: Logging (028-FR-018)

    @Test("028-FR-018 the log lines carry stage, outcome and reference, never the file name, path or bytes")
    func logsAreRedacted() async {
        let folder = TemporaryFolder("Ada Lovelace Private")
        let log = CapturingMacLog()
        let ok = makeFlow(FakeRemote(.succeed(export("ada-lovelace-secret.zip"))), log: log)
        await downloaded(ok)
        ok.save(to: folder.file("ada-private-copy.zip"))

        let failing = makeFlow(FakeRemote(.fail(error(.server, reference: "ref-9"))), log: log)
        await downloaded(failing)

        let lines = log.messages(.sync)
        #expect(lines.count == 3)
        #expect(lines.allSatisfy { $0.hasPrefix("account export stage=") })
        #expect(lines.contains { $0.contains("stage=download outcome=ok") })
        #expect(lines.contains { $0.contains("stage=write outcome=ok") })
        #expect(lines.contains { $0.contains("outcome=server") && $0.contains("reference=ref-9") })
        for line in lines {
            for secret in ["ada", "Ada", "Lovelace", "secret", "PK-fixture", folder.root.path, ".zip"] {
                #expect(!line.contains(secret), "028-FR-018 leaked \(secret) in: \(line)")
            }
        }
    }
}

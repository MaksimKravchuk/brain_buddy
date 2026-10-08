import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The launch order of contracts/mac-app-host.md §1 when a step fails: the workspace opens only
/// once the import reached a terminal state (data-model E7.1 invariant 4), so a failed import can
/// never leave an empty workspace that later turns the previous version's file into a "later file".
/// Failures are injected with `MacFileFaults`, scoped to each test's own folder.
@Suite("Launch")
@MainActor
struct MacLaunchTests {
    private static let populatedTaskCount = 18

    private func makeLaunch(_ folder: TemporaryFolder, transport: CountingTransport = CountingTransport()) -> MacLaunch {
        MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: MacHostConfiguration(directory: folder.url, isDryRun: false), tokenStore: SpyTokenStore(),
                transport: transport, cookieJar: FakeCookieJar(), responseCache: FakeResponseCache(),
                now: TestClock().provider, makeID: SequentialIDs().provider, log: CapturingMacLog()
            )
        )
    }

    private func importRecord(_ folder: TemporaryFolder) -> LegacyImportRecord? {
        MacLocalStateStore(directory: folder.url).load()?.legacyImport
    }

    private func stagingFiles(_ folder: TemporaryFolder) -> [String] {
        folder.names.filter { LegacyFileNames.isStaging($0) }
    }

    @Test("021-FR-020 021-FR-033 a failed import write opens no workspace, so the old file can never become a later file")
    func failedImportOpensNoWorkspace() async throws {
        let folder = TemporaryFolder()
        let legacy = try Fixture.install("legacy-populated", in: folder)
        let transport = CountingTransport()
        let full = MacFileFaults.inject(.write, in: folder.url, namePrefix: LegacyFileNames.stagingPrefix)
        let launch = makeLaunch(folder, transport: transport)
        await launch.run { _ in }
        MacFileFaults.clear(full)

        #expect(launch.importFailed, "the launch stops at the import-failed state")
        #expect(launch.host == nil && launch.model == nil, "no workspace opens while the import has not finished")
        #expect(folder.bytes(LegacyFileNames.legacy) == legacy, "the previous version's file is exactly as it was")
        #expect(!MacFiles.exists(folder.store))
        #expect(stagingFiles(folder).isEmpty, "the half-written staging file is gone")
        #expect(importRecord(folder)?.state == .inProgress, "the attempt is on disk, so the retry resumes it")
        #expect(transport.requests.isEmpty)
    }

    @Test("021-FR-020 021-FR-021 “Try again” after the disk has room resumes the import and opens the carried-over tasks")
    func retryResumesTheImport() async throws {
        let folder = TemporaryFolder()
        let legacy = try Fixture.install("legacy-populated", in: folder)
        let full = MacFileFaults.inject(.write, in: folder.url, namePrefix: LegacyFileNames.stagingPrefix)
        let launch = makeLaunch(folder)
        await launch.run { _ in }
        #expect(launch.importFailed)

        await launch.retryImport()
        #expect(launch.importFailed && launch.host == nil, "still failing: still nothing opened")
        #expect(folder.bytes(LegacyFileNames.legacy) == legacy)

        MacFileFaults.clear(full)
        await launch.retryImport()
        let host = try #require(launch.host, "the workspace opens once the import finished")
        #expect(!launch.importFailed && launch.model != nil)
        let record = try #require(importRecord(folder))
        #expect(record.state == .completed)
        #expect(host.workspace.state.tasks.count == Self.populatedTaskCount, "every task carried over, none twice")
        let backup = try #require(record.backupFileName)
        #expect(folder.bytes(backup) == legacy && !MacFiles.exists(folder.legacy), "the old file is the backup, unchanged")
        #expect(stagingFiles(folder).isEmpty)
    }

    @Test("021-FR-021 021-FR-033 a sidecar that cannot be written stops the launch before any decision; the retry imports")
    func sidecarWriteFailureStopsTheLaunch() async throws {
        let folder = TemporaryFolder()
        let legacy = try Fixture.install("legacy-populated", in: folder)
        let full = MacFileFaults.inject(.write, in: folder.url, namePrefix: MacLocalStateStore.fileName)
        let launch = makeLaunch(folder)
        await launch.run { _ in }
        #expect(launch.importFailed && launch.host == nil)
        #expect(importRecord(folder) == nil && !MacFiles.exists(folder.store))
        #expect(folder.bytes(LegacyFileNames.legacy) == legacy)

        MacFileFaults.clear(full)
        await launch.retryImport()
        #expect(launch.host != nil && importRecord(folder)?.state == .completed)
    }

    @Test("021-FR-021 a failed rename into store.json stops the launch; the retry finishes only the renames")
    func failedRenameIsFinishedByTheRetry() async throws {
        let folder = TemporaryFolder()
        let legacy = try Fixture.install("legacy-populated", in: folder)
        let refused = MacFileFaults.inject(.rename, in: folder.url, namePrefix: LegacyFileNames.store, code: EIO)
        let launch = makeLaunch(folder)
        await launch.run { _ in }
        MacFileFaults.clear(refused)

        #expect(launch.importFailed && launch.host == nil)
        #expect(importRecord(folder)?.state == .completed, "the decision is recorded; only the renames are left")
        #expect(stagingFiles(folder).count == 1 && !MacFiles.exists(folder.store))
        #expect(folder.bytes(LegacyFileNames.legacy) == legacy)

        await launch.retryImport()
        let host = try #require(launch.host)
        #expect(host.workspace.state.tasks.count == Self.populatedTaskCount)
        #expect(stagingFiles(folder).isEmpty && !MacFiles.exists(folder.legacy))
        #expect(folder.bytes(try #require(importRecord(folder)?.backupFileName)) == legacy)
    }

    @Test("021-FR-033 a corrupt previous-version file is a terminal state: the notice, then the empty workspace opens")
    func corruptFileStillOpens() async throws {
        let folder = TemporaryFolder()
        try Fixture.install("legacy-corrupt", in: folder)
        let launch = makeLaunch(folder)
        var notices: [LegacyImportNotice] = []
        await launch.run { notices.append($0) }
        #expect(!launch.importFailed && launch.host != nil)
        #expect(notices.count == 1)
    }

    @Test("021-FR-021 backup retention that fails after a completed import is left for the next launch; the workspace opens")
    func retentionFailureDoesNotBlock() async throws {
        let folder = TemporaryFolder()
        let clock = TestClock()
        try Fixture.install("legacy-populated", in: folder)
        _ = try LegacyImportCoordinator.forTest(folder, clock: clock).run()
        _ = try MacLocalStateStore(directory: folder.url).update { $0.legacyImport?.signedOutSinceImport = true }
        let backup = try #require(importRecord(folder)?.backupFileName)
        clock.advance(31 * TestClock.day)

        let refused = MacFileFaults.inject(.remove, in: folder.url, namePrefix: LegacyFileNames.backupPrefix, code: EPERM)
        let result = try LegacyImportCoordinator.forTest(folder, clock: clock).run()
        MacFileFaults.clear(refused)
        #expect(result.notices.isEmpty)
        #expect(MacFiles.exists(folder.file(backup)) && importRecord(folder)?.backupDeletedAt == nil, "kept for now")

        _ = try LegacyImportCoordinator.forTest(folder, clock: clock).run()
        #expect(!MacFiles.exists(folder.file(backup)) && importRecord(folder)?.backupDeletedAt != nil, "the next launch deletes it")
    }

    @Test("021-FR-020 the import-failed panel's words")
    func importFailedCopy() {
        #expect(LegacyImportFailedCopy.title == "Brain Buddy couldn't finish the update")
        #expect(LegacyImportFailedCopy.message.contains("The file from the previous version was left exactly as it was."))
        #expect(LegacyImportFailedCopy.tryAgain == "Try again" && LegacyImportFailedCopy.tryingAgain == "Trying again…")
    }
}

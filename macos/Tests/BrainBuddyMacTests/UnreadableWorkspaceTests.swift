import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// Design X-09 (contracts/mac-app-host.md §9; T097): a `store.json` this build cannot read is never
/// overwritten, starts no sync and sends nothing; "Start fresh" sets it aside, and the import then
/// treats the folder as in use.
@Suite("Unreadable workspace")
@MainActor
struct UnreadableWorkspaceTests {
    private func launch(_ folder: TemporaryFolder, transport: CountingTransport, tokens: SpyTokenStore = SpyTokenStore()) async -> WorkspaceHost? {
        let launch = MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: MacHostConfiguration(directory: folder.url, isDryRun: false), tokenStore: tokens,
                transport: transport, cookieJar: FakeCookieJar(), responseCache: FakeResponseCache(),
                now: TestClock().provider, log: CapturingMacLog()
            )
        )
        await launch.run { _ in }
        return launch.host
    }

    @Test("021-FR-022 021-FR-017 a store.json that does not decode shows X-09, starts no sync, sends nothing, and is left as it was")
    func unreadableShowsX09() async throws {
        let folder = TemporaryFolder()
        let damaged = Data("{\"version\": 2, \"generation\": 4, \"base\": ".utf8)
        try damaged.write(to: folder.store)
        let transport = CountingTransport()
        let tokens = SpyTokenStore()
        let host = try #require(await launch(folder, transport: transport, tokens: tokens))
        try await Task.sleep(nanoseconds: 100_000_000)

        #expect(host.workspace.loadError != nil, "the window shows X-09 instead of the lists")
        #expect(host.workspace.account == nil && host.workspace.state == .empty)
        #expect(transport.requests.isEmpty && tokens.calls.isEmpty, "nothing syncs, nothing is sent")
        #expect(folder.bytes(LegacyFileNames.store) == damaged)
        #expect(UnreadableWorkspaceCopy.title == "We couldn't open your tasks")
        #expect(UnreadableWorkspaceCopy.message == "Your tasks are still on this Mac and nothing was changed.")
        #expect(UnreadableWorkspaceCopy.tryAgain == "Try again" && UnreadableWorkspaceCopy.startFresh == "Start fresh…")
        #expect(UnreadableWorkspaceCopy.confirmTitle == "Set the file aside and start fresh?")
        #expect(UnreadableWorkspaceCopy.keepTrying == "Keep trying" && UnreadableWorkspaceCopy.confirm == "Set aside and start fresh")
    }

    @Test("021-FR-022 a store.json written by a newer version is X-09 too")
    func newerDocumentShowsX09() async throws {
        let folder = TemporaryFolder()
        try Data("{\"version\": 99, \"generation\": 1}".utf8).write(to: folder.store)
        let host = try #require(await launch(folder, transport: CountingTransport()))
        #expect(host.workspace.loadError != nil)
    }

    @Test("021-FR-022 “Try again” reloads")
    func tryAgainReloads() async throws {
        let folder = TemporaryFolder()
        try Data("garbage".utf8).write(to: folder.store)
        let host = try #require(await launch(folder, transport: CountingTransport()))
        #expect(host.workspace.loadError != nil)
        let readable = StoreDocument(generation: 1, outbox: [
            PendingOperation(command: .createTask(.init(taskID: "t1", title: "Call the landlord", list: .inbox)), issuedAt: TestClock.importTime),
        ])
        try StoreDocumentCoding.encode(readable).write(to: folder.store)
        await host.retryLoad()
        #expect(host.workspace.loadError == nil)
        #expect(host.workspace.state.tasks.values.map(\.title) == ["Call the landlord"])
    }

    @Test("021-FR-022 021-FR-033 “Start fresh” sets the file aside, opens an empty workspace, and a later local-gtd.json is not imported")
    func startFreshThenNoImport() async throws {
        let folder = TemporaryFolder()
        let damaged = Data("garbage".utf8)
        try damaged.write(to: folder.store)
        let transport = CountingTransport()
        let host = try #require(await launch(folder, transport: transport))
        await host.startFresh()

        #expect(host.workspace.loadError == nil && host.workspace.state == .empty)
        let aside = try #require(folder.names.first { $0.hasPrefix("store.unreadable-") })
        #expect(folder.bytes(aside) == damaged, "the unreadable file is kept, set aside")
        #expect(!MacFiles.exists(folder.store))

        let legacy = try Fixture.install("legacy-populated", in: folder)
        let result = try LegacyImportCoordinator.forTest(folder).run()
        #expect(result.notices == [.laterFile(file: folder.legacy)], "the folder is in use: a later file, never imported")
        #expect(folder.bytes(LegacyFileNames.legacy) == legacy && !MacFiles.exists(folder.store))
        #expect(transport.requests.isEmpty)
    }
}

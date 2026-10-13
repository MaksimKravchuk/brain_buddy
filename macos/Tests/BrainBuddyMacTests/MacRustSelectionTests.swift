import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The Mac follows the same runtime selection as the iOS app (spec 026, T044): a file in its own
/// folder, written only by an import the pilot switch allowed, read by every launch after.
@Suite("Mac runtime selection (026-FR-025)")
@MainActor
struct MacRustSelectionTests {
    private func makeLaunch(_ folder: TemporaryFolder, pilot: Bool) throws -> MacLaunch {
        let suite = "mac-rust-\(UUID().uuidString)"
        let switchBox = RustRuntimePilotSwitch(suiteName: suite)
        switchBox.set(pilot)
        let configuration = MacHostConfiguration(directory: folder.url, isDryRun: false)
        return MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: configuration, tokenStore: SpyTokenStore(), transport: CountingTransport(),
                cookieJar: FakeCookieJar(), responseCache: FakeResponseCache(), now: TestClock().provider,
                makeID: SequentialIDs().provider, log: CapturingMacLog(),
                rustRuntime: try .mac(configuration, tokenStore: SpyTokenStore()), rustPilot: switchBox))
    }

    @Test("026-FR-025: with the pilot switch off the Mac launches the legacy runtime and writes no selection")
    func pilotOff() async throws {
        let folder = TemporaryFolder()
        let launch = try makeLaunch(folder, pilot: false)
        await launch.run { _ in }
        let host = try #require(launch.host)
        #expect(!host.workspace.isRustSelected)
        #expect(!FileManager.default.fileExists(atPath: folder.url.appendingPathComponent("runtime").path))
    }

    @Test("026-FR-025: with the pilot switch on the Mac selects the Rust runtime once and keeps it at the next launch")
    func pilotOnSelectsAndSticks() async throws {
        let folder = TemporaryFolder()
        let first = try makeLaunch(folder, pilot: true)
        await first.run { _ in }
        let host = try #require(first.host)
        #expect(host.workspace.isRustSelected && host.workspace.isRustBound)
        let record = try #require(try RustRuntimeSelectionStore(location: .directory(folder.url)).load())
        #expect(record.runtime == .rust && record.account == nil)
        await host.workspace.closeRuntime()

        // Switch off again: the selection stays, the work is in the Rust store.
        let second = try makeLaunch(folder, pilot: false)
        await second.run { _ in }
        let again = try #require(second.host)
        #expect(again.workspace.isRustSelected)
        #expect(try RustRuntimeSelectionStore(location: .directory(folder.url)).load()?.workspaceID == record.workspaceID)
        await again.workspace.closeRuntime()
    }

    @Test("026-FR-025: a selected install whose bridge cannot initialize is unavailable, never legacy")
    func selectedInstallWithFailingBridgeIsUnavailable() async throws {
        let folder = TemporaryFolder()
        let first = try makeLaunch(folder, pilot: true)
        await first.run { _ in }
        let selected = try #require(first.host)
        await selected.workspace.closeRuntime()

        // The next launch cannot build a Rust environment (`live` leaves it nil when `.mac` throws).
        let configuration = MacHostConfiguration(directory: folder.url, isDryRun: false)
        let failing = MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: configuration, tokenStore: SpyTokenStore(), transport: CountingTransport(),
                cookieJar: FakeCookieJar(), responseCache: FakeResponseCache(), now: TestClock().provider,
                makeID: SequentialIDs().provider, log: CapturingMacLog(), rustRuntime: nil))
        await failing.run { _ in }
        #expect(failing.importFailed && failing.host == nil)
    }

    @Test("026-FR-025: an unselected install with no bridge still launches legacy")
    func unselectedInstallWithFailingBridgeStaysLegacy() async throws {
        let folder = TemporaryFolder()
        let configuration = MacHostConfiguration(directory: folder.url, isDryRun: false)
        let launch = MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: configuration, tokenStore: SpyTokenStore(), transport: CountingTransport(),
                cookieJar: FakeCookieJar(), responseCache: FakeResponseCache(), now: TestClock().provider,
                makeID: SequentialIDs().provider, log: CapturingMacLog(), rustRuntime: nil))
        await launch.run { _ in }
        #expect(try #require(launch.host).workspace.isRustSelected == false)
    }

    @Test("026-FR-025: a selection that cannot be read stops the launch instead of opening the retired file")
    func unreadableSelectionStopsTheLaunch() async throws {
        let folder = TemporaryFolder()
        let runtime = folder.url.appendingPathComponent("runtime", isDirectory: true)
        try FileManager.default.createDirectory(at: runtime, withIntermediateDirectories: true)
        try Data("garbage".utf8).write(to: runtime.appendingPathComponent("selection.json"))
        let launch = try makeLaunch(folder, pilot: true)
        await launch.run { _ in }
        #expect(launch.importFailed && launch.host == nil)
    }
}

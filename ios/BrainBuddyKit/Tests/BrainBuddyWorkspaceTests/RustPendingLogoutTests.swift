import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import BrainBuddySync
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyWorkspace

/// A sign-out that could not reach the server is not forgotten by the Rust runtime (review of
/// PR #398): the pending logout waits in the token store and is sent, by the legacy engine's rule,
/// when the network is back, with or without a sync session.
@Suite("Rust runtime pending logouts (026-FR-003, 026-FR-025)")
struct RustPendingLogoutTests {
    private static let email = "ada@example.com"
    private static let password = "correct horse battery"

    private func fixture() -> (server: FakeBrainBuddyServer, transport: FakeServerTransport, tokens: InMemorySessionTokenStore,
                               api: APIRustAccountServer) {
        let clock = ManualClock()
        let server = FakeBrainBuddyServer(now: clock.provider)
        server.addAccount(email: Self.email, password: Self.password, displayName: "Ada")
        let transport = server.makeTransport()
        let tokens = InMemorySessionTokenStore()
        return (server, transport, tokens, APIRustAccountServer(tokenStore: tokens, transport: transport, identity: .iOS))
    }

    @Test("026-FR-003: an offline sign-out leaves a pending logout that the drain sends and clears once online")
    func offlineSignOutIsDrained() async throws {
        let (server, transport, tokens, api) = fixture()
        let login = try await api.login(serverURL: FakeBrainBuddyServer.baseURL, email: Self.email, password: Self.password)
        let ticket = try await api.beginSignOut(of: login.account)
        transport.inject(.offline)
        await api.finishSignOut(ticket, of: login.account)

        #expect(try tokens.token(for: FakeBrainBuddyServer.baseURL) == nil)
        #expect(try tokens.pendingLogouts().count == 1)
        #expect(server.liveSessionCount(email: Self.email) == 1)

        transport.clearFaults()
        await api.drainPendingLogouts()
        #expect(try tokens.pendingLogouts().isEmpty)
        #expect(server.liveSessionCount(email: Self.email) == 0)
    }

    @Test("026-FR-003: a retryable failure keeps the pending logout for the next drain")
    func retryableFailureKeepsIt() async throws {
        let (server, transport, tokens, api) = fixture()
        let login = try await api.login(serverURL: FakeBrainBuddyServer.baseURL, email: Self.email, password: Self.password)
        let ticket = try await api.beginSignOut(of: login.account)
        transport.inject(.offline, times: 2)
        await api.finishSignOut(ticket, of: login.account)
        await api.drainPendingLogouts()
        #expect(try tokens.pendingLogouts().count == 1, "still offline: kept")
        await api.drainPendingLogouts()
        #expect(try tokens.pendingLogouts().isEmpty)
        #expect(server.liveSessionCount(email: Self.email) == 0)
    }

    @Test("026-FR-003: the workspace drains pending logouts when the network comes back, with no sync session")
    @MainActor
    func workspaceDrainsOnNetworkRestored() async throws {
        let harness = Harness()
        defer { harness.cleanup() }
        let counter = DrainCounter()
        let workspace = try await harness.workspace(
            scope: "local-drain", account: nil, lifecycle: CountingDrainLifecycle(counter: counter))
        await workspace.waitForLogoutDrain()
        let atLaunch = counter.value
        #expect(atLaunch >= 1, "a launch drains what an earlier session left")

        workspace.networkAvailabilityChanged(isAvailable: false)
        await workspace.waitForNetworkUpdates()
        #expect(counter.value == atLaunch, "offline: nothing to send")
        workspace.networkAvailabilityChanged(isAvailable: true)
        await workspace.waitForNetworkUpdates()
        await workspace.waitForLogoutDrain()
        #expect(counter.value == atLaunch + 1)
        await workspace.closeRuntime()
    }
}

final class DrainCounter: Sendable {
    private let count = Mutex(0)
    var value: Int { count.withLock { $0 } }
    func bump() { count.withLock { $0 += 1 } }
}

struct CountingDrainLifecycle: RustAccountLifecyclePort {
    let counter: DrainCounter

    func signIn(_ request: RustSignInRequest) async throws -> RustSignInOutcome { throw CancellationError() }
    func signOut(_ request: RustSignOutRequest) async throws -> RustWorkspaceSelection { throw CancellationError() }
    func drainPendingLogouts() async { counter.bump() }
}

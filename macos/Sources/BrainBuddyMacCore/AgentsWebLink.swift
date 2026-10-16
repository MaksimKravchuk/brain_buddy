import BrainBuddyAPI
import Foundation
import Observation

/// The public `GET /auth/methods` read that reports the web origin (spec 028-FR-019).
package protocol WebOriginRemote: Sendable {
    func authMethods() async throws(APIError) -> AuthMethodsDTO
}

extension BrainBuddyAPIClient: WebOriginRemote {}

/// S-03: the web agents page address. The origin comes from the account's server (or the default
/// server when signed out), is validated by the kit's destination builder, and the URL never
/// carries a credential, query or fragment (028-SC-006).
@MainActor
@Observable
package final class AgentsWebLink {
    package enum State: Equatable, Sendable {
        case loading, ready(URL), unavailable
    }

    package private(set) var state: State = .loading
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private let remote: @MainActor (URL) -> any WebOriginRemote
    @ObservationIgnored private let log: any MacLogSink

    package init(
        remote: @escaping @MainActor (URL) -> any WebOriginRemote = AgentsWebLink.liveRemote,
        log: any MacLogSink = SystemMacLog()
    ) {
        self.remote = remote
        self.log = log
    }

    package static func liveRemote(for server: URL) -> any WebOriginRemote {
        BrainBuddyAPIClient(
            baseURL: server, tokenStore: WorkspaceHost.systemTokenStore(), identity: WorkspaceHost.clientIdentity)
    }

    /// Reads the origin from `server`; the latest call wins and a late answer is dropped.
    package func load(server: URL) async {
        generation += 1
        let ticket = generation
        state = .loading
        let client = remote(server)
        let origin = await Self.readOrigin(client)
        guard ticket == generation else { return }
        if let origin, let url = NativeAccountDestination.agentsURL(origin: origin) {
            state = .ready(url)
        } else {
            state = .unavailable
        }
        log.log(.sync, "agents-link stage=origin outcome=\(state == .unavailable ? "unavailable" : "ready")")
    }

    private nonisolated static func readOrigin(_ remote: any WebOriginRemote) async -> String? {
        do throws(APIError) { return try await remote.authMethods().webAccountOrigin } catch { return nil }
    }
}

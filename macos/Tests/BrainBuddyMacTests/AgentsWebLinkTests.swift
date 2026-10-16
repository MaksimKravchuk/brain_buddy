import BrainBuddyAPI
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyMacCore

/// Answers `authMethods()` with a scripted origin.
final class FakeWebOriginRemote: WebOriginRemote {
    private let origin: Result<String?, APIError>

    init(origin: Result<String?, APIError>) { self.origin = origin }

    func authMethods() async throws(APIError) -> AuthMethodsDTO {
        let value = try origin.get()
        let json = value.map { #"{"password":true,"google":false,"apple":false,"email":true,"web_account_origin":"\#($0)"}"# }
            ?? #"{"password":true,"google":false,"apple":false,"email":true}"#
        return try! BrainBuddyAPI.makeDecoder().decode(AuthMethodsDTO.self, from: Data(json.utf8))
    }
}

/// The servers the link built a remote for.
final class ServerLog: Sendable {
    let urls = Mutex<[URL]>([])
}

@MainActor
@Suite("028 Agents web link")
struct AgentsWebLinkTests {
    private let server = URL(string: "https://api.example.com/api")!

    private func makeLink(
        _ origin: Result<String?, APIError>, servers: ServerLog = ServerLog(), log: CapturingMacLog = CapturingMacLog()
    ) -> AgentsWebLink {
        AgentsWebLink(
            remote: { url in
                servers.urls.withLock { $0.append(url) }
                return FakeWebOriginRemote(origin: origin)
            }, log: log)
    }

    @Test("028_FR_019 a reported https origin becomes the agents page URL without a credential")
    func readyForHTTPSOrigin() async {
        let servers = ServerLog()
        let link = makeLink(.success("https://app.example.com"), servers: servers)
        #expect(link.state == .loading)
        await link.load(server: server)
        #expect(link.state == .ready(URL(string: "https://app.example.com/settings/agents")!))
        #expect(servers.urls.withLock { $0 } == [server], "the origin is asked of the server it was given")
    }

    @Test("028_FR_019 localhost over http is accepted")
    func readyForLocalhost() async {
        let link = makeLink(.success("http://localhost:5173"))
        await link.load(server: server)
        #expect(link.state == .ready(URL(string: "http://localhost:5173/settings/agents")!))
    }

    @Test("028_FR_019 028_SC_006 an origin that is not https, has user info or a path is unavailable")
    func unavailableForUnsafeOrigins() async {
        for origin in ["http://app.example.com", "https://user:pw@app.example.com", "https://app.example.com/x", "https://app.example.com?a=b"] {
            let link = makeLink(.success(origin))
            await link.load(server: server)
            #expect(link.state == .unavailable, "\(origin)")
        }
    }

    @Test("028_FR_019 a missing origin or a failed read is unavailable")
    func unavailableWithoutOrigin() async {
        for origin: Result<String?, APIError> in [.success(nil), .failure(APIError(kind: .network("down"), message: "down"))] {
            let link = makeLink(origin)
            await link.load(server: server)
            #expect(link.state == .unavailable)
        }
    }

    @Test("028_FR_018 the log says only the outcome")
    func logHasNoAddress() async {
        let log = CapturingMacLog()
        await makeLink(.success("https://app.example.com"), log: log).load(server: server)
        let lines = log.messages(.sync)
        #expect(lines == ["agents-link stage=origin outcome=ready"])
    }
}

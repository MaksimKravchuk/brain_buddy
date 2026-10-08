import Foundation
import Testing

@testable import BrainBuddyAPI

@Suite("Client identity")
struct ClientIdentityTests {
    /// The one request `listTags` sends through a client built by `make`.
    private func sent(_ make: (ScriptedTransport) -> BrainBuddyAPIClient) async throws -> HTTPRequest {
        let transport = ScriptedTransport([Fixture.json(200, "[]")])
        _ = try await make(transport).listTags()
        return try #require(transport.lastRequest)
    }

    private func client(
        _ transport: ScriptedTransport, version: String? = nil, identity: ClientIdentity = .iOS,
        correlationID: @escaping @Sendable () -> UUID = { Fixture.correlationID }
    ) -> BrainBuddyAPIClient {
        BrainBuddyAPIClient(
            baseURL: Fixture.baseURL, transport: transport, tokenStore: InMemorySessionTokenStore(),
            clientVersion: version, identity: identity, correlationID: correlationID)
    }

    @Test("021-FR-031 the iPhone identity is brainbuddy-ios and the macOS one carries the app version")
    func names() {
        #expect(ClientIdentity.iOS.name == "brainbuddy-ios")
        #expect(ClientIdentity.macOS(version: "0.1.0") == ClientIdentity(name: "brainbuddy-macos", version: "0.1.0"))
    }

    @Test("021-FR-031 a macOS identity sends X-Client: brainbuddy-macos/<version>")
    func macOSHeader() async throws {
        let request = try await sent { client($0, identity: .macOS(version: "0.1.0")) }
        #expect(request.header("X-Client") == "brainbuddy-macos/0.1.0")
    }

    @Test("021-FR-031 without an identity the iPhone value goes out, with the configured version")
    func iOSHeaderByDefault() async throws {
        #expect(try await sent { Fixture.client($0) }.header("X-Client") == "brainbuddy-ios/1.2.3")
        #expect(try await sent { client($0, version: "7") }.header("X-Client") == "brainbuddy-ios/7")
    }

    @Test("021-FR-015 021-FR-031 every request has its own lower-cased UUID correlation id")
    func correlationIDs() async throws {
        let first = try await sent { client($0, correlationID: { UUID() }) }.header("X-Correlation-ID")
        let second = try await sent { client($0, correlationID: { UUID() }) }.header("X-Correlation-ID")
        for id in [first, second] {
            let text = try #require(id)
            #expect(UUID(uuidString: text) != nil && text == text.lowercased())
        }
        #expect(first != second)
    }

    @Test("021-FR-015 a timeout error carries the correlation id that was sent, so server logs can match it")
    func timeoutKeepsTheSentID() async throws {
        let transport = ScriptedTransport([
            .fail(TransportError(description: "timed out", requestMayHaveBeenSent: true))
        ])
        let client = Fixture.client(transport)
        let error = await expectAPIError { _ = try await client.listTags() }
        #expect(error?.referenceID == Fixture.correlationHeader)
        #expect(transport.lastRequest?.header("X-Correlation-ID") == Fixture.correlationHeader)
    }
}

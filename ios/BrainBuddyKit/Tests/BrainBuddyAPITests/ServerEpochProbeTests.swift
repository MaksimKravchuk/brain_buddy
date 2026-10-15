import Foundation
import Testing

@testable import BrainBuddyAPI

@Suite("Server epoch probe")
struct ServerEpochProbeTests {
    private func probe(_ transport: ScriptedTransport) -> ServerEpochProbe {
        ServerEpochProbe(baseURL: Fixture.baseURL, transport: transport)
    }

    @Test("027-FR-018 every API request carries X-Client-Epoch")
    func apiClientSendsEpoch() async throws {
        let transport = ScriptedTransport([Fixture.json(200, "[]")])
        _ = try await Fixture.client(transport).listTags()
        let request = try #require(transport.lastRequest)
        #expect(request.header("X-Client-Epoch") == String(ClientEpoch.current))
        #expect(request.header("X-Client") == "brainbuddy-ios/1.2.3")
    }

    @Test("027-FR-021 the probe reads a 404 as the old server, epoch 0, without a cookie")
    func legacyServer() async throws {
        let transport = ScriptedTransport([Fixture.json(404, #"{"detail":"Not Found"}"#)])
        let epoch = try await probe(transport).probe()
        #expect(epoch == .legacy)
        #expect(epoch.serverEpoch == 0)
        let request = try #require(transport.lastRequest)
        #expect(request.url.absoluteString == "https://api.example.test/api/meta")
        #expect(request.method == .get)
        #expect(request.header("Cookie") == nil)
        #expect(request.header("X-Client-Epoch") == String(ClientEpoch.current))
    }

    @Test("027-FR-021 the probe reads the new server's meta body")
    func newServer() async throws {
        let transport = ScriptedTransport([Fixture.json(200, #"{"server_epoch":1,"min_client_epoch":1}"#)])
        let epoch = try await probe(transport).probe()
        #expect(epoch == ServerEpoch(serverEpoch: 1, minClientEpoch: 1))
    }

    @Test("027-FR-021 a 5xx or unreadable body is an error, not epoch 0")
    func unreadable() async {
        for step in [Fixture.json(503, "{}"), Fixture.json(200, "not json")] {
            let transport = ScriptedTransport([step])
            await #expect(throws: ServerEpochProbeError.self) { try await probe(transport).probe() }
        }
    }

    @Test("027-FR-021 a transport failure propagates")
    func offline() async {
        let transport = ScriptedTransport([.fail(TransportError(description: "offline", requestMayHaveBeenSent: false))])
        await #expect(throws: TransportError.self) { try await probe(transport).probe() }
    }

    @Test("027-FR-018 X-Server-Epoch is observed on any response, and absent on the old server")
    func observed() {
        #expect(ServerEpochProbe.observed(in: HTTPResponse(statusCode: 200, headers: ["x-server-epoch": "1"])) == 1)
        #expect(ServerEpochProbe.observed(in: HTTPResponse(statusCode: 200)) == nil)
    }
}

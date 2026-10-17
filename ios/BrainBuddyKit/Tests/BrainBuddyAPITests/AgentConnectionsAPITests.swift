import Foundation
import Testing

@testable import BrainBuddyAPI

/// Fixtures are `AgentConnectionResponse` field for field (`backend/app/schemas/agents.py`).
private enum AgentFixture {
    static func connection(
        id: String = "agent_conn_1", status: String = "ready", scheme: String = "bearer",
        headerName: String? = nil, stale: Bool = false, ready: Bool = true, card: String? = nil,
        errorCode: String? = nil, revision: Int = 3
    ) -> String {
        let header = headerName.map { "\"\($0)\"" } ?? "null"
        let error = errorCode.map { "\"\($0)\"" } ?? "null"
        let cardJSON = card ?? "null"
        return #"""
            {"id":"\#(id)","name":"Research agent","agent_address":"https://agent.example.org","auth_scheme":"\#(scheme)",\#
            "auth_header_name":\#(header),"status":"\#(status)","stale":\#(stale),"ready_for_handoff":\#(ready),\#
            "capabilities":{"streaming":true,"push_notifications":false},"controls_offered":{"reply":true,"cancel":true},\#
            "card":\#(cardJSON),"guarantee_tier":"best_effort","tier_disclosure":"Updates may be delayed.",\#
            "tier_disclosure_url":null,"cancellation_disclosure":"Stopping asks the agent to stop.","agent_changed":false,\#
            "best_effort_acknowledged_at":null,"correlation_id_honoured":null,"disconnect_reason":null,\#
            "last_test_error_code":\#(error),"last_test_error_detail":null,"last_contact_at":"2026-10-16T09:00:00Z",\#
            "last_tested_at":"2026-10-16T08:00:00.250000Z","stale_after_seconds":900,"created_at":"2026-10-01T08:00:00Z",\#
            "revision":\#(revision)}
            """#
    }

    static let card = #"""
        {"name":"Researcher","version":"1.2","description":"Finds things","protocol_version":"0.3.0",\#
        "interface_url":"https://agent.example.org/a2a","streaming":true,"push_notifications":false,\#
        "skills":[{"id":"s1","name":"Search","description":"Looks up"}],\#
        "auth_schemes_offered":[{"name":"bearerAuth","kind":"bearer","header_name":null},\#
        {"name":"oauth","kind":"oauth2","header_name":null}],"extension_uris":[],"fetched_at":"2026-10-16T08:00:00Z"}
        """#

    static func relayOff() -> ScriptedTransport.Step {
        Fixture.error(404, "External agent relay is not available.")
    }
}

@Suite("030 agent connections API")
struct AgentConnectionsAPITests {
    private func client(_ steps: [ScriptedTransport.Step]) -> (BrainBuddyAPIClient, ScriptedTransport) {
        let transport = ScriptedTransport(steps)
        return (Fixture.client(transport, store: Fixture.signedInStore()), transport)
    }

    // MARK: requests

    @Test("030-FR-029 list and read send GET to the documented paths with no body and no key")
    func agentConnectionsReadRequests_030_FR_029() async throws {
        let (api, transport) = client([
            Fixture.json(200, "[\(AgentFixture.connection())]"), Fixture.json(200, AgentFixture.connection(id: "a/b")),
        ])
        let list = try await api.agentConnections()
        let one = try await api.agentConnection(id: "a/b")
        let requests = transport.requests
        #expect(list.count == 1)
        #expect(one.id == "a/b")
        #expect(requests.map(\.method) == [.get, .get])
        #expect(requests.map(\.url.path) == ["/api/agent-connections", "/api/agent-connections/a/b"])
        #expect(requests.map(\.url.absoluteString).last?.hasSuffix("/agent-connections/a%2Fb") == true)
        #expect(requests.allSatisfy { $0.body == nil && $0.header("Idempotency-Key") == nil })
        #expect(requests.allSatisfy { $0.header("Cookie") == "brainbuddy_session=\(Fixture.token)" })
    }

    @Test("030-FR-031 create posts name, address, scheme, credential and password with the key")
    func createAgentConnectionRequest_030_FR_031() async throws {
        let (api, transport) = client([Fixture.json(201, AgentFixture.connection(status: "untested", ready: false))])
        let created = try await api.createAgentConnection(
            name: "Research agent", address: "https://agent.example.org", scheme: .apiKey, credential: "s3cret-token",
            currentPassword: "hunter2-pw", idempotencyKey: Fixture.key)
        let request = try #require(transport.lastRequest)
        #expect(created.status == .untested)
        #expect(request.method == .post)
        #expect(request.url.path == "/api/agent-connections")
        #expect(request.header("Idempotency-Key") == Fixture.keyHeader)
        #expect(request.header("Content-Type") == "application/json")
        #expect(
            request.bodyText
                == #"{"agent_address":"https://agent.example.org","auth_scheme":"api_key","credential":"s3cret-token","current_password":"hunter2-pw","name":"Research agent"}"#
        )
    }

    @Test("030-FR-033 update sends current_password only when given, and omits nil fields")
    func updateAgentConnectionPassword_030_FR_033() async throws {
        let (api, transport) = client([
            Fixture.json(200, AgentFixture.connection(revision: 4)), Fixture.json(200, AgentFixture.connection(revision: 5)),
        ])
        _ = try await api.updateAgentConnection(
            id: "agent_conn_1", name: "Renamed", address: nil, scheme: nil, currentPassword: nil, expectedRevision: 3,
            idempotencyKey: Fixture.key)
        _ = try await api.updateAgentConnection(
            id: "agent_conn_1", name: nil, address: "https://new.example.org", scheme: .bearer,
            currentPassword: "hunter2-pw", expectedRevision: 4, idempotencyKey: Fixture.key)
        let requests = transport.requests
        #expect(requests.map(\.method) == [.put, .put])
        #expect(requests.map(\.url.path) == Array(repeating: "/api/agent-connections/agent_conn_1", count: 2))
        #expect(requests.allSatisfy { $0.header("Idempotency-Key") == Fixture.keyHeader })
        #expect(requests[0].bodyText == #"{"expected_revision":3,"name":"Renamed"}"#)
        #expect(
            requests[1].bodyText
                == #"{"agent_address":"https://new.example.org","auth_scheme":"bearer","current_password":"hunter2-pw","expected_revision":4}"#
        )
    }

    @Test("030-FR-029 test posts with no body and the key")
    func testAgentConnectionRequest_030_FR_029() async throws {
        let (api, transport) = client([Fixture.json(200, AgentFixture.connection(status: "unreachable", ready: false))])
        let tested = try await api.testAgentConnection(id: "agent_conn_1", idempotencyKey: Fixture.key)
        let request = try #require(transport.lastRequest)
        #expect(tested.status == .unreachable)
        #expect(request.method == .post)
        #expect(request.url.path == "/api/agent-connections/agent_conn_1/test")
        #expect(request.body == nil)
        #expect(request.header("Idempotency-Key") == Fixture.keyHeader)
    }

    @Test("030-FR-032 replace credential posts the credential, password and expected revision")
    func replaceAgentCredentialRequest_030_FR_032() async throws {
        let (api, transport) = client([Fixture.json(200, AgentFixture.connection(revision: 4))])
        _ = try await api.replaceAgentCredential(
            id: "agent_conn_1", credential: "new-secret", currentPassword: "hunter2-pw", expectedRevision: 3,
            idempotencyKey: Fixture.key)
        let request = try #require(transport.lastRequest)
        #expect(request.method == .post)
        #expect(request.url.path == "/api/agent-connections/agent_conn_1/credential")
        #expect(request.header("Idempotency-Key") == Fixture.keyHeader)
        #expect(
            request.bodyText == #"{"credential":"new-secret","current_password":"hunter2-pw","expected_revision":3}"#)
    }

    @Test("030-FR-035 disconnect posts the password and expected revision")
    func disconnectAgentConnectionRequest_030_FR_035() async throws {
        let (api, transport) = client([Fixture.json(200, AgentFixture.connection(status: "disconnected", ready: false))])
        let result = try await api.disconnectAgentConnection(
            id: "agent_conn_1", currentPassword: "hunter2-pw", expectedRevision: 3, idempotencyKey: Fixture.key)
        let request = try #require(transport.lastRequest)
        #expect(result.status == .disconnected)
        #expect(request.method == .post)
        #expect(request.url.path == "/api/agent-connections/agent_conn_1/disconnect")
        #expect(request.header("Idempotency-Key") == Fixture.keyHeader)
        #expect(request.bodyText == #"{"current_password":"hunter2-pw","expected_revision":3}"#)
    }

    // MARK: redaction

    @Test("030-FR-035 030-FR-034 bodies carrying a credential or password never print it")
    func requestBodiesAreRedacted_030_FR_035() {
        let secrets = ["s3cret-token", "hunter2-pw"]
        let bodies: [any RedactedRequestBody] = [
            AgentConnectionCreateBody(
                name: "n", agentAddress: "https://a.example.org", authScheme: .bearer, credential: secrets[0],
                currentPassword: secrets[1]),
            AgentConnectionUpdateBody(
                name: nil, agentAddress: "https://a.example.org", authScheme: nil, currentPassword: secrets[1],
                expectedRevision: 1),
            AgentCredentialBody(credential: secrets[0], currentPassword: secrets[1], expectedRevision: 1),
            AgentDisconnectBody(currentPassword: secrets[1], expectedRevision: 1),
        ]
        for body in bodies {
            var dumped = ""
            dump(body, to: &dumped)
            let texts = [String(describing: body), String(reflecting: body), "\(body)", body.debugDescription, dumped]
            for text in texts {
                for secret in secrets { #expect(!text.contains(secret), "\(text)") }
            }
        }
    }

    // MARK: decoding

    @Test("030-FR-030 a ready connection decodes with card, controls, tier, disclosures and revision")
    func decodesReadyConnection_030_FR_030() throws {
        let json = AgentFixture.connection(card: AgentFixture.card)
        let dto: AgentConnectionDTO = try BrainBuddyAPI.makeDecoder().decode(
            AgentConnectionDTO.self, from: Data(json.utf8))
        #expect(dto.id == "agent_conn_1")
        #expect(dto.name == "Research agent")
        #expect(dto.agentAddress == "https://agent.example.org")
        #expect(dto.authScheme == .bearer)
        #expect(dto.authHeaderName == nil)
        #expect(dto.status == .ready)
        #expect(dto.readyForHandoff)
        #expect(!dto.stale)
        #expect(dto.staleAfterSeconds == 900)
        #expect(dto.capabilities == AgentCapabilitiesDTO(streaming: true, pushNotifications: false))
        #expect(dto.controlsOffered == AgentControlsDTO(reply: true, cancel: true))
        #expect(dto.guaranteeTier == .bestEffort)
        #expect(dto.tierDisclosure == "Updates may be delayed.")
        #expect(dto.cancellationDisclosure == "Stopping asks the agent to stop.")
        #expect(dto.revision == 3)
        #expect(dto.lastContactAt == Fixture.utc(2026, 10, 16, 9))
        #expect(dto.lastTestedAt != nil)
        #expect(dto.card?.name == "Researcher")
        #expect(dto.card?.protocolVersion == "0.3.0")
        #expect(dto.card?.skills.map(\.name) == ["Search"])
        #expect(!String(describing: dto).contains("Research agent"))
        #expect(!String(describing: dto).contains("agent.example.org"))
    }

    @Test("030-FR-030 stale, unsupported and api key connections decode")
    func decodesStaleUnsupportedAndApiKey_030_FR_030() throws {
        let decoder = BrainBuddyAPI.makeDecoder()
        let stale = try decoder.decode(
            AgentConnectionDTO.self, from: Data(AgentFixture.connection(stale: true).utf8))
        #expect(stale.stale)
        #expect(stale.status == .ready)
        let unsupported = try decoder.decode(
            AgentConnectionDTO.self,
            from: Data(AgentFixture.connection(status: "unsupported", ready: false, errorCode: "unsupported_auth").utf8))
        #expect(unsupported.status == .unsupported)
        #expect(!unsupported.readyForHandoff)
        #expect(unsupported.lastTestErrorCode == "unsupported_auth")
        let apiKey = try decoder.decode(
            AgentConnectionDTO.self,
            from: Data(AgentFixture.connection(scheme: "api_key", headerName: "X-Agent-Key").utf8))
        #expect(apiKey.authScheme == .apiKey)
        #expect(apiKey.authHeaderName == "X-Agent-Key")
    }

    @Test("030-FR-042 unknown status, scheme and tier read leniently and a connection without a card decodes")
    func decodesUnknownValuesLeniently_030_FR_042() throws {
        let json = AgentFixture.connection(status: "quarantined", scheme: "mtls")
            .replacingOccurrences(of: "best_effort", with: "platinum")
        let dto = try BrainBuddyAPI.makeDecoder().decode(AgentConnectionDTO.self, from: Data(json.utf8))
        #expect(dto.status == .unknown("quarantined"))
        #expect(dto.authScheme == .unknown("mtls"))
        #expect(dto.guaranteeTier == .unknown("platinum"))
        #expect(dto.card == nil)
    }

    // MARK: error mapping

    @Test("030-FR-002 030-FR-042 the relay's 404 maps to relayUnavailable while APIError.from is unchanged")
    func relayUnavailableMapping_030_FR_002() async {
        let (api, _) = client([AgentFixture.relayOff(), Fixture.error(404, "This item no longer exists.")])
        let off = await expectAPIError { _ = try await api.agentConnections() }
        let missing = await expectAPIError { _ = try await api.agentConnection(id: "gone") }
        #expect(off?.kind == .notFound(resource: nil, id: nil))
        #expect(off?.agentFailure == .relayUnavailable)
        #expect(missing?.kind == .notFound(resource: nil, id: nil))
        #expect(missing?.agentFailure == .other)
    }

    @Test("030-FR-034 a 403 on a password-bearing call maps to wrongPassword and stays rejected")
    func wrongPasswordMapping_030_FR_034() async {
        let (api, _) = client([Fixture.error(403, "Current password is incorrect.")])
        let error = await expectAPIError {
            _ = try await api.disconnectAgentConnection(
                id: "agent_conn_1", currentPassword: "nope", expectedRevision: 3, idempotencyKey: Fixture.key)
        }
        #expect(error?.kind == .rejected)
        #expect(error?.statusCode == 403)
        #expect(error?.agentFailure == .wrongPassword)
    }

    @Test("030-FR-034 a stale revision, 429, offline and other failures map to typed agent failures")
    func otherFailureMapping_030_FR_034() async {
        let detail = #"{"resource":"Agent connection","id":"agent_conn_1"}"#
        let (api, _) = client([
            Fixture.error(409, "This agent changed elsewhere; reload and try again.", detail: detail),
            Fixture.error(409, "Agent connection 'x' already exists.", detail: detail),
            Fixture.error(429, "Too many attempts. Try again later."),
            .fail(TransportError(description: "offline", requestMayHaveBeenSent: false)),
            Fixture.error(500, "Boom"),
        ])
        func attempt() async -> AgentFailure? {
            let error = await expectAPIError {
                _ = try await api.replaceAgentCredential(
                    id: "agent_conn_1", credential: "c", currentPassword: "p", expectedRevision: 3,
                    idempotencyKey: Fixture.key)
            }
            return error?.agentFailure
        }
        var results: [AgentFailure?] = []
        for _ in 0..<5 { results.append(await attempt()) }
        #expect(results == [.staleRevision, .other, .rateLimited, .offline, .other])
    }

    @Test("030-FR-042 APIError.from still maps the relay's 403 and 404 as before")
    func apiErrorFromUnchanged_030_FR_042() {
        let forbidden = APIError.from(
            response: HTTPResponse(
                statusCode: 403, headers: [:],
                body: Data(#"{"message":"Current password is incorrect.","detail":null,"reference_id":"r"}"#.utf8)),
            sentCorrelationID: nil)
        #expect(forbidden.kind == .rejected)
        #expect(forbidden.statusCode == 403)
        let missing = APIError.from(
            response: HTTPResponse(
                statusCode: 404, headers: [:],
                body: Data(#"{"message":"External agent relay is not available.","detail":null,"reference_id":"r"}"#.utf8)),
            sentCorrelationID: nil)
        #expect(missing.kind == .notFound(resource: nil, id: nil))
    }
}

import Foundation
import Testing

@testable import BrainBuddyAPI

@Suite("028 account summary and agents destination")
struct AccountAPITests {
    @Test("028-FR-006 028-FR-007 028-FR-024 GET /account decodes the summary and ignores other fields")
    func summaryRequestAndDecoding() async throws {
        let body = #"""
            {"id":"user_1a2b3c4d5e6f","email":"max@example.com","display_name":"Max","completed_task_count":214,\#
            "created_at":"2026-01-02T03:04:05Z","deletion_requested_at":null,"purge_at":null,"future_field":{"a":1}}
            """#
        let transport = ScriptedTransport([Fixture.json(200, body)])
        let summary = try await Fixture.client(transport, store: Fixture.signedInStore()).accountSummary()
        #expect(transport.lastRequest?.method == .get)
        #expect(transport.lastRequest?.url.path == "/api/account")
        #expect(transport.lastRequest?.url.query == nil)
        #expect(summary.id == "user_1a2b3c4d5e6f")
        #expect(summary.email == "max@example.com")
        #expect(summary.displayName == "Max")
        #expect(summary.completedTaskCount == 214)
        #expect(!String(describing: summary).contains("max@example.com"))
    }

    @Test("028-FR-006 a null display_name decodes to nil")
    func summaryWithoutName() async throws {
        let body = #"{"id":"u1","email":"a@example.com","display_name":null,"completed_task_count":0}"#
        let transport = ScriptedTransport([Fixture.json(200, body)])
        let summary = try await Fixture.client(transport, store: Fixture.signedInStore()).accountSummary()
        #expect(summary.displayName == nil)
        #expect(summary.completedTaskCount == 0)
    }

    @Test("028-FR-017 a 401 maps to unauthorized with the reference id")
    func summaryUnauthorized() async {
        let transport = ScriptedTransport([Fixture.error(401, "Not signed in")])
        let client = Fixture.client(transport, store: Fixture.signedInStore())
        let error = await expectAPIError { _ = try await client.accountSummary() }
        #expect(error?.kind == .unauthorized)
        #expect(error?.referenceID == "ref-server-1")
    }

    @Test("028-FR-019 028-SC-006 agentsURL accepts https and localhost http origins")
    func agentsURLAccepts() {
        #expect(NativeAccountDestination.agentsURL(origin: "https://app.example.com")?.absoluteString
            == "https://app.example.com/settings/agents")
        #expect(NativeAccountDestination.agentsURL(origin: "https://app.example.com/")?.absoluteString
            == "https://app.example.com/settings/agents")
        #expect(NativeAccountDestination.agentsURL(origin: "http://localhost:5173")?.absoluteString
            == "http://localhost:5173/settings/agents")
    }

    @Test("028-FR-019 028-SC-006 agentsURL rejects plain http, user info, path, query and fragment")
    func agentsURLRejects() {
        let rejected = [
            "http://app.example.com", "ftp://app.example.com", "https://user:pw@app.example.com",
            "https://user@app.example.com", "https://app.example.com/x", "https://app.example.com?a=b",
            "https://app.example.com/?a=b", "https://app.example.com#frag", "", "not a url", "https://",
        ]
        for origin in rejected {
            #expect(NativeAccountDestination.agentsURL(origin: origin) == nil, "\(origin)")
        }
    }

    @Test("028-FR-019 028-SC-006 agentsURL carries no query or credential")
    func agentsURLHasNoCredential() throws {
        let url = try #require(NativeAccountDestination.agentsURL(origin: "https://app.example.com"))
        #expect(url.query == nil)
        #expect(url.user == nil)
        #expect(url.fragment == nil)
    }
}

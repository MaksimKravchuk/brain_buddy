import Foundation
import Testing

@testable import BrainBuddyAPI

/// Spec 028 T008: `GET /account/export` through the shared client.
@Suite("028 account export client")
struct AccountExportAPITests {
    private static let archive = Data([0x50, 0x4B, 0x03, 0x04, 0x01, 0x02])

    private func zip(_ disposition: String?, status: Int = 200) -> ScriptedTransport.Step {
        var headers = ["content-type": "application/zip", "x-correlation-id": Fixture.correlationHeader]
        if let disposition { headers["Content-Disposition"] = disposition }
        return .respond(HTTPResponse(statusCode: status, headers: headers, body: Self.archive))
    }

    @Test("028-FR-012 the export is a GET of /account/export with the session and no query, and returns the bytes")
    func exportRequestPath() async throws {
        let transport = ScriptedTransport([zip(#"attachment; filename="brainbuddy-export-2026-10-16.zip""#)])
        let client = Fixture.client(transport, store: Fixture.signedInStore())

        let export = try await client.exportAccount()

        #expect(export.data == Self.archive)
        #expect(export.suggestedFileName == "brainbuddy-export-2026-10-16.zip")
        let request = try #require(transport.lastRequest)
        #expect(request.method == .get)
        #expect(request.url.path == "/api/account/export")
        #expect(request.url.query == nil)
        #expect(request.body == nil)
        #expect(request.header("Cookie") == "brainbuddy_session=\(Fixture.token)")
        #expect(request.header("X-Correlation-ID") == Fixture.correlationHeader)
        // 028-SC-006: the session travels in the cookie header only, never in the URL.
        #expect(!request.url.absoluteString.contains(Fixture.token))
    }

    @Test("028-FR-012 the suggested file name comes from Content-Disposition, path components stripped")
    func fileNameParsing() {
        let cases: [(header: String?, expected: String)] = [
            (#"attachment; filename="export.zip""#, "export.zip"),
            ("attachment; filename=export.zip", "export.zip"),
            (#"attachment; filename="a;b.zip""#, "a;b.zip"),
            (#"attachment; filename="a\"b.zip""#, #"a"b.zip"#),
            ("attachment; filename*=UTF-8''my%20data.zip", "my data.zip"),
            (#"attachment; filename="plain.zip"; filename*=UTF-8''better%20name.zip"#, "better name.zip"),
            ("attachment; filename*=ISO-8859-1''x.zip", AccountExport.fallbackFileName),
            (#"attachment; filename="../../evil.zip""#, "evil.zip"),
            (#"attachment; filename="..\..\evil.zip""#, "evil.zip"),
            (#"attachment; filename="/etc/passwd""#, "passwd"),
            ("attachment; filename*=UTF-8''..%2F..%2Fescape.zip", "escape.zip"),
            (#"attachment; filename="..""#, AccountExport.fallbackFileName),
            (#"attachment; filename="""#, AccountExport.fallbackFileName),
            (#"attachment; filename="dir/""#, "dir"),
            ("attachment", AccountExport.fallbackFileName),
            ("inline; size=3", AccountExport.fallbackFileName),
            (nil, AccountExport.fallbackFileName),
        ]
        for (header, expected) in cases {
            #expect(
                AccountExport.fileName(fromContentDisposition: header) == expected,
                "028-FR-012 header: \(header ?? "nil")")
        }
    }

    @Test("028-FR-012 a missing Content-Disposition falls back to brainbuddy-export.zip")
    func missingHeaderFallsBack() async throws {
        let transport = ScriptedTransport([zip(nil)])
        let export = try await Fixture.client(transport, store: Fixture.signedInStore()).exportAccount()
        #expect(export.suggestedFileName == "brainbuddy-export.zip")
    }

    @Test("028-FR-024 control characters are removed from a suggested name")
    func controlCharactersRemoved() {
        let name = AccountExport.fileName(fromContentDisposition: "attachment; filename=\"ex\u{0007}port.zip\"")
        #expect(name == "export.zip")
    }

    @Test("028-FR-017 failures map to the shared kinds and carry the reference id")
    func errorMappingWithReference() async {
        let cases: [(status: Int, check: @Sendable (APIError.Kind) -> Bool)] = [
            (401, { $0 == .unauthorized }),
            (429, { $0 == .rateLimited }),
            (500, { $0 == .server }),
            (503, { $0 == .server }),
        ]
        for (status, check) in cases {
            let transport = ScriptedTransport([Fixture.error(status, "No export today.")])
            let client = Fixture.client(transport, store: Fixture.signedInStore())
            let error = await expectAPIError { _ = try await client.exportAccount() }
            #expect(error.map { check($0.kind) } == true, "028-FR-017 HTTP \(status)")
            #expect(error?.referenceID == "ref-server-1", "028-FR-017 HTTP \(status) reference")
            #expect(error?.statusCode == status)
        }
    }

    @Test("028-FR-017 a response without a body envelope still carries the correlation id as reference")
    func referenceFallsBackToCorrelationID() async {
        let transport = ScriptedTransport([.respond(HTTPResponse(statusCode: 502, body: Data("<html>".utf8)))])
        let client = Fixture.client(transport, store: Fixture.signedInStore())
        let error = await expectAPIError { _ = try await client.exportAccount() }
        #expect(error?.kind == .server)
        #expect(error?.referenceID == Fixture.correlationHeader)
    }

    @Test("028-FR-017 no connection is a network failure that quotes the correlation id")
    func offlineIsNetwork() async {
        let transport = ScriptedTransport([
            .fail(TransportError(description: "offline", requestMayHaveBeenSent: false))
        ])
        let client = Fixture.client(transport, store: Fixture.signedInStore())
        let error = await expectAPIError { _ = try await client.exportAccount() }
        guard case .network = error?.kind else {
            Issue.record("Expected .network, got \(String(describing: error?.kind))")
            return
        }
        #expect(error?.referenceID == Fixture.correlationHeader)
    }

    @Test("028-FR-013 cancelling the transport ends the export as .cancelled")
    func transportCancellation() async {
        let transport = ScriptedTransport([
            .fail(TransportError(description: "cancelled", requestMayHaveBeenSent: true, isCancellation: true))
        ])
        let client = Fixture.client(transport, store: Fixture.signedInStore())
        let error = await expectAPIError { _ = try await client.exportAccount() }
        #expect(error?.kind == .cancelled)
    }

    @Test("028-FR-013 a task cancelled before the request goes out sends nothing")
    func cancelledBeforeSending() async {
        let transport = ScriptedTransport()
        let client = Fixture.client(transport, store: Fixture.signedInStore())
        let task = Task { () -> APIError? in
            withUnsafeCurrentTask { $0?.cancel() }
            do { _ = try await client.exportAccount() } catch { return error }
            return nil
        }
        let error = await task.value
        #expect(error?.kind == .cancelled)
        #expect(error?.requestMayHaveBeenSent == false)
        #expect(transport.requests.isEmpty)
    }

    @Test("028-FR-018 the description never prints the archive or its name")
    func descriptionIsRedacted() {
        let export = AccountExport(suggestedFileName: "ada-lovelace-secret.zip", data: Self.archive)
        for text in [export.description, export.debugDescription, "\(export)", String(reflecting: export)] {
            #expect(text == "AccountExport(6 bytes)")
            #expect(!text.contains("ada"))
        }
    }
}

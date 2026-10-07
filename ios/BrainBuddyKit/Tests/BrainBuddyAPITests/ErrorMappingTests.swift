import Foundation
import Testing

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

@testable import BrainBuddyAPI

/// Error bodies below are the exact strings `backend/app/modules/tasks/service.py`,
/// `backend/app/api/*.py` and `backend/app/exceptions.py` produce.
@Suite("Error mapping")
struct ErrorMappingTests {
    private func failure(_ step: ScriptedTransport.Step, store: any SessionTokenStore = InMemorySessionTokenStore()) async throws
        -> APIError
    {
        let client = Fixture.client(ScriptedTransport([step]), store: store)
        return try #require(
            await expectAPIError {
                _ = try await client.updateTask(
                    id: "task_1a2b3c4d5e6f", TaskUpdateBody(expectedRevision: 7, title: .set("x")),
                    idempotencyKey: Fixture.key
                )
            }
        )
    }

    @Test("401 Authentication required")
    func unauthorized() async throws {
        let error = try await failure(Fixture.error(401, "Authentication required.", reference: "ref-401"))
        #expect(error.kind == .unauthorized)
        #expect(error.message == "Authentication required.")
        #expect(error.referenceID == "ref-401")
        #expect(error.statusCode == 401)
        #expect(!error.isRetryable)
        #expect(!error.isUncertainOutcome)
    }

    @Test("404 names the missing record from the detail")
    func notFound() async throws {
        let error = try await failure(
            Fixture.error(
                404, "Task 'task_1a2b3c4d5e6f' was not found.", detail: #"{"resource":"Task","id":"task_1a2b3c4d5e6f"}"#
            )
        )
        #expect(error.kind == .notFound(resource: "Task", id: "task_1a2b3c4d5e6f"))
        #expect(error.message == "Task 'task_1a2b3c4d5e6f' was not found.")
        #expect(!error.isRetryable)
    }

    @Test("404 for a referenced record names that record")
    func notFoundReference() async throws {
        let error = try await failure(
            Fixture.error(
                404, "Task subtask 'subtask_5e6f7a8b9c0d' was not found.",
                detail: #"{"resource":"Task subtask","id":"subtask_5e6f7a8b9c0d"}"#
            )
        )
        #expect(error.kind == .notFound(resource: "Task subtask", id: "subtask_5e6f7a8b9c0d"))
    }

    @Test("404 without a structured detail (unknown route)")
    func notFoundRoute() async throws {
        let error = try await failure(Fixture.error(404, "Not Found"))
        #expect(error.kind == .notFound(resource: nil, id: nil))
    }

    @Test(
        "409 stale revision for every resource",
        arguments: [
            ("Task", "task_1a2b3c4d5e6f"), ("Project", "project_0a1b2c3d4e5f"), ("Tag", "tag_0a1b2c3d4e5f"),
            ("Subtask", "subtask_5e6f7a8b9c0d"), ("Comment", "comment_9c0d1e2f3a4b"),
        ]
    )
    func staleRevision(resource: String, id: String) async throws {
        let error = try await failure(
            Fixture.error(
                409, "\(resource) '\(id)' has newer changes; reload before saving.",
                detail: #"{"resource":"\#(resource)","id":"\#(id)"}"#
            )
        )
        #expect(error.kind == .staleRevision(resource: resource, id: id))
        #expect(!error.isRetryable)
        #expect(!error.isUncertainOutcome)
    }

    @Test("020-FR-035 020-FR-039 the backend's review-settings 409 (no reason, its own wording) is a stale revision")
    func reviewSettingsStale() async throws {
        // `ReviewService.update_settings` raises `ConflictError("Review
        // settings", owner_id, "Review settings have newer changes; reload
        // before saving.")`; `errors.py` answers {message, detail: {resource, id}}.
        let error = try await failure(
            Fixture.error(
                409, "Review settings have newer changes; reload before saving.",
                detail: #"{"resource":"Review settings","id":"user_0a1b2c3d4e5f"}"#
            )
        )
        #expect(error.kind == .staleRevision(resource: "Review settings", id: "user_0a1b2c3d4e5f"))
        #expect(!error.isRetryable)
    }

    @Test("409 Idempotency-Key reused for a different request (tasks module)")
    func idempotencyConflict() async throws {
        let error = try await failure(
            Fixture.error(
                409, "Idempotency-Key '\(Fixture.keyHeader)' already exists.",
                detail: #"{"resource":"Idempotency-Key","id":"\#(Fixture.keyHeader)"}"#
            )
        )
        #expect(error.kind == .idempotencyConflict)
    }

    @Test("409 IdempotencyConflictError shape from other modules")
    func idempotencyConflictReason() async throws {
        let error = try await failure(
            Fixture.error(
                409, "The Idempotency-Key was reused with a different request.",
                detail: #"{"reason":"idempotency_conflict"}"#
            )
        )
        #expect(error.kind == .idempotencyConflict)
    }

    @Test("409 duplicate project and tag names")
    func duplicateNames() async throws {
        let project = try await failure(
            Fixture.error(409, "Project 'Home' already exists.", detail: #"{"resource":"Project","id":"Home"}"#)
        )
        #expect(project.kind == .duplicateName(resource: "Project", name: "Home"))

        let tag = try await failure(
            Fixture.error(409, "Tag 'errands' already exists.", detail: #"{"resource":"Tag","id":"errands"}"#)
        )
        #expect(tag.kind == .duplicateName(resource: "Tag", name: "errands"))
    }

    @Test("Other 409s are .rejected (signup's taken email)")
    func otherConflict() async throws {
        let error = try await failure(Fixture.error(409, "An account with that email already exists."))
        #expect(error.kind == .rejected)
        #expect(error.statusCode == 409)
        #expect(error.message == "An account with that email already exists.")
    }

    @Test(
        "400 domain rules are .rejected with the server's message",
        arguments: [
            "Idempotency-Key header is required.", "Task title cannot be null.",
            "waiting_for can only be edited on Waiting tasks.", "Move requires a different open destination.",
            "Task project must be active.", "Invalid or mismatched task cursor.",
        ]
    )
    func badRequest(message: String) async throws {
        let error = try await failure(Fixture.error(400, message))
        #expect(error.kind == .rejected)
        #expect(error.statusCode == 400)
        #expect(error.message == message)
        #expect(!error.isRetryable)
    }

    @Test("422 keeps pydantic's error list as the detail")
    func validation() async throws {
        let error = try await failure(
            Fixture.error(
                422, "Request validation failed.",
                detail:
                    #"[{"type":"extra_forbidden","loc":["body","source_capture_ids"],"msg":"Extra inputs are not permitted"}]"#
            )
        )
        #expect(error.kind == .rejected)
        #expect(error.statusCode == 422)
        #expect(
            error.detail
                == .array([
                    .object([
                        "type": .string("extra_forbidden"), "loc": .array([.string("body"), .string("source_capture_ids")]),
                        "msg": .string("Extra inputs are not permitted"),
                    ])
                ])
        )
    }

    @Test("429 with and without Retry-After")
    func rateLimited() async throws {
        let plain = try await failure(Fixture.error(429, "Too many login attempts. Try again in a few minutes."))
        #expect(plain.kind == .rateLimited)
        #expect(plain.retryAfter == nil)
        #expect(plain.isRetryable)
        #expect(plain.isUncertainOutcome)

        let timed = try await failure(Fixture.error(429, "Title completion rate limit exceeded", headers: ["Retry-After": "60"]))
        #expect(timed.retryAfter == 60)
    }

    @Test("503 storage unavailable is a retryable server error")
    func storageUnavailable() async throws {
        let error = try await failure(Fixture.error(503, "Storage is temporarily unavailable; please retry."))
        #expect(error.kind == .server)
        #expect(error.statusCode == 503)
        #expect(error.message == "Storage is temporarily unavailable; please retry.")
        #expect(error.isRetryable)
        #expect(error.isUncertainOutcome)
    }

    @Test("A 3xx from any transport is a retryable server failure nothing processed, in Brain Buddy's words", arguments: [301, 302, 303, 304, 307, 308])
    func redirect(status: Int) async throws {
        let error = try await failure(Fixture.error(status, "Moved elsewhere.", reference: "ref-3xx"))
        #expect(error.kind == .server)
        #expect(error.isRedirect)
        #expect(error.statusCode == status)
        #expect(error.message == APIError.redirectMessage, "a redirect's body is never the API speaking")
        #expect(error.referenceID == "ref-3xx")
        #expect(error.detail == nil)
        #expect(error.isRetryable)
        #expect(!error.isUncertainOutcome)
    }

    @Test("Only a 3xx counts as a redirect")
    func notRedirects() async throws {
        let bad = try await failure(Fixture.error(502, "Bad gateway."))
        #expect(!bad.isRedirect)
        #expect(bad.isUncertainOutcome)
        #expect(!APIError(kind: .rejected, message: "x", statusCode: 302).isRedirect, "only a .server answer")
        #expect(!APIError(kind: .server, message: "x").isRedirect)
    }

    @Test("A proxy's HTML 502 falls back to a calm message and the correlation header")
    func htmlBadGateway() async throws {
        let error = try await failure(
            .respond(
                HTTPResponse(
                    statusCode: 502, headers: ["Content-Type": "text/html", "X-Correlation-ID": "hdr-502"],
                    body: Data("<html><body>502 Bad Gateway</body></html>".utf8)
                )
            )
        )
        #expect(error.kind == .server)
        #expect(error.message == "The server had a problem (HTTP 502). Try again later.")
        #expect(error.referenceID == "hdr-502")
    }

    @Test("reference_id falls back to X-Correlation-ID, then to the id this client sent")
    func referenceFallbacks() async throws {
        let fromHeader = try await failure(
            .respond(
                HTTPResponse(
                    statusCode: 400, headers: ["x-correlation-id": "hdr-1"],
                    body: Data(#"{"message":"Nope.","detail":null,"reference_id":null}"#.utf8)
                )
            )
        )
        #expect(fromHeader.referenceID == "hdr-1")

        let fromRequest = try await failure(.respond(HTTPResponse(statusCode: 500, body: Data())))
        #expect(fromRequest.referenceID == Fixture.correlationHeader)
    }

    @Test("408 counts as a network failure whose outcome is unknown")
    func requestTimeout() async throws {
        let error = try await failure(.respond(HTTPResponse(statusCode: 408)))
        #expect(error.kind == .network("HTTP 408"))
        #expect(error.isRetryable)
        #expect(error.isUncertainOutcome)
    }

    @Test("Transport failure before sending: retryable, outcome known")
    func offline() async throws {
        let offline = TransportError(
            description: "The Internet connection appears to be offline.", requestMayHaveBeenSent: false
        )
        let error = try await failure(.fail(offline))
        #expect(error.kind == .network("The Internet connection appears to be offline."))
        #expect(error.statusCode == nil)
        #expect(error.referenceID == Fixture.correlationHeader)
        #expect(error.isRetryable)
        #expect(!error.isUncertainOutcome)
    }

    @Test("Timeout after sending: retryable, outcome unknown")
    func timeout() async throws {
        let error = try await failure(.fail(TransportError(description: "The request timed out.", requestMayHaveBeenSent: true)))
        #expect(error.isRetryable)
        #expect(error.isUncertainOutcome)
    }

    @Test("Cancellation in flight")
    func cancellation() async throws {
        let transportCancel = try await failure(
            .fail(TransportError(description: "cancelled", requestMayHaveBeenSent: true, isCancellation: true))
        )
        #expect(transportCancel.kind == .cancelled)
        #expect(transportCancel.isUncertainOutcome)

        let taskCancel = try await failure(.raise(CancellationError()))
        #expect(taskCancel.kind == .cancelled)
    }

    @Test("A cancelled task sends nothing")
    func cancelledBeforeSend() async throws {
        let transport = ScriptedTransport()
        let client = Fixture.client(transport)
        let task = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            return await expectAPIError { _ = try await client.listTags() }
        }
        let error = try #require(await task.value)
        #expect(error.kind == .cancelled)
        #expect(!error.requestMayHaveBeenSent)
        #expect(transport.requests.isEmpty)
    }

    @Test("An unknown transport error is treated as possibly sent")
    func unknownTransportError() async throws {
        struct Weird: Error {}
        let error = try await failure(.raise(Weird()))
        guard case .network = error.kind else {
            Issue.record("Expected .network, got \(error.kind)")
            return
        }
        #expect(error.isUncertainOutcome)
    }

    @Test("A 2xx that can't be decoded: applied on the server, keep the key")
    func undecodableSuccess() async throws {
        let error = try await failure(Fixture.json(200, #"{"id":"task_1a2b3c4d5e6f"}"#))
        guard case .decoding = error.kind else {
            Issue.record("Expected .decoding, got \(error.kind)")
            return
        }
        #expect(error.statusCode == 200)
        #expect(!error.isRetryable)
        #expect(error.isUncertainOutcome)
    }

    @Test("An unknown enum value from the server is a decoding error")
    func unknownState() async throws {
        let body = Fixture.task().replacingOccurrences(of: #""state":"inbox""#, with: #""state":"blocked""#)
        let error = try await failure(Fixture.json(200, body))
        guard case .decoding = error.kind else {
            Issue.record("Expected .decoding, got \(error.kind)")
            return
        }
    }

    @Test("Human-readable description carries the reference")
    func descriptions() {
        let error = APIError(kind: .rejected, message: "Task project must be active.", referenceID: "ref-9", statusCode: 400)
        #expect(error.errorDescription == "Task project must be active. Reference ID: ref-9.")
        #expect(error.description == "APIError(rejected, HTTP 400): Task project must be active. [ref ref-9]")
    }

    @Test("URLSession errors: which ones provably never left the device")
    func urlErrorMapping() {
        let offline = URLSessionTransport.transportError(for: URLError(.notConnectedToInternet))
        #expect(!offline.requestMayHaveBeenSent)
        #expect(!URLSessionTransport.transportError(for: URLError(.cannotFindHost)).requestMayHaveBeenSent)
        #expect(!URLSessionTransport.transportError(for: URLError(.secureConnectionFailed)).requestMayHaveBeenSent)
        #expect(URLSessionTransport.transportError(for: URLError(.timedOut)).requestMayHaveBeenSent)
        #expect(URLSessionTransport.transportError(for: URLError(.networkConnectionLost)).requestMayHaveBeenSent)
        let cancelled = URLSessionTransport.transportError(for: URLError(.cancelled))
        #expect(cancelled.isCancellation)
        #expect(cancelled.requestMayHaveBeenSent)
    }
}

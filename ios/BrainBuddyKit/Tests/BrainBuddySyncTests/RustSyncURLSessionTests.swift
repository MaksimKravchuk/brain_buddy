import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyFakeServer
import Foundation
import Synchronization
import Testing

@testable import BrainBuddySync

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

/// The Apple HTTP adapter for the Rust sync core (026 PR-40): the credential is the session cookie
/// from the token store, never given to the core; statuses, `Retry-After`, timeouts and
/// cancellation come back as the core's ports describe them.
@Suite("Rust sync URLSession adapter")
struct RustSyncURLSessionTests {
    private let identity = ClientIdentity(name: "brainbuddy-test", version: "1.2.3")

    private func rig(token: String? = "tok-1") -> (StubServer, InMemorySessionTokenStore, URLSessionRustSyncTransport) {
        let server = StubServer()
        let tokens = InMemorySessionTokenStore(tokens: token.map { [server.serverURL: $0] } ?? [:])
        let transport = URLSessionRustSyncTransport(
            serverURL: server.serverURL, tokenStore: tokens, identity: identity,
            configuration: server.sessionConfiguration)
        return (server, tokens, transport)
    }

    private func get(_ path: String = "/api/sync/v1/changes?scope_id=s", timeout: TimeInterval = 5) -> RustSyncRequest {
        RustSyncRequest(method: .get, path: path, timeout: timeout)
    }

    @Test("026-FR-005 a request goes to the same origin with the session cookie and the client headers")
    func attachesTheCookieAndResolvesAgainstTheOrigin() throws {
        let (server, _, transport) = rig()
        server.respond { _ in .response(status: 200, body: Data("{}".utf8)) }
        let body = Data(#"{"command":1}"#.utf8)
        let answer = try transport.send(
            RustSyncRequest(method: .post, path: "/api/sync/v1/commands", body: body, timeout: 5),
            cancel: RustSyncCancellation())
        #expect(answer == RustSyncResponse(status: 200, retryAfter: nil, body: Data("{}".utf8)))

        let seen = try #require(server.requests.first)
        #expect(seen.method == "POST")
        #expect(seen.url.absoluteString == "http://\(server.host)/api/sync/v1/commands")
        #expect(seen.header("Cookie") == "brainbuddy_session=tok-1")
        #expect(seen.header("Content-Type") == "application/json")
        #expect(seen.header("Accept") == "application/json")
        #expect(seen.header("X-Client") == "brainbuddy-test/1.2.3")
        #expect(seen.header("X-Correlation-ID") != nil)
        #expect(seen.body == body, "the body arrives byte for byte")
    }

    @Test("026-FR-005 a percent-encoded query goes out unchanged")
    func keepsTheEncodedQuery() throws {
        let (server, _, transport) = rig()
        server.respond { _ in .response(status: 200) }
        _ = try transport.send(get("/api/sync/v1/changes?scope_id=a%2Bb&cursor=c%20d"), cancel: RustSyncCancellation())
        #expect(server.requests.first?.url.absoluteString.hasSuffix("/api/sync/v1/changes?scope_id=a%2Bb&cursor=c%20d") == true)
    }

    @Test("026-FR-005 with no stored session the request goes out bare and the 401 is the answer")
    func anonymousRequest() throws {
        let (server, _, transport) = rig(token: nil)
        server.respond { _ in .response(status: 401, body: Data("{}".utf8)) }
        let answer = try transport.send(get(), cancel: RustSyncCancellation())
        #expect(answer.status == 401)
        #expect(server.requests.first?.header("Cookie") == nil)
    }

    @Test("026-FR-005 every status is an answer, with Retry-After in seconds or as a date")
    func statusesAreAnswers() throws {
        let (server, _, transport) = rig()
        for status in [400, 403, 404, 409, 422, 429, 500, 503] {
            server.respond { _ in
                .response(status: status, headers: status == 429 ? ["Retry-After": "17"] : [:], body: Data("e\(status)".utf8))
            }
            let answer = try transport.send(get(), cancel: RustSyncCancellation())
            #expect(answer.status == status)
            #expect(answer.body == Data("e\(status)".utf8))
            #expect(answer.retryAfter == (status == 429 ? 17 : nil))
        }
        #expect(RustSyncURLSession.retryAfter("120") == 120)
        let now = Date(timeIntervalSince1970: 1_790_000_000)
        let later = now.addingTimeInterval(90)
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(identifier: "GMT")
        formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss 'GMT'"
        #expect(RustSyncURLSession.retryAfter(formatter.string(from: later), now: now) == 90)
        #expect(RustSyncURLSession.retryAfter("soon") == nil)
        #expect(RustSyncURLSession.retryAfter(nil) == nil)
    }

    @Test("026-FR-005 a 401 forgets the token the request used, and only that one")
    func unauthorizedForgetsTheSentToken() throws {
        let (server, tokens, transport) = rig()
        server.respond { _ in .response(status: 401) }
        _ = try transport.send(get(), cancel: RustSyncCancellation())
        #expect(try tokens.token(for: server.serverURL) == nil)

        // A sign-in that finished meanwhile stored a newer token: it survives the old one's 401.
        try tokens.setToken("old", for: server.serverURL)
        server.respond { _ in
            try? tokens.setToken("new", for: server.serverURL)
            return .response(status: 401)
        }
        _ = try transport.send(get(), cancel: RustSyncCancellation())
        #expect(try tokens.token(for: server.serverURL) == "new")
    }

    @Test("026-FR-005 a renewed session cookie is stored, and a deleted one removed")
    func setCookieRenewsOrRemoves() throws {
        let (server, tokens, transport) = rig()
        server.respond { _ in
            .response(status: 200, headers: ["Set-Cookie": "brainbuddy_session=renewed; Path=/; HttpOnly"])
        }
        _ = try transport.send(get(), cancel: RustSyncCancellation())
        #expect(try tokens.token(for: server.serverURL) == "renewed")
        server.respond { _ in
            .response(status: 200, headers: ["Set-Cookie": "brainbuddy_session=; Max-Age=0; Path=/"])
        }
        _ = try transport.send(get(), cancel: RustSyncCancellation())
        #expect(try tokens.token(for: server.serverURL) == nil)
    }

    @Test("026-FR-005 a store this build may not read sends nothing and reads as a 401")
    func deniedStoreSendsNothing() throws {
        struct Denied: SessionTokenStore {
            func token(for serverURL: URL) throws -> String? { throw TokenStoreError.accessDenied }
            func setToken(_ token: String, for serverURL: URL) throws {}
            func removeToken(for serverURL: URL) throws {}
        }
        let server = StubServer()
        let transport = URLSessionRustSyncTransport(
            serverURL: server.serverURL, tokenStore: Denied(), configuration: server.sessionConfiguration)
        let answer = try transport.send(get(), cancel: RustSyncCancellation())
        #expect(answer.status == 401)
        #expect(server.requests.isEmpty)
    }

    @Test("026-FR-005 an unreadable store is a lost connection, not a sign-out")
    func unreadableStoreIsAConnectionFailure() {
        struct Locked: SessionTokenStore {
            struct Failure: Error {}
            func token(for serverURL: URL) throws -> String? { throw Failure() }
            func setToken(_ token: String, for serverURL: URL) throws {}
            func removeToken(for serverURL: URL) throws {}
        }
        let server = StubServer()
        let transport = URLSessionRustSyncTransport(
            serverURL: server.serverURL, tokenStore: Locked(), configuration: server.sessionConfiguration)
        #expect(throws: RustSyncTransportFailure.connection) {
            try transport.send(get(), cancel: RustSyncCancellation())
        }
        #expect(server.requests.isEmpty)
    }

    @Test("026-FR-005 a lost connection and a timeout are the core's two failures")
    func failuresAreMapped() {
        let (server, _, transport) = rig()
        server.respond { _ in .fail(.cannotConnectToHost) }
        #expect(throws: RustSyncTransportFailure.connection) { try transport.send(get(), cancel: RustSyncCancellation()) }
        server.respond { _ in .fail(.timedOut) }
        #expect(throws: RustSyncTransportFailure.timeout) { try transport.send(get(), cancel: RustSyncCancellation()) }
        // The core's timeout covers the whole answer: a server that never answers is cut off.
        server.respond { _ in .hang }
        #expect(throws: RustSyncTransportFailure.timeout) {
            try transport.send(get(timeout: 0.3), cancel: RustSyncCancellation())
        }
    }

    @Test("026-FR-005 raising the cancellation aborts a call in flight")
    func cancellationAbortsTheCall() async throws {
        let (server, _, transport) = rig()
        server.respond { _ in .hang }
        let cancel = RustSyncCancellation()
        let call = Task.detached { () -> Result<RustSyncResponse, RustSyncTransportFailure> in
            do throws(RustSyncTransportFailure) { return .success(try transport.send(get(timeout: 30), cancel: cancel)) } catch { return .failure(error) }
        }
        #expect(server.wait { requests, _ in requests.count == 1 }, "the request reached the server")
        cancel.cancel()
        #expect(await call.value == .failure(.cancelled))
        #expect(server.wait { _, stopped in stopped == 1 }, "the connection was released")
        // Already raised: nothing is sent at all.
        #expect(throws: RustSyncTransportFailure.cancelled) { try transport.send(get(), cancel: cancel) }
        #expect(server.requests.count == 1)
    }

    @Test("026-FR-005 a redirect is not followed and the cookie goes nowhere else")
    func redirectIsRefused() throws {
        let (server, _, transport) = rig()
        server.respond { _ in .response(status: 302, headers: ["Location": "http://elsewhere.test/steal"]) }
        let answer = try transport.send(get(), cancel: RustSyncCancellation())
        #expect(answer.status == 302)
        #expect(server.requests.count == 1)
    }

    @Test("026-FR-005 the server address maps to the origin the core's paths are relative to")
    func originDropsTheApiSuffix() {
        let origin = RustSyncURLSession.origin
        #expect(origin(URL(string: "https://example.test/api")!).absoluteString == "https://example.test")
        #expect(origin(URL(string: "https://example.test/api/")!).absoluteString == "https://example.test")
        #expect(origin(URL(string: "http://localhost:8000")!).absoluteString == "http://localhost:8000")
    }
}

/// `GET /api/sync/v1/hints`: the authenticated event stream the watcher reads.
@Suite("Rust sync hint stream adapter")
struct RustSyncHintStreamTests {
    private func rig(token: String? = "tok-1") -> (StubServer, URLSessionRustSyncHintStream) {
        let server = StubServer()
        let tokens = InMemorySessionTokenStore(tokens: token.map { [server.serverURL: $0] } ?? [:])
        let stream = URLSessionRustSyncHintStream(
            serverURL: server.serverURL, tokenStore: tokens, configuration: server.sessionConfiguration)
        return (server, stream)
    }

    private let path = "/api/sync/v1/hints?scope_id=s"

    @Test("026-FR-007 it asks for an event stream with the cookie and no Last-Event-ID, then reads chunks as they arrive")
    func opensAndReadsChunks() throws {
        let (server, hints) = rig()
        let body = StubStream()
        server.respond { _ in .stream(status: 200, headers: ["Content-Type": "text/event-stream"], body) }
        let reader = try hints.open(path: path, idleTimeout: 5, cancel: RustSyncCancellation())

        let seen = try #require(server.requests.first)
        #expect(seen.method == "GET")
        #expect(seen.header("Accept") == "text/event-stream")
        #expect(seen.header("Cookie") == "brainbuddy_session=tok-1")
        #expect(seen.header("Last-Event-ID") == nil)
        #expect(seen.url.path == "/api/sync/v1/hints")

        body.send(": heartbeat\n\n")
        #expect(try reader.read(maxLength: 4096, cancel: RustSyncCancellation()) == Data(": heartbeat\n\n".utf8))
        body.send("event: scope_changed\ndata: {}\n\n")
        // A small buffer splits a chunk; nothing is lost.
        let first = try reader.read(maxLength: 5, cancel: RustSyncCancellation())
        let rest = try reader.read(maxLength: 4096, cancel: RustSyncCancellation())
        #expect(first + rest == Data("event: scope_changed\ndata: {}\n\n".utf8))
    }

    @Test("026-FR-007 the server closing the stream reads as an empty chunk")
    func serverCloseIsEmpty() throws {
        let (server, hints) = rig()
        let body = StubStream()
        server.respond { _ in .stream(status: 200, body) }
        let reader = try hints.open(path: path, idleTimeout: 5, cancel: RustSyncCancellation())
        body.send("data")
        body.finish()
        #expect(try reader.read(maxLength: 100, cancel: RustSyncCancellation()) == Data("data".utf8))
        #expect(try reader.read(maxLength: 100, cancel: RustSyncCancellation()).isEmpty)
    }

    @Test("026-FR-007 a dropped connection is a connection failure")
    func droppedConnection() throws {
        let (server, hints) = rig()
        let body = StubStream()
        server.respond { _ in .stream(status: 200, body) }
        let reader = try hints.open(path: path, idleTimeout: 5, cancel: RustSyncCancellation())
        body.fail(.networkConnectionLost)
        #expect(throws: RustSyncStreamFailure.connection) { try reader.read(maxLength: 100, cancel: RustSyncCancellation()) }
    }

    @Test("026-FR-007 anything but a 200 is reported by status and no stream opens")
    func nonOkStatuses() {
        let (server, hints) = rig()
        for status in [401, 403, 404, 429, 500, 503] {
            server.respond { _ in .response(status: status, body: Data("nope".utf8)) }
            #expect(throws: RustSyncStreamFailure.status(status)) {
                try hints.open(path: path, idleTimeout: 5, cancel: RustSyncCancellation())
            }
        }
    }

    @Test("026-FR-007 a 401 forgets the token the stream used")
    func unauthorizedForgetsTheToken() throws {
        let server = StubServer()
        let tokens = InMemorySessionTokenStore(tokens: [server.serverURL: "tok-1"])
        let hints = URLSessionRustSyncHintStream(
            serverURL: server.serverURL, tokenStore: tokens, configuration: server.sessionConfiguration)
        server.respond { _ in .response(status: 401) }
        #expect(throws: RustSyncStreamFailure.status(401)) {
            try hints.open(path: path, idleTimeout: 5, cancel: RustSyncCancellation())
        }
        #expect(try tokens.token(for: server.serverURL) == nil)
    }

    @Test("026-FR-007 a stream that stays silent for the idle timeout is dead")
    func idleTimeout() throws {
        let (server, hints) = rig()
        server.respond { _ in .stream(status: 200, StubStream()) }
        let reader = try hints.open(path: path, idleTimeout: 0.3, cancel: RustSyncCancellation())
        #expect(throws: RustSyncStreamFailure.timeout) { try reader.read(maxLength: 100, cancel: RustSyncCancellation()) }
    }

    @Test("026-FR-007 a server that never sends headers times out on open")
    func openTimesOut() {
        let (server, hints) = rig()
        server.respond { _ in .hang }
        #expect(throws: RustSyncStreamFailure.timeout) {
            try hints.open(path: path, idleTimeout: 0.3, cancel: RustSyncCancellation())
        }
    }

    @Test("026-FR-007 cancelling ends a read in flight and releasing the reader releases the connection")
    func cancellation() async throws {
        let (server, hints) = rig()
        server.respond { _ in .stream(status: 200, StubStream()) }
        // The reader lives only inside this call, as it does inside one hint-watcher connection.
        let outcome = try await readUntilCancelled(hints)
        #expect(outcome == .failure(.cancelled))
        #expect(server.wait { _, stopped in stopped == 1 }, "the stream's connection was released")
    }

    private func readUntilCancelled(_ hints: URLSessionRustSyncHintStream) async throws
        -> Result<Data, RustSyncStreamFailure>
    {
        let reader = try hints.open(path: path, idleTimeout: 30, cancel: RustSyncCancellation())
        let cancel = RustSyncCancellation()
        let read = Task.detached { () -> Result<Data, RustSyncStreamFailure> in
            do throws(RustSyncStreamFailure) { return .success(try reader.read(maxLength: 100, cancel: cancel)) } catch {
                return .failure(error)
            }
        }
        cancel.cancel()
        return await read.value
    }

    @Test("026-FR-007 opening with the cancellation already raised connects to nothing")
    func openCancelled() {
        let (server, hints) = rig()
        let cancel = RustSyncCancellation()
        cancel.cancel()
        #expect(throws: RustSyncStreamFailure.cancelled) { try hints.open(path: path, idleTimeout: 5, cancel: cancel) }
        #expect(server.requests.isEmpty)
    }

    @Test("026-FR-007 a redirect on the stream is not followed")
    func redirectRefused() {
        let (server, hints) = rig()
        server.respond { _ in .response(status: 307, headers: ["Location": "http://elsewhere.test/x"]) }
        #expect(throws: RustSyncStreamFailure.status(307)) {
            try hints.open(path: path, idleTimeout: 5, cancel: RustSyncCancellation())
        }
        #expect(server.requests.count == 1)
    }
}

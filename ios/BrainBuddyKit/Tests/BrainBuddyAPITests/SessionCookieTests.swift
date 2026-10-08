import Foundation
import Testing

@testable import BrainBuddyAPI

@Suite("Session cookie handling")
struct SessionCookieTests {
    @Test("Login captures the cookie and later requests send it")
    func loginCapturesAndInjects() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, Fixture.me, headers: ["set-cookie": Fixture.loginSetCookie]),
            Fixture.json(200, "[]"),
        ])
        let store = InMemorySessionTokenStore()
        let client = Fixture.client(transport, store: store)

        _ = try await client.login(email: "ada@example.com", password: "pw")
        _ = try await client.listProjects()

        #expect(try store.token(for: Fixture.baseURL) == Fixture.token)
        #expect(try client.hasStoredSession())
        #expect(transport.requests[1].header("Cookie") == "brainbuddy_session=\(Fixture.token)")
    }

    @Test("A login response without the session cookie is an error, not a silent sign-in")
    func loginWithoutCookie() async throws {
        let transport = ScriptedTransport([Fixture.json(200, Fixture.me)])
        let store = InMemorySessionTokenStore()
        let client = Fixture.client(transport, store: store)

        let error = try #require(await expectAPIError { _ = try await client.login(email: "a@b.c", password: "pw") })
        guard case .decoding = error.kind else {
            Issue.record("Expected .decoding, got \(error.kind)")
            return
        }
        #expect(error.statusCode == 200)
        #expect(try store.token(for: Fixture.baseURL) == nil)
    }

    @Test("Wrong credentials are .unauthorized and keep the stored session")
    func loginWrongPassword() async throws {
        let transport = ScriptedTransport([Fixture.error(401, "Invalid email or password.")])
        let store = Fixture.signedInStore()
        let client = Fixture.client(transport, store: store)

        let error = try #require(await expectAPIError { _ = try await client.login(email: "a@b.c", password: "nope") })

        #expect(error.kind == .unauthorized)
        #expect(error.message == "Invalid email or password.")
        #expect(try store.token(for: Fixture.baseURL) == Fixture.token)
    }

    @Test("Logout removes the token when the server deletes the cookie")
    func logoutClears() async throws {
        let transport = ScriptedTransport([Fixture.noContent(headers: ["set-cookie": Fixture.logoutSetCookie])])
        let store = Fixture.signedInStore()

        try await Fixture.client(transport, store: store).logout()

        #expect(try store.token(for: Fixture.baseURL) == nil)
    }

    @Test("Logout removes the token even when the server can't be reached")
    func logoutOffline() async throws {
        let transport = ScriptedTransport([
            .fail(TransportError(description: "offline", requestMayHaveBeenSent: false)),
        ])
        let store = Fixture.signedInStore()
        let client = Fixture.client(transport, store: store)

        let error = try #require(await expectAPIError { try await client.logout() })

        #expect(error.kind == .network("offline"))
        #expect(try store.token(for: Fixture.baseURL) == nil)
    }

    @Test("Logout with an already expired session succeeds")
    func logoutUnauthorized() async throws {
        let transport = ScriptedTransport([Fixture.error(401, "Authentication required.")])
        let store = Fixture.signedInStore()

        try await Fixture.client(transport, store: store).logout()

        #expect(try store.token(for: Fixture.baseURL) == nil)
    }

    @Test("A 401 on a request that carried the token removes it")
    func unauthorizedClears() async throws {
        let transport = ScriptedTransport([Fixture.error(401, "Authentication required.")])
        let store = Fixture.signedInStore()
        let client = Fixture.client(transport, store: store)

        let error = try #require(await expectAPIError { _ = try await client.me() })

        #expect(error.kind == .unauthorized)
        #expect(try store.token(for: Fixture.baseURL) == nil)
        #expect(try !client.hasStoredSession())
    }

    @Test("A 401 does not remove a token that a newer sign-in stored meanwhile")
    func unauthorizedKeepsNewerToken() async throws {
        let store = Fixture.signedInStore("old-token")
        let transport = ScriptedTransport([
            .run { _ in
                try store.setToken("new-token", for: Fixture.baseURL)
                return HTTPResponse(
                    statusCode: 401, body: Data(#"{"message":"Authentication required.","detail":null,"reference_id":null}"#.utf8)
                )
            },
        ])
        let client = Fixture.client(transport, store: store)

        _ = await expectAPIError { _ = try await client.listTags() }

        #expect(transport.lastRequest?.header("Cookie") == "brainbuddy_session=old-token")
        #expect(try store.token(for: Fixture.baseURL) == "new-token")
    }

    @Test("Without a stored token no Cookie header is sent")
    func noTokenNoCookie() async throws {
        let transport = ScriptedTransport([Fixture.json(200, "[]")])
        _ = try await Fixture.client(transport).listTags()
        #expect(transport.lastRequest?.header("Cookie") == nil)
    }

    @Test("Tokens are kept per server host")
    func scopedPerHost() async throws {
        let other = URL(string: "http://localhost:8000/api")!
        let store = InMemorySessionTokenStore(tokens: [Fixture.baseURL: "prod-token", other: "dev-token"])
        let transport = ScriptedTransport([Fixture.json(200, "[]"), Fixture.json(200, "[]")])

        _ = try await Fixture.client(transport, store: store).listTags()
        _ = try await Fixture.client(transport, store: store, baseURL: other).listTags()

        #expect(transport.requests.map { $0.header("Cookie") } == [
            "brainbuddy_session=prod-token", "brainbuddy_session=dev-token",
        ])
        #expect(BrainBuddyAPI.sessionScope(for: URL(string: "https://API.Example.TEST/api")!) == "api.example.test")
    }

    @Test("discardStoredSession forgets the token without a request")
    func discard() async throws {
        let transport = ScriptedTransport()
        let store = Fixture.signedInStore()
        let client = Fixture.client(transport, store: store)

        try client.discardStoredSession()

        #expect(try store.token(for: Fixture.baseURL) == nil)
        #expect(transport.requests.isEmpty)
    }

    @Test("An unreadable token store fails before anything is sent")
    func unreadableStore() async throws {
        let transport = ScriptedTransport()
        let client = Fixture.client(transport, store: FailingTokenStore())

        let error = try #require(await expectAPIError { _ = try await client.listTasks() })

        guard case .tokenStorage = error.kind else {
            Issue.record("Expected .tokenStorage, got \(error.kind)")
            return
        }
        #expect(!error.requestMayHaveBeenSent)
        #expect(error.isRetryable)
        #expect(!error.isUncertainOutcome)
        #expect(transport.requests.isEmpty)
        #expect(throws: APIError.self) { try client.hasStoredSession() }
    }

    @Test("021-FR-005 021-FR-017 a session this build may not read is an ended session, and nothing is sent")
    func deniedStoreIsAnEndedSession() async throws {
        let transport = ScriptedTransport()
        let client = Fixture.client(transport, store: DeniedTokenStore())

        let error = try #require(await expectAPIError { _ = try await client.listTasks() })

        #expect(error.kind == .unauthorized, "only a sign-in the person starts can replace the item")
        #expect(!error.requestMayHaveBeenSent)
        #expect(!error.isUncertainOutcome)
        #expect(transport.requests.isEmpty)
    }

    @Test("021-FR-005 021-FR-015 a session that can't be saved after login is ended at once and reported with a reference id")
    func unwritableStore() async throws {
        let transport = ScriptedTransport([
            Fixture.json(200, Fixture.me, headers: ["set-cookie": Fixture.loginSetCookie]),
            Fixture.noContent(headers: ["set-cookie": Fixture.logoutSetCookie]),
        ])
        let client = Fixture.client(transport, store: ReadOnlyTokenStore())

        let error = try #require(await expectAPIError { _ = try await client.login(email: "a@b.c", password: "pw") })

        guard case .tokenStorage = error.kind else {
            Issue.record("Expected .tokenStorage, got \(error.kind)")
            return
        }
        #expect(error.message == "Brain Buddy couldn't save your sign-in on this device. Try again.")
        #expect(error.referenceID == Fixture.correlationHeader, "the id of the login request")
        #expect(transport.requests.map { "\($0.method.rawValue) \($0.url.path)" } == ["POST /api/auth/login", "POST /api/auth/logout"])
        #expect(transport.requests.last?.header("Cookie") == "brainbuddy_session=\(Fixture.token)", "it carries the issued token")
    }
}

@Suite("Set-Cookie parsing")
struct SetCookieParserTests {
    private let name = "brainbuddy_session"

    @Test("Starlette's set_cookie")
    func productionCookie() {
        #expect(SetCookieParser.update(for: name, in: Fixture.loginSetCookie) == .set(Fixture.token))
    }

    @Test("Starlette's delete_cookie, whose expires attribute contains a comma")
    func deleteCookie() {
        #expect(SetCookieParser.update(for: name, in: Fixture.logoutSetCookie) == .removed)
    }

    @Test("Max-Age=0 removes even with a value")
    func maxAgeZero() {
        #expect(SetCookieParser.update(for: name, in: "brainbuddy_session=abc; Max-Age=0; Path=/") == .removed)
    }

    @Test("Several cookies joined by HTTPURLResponse")
    func joinedCookies() {
        let header =
            "theme=dark; Path=/; Expires=Wed, 21 Oct 2026 07:28:00 GMT, brainbuddy_session=tok123; HttpOnly; Path=/, other=1"
        #expect(SetCookieParser.update(for: name, in: header) == .set("tok123"))
        #expect(SetCookieParser.splitCookies(header).count == 3)
    }

    @Test("Quoted values are unquoted; the last occurrence wins")
    func quotedAndLastWins() {
        #expect(SetCookieParser.update(for: name, in: #"brainbuddy_session="tok-9"; Path=/"#) == .set("tok-9"))
        #expect(
            SetCookieParser.update(for: name, in: "brainbuddy_session=first; Path=/, brainbuddy_session=second; Path=/")
                == .set("second")
        )
    }

    @Test("Other cookies and look-alike names are ignored")
    func ignoresOthers() {
        #expect(SetCookieParser.update(for: name, in: "csrftoken=abc; Path=/") == nil)
        #expect(SetCookieParser.update(for: name, in: "xbrainbuddy_session=abc; Path=/") == nil)
    }
}

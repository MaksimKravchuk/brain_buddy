import Foundation
import Synchronization
import Testing

#if canImport(FoundationNetworking)
    import FoundationNetworking
#endif

@testable import BrainBuddyAPI

/// The API never redirects. `URLSessionTransport` refuses every redirect (so
/// the hand-set `Cookie` header and a login's body never reach the
/// `Location`) and turns the 3xx into an error response the client reports
/// as `.rejected`. No network: the delegate is called directly and the
/// converted responses go through `ScriptedTransport`.
@Suite("URLSession transport")
struct URLSessionTransportTests {
    static let redirects = [301, 302, 303, 307, 308]

    /// A redirect as a hostile or misconfigured server would send it: away to
    /// another host, trying to replace the session on the way.
    private func redirect(_ status: Int, url: URL = Fixture.baseURL.appending(path: "auth/login")) -> HTTPResponse {
        let http = HTTPURLResponse(
            url: url, statusCode: status, httpVersion: "HTTP/1.1",
            headerFields: [
                "Location": "https://elsewhere.example.test/collect",
                "Set-Cookie": "brainbuddy_session=planted; Path=/; HttpOnly",
                "Content-Type": "text/html",
                "X-Correlation-ID": "hdr-redirect",
            ]
        )!
        return URLSessionTransport.response(from: http, body: Data("<html>Moved</html>".utf8))
    }

    @Test("The session delegate refuses every redirect")
    func delegateRefuses() async throws {
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        // Created, never resumed: nothing is sent.
        let task = session.dataTask(with: Fixture.baseURL.appending(path: "tasks"))
        let redirect = try #require(
            HTTPURLResponse(
                url: Fixture.baseURL.appending(path: "tasks"), statusCode: 307, httpVersion: "HTTP/1.1",
                headerFields: ["Location": "https://elsewhere.example.test/tasks"]
            )
        )
        var onward = URLRequest(url: URL(string: "https://elsewhere.example.test/tasks")!)
        onward.setValue("brainbuddy_session=\(Fixture.token)", forHTTPHeaderField: "Cookie")

        let recorder = Recorder()
        RedirectRefusal().urlSession(
            session, task: task, willPerformHTTPRedirection: redirect, newRequest: onward
        ) { request in recorder.answers.withLock { $0.append(request) } }

        let answers = recorder.answers.withLock { $0 }
        #expect(answers.count == 1)
        #expect(answers.allSatisfy { $0 == nil })
    }

    private final class Recorder: Sendable {
        let answers = Mutex<[URLRequest?]>([])
    }

    @Test("A 3xx keeps its status and correlation id but loses its cookies and body", arguments: redirects)
    func redirectResponseIsSanitized(status: Int) throws {
        let response = redirect(status)
        #expect(response.statusCode == status)
        #expect(response.header("Set-Cookie") == nil)
        #expect(response.header("X-Correlation-ID") == "hdr-redirect")
        #expect(response.header("Location") == "https://elsewhere.example.test/collect")
        #expect(response.header("Content-Type") == "application/json")
        let body = try JSONDecoder().decode([String: String].self, from: response.body)
        #expect(body == ["message": URLSessionTransport.redirectMessage])
    }

    @Test("A redirected login is .rejected with the redirect message and stores no session", arguments: redirects)
    func redirectedLogin(status: Int) async throws {
        let transport = ScriptedTransport([.respond(redirect(status))])
        let store = InMemorySessionTokenStore()
        let client = Fixture.client(transport, store: store)

        let error = try #require(
            await expectAPIError { _ = try await client.login(email: "ada@example.com", password: "pw") }
        )

        #expect(error.kind == .rejected)
        #expect(error.message == "The server redirected the request, which Brain Buddy doesn't follow.")
        #expect(error.statusCode == status)
        #expect(error.referenceID == "hdr-redirect")
        #expect(!error.isRetryable)
        #expect(!error.isUncertainOutcome)
        #expect(try store.token(for: Fixture.baseURL) == nil)
        #expect(transport.requests.count == 1)
    }

    @Test("A redirected signed-in request neither replaces nor clears the session")
    func redirectedSignedInRequest() async throws {
        let transport = ScriptedTransport([.respond(redirect(302, url: Fixture.baseURL.appending(path: "tasks")))])
        let store = Fixture.signedInStore()
        let client = Fixture.client(transport, store: store)

        let error = try #require(await expectAPIError { _ = try await client.listTags() })

        #expect(error.kind == .rejected)
        #expect(error.message == URLSessionTransport.redirectMessage)
        #expect(try store.token(for: Fixture.baseURL) == Fixture.token)
    }

    @Test("Other responses pass through with their cookies and body")
    func nonRedirectPassesThrough() throws {
        let http = try #require(
            HTTPURLResponse(
                url: Fixture.baseURL.appending(path: "auth/login"), statusCode: 200, httpVersion: "HTTP/1.1",
                headerFields: ["Set-Cookie": Fixture.loginSetCookie, "Content-Type": "application/json"]
            )
        )
        let response = URLSessionTransport.response(from: http, body: Data(Fixture.me.utf8))
        #expect(response.statusCode == 200)
        #expect(response.header("Set-Cookie") == Fixture.loginSetCookie)
        #expect(response.header("Content-Type") == "application/json")
        #expect(response.body == Data(Fixture.me.utf8))
    }
}

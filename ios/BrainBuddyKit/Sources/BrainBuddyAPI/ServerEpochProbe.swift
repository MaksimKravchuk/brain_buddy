import Foundation

/// The release epoch this build sends as `X-Client-Epoch` on every request
/// (specs/027-rust-server/contracts/release-epoch.md). A constant compiled into the client,
/// bumped only when the server raises its minimum; never derived from the marketing version.
public enum ClientEpoch {
    public static let current = 1
    public static let header = "X-Client-Epoch"
    public static let serverHeader = "X-Server-Epoch"
}

/// What `GET /api/meta` said. `serverEpoch == 0` is the old (Python) server, which has no such route.
public struct ServerEpoch: Equatable, Sendable {
    public var serverEpoch: Int
    public var minClientEpoch: Int

    public static let legacy = ServerEpoch(serverEpoch: 0, minClientEpoch: 0)
}

/// The probe got an answer that says nothing about the epoch (not a 200 with the meta body, not a 404).
public struct ServerEpochProbeError: Error, Equatable, Sendable {
    public var statusCode: Int
}

/// Asks the server which epoch it runs, before any sign-in, session use or sync push
/// (027-FR-018, 027-FR-021). The request carries no cookie. A 404 reads as epoch 0; any other
/// failure throws, so the caller blocks rather than guessing.
public struct ServerEpochProbe: Sendable {
    private let baseURL: URL
    private let transport: any HTTPTransport
    private let identity: ClientIdentity

    /// - Parameter baseURL: the API base the client uses (it already ends in `/api`).
    public init(baseURL: URL, transport: any HTTPTransport, identity: ClientIdentity = .iOS) {
        self.baseURL = baseURL
        self.transport = transport
        self.identity = identity
    }

    public func probe() async throws -> ServerEpoch {
        var text = baseURL.absoluteString
        while text.hasSuffix("/") { text.removeLast() }
        guard let url = URL(string: text + "/meta") else {
            throw APIError(kind: .rejected, message: "The server address isn't valid.", requestMayHaveBeenSent: false)
        }
        let headers = [
            "Accept": "application/json",
            "X-Client": "\(identity.name)/\(identity.version)",
            ClientEpoch.header: String(ClientEpoch.current),
        ]
        let response = try await transport.send(HTTPRequest(method: .get, url: url, headers: headers))
        if response.statusCode == 404 { return .legacy }
        guard response.statusCode == 200, let meta = try? JSONDecoder().decode(Meta.self, from: response.body)
        else { throw ServerEpochProbeError(statusCode: response.statusCode) }
        return ServerEpoch(serverEpoch: meta.serverEpoch, minClientEpoch: meta.minClientEpoch)
    }

    /// The epoch announced by any response's `X-Server-Epoch` header, or nil when absent (old server).
    public static func observed(in response: HTTPResponse) -> Int? {
        response.header(ClientEpoch.serverHeader).flatMap { Int($0.trimmingCharacters(in: .whitespaces)) }
    }

    private struct Meta: Decodable {
        var serverEpoch: Int
        var minClientEpoch: Int
        enum CodingKeys: String, CodingKey {
            case serverEpoch = "server_epoch"
            case minClientEpoch = "min_client_epoch"
        }
    }
}

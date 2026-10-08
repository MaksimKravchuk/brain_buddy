import BrainBuddyCore
import Foundation

/// Constants and helpers shared by the typed REST client. The client itself is
/// `BrainBuddyAPIClient`; see `docs/native-ios-app.md` › Commands and endpoints.
public enum BrainBuddyAPI {
    /// The production API base (the Fly frontend proxies `/api` to the backend).
    public static let defaultServerURL = URL(string: "https://brain-buddy-frontend.fly.dev/api")!

    /// Name of the opaque session cookie set by `POST /auth/login` and `/auth/signup`.
    public static let sessionCookieName = "brainbuddy_session"

    /// `GET /tasks` accepts `limit` in 1...200 (default 50).
    public static let maximumPageSize = 200

    /// The app's marketing version from the main bundle, or `"dev"` when the
    /// bundle has none (tests, command-line tools).
    public static var bundleVersion: String {
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
        guard let version, !version.isEmpty else { return "dev" }
        return version
    }

    /// Validates a user-entered server address: `https` for any host, `http`
    /// only for the host `localhost` (development). That is the one plain-http
    /// host App Transport Security lets the app reach without an exception
    /// (unqualified names are allowed; the literal loopback addresses
    /// `127.0.0.1` and `::1` are not), so any other would only fail later.
    /// Surrounding whitespace and trailing slashes are dropped. Returns nil
    /// when invalid.
    public static func serverURL(from raw: String) -> URL? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        while text.hasSuffix("/") { text.removeLast() }
        guard let components = URLComponents(string: text), let scheme = components.scheme?.lowercased(),
            let host = components.host?.lowercased(), !host.isEmpty,
            components.query == nil, components.fragment == nil, components.user == nil, components.password == nil
        else { return nil }
        switch scheme {
        case "https": break
        case "http" where host == "localhost": break
        default: return nil
        }
        return components.url
    }

    /// The key a session token is stored under: the server's lowercased host,
    /// like a cookie's host scope (paths and ports share one session).
    public static func sessionScope(for serverURL: URL) -> String {
        if let host = serverURL.host, !host.isEmpty { return host.lowercased() }
        return serverURL.absoluteString
    }

    /// A decoder for API payloads: ISO-8601 datetimes with or without
    /// fractional seconds (`WireDate`), `YYYY-MM-DD` calendar days (`CalendarDay`).
    public static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let raw = try container.decode(String.self)
            guard let date = WireDate.parse(raw) else {
                throw DecodingError.dataCorruptedError(
                    in: container, debugDescription: "Expected an ISO-8601 datetime, got \(raw)"
                )
            }
            return date
        }
        return decoder
    }

    /// An encoder that writes request bodies deterministically (sorted keys,
    /// unescaped slashes) and dates the way the server does (`WireDate.format`).
    public static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        encoder.dateEncodingStrategy = .custom { date, encoder in
            var container = encoder.singleValueContainer()
            try container.encode(WireDate.format(date))
        }
        return encoder
    }
}

/// The product and version a client reports as `X-Client: <name>/<version>`
/// (spec 021, FR-031): a label for server logs, never a behaviour switch.
public struct ClientIdentity: Sendable, Equatable {
    public var name: String
    /// The app's marketing version, or `"dev"`.
    public var version: String

    public init(name: String, version: String) {
        self.name = name
        self.version = version
    }

    public static let iOS = ClientIdentity(name: "brainbuddy-ios", version: BrainBuddyAPI.bundleVersion)

    public static func macOS(version: String) -> ClientIdentity {
        ClientIdentity(name: "brainbuddy-macos", version: version)
    }
}

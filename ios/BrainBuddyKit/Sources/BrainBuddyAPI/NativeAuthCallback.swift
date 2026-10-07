import Foundation

public struct NativeAuthCallback: Sendable, CustomStringConvertible {
    public struct InvalidCallback: Error, Sendable {}
    public let handoffCode: String
    public var description: String { "Native authentication callback (redacted)" }

    public static func parse(_ url: URL, attemptID: String, state: String) throws(InvalidCallback) -> Self {
        guard let c = URLComponents(url: url, resolvingAgainstBaseURL: false),
            c.scheme == "brainbuddy", c.host == "auth", c.percentEncodedPath == "/callback",
            c.user == nil, c.password == nil, c.port == nil, c.fragment == nil,
            let items = c.queryItems, items.count == 3,
            Set(items.map(\.name)) == Set(["attempt", "state", "grant"]),
            items.first(where: { $0.name == "attempt" })?.value == attemptID,
            items.first(where: { $0.name == "state" })?.value == state,
            let grant = items.first(where: { $0.name == "grant" })?.value,
            isRandomToken(grant), isRandomToken(state)
        else { throw InvalidCallback() }
        return Self(handoffCode: grant)
    }

    public static func isRandomToken(_ text: String) -> Bool {
        text.utf8.count == 43 && text.utf8.allSatisfy { (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || $0 == 45 || $0 == 95 }
    }
}

public enum NativeAccountDestination {
    public static func url(origin: String, ownerID: String, deleting: Bool) -> URL? {
        guard !ownerID.isEmpty, ownerID.utf8.count <= 128,
            ownerID.utf8.allSatisfy({ (65...90).contains($0) || (97...122).contains($0) || (48...57).contains($0) || $0 == 45 || $0 == 95 }),
            var c = URLComponents(string: origin), let host = c.host, !host.isEmpty,
            c.scheme == "https" || (c.scheme == "http" && host == "localhost"),
            c.user == nil, c.password == nil, c.query == nil, c.fragment == nil,
            c.path.isEmpty || c.path == "/"
        else { return nil }
        c.path = deleting ? "/settings/account/delete" : "/settings/account"
        c.queryItems = [URLQueryItem(name: "expected_owner", value: ownerID)]
        return c.url
    }
}

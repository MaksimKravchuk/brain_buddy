import Foundation

/// What a response's `Set-Cookie` header says about one cookie.
enum CookieUpdate: Hashable, Sendable {
    case set(String)
    /// Starlette's `delete_cookie`: an empty value with `Max-Age=0` (and an
    /// `expires` date in the past).
    case removed
}

/// Minimal `Set-Cookie` reader for the one cookie the client cares about.
///
/// `HTTPURLResponse` joins several `Set-Cookie` headers with ", ", and an
/// `expires=Thu, 01 Jan 1970 00:00:00 GMT` attribute contains a comma too, so
/// a comma only starts a new cookie when the text after it (up to the next
/// `;`) is a `name=value` pair that is not a cookie attribute.
enum SetCookieParser {
    private static let attributeNames: Set<String> = [
        "expires", "max-age", "domain", "path", "secure", "httponly", "samesite", "priority", "partitioned",
    ]

    /// The last update for `name` in `header`, or nil when the header does not mention it.
    static func update(for name: String, in header: String) -> CookieUpdate? {
        var result: CookieUpdate?
        for cookie in splitCookies(header) {
            let parts = cookie.split(separator: ";", omittingEmptySubsequences: false).map {
                $0.trimmingCharacters(in: .whitespaces)
            }
            guard let pair = parts.first, let equals = pair.firstIndex(of: "=") else { continue }
            guard pair[..<equals].trimmingCharacters(in: .whitespaces) == name else { continue }
            var value = String(pair[pair.index(after: equals)...]).trimmingCharacters(in: .whitespaces)
            if value.count >= 2, value.hasPrefix("\""), value.hasSuffix("\"") {
                value = String(value.dropFirst().dropLast())
            }
            var expired = false
            for attribute in parts.dropFirst() {
                let pieces = attribute.split(separator: "=", maxSplits: 1).map {
                    $0.trimmingCharacters(in: .whitespaces)
                }
                if pieces.count == 2, pieces[0].lowercased() == "max-age", let seconds = Int(pieces[1]), seconds <= 0 {
                    expired = true
                }
            }
            result = value.isEmpty || expired ? .removed : .set(value)
        }
        return result
    }

    static func splitCookies(_ header: String) -> [String] {
        var cookies: [String] = []
        for piece in header.split(separator: ",", omittingEmptySubsequences: false).map(String.init) {
            if let last = cookies.last, !startsCookie(piece) {
                cookies[cookies.count - 1] = last + "," + piece
            } else {
                cookies.append(piece)
            }
        }
        return cookies.map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }

    private static func startsCookie(_ piece: String) -> Bool {
        let head = piece.split(separator: ";", maxSplits: 1, omittingEmptySubsequences: false).first ?? ""
        guard let equals = head.firstIndex(of: "=") else { return false }
        let name = head[..<equals].trimmingCharacters(in: .whitespaces)
        return !name.isEmpty && !name.contains(" ") && !attributeNames.contains(name.lowercased())
    }
}

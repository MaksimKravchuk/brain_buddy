import Foundation

// `GET /account/export` (spec 028 T007): the ZIP the backend streams with
// `Content-Disposition: attachment; filename="…"`. Additive to the shared client.

/// One downloaded account export, held in memory until the caller writes it.
public struct AccountExport: Equatable, Sendable, CustomStringConvertible, CustomDebugStringConvertible {
    /// Used when the response names no usable file.
    public static let fallbackFileName = "brainbuddy-export.zip"

    public var suggestedFileName: String
    public var data: Data

    public init(suggestedFileName: String, data: Data) {
        self.suggestedFileName = suggestedFileName
        self.data = data
    }

    /// Redacted: the archive holds personal data and the name may too.
    public var description: String { "AccountExport(\(data.count) bytes)" }
    public var debugDescription: String { description }

    /// The bare file name a `Content-Disposition` value suggests (`filename*` before `filename`),
    /// else `fallbackFileName`.
    public static func fileName(fromContentDisposition header: String?) -> String {
        var plain: String?
        var extended: String?
        for segment in segments(of: header ?? "").dropFirst() {
            guard let equals = segment.firstIndex(of: "=") else { continue }
            let name = segment[..<equals].trimmingCharacters(in: .whitespaces).lowercased()
            let value = String(segment[segment.index(after: equals)...])
            if name == "filename" { plain = value } else if name == "filename*" { extended = decodeExtended(value) }
        }
        return [extended, plain].lazy.compactMap(bareName).first ?? fallbackFileName
    }

    /// Splits on `;` outside quotes, removing the quotes and resolving `\x` escapes inside them.
    private static func segments(of header: String) -> [String] {
        var result: [String] = []
        var current = ""
        var quoted = false
        var escaped = false
        for character in header {
            if escaped {
                current.append(character)
                escaped = false
            } else if quoted && character == "\\" {
                escaped = true
            } else if character == "\"" {
                quoted.toggle()
            } else if character == ";" && !quoted {
                result.append(current)
                current = ""
            } else {
                current.append(character)
            }
        }
        return result + [current]
    }

    /// `UTF-8''Name%20Here.zip` → `Name Here.zip`; any other charset is ignored.
    private static func decodeExtended(_ value: String) -> String? {
        let parts = value.split(separator: "'", maxSplits: 2, omittingEmptySubsequences: false)
        guard parts.count == 3, parts[0].uppercased() == "UTF-8" else { return nil }
        return String(parts[2]).removingPercentEncoding
    }

    /// The last path component without control characters; nil when nothing usable remains.
    private static func bareName(_ candidate: String?) -> String? {
        let unified = (candidate ?? "").replacingOccurrences(of: "\\", with: "/")
        guard let last = unified.split(separator: "/").last else { return nil }
        let name = String(String.UnicodeScalarView(last.unicodeScalars.filter { !CharacterSet.controlCharacters.contains($0) }))
            .trimmingCharacters(in: .whitespaces)
        return name.isEmpty || name == "." || name == ".." || name.utf8.count > 255 ? nil : name
    }
}

extension BrainBuddyAPIClient {
    /// `GET /account/export` → the ZIP and the server's suggested name. Cancelling the calling task
    /// ends the request as `.cancelled`.
    public func exportAccount() async throws(APIError) -> AccountExport {
        let exchange = try await exchange(Endpoint(.get, ["account", "export"]))
        let name = AccountExport.fileName(fromContentDisposition: exchange.response.header("Content-Disposition"))
        return AccountExport(suggestedFileName: name, data: exchange.response.body)
    }
}

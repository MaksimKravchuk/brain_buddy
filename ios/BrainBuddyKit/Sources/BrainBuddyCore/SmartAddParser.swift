import Foundation

/// The Smart Add grammar, ported from the web tokenizer
/// (`frontend/src/features/tasks/smartAdd.ts`, normative contract
/// `specs/003-smart-add-classification/contracts/smart-add.md`, ADR-0007) and
/// the macOS prototype (`macos/Sources/BrainBuddyMac/SmartAddParser.swift`).
///
/// The parser only knows the grammar. Resolving names against projects and
/// tags, contexts and validation live in `CapturePlanner`.
///
/// - `#tag` and `@project`; quoted `#"deep work"` / `@"Two words"` with `\"`
///   and `\\` escapes, no line break, and an unterminated quote stays literal.
/// - `\#` and `\@` at a token boundary are literal sigils; the backslash is
///   dropped from the title.
/// - A token needs a left boundary (start, whitespace, `(`, `[`, `{`), so
///   `C#` and `max@example.com` stay literal.
/// - Unquoted names are Unicode letters, marks and numbers plus `_`, with `-`
///   or `.` inside the name only when a name character follows.
///
/// The text is walked by Unicode scalar. The web walks UTF-16 code units, which
/// differs only for characters outside the Basic Multilingual Plane: there the
/// scalar reading is the one the contract describes (see `Result.tokens`).
public enum SmartAddParser {
    public struct Result: Hashable, Sendable {
        /// The title that is stored: completed tokens, brackets that wrapped a
        /// lone token and escape backslashes removed, whitespace runs collapsed
        /// to one space, ends trimmed, and no space before `,.;:!?)]}`.
        public var cleanTitle: String
        /// Every completed token in text order, including duplicate tags and
        /// superseded projects (they are removed from the title too). `name` is
        /// the decoded body after NFKC, trim and whitespace collapse; a legacy
        /// sigil inside a quoted name (`#"#work"`) is still there, the planner
        /// drops it when it resolves the name.
        public var tokens: [SmartAddToken]

        public init(cleanTitle: String, tokens: [SmartAddToken]) {
            self.cleanTitle = cleanTitle
            self.tokens = tokens
        }
    }

    public static func parse(_ text: String) -> Result {
        let scalars = Array(text.unicodeScalars)
        var utf16Offsets = [0]
        utf16Offsets.reserveCapacity(scalars.count + 1)
        for scalar in scalars { utf16Offsets.append(utf16Offsets[utf16Offsets.count - 1] + scalar.utf16.count) }

        var spans: [Span] = []
        var escapes: [Int] = []
        var index = 0
        while index < scalars.count {
            let scalar = scalars[index]
            let next = index + 1 < scalars.count ? scalars[index + 1] : nil
            if scalar == "\\", next == "#" || next == "@", hasLeftBoundary(scalars, index) {
                escapes.append(index)
                index += 2
                continue
            }
            guard scalar == "#" || scalar == "@", hasLeftBoundary(scalars, index) else {
                index += 1
                continue
            }
            let body = next == "\"" ? parseQuoted(scalars, quote: index + 1) : parseUnquoted(scalars, from: index + 1)
            guard let body else {
                index += 1
                continue
            }
            let name = collapsed(body.name.precomposedStringWithCompatibilityMapping.unicodeScalars)
            guard !name.isEmpty else {
                index += 1
                continue
            }
            spans.append(Span(kind: scalar == "#" ? .tag : .project, start: index, end: body.end, name: name))
            index = body.end
        }

        let tokens = spans.map { span in
            SmartAddToken(
                kind: span.kind, utf16Range: utf16Offsets[span.start]..<utf16Offsets[span.end], name: span.name
            )
        }
        return Result(cleanTitle: cleanTitle(scalars, spans: spans, escapes: escapes), tokens: tokens)
    }

    // MARK: - Grammar

    private struct Span {
        var kind: SmartAddToken.Kind
        /// Scalar offsets: `start` is the sigil, `end` is one past the body.
        var start: Int
        var end: Int
        var name: String
    }

    private static func hasLeftBoundary(_ scalars: [Unicode.Scalar], _ index: Int) -> Bool {
        guard index > 0 else { return true }
        let previous = scalars[index - 1]
        return isWhitespace(previous) || previous == "(" || previous == "[" || previous == "{"
    }

    /// `quote` is the opening `"`. Nil when the quote never closes or a line
    /// break comes first: the token is then incomplete and stays literal.
    private static func parseQuoted(_ scalars: [Unicode.Scalar], quote: Int) -> (name: String, end: Int)? {
        var name = String.UnicodeScalarView()
        var index = quote + 1
        while index < scalars.count {
            let scalar = scalars[index]
            if scalar == "\n" || scalar == "\r" { return nil }
            if scalar == "\\", index + 1 < scalars.count, scalars[index + 1] == "\"" || scalars[index + 1] == "\\" {
                name.append(scalars[index + 1])
                index += 2
                continue
            }
            if scalar == "\"" { return (String(name), index + 1) }
            // Any other backslash is kept as written (`#"literal \q"`).
            name.append(scalar)
            index += 1
        }
        return nil
    }

    private static func parseUnquoted(_ scalars: [Unicode.Scalar], from start: Int) -> (name: String, end: Int)? {
        guard start < scalars.count, isNameCharacter(scalars[start]) else { return nil }
        var end = start + 1
        while end < scalars.count {
            if isNameCharacter(scalars[end]) {
                end += 1
            } else if scalars[end] == "-" || scalars[end] == ".", end + 1 < scalars.count,
                isNameCharacter(scalars[end + 1])
            {
                end += 1
            } else {
                break
            }
        }
        return (String(String.UnicodeScalarView(scalars[start..<end])), end)
    }

    /// Unicode Letter, Number or Mark, or `_` (the web's `[\p{L}\p{N}\p{M}_]`).
    private static func isNameCharacter(_ scalar: Unicode.Scalar) -> Bool {
        if scalar == "_" { return true }
        switch scalar.properties.generalCategory {
        case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter, .otherLetter,
            .decimalNumber, .letterNumber, .otherNumber,
            .nonspacingMark, .spacingMark, .enclosingMark:
            return true
        default:
            return false
        }
    }

    /// Exactly JavaScript's `\s` (WhiteSpace and LineTerminator), so the
    /// boundaries and the title cleanup agree with the web character for
    /// character. It differs from Unicode `White_Space` in U+FEFF (included)
    /// and U+0085 (excluded).
    private static func isWhitespace(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.value {
        case 0x09...0x0D, 0x20, 0xA0, 0x1680, 0x2000...0x200A, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF:
            true
        default:
            false
        }
    }

    // MARK: - Title cleanup

    private static let wrapperClose: [Unicode.Scalar: Unicode.Scalar] = ["(": ")", "[": "]", "{": "}"]
    private static let closingPunctuation: Set<Unicode.Scalar> = [",", ".", ";", ":", "!", "?", ")", "]", "}"]

    private static func cleanTitle(_ scalars: [Unicode.Scalar], spans: [Span], escapes: [Int]) -> String {
        var removed = [Bool](repeating: false, count: scalars.count)
        for span in spans {
            var start = span.start
            var end = span.end
            // Everything between a bracket found here and the token is
            // whitespace, so a matching pair wraps the token alone.
            var left = start - 1
            while left >= 0, isWhitespace(scalars[left]) { left -= 1 }
            var right = end
            while right < scalars.count, isWhitespace(scalars[right]) { right += 1 }
            if left >= 0, right < scalars.count, let close = wrapperClose[scalars[left]], scalars[right] == close {
                start = left
                end = right + 1
            }
            for position in start..<end { removed[position] = true }
        }
        for position in escapes { removed[position] = true }
        let kept = scalars.indices.lazy.filter { !removed[$0] }.map { scalars[$0] }
        return collapsed(kept, tightenPunctuation: true)
    }

    /// Collapses whitespace runs to one ASCII space and trims the ends. With
    /// `tightenPunctuation`, a run before closing punctuation is dropped.
    private static func collapsed<S: Sequence<Unicode.Scalar>>(
        _ scalars: S, tightenPunctuation: Bool = false
    ) -> String {
        var output = String.UnicodeScalarView()
        var pendingSpace = false
        for scalar in scalars {
            if isWhitespace(scalar) {
                pendingSpace = !output.isEmpty
                continue
            }
            if pendingSpace, !(tightenPunctuation && closingPunctuation.contains(scalar)) { output.append(" ") }
            pendingSpace = false
            output.append(scalar)
        }
        return String(output)
    }
}

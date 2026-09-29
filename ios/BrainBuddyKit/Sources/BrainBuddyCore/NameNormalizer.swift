import Foundation

/// The server's project and tag name rules (`backend/app/modules/tasks/repository.py`),
/// reproduced code point for code point: NFKC, Python `str.strip()` / `str.split()`
/// whitespace, and Python `str.casefold()` — full Unicode case folding, so
/// "Straße" and "STRASSE" collide. The work is done on Unicode scalars with the
/// stdlib's own tables, so Linux and Apple platforms agree. Uniqueness only
/// applies among active records.
public enum NameNormalizer {
    /// `normalize_task_name(name)`: the key two project names collide on.
    public static func project(_ name: String) -> String {
        caseFolded(collapsed(nfkc(name)))
    }

    /// `normalize_task_name(name, strip_tag_prefix=True)`: the key two tag
    /// names collide on; one leading `@` is ignored. Compare a stored tag's
    /// name as is, and a newly typed one as `tag(tagDisplay(input))`, which is
    /// what the server stores and then keys.
    public static func tag(_ name: String) -> String {
        caseFolded(collapsed(droppingAtPrefix(stripped(nfkc(name)))))
    }

    /// `display_project_name`: NFKC, trimmed, whitespace collapsed — the
    /// project name the server stores.
    public static func display(_ name: String) -> String {
        collapsed(nfkc(name))
    }

    /// `display_tag_name`: like `display`, and one leading `@` is dropped —
    /// the tag name the server stores.
    public static func tagDisplay(_ name: String) -> String {
        collapsed(droppingAtPrefix(stripped(nfkc(name))))
    }

    // MARK: - Python string semantics

    /// Python's `str.isspace()`: Unicode `Zs`, or bidirectional class `WS`, `B`
    /// or `S`. Unlike `Character.isWhitespace` it includes U+001C…U+001F.
    static func isSpace(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.value {
        case 0x09...0x0D, 0x1C...0x20, 0x85, 0xA0, 0x1680, 0x2000...0x200A, 0x2028, 0x2029, 0x202F, 0x205F,
            0x3000:
            true
        default:
            false
        }
    }

    /// Python's `str.strip()` with no arguments: leading and trailing
    /// `isSpace` scalars removed, nothing else touched. It is how the server
    /// and every client trim a title, and how `GTDReducer` stores titles and
    /// waiting notes, so sync uses it to send and match exactly those values.
    public static func stripped(_ value: String) -> String {
        let scalars = value.unicodeScalars
        guard let first = scalars.firstIndex(where: { !isSpace($0) }),
            let last = scalars.lastIndex(where: { !isSpace($0) })
        else { return "" }
        return String(scalars[first...last])
    }

    /// Python's `" ".join(value.split())`.
    static func collapsed(_ value: String) -> String {
        var result = String.UnicodeScalarView()
        var pendingSpace = false
        for scalar in value.unicodeScalars {
            if isSpace(scalar) {
                pendingSpace = !result.isEmpty
                continue
            }
            if pendingSpace {
                result.append(" ")
                pendingSpace = false
            }
            result.append(scalar)
        }
        return String(result)
    }

    private static func nfkc(_ value: String) -> String {
        value.precomposedStringWithCompatibilityMapping
    }

    private static func droppingAtPrefix(_ value: String) -> String {
        guard value.unicodeScalars.first == "@" else { return value }
        return stripped(String(value.unicodeScalars.dropFirst()))
    }

    /// Python's `str.casefold()` for NFKC text: each scalar's full lowercase
    /// mapping, except where Unicode's full case folding differs from it.
    /// Python does not renormalize the result, and neither does this.
    static func caseFolded(_ value: String) -> String {
        var result = String.UnicodeScalarView()
        for scalar in value.unicodeScalars {
            let code = scalar.value
            switch code {
            case 0x13A0...0x13F5:
                // Cherokee capitals fold to themselves (their lowercase is U+AB70…).
                result.append(scalar)
            case 0x13F8...0x13FD:
                result.append(Unicode.Scalar(code - 8)!)
            case 0xAB70...0xABBF:
                result.append(Unicode.Scalar(code - 0xAB70 + 0x13A0)!)
            case 0x1F80...0x1FAF:
                // Greek with ypogegrammeni / prosgegrammeni: base letter + iota.
                let base: UInt32 = [0x1F00, 0x1F20, 0x1F60][Int((code - 0x1F80) / 16)] + (code & 0x7)
                result.append(Unicode.Scalar(base)!)
                result.append("\u{3B9}")
            default:
                if let folded = foldingExceptions[code] {
                    result.append(contentsOf: folded.map { Unicode.Scalar($0)! })
                } else {
                    result.append(contentsOf: scalar.properties.lowercaseMapping.unicodeScalars)
                }
            }
        }
        return String(result)
    }

    /// NFKC-stable scalars whose full case folding (CaseFolding.txt, status C
    /// and F) is not their full lowercase mapping, as of Unicode 14 (the
    /// server's Python 3.11), apart from the ranges handled above.
    private static let foldingExceptions: [UInt32: [UInt32]] = [
        0x00DF: [0x73, 0x73], 0x1E9E: [0x73, 0x73], 0x01F0: [0x6A, 0x30C], 0x0345: [0x3B9],
        0x0390: [0x3B9, 0x308, 0x301], 0x03B0: [0x3C5, 0x308, 0x301], 0x03C2: [0x3C3],
        0x1C80: [0x432], 0x1C81: [0x434], 0x1C82: [0x43E], 0x1C83: [0x441], 0x1C84: [0x442],
        0x1C85: [0x442], 0x1C86: [0x44A], 0x1C87: [0x463], 0x1C88: [0xA64B],
        0x1E96: [0x68, 0x331], 0x1E97: [0x74, 0x308], 0x1E98: [0x77, 0x30A], 0x1E99: [0x79, 0x30A],
        0x1F50: [0x3C5, 0x313], 0x1F52: [0x3C5, 0x313, 0x300], 0x1F54: [0x3C5, 0x313, 0x301],
        0x1F56: [0x3C5, 0x313, 0x342],
        0x1FB2: [0x1F70, 0x3B9], 0x1FB3: [0x3B1, 0x3B9], 0x1FB4: [0x3AC, 0x3B9], 0x1FB6: [0x3B1, 0x342],
        0x1FB7: [0x3B1, 0x342, 0x3B9], 0x1FBC: [0x3B1, 0x3B9],
        0x1FC2: [0x1F74, 0x3B9], 0x1FC3: [0x3B7, 0x3B9], 0x1FC4: [0x3AE, 0x3B9], 0x1FC6: [0x3B7, 0x342],
        0x1FC7: [0x3B7, 0x342, 0x3B9], 0x1FCC: [0x3B7, 0x3B9],
        0x1FD2: [0x3B9, 0x308, 0x300], 0x1FD6: [0x3B9, 0x342], 0x1FD7: [0x3B9, 0x308, 0x342],
        0x1FE2: [0x3C5, 0x308, 0x300], 0x1FE4: [0x3C1, 0x313], 0x1FE6: [0x3C5, 0x342],
        0x1FE7: [0x3C5, 0x308, 0x342],
        0x1FF2: [0x1F7C, 0x3B9], 0x1FF3: [0x3C9, 0x3B9], 0x1FF4: [0x3CE, 0x3B9], 0x1FF6: [0x3C9, 0x342],
        0x1FF7: [0x3C9, 0x342, 0x3B9], 0x1FFC: [0x3C9, 0x3B9],
    ]
}

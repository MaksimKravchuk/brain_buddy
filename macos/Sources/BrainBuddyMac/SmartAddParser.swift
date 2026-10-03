import Foundation

struct SmartAddDraft {
    let cleanTitle: String
    let tags: [ClassificationRef]
    let project: ClassificationRef?
    let hasCompletedTokens: Bool
    let isValid: Bool

    func previewProjectName(in projects: [BrainBuddyProject]) -> String? {
        switch project {
        case .id(let id): projects.first(where: { $0.id == id })?.name ?? id
        case .name(let name): name
        case nil: nil
        }
    }

    func previewTagNames(in tags: [BrainBuddyTag]) -> [String] {
        self.tags.map { ref in
            switch ref {
            case .id(let id): tags.first(where: { $0.id == id })?.name ?? id
            case .name(let name): name
            }
        }
    }
}

enum SmartAddParser {
    private enum Kind { case tag, project }

    private struct Token {
        let kind: Kind
        let start: Int
        let end: Int
        let name: String
    }

    static func parse(
        _ input: String, projects: [BrainBuddyProject], tags: [BrainBuddyTag],
        contextProjectId: String? = nil, contextTagId: String? = nil
    ) -> SmartAddDraft {
        let scalars = Array(input.unicodeScalars)
        var tokens: [Token] = []
        var escapedBackslashes: [Int] = []
        var index = 0
        while index < scalars.count {
            let scalar = scalars[index]
            let next = index + 1 < scalars.count ? scalars[index + 1] : nil
            if scalar == "\\", (next == "#" || next == "@"), hasLeftBoundary(scalars, index) {
                escapedBackslashes.append(index)
                index += 2
                continue
            }
            guard (scalar == "#" || scalar == "@"), hasLeftBoundary(scalars, index),
                  let parsed = next == "\""
                    ? parseQuoted(scalars, from: index + 1)
                    : parseUnquoted(scalars, from: index + 1),
                  !displayName(parsed.name).isEmpty else {
                index += 1
                continue
            }
            tokens.append(Token(
                kind: scalar == "#" ? .tag : .project,
                start: index, end: parsed.end, name: displayName(parsed.name)
            ))
            index = parsed.end
        }

        var tagRefs: [ClassificationRef] = []
        var seenTags: Set<String> = []
        func appendTag(_ ref: ClassificationRef) {
            let key: String
            switch ref {
            case .id(let id): key = "id:\(id)"
            case .name(let name): key = "name:\(normalize(stripTagSigil(name)))"
            }
            if seenTags.insert(key).inserted { tagRefs.append(ref) }
        }
        if let contextTagId { appendTag(.id(contextTagId)) }
        var projectRef = contextProjectId.map(ClassificationRef.id)
        for token in tokens {
            switch token.kind {
            case .tag:
                let name = stripTagSigil(token.name)
                let key = normalize(name)
                if let existing = tags.first(where: { normalize(stripTagSigil($0.name)) == key }) {
                    appendTag(.id(existing.id))
                } else {
                    appendTag(.name(displayName(name)))
                }
            case .project:
                let name = stripProjectSigil(token.name)
                let key = normalize(name)
                if let existing = projects.first(where: { normalize(stripProjectSigil($0.name)) == key }) {
                    projectRef = .id(existing.id)
                } else {
                    projectRef = .name(displayName(name))
                }
            }
        }

        let title = cleanTitle(scalars, tokens: tokens, escapedBackslashes: escapedBackslashes)
        let validTags = tagRefs.allSatisfy { ref in
            if case .name(let name) = ref { return name.utf16.count <= 500 }
            return true
        }
        let validProject: Bool
        if case .name(let name) = projectRef { validProject = name.utf16.count <= 500 }
        else { validProject = true }
        return SmartAddDraft(
            cleanTitle: title, tags: tagRefs, project: projectRef,
            hasCompletedTokens: !tokens.isEmpty,
            isValid: !title.isEmpty && title.utf16.count <= 500 && validTags && validProject
        )
    }

    private static func hasLeftBoundary(_ scalars: [Unicode.Scalar], _ index: Int) -> Bool {
        index == 0 || isWhitespace(scalars[index - 1]) ||
            scalars[index - 1] == "(" || scalars[index - 1] == "[" || scalars[index - 1] == "{"
    }

    private static func parseQuoted(
        _ scalars: [Unicode.Scalar], from quote: Int
    ) -> (name: String, end: Int)? {
        var name = String.UnicodeScalarView()
        var index = quote + 1
        while index < scalars.count {
            let scalar = scalars[index]
            if scalar == "\n" || scalar == "\r" { return nil }
            if scalar == "\\", index + 1 < scalars.count,
               scalars[index + 1] == "\"" || scalars[index + 1] == "\\" {
                name.append(scalars[index + 1])
                index += 2
                continue
            }
            if scalar == "\"" { return (String(name), index + 1) }
            name.append(scalar)
            index += 1
        }
        return nil
    }

    private static func parseUnquoted(
        _ scalars: [Unicode.Scalar], from start: Int
    ) -> (name: String, end: Int)? {
        guard start < scalars.count, isNameChar(scalars[start]) else { return nil }
        var end = start + 1
        while end < scalars.count {
            if isNameChar(scalars[end]) { end += 1; continue }
            if (scalars[end] == "-" || scalars[end] == "."),
               end + 1 < scalars.count, isNameChar(scalars[end + 1]) {
                end += 1
                continue
            }
            break
        }
        return (String(String.UnicodeScalarView(scalars[start..<end])), end)
    }

    private static func isNameChar(_ scalar: Unicode.Scalar) -> Bool {
        if scalar == "_" { return true }
        switch scalar.properties.generalCategory {
        case .uppercaseLetter, .lowercaseLetter, .titlecaseLetter, .modifierLetter,
             .otherLetter, .decimalNumber, .letterNumber, .otherNumber,
             .nonspacingMark, .spacingMark, .enclosingMark:
            return true
        default:
            return false
        }
    }

    private static func isWhitespace(_ scalar: Unicode.Scalar) -> Bool {
        CharacterSet.whitespacesAndNewlines.contains(scalar)
    }

    private static func displayName(_ value: String) -> String {
        collapseWhitespace(value.precomposedStringWithCompatibilityMapping)
    }

    private static func normalize(_ value: String) -> String {
        displayName(value).lowercased()
    }

    private static func collapseWhitespace(_ value: String) -> String {
        var result = ""
        var pendingSpace = false
        for scalar in value.unicodeScalars {
            if isWhitespace(scalar) {
                if !result.isEmpty { pendingSpace = true }
            } else {
                if pendingSpace { result.append(" "); pendingSpace = false }
                result.unicodeScalars.append(scalar)
            }
        }
        return result
    }

    private static func stripTagSigil(_ value: String) -> String {
        if value.hasPrefix("#") || value.hasPrefix("@") { return String(value.dropFirst()) }
        return value
    }

    private static func stripProjectSigil(_ value: String) -> String {
        value.hasPrefix("@") ? String(value.dropFirst()) : value
    }

    private static func cleanTitle(
        _ scalars: [Unicode.Scalar], tokens: [Token], escapedBackslashes: [Int]
    ) -> String {
        var removed = Array(repeating: false, count: scalars.count)
        for token in tokens {
            var start = token.start
            var end = token.end
            var left = start - 1
            while left >= 0, isWhitespace(scalars[left]) { left -= 1 }
            var right = end
            while right < scalars.count, isWhitespace(scalars[right]) { right += 1 }
            let close: Unicode.Scalar?
            if left >= 0 {
                switch scalars[left] {
                case "(": close = ")"
                case "[": close = "]"
                case "{": close = "}"
                default: close = nil
                }
            } else { close = nil }
            if let close, right < scalars.count, scalars[right] == close {
                start = left
                end = right + 1
            }
            for position in start..<end { removed[position] = true }
        }
        for position in escapedBackslashes { removed[position] = true }
        let kept = String(String.UnicodeScalarView(scalars.enumerated().compactMap {
            removed[$0.offset] ? nil : $0.element
        }))
        let collapsed = collapseWhitespace(kept)
        var output = ""
        for character in collapsed {
            if ",.;:!?])}".contains(character), output.last == " " { output.removeLast() }
            output.append(character)
        }
        return output
    }
}

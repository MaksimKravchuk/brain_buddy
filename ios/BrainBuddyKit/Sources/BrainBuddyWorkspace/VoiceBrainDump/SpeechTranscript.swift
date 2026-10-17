import Foundation

/// Joins on-device recognition results into the whole text heard since `start`.
///
/// On-device recognition starts its transcription over after a pause: the next partial result
/// holds only the new words. Each pause therefore closes an utterance, and the text heard is the
/// utterances in order. An utterance closes when the recogniser says it ended (`endsUtterance`), or
/// when a result plainly starts over (fewer words, a different first word). If the recogniser
/// carries on with the whole text after all, the closed utterance is reopened, so nothing repeats.
public struct SpeechTranscript: Equatable, Sendable {
    private var closed: [String] = []
    private var current = ""

    public init() {}

    /// The utterances in order; one that ends without punctuation gets a full stop, so each pause
    /// reads as its own sentence.
    public var text: String {
        let parts = closed + (current.isEmpty ? [] : [current])
        return parts.enumerated().map { index, part in
            index < parts.count - 1 && !Self.endsSentence(part) ? part + "." : part
        }.joined(separator: " ")
    }

    /// Takes the recogniser's latest text and returns the whole text heard.
    @discardableResult
    public mutating func receive(_ result: String, endsUtterance: Bool = false) -> String {
        let fresh = result.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !fresh.isEmpty else {
            if endsUtterance, !current.isEmpty {
                closed.append(current)
                current = ""
            }
            return text
        }
        if current.isEmpty, let last = closed.last, Self.continues(fresh, last) {
            closed.removeLast()  // the recogniser did not start over: this result holds the last utterance
        } else if Self.startsOver(fresh, after: current) {
            closed.append(current)
        }
        current = fresh
        if endsUtterance, !current.isEmpty {
            closed.append(current)
            current = ""
        }
        return text
    }

    // MARK: Private

    private static func words(_ text: String) -> [String] {
        text.lowercased()
            .split(whereSeparator: { $0.isWhitespace })
            .map { $0.trimmingCharacters(in: .punctuationCharacters) }
            .filter { !$0.isEmpty }
    }

    /// `fresh` begins with every word of `earlier`.
    private static func continues(_ fresh: String, _ earlier: String) -> Bool {
        let before = words(earlier)
        return !before.isEmpty && words(fresh).starts(with: before)
    }

    /// A revision keeps the first word and rarely loses words; a new utterance does neither.
    private static func startsOver(_ fresh: String, after current: String) -> Bool {
        let old = words(current), new = words(fresh)
        guard let oldFirst = old.first, let newFirst = new.first else { return false }
        return new.count < old.count && newFirst != oldFirst
    }

    private static func endsSentence(_ text: String) -> Bool {
        guard let last = text.last else { return true }
        return ".!?;…".contains(last)
    }
}

import Testing

@testable import BrainBuddyCore

/// Expected values were produced by the server's own functions
/// (`display_project_name`, `normalize_task_name`, `display_tag_name`) on
/// Python 3.14 / Unicode 16.0.0, the backend's runtime, and are compared scalar by
/// scalar rather than with `String ==` (which is canonical equivalence).
@Suite("Name normalization matches the server")
struct NameNormalizerTests {
    struct Vector: CustomTestStringConvertible, Sendable {
        let input: String
        let display: String
        let project: String
        let tagDisplay: String
        let tag: String
        var testDescription: String { input.unicodeScalars.map { String($0.value, radix: 16) }.joined(separator: " ") }
    }

    static let vectors: [Vector] = [
        ("  Deep   Work ", "Deep Work", "deep work", "Deep Work", "deep work"),
        ("\u{FF37}\u{FF4F}\u{FF52}\u{FF4B}", "Work", "work", "Work", "work"),
        ("\u{FB01}le", "file", "file", "file", "file"),
        ("Stra\u{DF}e", "Stra\u{DF}e", "strasse", "Stra\u{DF}e", "strasse"),
        ("STRASSE", "STRASSE", "strasse", "STRASSE", "strasse"),
        ("\u{1E9E}", "\u{1E9E}", "ss", "\u{1E9E}", "ss"),
        ("\u{39F}\u{394}\u{39F}\u{3A3}", "\u{39F}\u{394}\u{39F}\u{3A3}", "\u{3BF}\u{3B4}\u{3BF}\u{3C3}",
         "\u{39F}\u{394}\u{39F}\u{3A3}", "\u{3BF}\u{3B4}\u{3BF}\u{3C3}"),
        ("\u{3BF}\u{3B4}\u{3BF}\u{3C2}", "\u{3BF}\u{3B4}\u{3BF}\u{3C2}", "\u{3BF}\u{3B4}\u{3BF}\u{3C3}",
         "\u{3BF}\u{3B4}\u{3BF}\u{3C2}", "\u{3BF}\u{3B4}\u{3BF}\u{3C3}"),
        ("\u{13A0}\u{13F8}", "\u{13A0}\u{13F8}", "\u{13A0}\u{13F0}", "\u{13A0}\u{13F8}", "\u{13A0}\u{13F0}"),
        ("\u{AB70}\u{13F0}", "\u{AB70}\u{13F0}", "\u{13A0}\u{13F0}", "\u{AB70}\u{13F0}", "\u{13A0}\u{13F0}"),
        ("\u{1FB3}", "\u{1FB3}", "\u{3B1}\u{3B9}", "\u{1FB3}", "\u{3B1}\u{3B9}"),
        ("\u{1FBC}", "\u{1FBC}", "\u{3B1}\u{3B9}", "\u{1FBC}", "\u{3B1}\u{3B9}"),
        ("\u{1F88}x", "\u{1F88}x", "\u{1F00}\u{3B9}x", "\u{1F88}x", "\u{1F00}\u{3B9}x"),
        ("\u{1F0}", "\u{1F0}", "j\u{30C}", "\u{1F0}", "j\u{30C}"),
        ("\u{130}stanbul", "\u{130}stanbul", "i\u{307}stanbul", "\u{130}stanbul", "i\u{307}stanbul"),
        ("\u{1C}Work\u{1F}", "Work", "work", "Work", "work"),
        ("a\u{A0}\u{3000}b", "a b", "a b", "a b", "a b"),
        ("a\u{200B}b", "a\u{200B}b", "a\u{200B}b", "a\u{200B}b", "a\u{200B}b"),
        ("a \u{301}b", "a \u{301}b", "a \u{301}b", "a \u{301}b", "a \u{301}b"),
        ("\u{212A}", "K", "k", "K", "k"),
        ("\u{1C80}", "\u{1C80}", "\u{432}", "\u{1C80}", "\u{432}"),
        ("@Home", "@Home", "@home", "Home", "home"),
        ("@ home", "@ home", "@ home", "home", "home"),
        ("@@home", "@@home", "@@home", "@home", "@home"),
        ("\u{FF20}Home", "@Home", "@home", "Home", "home"),
        (" @\u{301}x", "@\u{301}x", "@\u{301}x", "\u{301}x", "\u{301}x"),
        ("\u{2126}", "\u{3A9}", "\u{3C9}", "\u{3A9}", "\u{3C9}"),
        ("\u{B5}", "\u{3BC}", "\u{3BC}", "\u{3BC}", "\u{3BC}"),
        ("cafe\u{301}", "caf\u{E9}", "caf\u{E9}", "caf\u{E9}", "caf\u{E9}"),
        ("   ", "", "", "", ""),
        ("@", "@", "@", "", ""),
    ].map { Vector(input: $0.0, display: $0.1, project: $0.2, tagDisplay: $0.3, tag: $0.4) }

    @Test("Matches Python for every vector", arguments: vectors)
    func matchesServer(_ vector: Vector) {
        #expect(scalars(NameNormalizer.display(vector.input)) == scalars(vector.display))
        #expect(scalars(NameNormalizer.project(vector.input)) == scalars(vector.project))
        #expect(scalars(NameNormalizer.tagDisplay(vector.input)) == scalars(vector.tagDisplay))
        #expect(scalars(NameNormalizer.tag(vector.input)) == scalars(vector.tag))
    }

    @Test("Sharp s folds to ss, as Python's casefold does")
    func sharpS() {
        #expect(NameNormalizer.project("Straße") == NameNormalizer.project("STRASSE"))
        #expect(NameNormalizer.tag("Maß") == NameNormalizer.tag("MASS"))
        #expect(NameNormalizer.project("ẞ") == "ss")
    }

    @Test("The server keys a new tag on its stored (display) name")
    func newTagKey() {
        // normalize_task_name(display_tag_name("@@home"), strip_tag_prefix=True)
        #expect(NameNormalizer.tag(NameNormalizer.tagDisplay("@@home")) == "home")
        for raw in [" @Home ", "Ｗｏｒｋ", "Straße", "a\u{3000}b"] {
            #expect(NameNormalizer.project(NameNormalizer.display(raw)) == NameNormalizer.project(raw))
            #expect(NameNormalizer.display(NameNormalizer.display(raw)) == NameNormalizer.display(raw))
        }
    }

    @Test("Python whitespace: strip and split")
    func pythonWhitespace() {
        #expect(NameNormalizer.stripped("\u{1D} \t a b \u{2029}") == "a b")
        #expect(NameNormalizer.stripped(" \u{85} ") == "")
        #expect(NameNormalizer.collapsed("  a \u{1680}\u{3000} b\n") == "a b")
        #expect(!NameNormalizer.isSpace("\u{200B}"))
        #expect(NameNormalizer.isSpace("\u{1C}"))
    }

    private func scalars(_ value: String) -> [UInt32] { value.unicodeScalars.map(\.value) }
}

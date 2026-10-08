import Testing
@testable import BrainBuddyCore

/// Grammar, UTF-16 highlighting ranges and Unicode handling of
/// `SmartAddParser`. The web-parity cases live in `SmartAddWebParityTests`.
@Suite("Smart Add parser")
struct SmartAddParserTests {
    private func parse(_ text: String) -> SmartAddParser.Result { SmartAddParser.parse(text) }

    /// Each token's range must cover exactly its sigil and body in the original text.
    private func highlighted(_ text: String) -> [String] {
        parse(text).tokens.map { SmartAddFixtures.text(text, in: $0.utf16Range) }
    }

    // MARK: - Tokens and ranges

    @Test func reportsKindsNamesAndUTF16RangesInTextOrder() {
        let result = parse("Plan #work @\"Launch v2\" #\"deep work\"")

        #expect(
            result.tokens == [
                SmartAddToken(kind: .tag, utf16Range: 5..<10, name: "work"),
                SmartAddToken(kind: .project, utf16Range: 11..<23, name: "Launch v2"),
                SmartAddToken(kind: .tag, utf16Range: 24..<36, name: "deep work"),
            ])
        #expect(result.cleanTitle == "Plan")
    }

    @Test func keepsDuplicateAndSupersededTokensForHighlighting() {
        let text = "Draft @old #work @new #WORK"

        #expect(highlighted(text) == ["@old", "#work", "@new", "#WORK"])
        #expect(parse(text).cleanTitle == "Draft")
    }

    @Test func rangesCountSurrogatePairsBeforeAToken() {
        // 😀 is one scalar but two UTF-16 units. DIVERGENCE: the web currently
        // returns "😀 Plan #" here — its `cleanTitle` marks removals by UTF-16
        // index but filters `Array.from(input)`, which is indexed by code point,
        // so every astral character before a token shifts the removal by one.
        let text = "😀 Plan #work"
        let result = parse(text)

        #expect(result.tokens.map(\.utf16Range) == [8..<13])
        #expect(highlighted(text) == ["#work"])
        #expect(result.cleanTitle == "😀 Plan")
    }

    @Test func rangesSpanDecomposedCharactersAndReportTheComposedName() {
        // e + U+0301 is one character, two scalars, two UTF-16 units.
        let text = "Ping #cafe\u{301} now"
        let result = parse(text)

        #expect(result.tokens.map(\.utf16Range) == [5..<11])
        #expect(result.tokens.map(\.name) == ["caf\u{E9}"])
        #expect(highlighted(text) == ["#cafe\u{301}"])
    }

    @Test func rangesCoverEmojiInsideAQuotedName() {
        let text = "Ship @\"🚀 Launch\" today"
        let result = parse(text)

        #expect(result.tokens.map(\.utf16Range) == [5..<17])
        #expect(result.tokens.map(\.name) == ["🚀 Launch"])
        #expect(result.cleanTitle == "Ship today")
    }

    @Test func anEmojiEndsAnUnquotedNameWithoutSplittingIt() {
        let text = "#work👨‍👩‍👧 done 🇷🇺 #дом"
        let result = parse(text)

        #expect(highlighted(text) == ["#work", "#дом"])
        #expect(result.cleanTitle == "👨‍👩‍👧 done 🇷🇺")
    }

    @Test func variationSelectorsAndKeycapMarksContinueAName() {
        // "1" + U+FE0F (Mn) + U+20E3 (Me): marks are name characters.
        let text = "Pick #1\u{FE0F}\u{20E3} first"

        #expect(highlighted(text) == ["#1\u{FE0F}\u{20E3}"])
        #expect(parse(text).cleanTitle == "Pick first")
    }

    @Test func astralLettersAreNameCharactersAndFoldThroughNFKC() {
        // DIVERGENCE: U+1D400 MATHEMATICAL BOLD CAPITAL A is a Letter, so the
        // contract makes it a name character. The web tests one UTF-16 unit at a
        // time and so rejects both halves of the surrogate pair.
        let text = "#𝐀bc now"
        let result = parse(text)

        #expect(result.tokens == [SmartAddToken(kind: .tag, utf16Range: 0..<5, name: "Abc")])
        #expect(result.cleanTitle == "now")
    }

    // MARK: - Unicode names

    @Test func parsesCyrillicProjectAndTag() {
        let result = parse("Купить молоко @Дом #срочно")

        #expect(result.cleanTitle == "Купить молоко")
        #expect(
            result.tokens == [
                SmartAddToken(kind: .project, utf16Range: 14..<18, name: "Дом"),
                SmartAddToken(kind: .tag, utf16Range: 19..<26, name: "срочно"),
            ])
    }

    @Test func quotedCyrillicNameWithSpacesAndHyphenatedBareName() {
        let result = parse("Позвонить @\"Ремонт   кухни\" #в-пути")

        #expect(result.cleanTitle == "Позвонить")
        #expect(result.tokens.map(\.name) == ["Ремонт кухни", "в-пути"])
    }

    @Test func normalizesNamesWithNFKC() {
        // Full-width letters and the ﬁ ligature are letters; NFKC maps them to ASCII.
        #expect(parse("Plan #ｗｏｒｋ @ﬁnance").tokens.map(\.name) == ["work", "finance"])
        // A no-break space inside a quoted name collapses like any other whitespace.
        #expect(parse("Plan #\"deep\u{A0}\u{A0}work\"").tokens.map(\.name) == ["deep work"])
    }

    @Test func otherScriptsAreNameCharacters() {
        #expect(parse("#日本語 #한국어 #العربية #हिन्दी x").tokens.map(\.name) == ["日本語", "한국어", "العربية", "हिन्दी"])
    }

    // MARK: - Boundaries and whitespace

    @Test(
        "JavaScript whitespace is a left boundary",
        arguments: ["\t", "\n", "\r", "\u{0B}", "\u{0C}", "\u{A0}", "\u{2003}", "\u{2028}", "\u{3000}", "\u{FEFF}"]
    )
    func whitespaceIsABoundary(_ space: String) {
        let result = parse("Plan\(space)#work")

        #expect(result.tokens.map(\.name) == ["work"])
        #expect(result.cleanTitle == "Plan")
    }

    @Test func nextLineIsNotABoundaryBecauseJavaScriptDoesNotTreatItAsWhitespace() {
        // U+0085 is Unicode White_Space but not JavaScript `\s`; the web leaves
        // the sigil literal, and so does iOS.
        #expect(parse("Plan\u{85}#work").tokens.isEmpty)
    }

    @Test(arguments: ["(", "[", "{"])
    func openingBracketsAreBoundaries(_ bracket: String) {
        #expect(parse("Plan \(bracket)#work").tokens.map(\.name) == ["work"])
    }

    @Test func withoutABoundaryTheSigilIsText() {
        #expect(parse("a#b c@d e)#f 'g\"#h").tokens.isEmpty)
    }

    @Test func aTokenRightAfterAnotherIsText() {
        let result = parse("#a#b")

        #expect(result.tokens.map(\.name) == ["a"])
        #expect(result.cleanTitle == "#b")
    }

    @Test(
        "closing punctuation ends a bare name and stays in the title",
        arguments: [
            ("Call #work, then", "Call, then"), ("Call #work; then", "Call; then"),
            ("Call #work: then", "Call: then"), ("Call #work! Now", "Call! Now"),
            ("Call #work? Yes", "Call? Yes"), ("Call (it #work)", "Call (it)"),
            ("Call #work/path", "Call /path"),
        ]
    )
    func punctuationEndsABareName(raw: String, title: String) {
        let result = parse(raw)

        #expect(result.tokens.map(\.name) == ["work"])
        #expect(result.cleanTitle == title)
    }

    @Test func internalPeriodsAndHyphensStayInTheName() {
        #expect(parse("Ship #v1.2.3 #a-b-c.").tokens.map(\.name) == ["v1.2.3", "a-b-c"])
    }

    // MARK: - Quotes and escapes

    @Test func anUnterminatedQuoteStaysLiteralButLaterTokensStillCount() {
        let result = parse("Plan @\"Launch #work")

        #expect(result.tokens.map(\.name) == ["work"])
        #expect(result.cleanTitle == "Plan @\"Launch")
    }

    @Test func aLineSeparatorDoesNotBreakAQuotedName() {
        // Only \n and \r end a quoted name (web parity); U+2028 is ordinary whitespace inside it.
        #expect(parse("Plan #\"a\u{2028}b\"").tokens.map(\.name) == ["a b"])
    }

    @Test func aQuotedNameMayHoldSigilsAndDelimiters() {
        #expect(parse("Plan #\"client:alpha\" @\"R&D (2026)\"").tokens.map(\.name) == ["client:alpha", "R&D (2026)"])
    }

    @Test func escapedSigilsAtBoundariesDropOnlyTheBackslash() {
        let result = parse("\\#one (\\@two) #three")

        #expect(result.tokens.map(\.name) == ["three"])
        #expect(result.cleanTitle == "#one (@two)")
    }

    @Test func aDoubleBackslashDoesNotEscape() {
        let result = parse("Path \\\\#tag")

        #expect(result.tokens.isEmpty)
        #expect(result.cleanTitle == "Path \\\\#tag")
    }

    @Test func aWhitespaceOnlyQuotedNameIsNotAToken() {
        #expect(parse("Plan #\"   \" now").tokens.isEmpty)
    }

    // MARK: - Title cleanup

    @Test func mismatchedBracketsAreKept() {
        #expect(parse("Plan (#work] now").cleanTitle == "Plan (] now")
    }

    @Test func tokensInsideOneBracketPairLeaveTheBrackets() {
        #expect(parse("Plan (#a #b) now").cleanTitle == "Plan () now")
    }

    @Test func collapsesEveryWhitespaceRunAndTrims() {
        #expect(parse("  Plan\t\t#work \n next\u{3000}step  ").cleanTitle == "Plan next step")
    }

    @Test func emptyAndBlankTextHaveNoTitleAndNoTokens() {
        #expect(parse("") == SmartAddParser.Result(cleanTitle: "", tokens: []))
        #expect(parse(" \n\t ") == SmartAddParser.Result(cleanTitle: "", tokens: []))
    }

    @Test func aTitleOfOnlyTokensIsEmpty() {
        #expect(parse("(#work) @Дом").cleanTitle == "")
    }
}

/// The Mac's `SmartAddParserTests` cases are covered by the suites above, `SmartAddWebParityTests` and
/// `CapturePlannerTests`, except what the kit did not say yet: the words for an archived project (design X-06).
@Suite("Smart Add: archived projects")
struct SmartAddArchivedProjectTests {
    private let state = SmartAddFixtures.state(
        projects: [
            SmartAddFixtures.project("p-launch", "Launch v2"),
            SmartAddFixtures.project("p-old", "Old Launch", state: .archived),
        ]
    )

    @Test("021-FR-025 an archived project's name is shown and capture is refused with the unarchive copy")
    func archivedNameIsShownAndRefused() {
        let preview = CapturePlanner.preview(CaptureDraft(text: "Plan @\"old launch\""), in: state)
        #expect(preview.project == ClassificationPreview(name: "Old Launch", isNew: false))
        #expect(preview.problem == .projectNotActive && !preview.isValid)
        #expect(preview.problemMessage == "Unarchive “Old Launch” before adding a task to it.")
    }

    @Test("021-FR-025 the same words when the archived project is the screen the capture started from")
    func archivedContextProject() {
        let preview = CapturePlanner.preview(CaptureDraft(text: "Plan", contextProjectID: "p-old"), in: state)
        #expect(preview.problemMessage == "Unarchive “Old Launch” before adding a task to it.")
    }

    @Test("021-FR-010 021-FR-025 other problems keep their own copy, and a valid capture has none")
    func otherProblemsKeepTheirCopy() {
        #expect(CapturePlanner.preview(CaptureDraft(text: "#work"), in: state).problemMessage == GTDValidationError.emptyTitle.message)
        #expect(CapturePlanner.preview(CaptureDraft(text: "Plan @\"Launch v2\""), in: state).problemMessage == nil)
    }
}

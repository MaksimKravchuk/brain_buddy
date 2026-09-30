import Testing
@testable import BrainBuddyCore

// Lockstep port of `frontend/src/features/tasks/__tests__/smartAdd.test.ts`
// (spec 003, `specs/003-smart-add-classification/contracts/smart-add.md`).
// Every `parseSmartAdd` / `smartAddChips` case is here with the web's input and
// expectation, in the web file's order; change both files together. The
// suggestion-popup cases (`smartAddSuggestions`, `applySmartAddSuggestion`) are
// not ported: the iOS capture sheet has no suggestion popup in pass 1.
// The one intentional divergence (`ß`) is marked where it occurs.

struct WebParseCase: Sendable, CustomTestStringConvertible {
    var raw: String
    var cleanTitle: String
    var tags: [WebRef]
    var project: WebRef?
    var testDescription: String { raw.debugDescription }
}

@Suite("Smart Add — web parity (smartAdd.test.ts)")
struct SmartAddWebParityTests {
    @Test(
        "parses into a clean task create draft",
        arguments: [
            WebParseCase(
                raw: "Draft update #work @\"Launch v2\"", cleanTitle: "Draft update", tags: [.id("tag-work")],
                project: .id("project-launch")),
            WebParseCase(raw: "Draft #work #WORK", cleanTitle: "Draft", tags: [.id("tag-work")], project: nil),
            WebParseCase(raw: "Draft @old @new", cleanTitle: "Draft", tags: [], project: .name("new")),
            WebParseCase(raw: "Draft (#work) today", cleanTitle: "Draft today", tags: [.id("tag-work")], project: nil),
            WebParseCase(raw: "Draft #work, today", cleanTitle: "Draft, today", tags: [.id("tag-work")], project: nil),
            WebParseCase(
                raw: "Discuss C# and max@example.com", cleanTitle: "Discuss C# and max@example.com", tags: [],
                project: nil),
            WebParseCase(raw: "Use \\#literal marker", cleanTitle: "Use #literal marker", tags: [], project: nil),
            WebParseCase(raw: "Plan #", cleanTitle: "Plan #", tags: [], project: nil),
            WebParseCase(raw: "Plan @\"Launch v2", cleanTitle: "Plan @\"Launch v2", tags: [], project: nil),
        ]
    )
    func parsesIntoCleanDraft(_ testCase: WebParseCase) {
        let parsed = parseSmartAdd(testCase.raw)

        #expect(parsed.cleanTitle == testCase.cleanTitle)
        #expect(parsed.tags == testCase.tags)
        #expect(parsed.project == testCase.project)
        #expect(parsed.hasCompletedTokens == (!testCase.tags.isEmpty || testCase.project != nil))
    }

    @Test func mergesContextualDefaultsDeduplicatesTagsAndLetsTheFinalProjectWin() {
        let parsed = parseSmartAdd(
            "Plan #calls @Admin @\"Vendor launch\" #work", contextProjectID: "project-launch", contextTagID: "tag-work"
        )

        #expect(parsed.cleanTitle == "Plan")
        #expect(parsed.tags == [.id("tag-work"), .id("tag-calls")])
        #expect(parsed.project == .id("project-vendor"))
    }

    @Test func rejectsCompletedClassificationsWhenTheCleanTitleIsEmpty() {
        let parsed = parseSmartAdd("#work @launch")

        #expect(parsed.cleanTitle == "")
        #expect(parsed.hasCompletedTokens)
        #expect(!parsed.isValid)
    }

    @Test func buildsPreviewChipModels() {
        // Web: `smartAddChips` → project chip first, then tag chips. On iOS the
        // chips are `CapturePreview.project` and `.tags`.
        let preview = CapturePlanner.preview(
            CaptureDraft(text: "Call partner #calls @\"Vendor launch\" #new"), in: SmartAddFixtures.webState
        )

        #expect(preview.project == ClassificationPreview(name: "Vendor launch", isNew: false))
        #expect(
            preview.tags == [
                ClassificationPreview(name: "calls", isNew: false), ClassificationPreview(name: "new", isNew: true),
            ])
    }

    @Test func decodesQuotedEscapesAndLeavesMalformedFormsAsLiteralTitleText() {
        let escaped = parseSmartAdd("Plan #\"deep \\\"work\\\"\"")
        #expect(escaped.cleanTitle == "Plan")
        #expect(escaped.tags == [.name("deep \"work\"")])

        let malformed = parseSmartAdd("Plan #-work @\"broken\nproject\"")
        #expect(malformed.cleanTitle == "Plan #-work @\"broken project\"")
        #expect(!malformed.hasCompletedTokens)
    }

    @Test func parsesPunctuationNamesAndWrapperCleanupWhilePreservingUnsupportedQuoteEscapes() {
        let wrapped = parseSmartAdd("Plan [#a-b] {#a.b}")
        #expect(wrapped.cleanTitle == "Plan")
        #expect(wrapped.tags == [.name("a-b"), .name("a.b")])

        #expect(parseSmartAdd("Plan #\"literal \\q\"").tags == [.name("literal \\q")])
    }

    @Test func validatesDraftBounds() {
        #expect(!parseSmartAdd(String(repeating: "x", count: 501) + " #work").isValid)
        #expect(!parseSmartAdd("Plan #" + String(repeating: "x", count: 501)).isValid)
    }

    @Test func matchesAStoredNameWhoseOwnSpacingAndCaseAreUntidy() {
        let untidy = SmartAddFixtures.state(tags: [SmartAddFixtures.tag("tag-untidy", "  Deep   Work  ")])

        #expect(parseSmartAdd("Plan #\"deep work\"", state: untidy).tags == [.id("tag-untidy")])
    }

    @Test func stripsALegacySigilOnlyFromTheFrontOfAName() {
        #expect(parseSmartAdd("Plan #\"c#sharp\"").tags == [.name("c#sharp")])
    }

    @Test func leavesALoneBackslashAloneWhenNoSigilFollowsIt() {
        let parsed = parseSmartAdd("Copy from C:\\ drive")

        #expect(parsed.cleanTitle == "Copy from C:\\ drive")
        #expect(!parsed.hasCompletedTokens)
    }

    @Test func ignoresAQuotedTokenWithAnEmptyName() {
        let parsed = parseSmartAdd("Plan #\"\" today")

        #expect(parsed.cleanTitle == "Plan #\"\" today")
        #expect(parsed.tags == [])
        #expect(!parsed.hasCompletedTokens)
    }

    @Test func treatsABackslashEscapedSigilAsLiteralTextForBothKinds() {
        let project = parseSmartAdd("Ping \\@nobody today")
        #expect(project.cleanTitle == "Ping @nobody today")
        #expect(project.project == nil)
        #expect(!project.hasCompletedTokens)

        let both = parseSmartAdd("Mail \\#one and \\@two")
        #expect(both.cleanTitle == "Mail #one and @two")
        #expect(both.tags == [])
        #expect(both.project == nil)
    }

    @Test func onlyHonoursAnEscapeThatStandsAtATokenBoundary() {
        let parsed = parseSmartAdd("id\\#42 wins")

        #expect(parsed.cleanTitle == "id\\#42 wins")
        #expect(parsed.tags == [])
        #expect(!parsed.hasCompletedTokens)
    }

    @Test func matchesAnExistingNameRegardlessOfCaseAndInnerSpacing() {
        let tag = parseSmartAdd("Plan #\"DEEP   WORK\"")
        #expect(tag.cleanTitle == "Plan")
        #expect(tag.tags == [.id("tag-deep")])

        #expect(parseSmartAdd("Plan @\"  vendor   LAUNCH  \"").project == .id("project-vendor"))
    }

    @Test func normalisesTheDisplayNameOfATagOrProjectItIsAboutToCreate() {
        #expect(parseSmartAdd("Plan #\"  New   Tag  \"").tags == [.name("New Tag")])
        #expect(parseSmartAdd("Plan @\"  Fresh   Project  \"").project == .name("Fresh Project"))
    }

    @Test func decodesAnEscapedBackslashInsideAQuotedName() {
        let parsed = parseSmartAdd("Plan #\"back\\\\slash\"")

        #expect(parsed.cleanTitle == "Plan")
        #expect(parsed.tags == [.name("back\\slash")])
    }

    @Test func abandonsAQuotedNameBrokenByACarriageReturn() {
        let parsed = parseSmartAdd("Plan #\"broken\rname\"")

        #expect(parsed.cleanTitle == "Plan #\"broken name\"")
        #expect(!parsed.hasCompletedTokens)
    }

    @Test func stopsAnUnquotedNameAtATrailingSeparator() {
        let hyphen = parseSmartAdd("Ping #a- now")
        #expect(hyphen.cleanTitle == "Ping - now")
        #expect(hyphen.tags == [.name("a")])

        let period = parseSmartAdd("Ping #a. now")
        #expect(period.cleanTitle == "Ping. now")
        #expect(period.tags == [.name("a")])
    }

    @Test func removesABracketPairOnlyWhenTheTokenIsTheWholeOfIt() {
        let spaced = parseSmartAdd("Draft ( #work ) today")
        #expect(spaced.cleanTitle == "Draft today")
        #expect(spaced.tags == [.id("tag-work")])

        #expect(parseSmartAdd("( #work ) alone").cleanTitle == "alone")

        let shared = parseSmartAdd("Draft (see #work) today")
        #expect(shared.cleanTitle == "Draft (see) today")
        #expect(shared.tags == [.id("tag-work")])

        let leading = parseSmartAdd("Draft (#work extra) today")
        #expect(leading.cleanTitle == "Draft ( extra) today")
        #expect(leading.tags == [.id("tag-work")])
    }

    @Test func deduplicatesATagWrittenWithAndWithoutItsLegacySigil() {
        #expect(parseSmartAdd("Plan #work #\"#work\"").tags == [.id("tag-work")])
        #expect(parseSmartAdd("Plan #\"brand new\" #\"BRAND   NEW\"").tags == [.name("brand new")])
    }

    @Test func acceptsADraftAtTheLengthLimitAndRejectsTheOnePastIt() {
        #expect(parseSmartAdd(String(repeating: "x", count: 500) + " #work").isValid)
        #expect(!parseSmartAdd(String(repeating: "x", count: 501) + " #work").isValid)
        #expect(parseSmartAdd("Plan #" + String(repeating: "x", count: 500)).isValid)
        #expect(parseSmartAdd("Plan @" + String(repeating: "x", count: 500)).isValid)
        #expect(!parseSmartAdd("Plan @" + String(repeating: "x", count: 501)).isValid)
    }

    @Test func acceptsEveryNameCharClassInABareUnquotedName() {
        let classes = parseSmartAdd("Ping #q3_a-b.c now")
        #expect(classes.cleanTitle == "Ping now")
        #expect(classes.tags == [.name("q3_a-b.c")])

        // "cafe" + U+0301: the mark continues the name, NFKC composes "café".
        let decomposed = parseSmartAdd("Ping #cafe\u{301} now")
        #expect(decomposed.cleanTitle == "Ping now")
        #expect(decomposed.tags == [.name("caf\u{E9}")])
    }

    @Test func foldsCaseLikeTheServerSoSharpSMatchesSS() {
        // DIVERGENCE. Web: "folds case downwards, so a name only equal when
        // upper-cased stays distinct" expects `#ß` → `{ name: "ß" }` next to an
        // existing "ss", because JavaScript lower-casing keeps ß. The contract
        // makes the backend authoritative where JS lower-casing and Python
        // casefold differ, and the server (and `NameNormalizer`, which the
        // reducer uses for duplicate names) folds ß to "ss". Creating "ß" here
        // would be refused as a duplicate, so iOS resolves to the existing tag.
        let sharp = SmartAddFixtures.state(tags: [SmartAddFixtures.tag("tag-ss", "ss")])

        #expect(parseSmartAdd("Plan #ß", state: sharp).tags == [.id("tag-ss")])
    }

    @Test func escapesOnlyASigilLeavingABoundaryBackslashBeforeAnythingElse() {
        let parsed = parseSmartAdd("Copy \\ drive")

        #expect(parsed.cleanTitle == "Copy \\ drive")
        #expect(!parsed.hasCompletedTokens)
    }

    @Test func keepsTheContextualProjectWhenNoInlineProjectTokenSupersedesIt() {
        let parsed = parseSmartAdd("Plan #work", contextProjectID: "project-launch")

        #expect(parsed.cleanTitle == "Plan")
        #expect(parsed.tags == [.id("tag-work")])
        #expect(parsed.project == .id("project-launch"))
    }

    // Contract tables (contracts/smart-add.md §1 and §3) not already above.
    @Test(
        "contract recognition examples",
        arguments: [
            ("Plan launch #work", "Plan launch", [WebRef.id("tag-work")]),
            ("Plan (#work)", "Plan", [.id("tag-work")]),
            ("Email max@example.com", "Email max@example.com", []),
            ("Read C# notes", "Read C# notes", []),
            ("word,#tag", "word,#tag", []),
            ("word, #tag", "word,", [.name("tag")]),
            ("\\#literal title", "#literal title", []),
        ]
    )
    func contractRecognitionExamples(raw: String, cleanTitle: String, tags: [WebRef]) {
        let parsed = parseSmartAdd(raw)

        #expect(parsed.cleanTitle == cleanTitle)
        #expect(parsed.tags == tags)
    }

    @Test func contractMergeExampleDraftUpdateLaunch() {
        let parsed = parseSmartAdd("Draft update #work @launch")

        #expect(parsed.cleanTitle == "Draft update")
        #expect(parsed.tags == [.id("tag-work")])
        #expect(parsed.project == .name("launch"))
    }
}

import XCTest
@testable import BrainBuddyMac

final class SmartAddParserTests: XCTestCase {
    private let projects = [
        BrainBuddyProject(id: "launch", name: "Launch v2", color: nil, state: "active", revision: 1, open_task_count: 0),
        BrainBuddyProject(id: "vendor", name: "Vendor launch", color: nil, state: "active", revision: 1, open_task_count: 0),
    ]
    private let tags = [
        BrainBuddyTag(id: "work", name: "work", state: "active", revision: 1, open_task_count: 0),
        BrainBuddyTag(id: "deep", name: "deep work", state: "active", revision: 1, open_task_count: 0),
    ]

    private func description(_ ref: ClassificationRef?) -> String? {
        guard let ref else { return nil }
        switch ref {
        case .id(let id): return "id:\(id)"
        case .name(let name): return "name:\(name)"
        }
    }

    func testResolvesCompletedTokensAndSelectedContext() {
        let draft = SmartAddParser.parse(
            "Draft #work #WORK @old @\"Vendor launch\" #\"deep work\"",
            projects: projects, tags: tags, contextProjectId: "launch", contextTagId: "deep"
        )

        XCTAssertEqual(draft.cleanTitle, "Draft")
        XCTAssertEqual(draft.tags.map { description($0) }, ["id:deep", "id:work"])
        XCTAssertEqual(description(draft.project), "id:vendor")
        XCTAssertEqual(draft.previewProjectName(in: projects), "Vendor launch")
        XCTAssertEqual(draft.previewTagNames(in: tags), ["deep work", "work"])
        XCTAssertTrue(draft.hasCompletedTokens)
        XCTAssertTrue(draft.isValid)
    }

    func testKeepsLiteralSigilsAndIncompleteTokensInTitle() {
        let draft = SmartAddParser.parse(
            "Discuss C# and max@example.com; use \\#literal, \\@nobody and @\"unfinished",
            projects: projects, tags: tags
        )

        XCTAssertEqual(draft.cleanTitle, "Discuss C# and max@example.com; use #literal, @nobody and @\"unfinished")
        XCTAssertTrue(draft.tags.isEmpty)
        XCTAssertNil(draft.project)
        XCTAssertFalse(draft.hasCompletedTokens)
    }

    func testQuotedEscapesUnicodeNamesAndPunctuationCleanup() {
        let draft = SmartAddParser.parse(
            "Plan [#cafe\u{301}] (#\"back\\\\slash\") @\"New   Project\", today",
            projects: projects, tags: tags
        )

        XCTAssertEqual(draft.cleanTitle, "Plan, today")
        XCTAssertEqual(draft.tags.map { description($0) }, ["name:café", "name:back\\slash"])
        XCTAssertEqual(description(draft.project), "name:New Project")
        XCTAssertEqual(draft.previewProjectName(in: projects), "New Project")
        XCTAssertEqual(draft.previewTagNames(in: tags), ["café", "back\\slash"])
    }

    func testRequiresNonemptyBoundedTitleAndNames() {
        let empty = SmartAddParser.parse("#work @Launch", projects: projects, tags: tags)
        XCTAssertEqual(empty.cleanTitle, "")
        XCTAssertFalse(empty.isValid)

        let titleTooLong = SmartAddParser.parse(String(repeating: "x", count: 501), projects: projects, tags: tags)
        XCTAssertFalse(titleTooLong.isValid)

        let tagTooLong = SmartAddParser.parse("Plan #" + String(repeating: "x", count: 501), projects: projects, tags: tags)
        XCTAssertFalse(tagTooLong.isValid)

        let atLimit = SmartAddParser.parse("Plan #" + String(repeating: "x", count: 500), projects: projects, tags: tags)
        XCTAssertTrue(atLimit.isValid)
    }
}

import Foundation
@testable import BrainBuddyCore

/// Shared Smart Add fixtures. `webProjects` / `webTags` are the records of
/// `frontend/src/features/tasks/__tests__/smartAdd.test.ts`, with the same ids,
/// so its cases can be copied here verbatim and the two parsers stay in lockstep.
enum SmartAddFixtures {
    static let epoch = Date(timeIntervalSince1970: 1_780_000_000)

    static func project(
        _ id: String, _ name: String, state: ProjectState = .active, createdAfter seconds: TimeInterval = 0
    ) -> ProjectRecord {
        ProjectRecord(id: ProjectID(id), name: name, state: state, createdAt: epoch.addingTimeInterval(seconds))
    }

    static func tag(
        _ id: String, _ name: String, state: TagState = .active, createdAfter seconds: TimeInterval = 0
    ) -> TagRecord {
        TagRecord(id: TagID(id), name: name, state: state, createdAt: epoch.addingTimeInterval(seconds))
    }

    static func state(projects: [ProjectRecord] = [], tags: [TagRecord] = []) -> GTDState {
        GTDState(
            projects: Dictionary(uniqueKeysWithValues: projects.map { ($0.id, $0) }),
            tags: Dictionary(uniqueKeysWithValues: tags.map { ($0.id, $0) })
        )
    }

    static let webProjects = [
        project("project-launch", "Launch v2"),
        project("project-vendor", "Vendor launch"),
        project("project-admin", "Admin"),
    ]

    static let webTags = [
        tag("tag-work", "work"),
        tag("tag-deep", "deep work"),
        tag("tag-calls", "calls"),
    ]

    static let webState = state(projects: webProjects, tags: webTags)

    /// The text a token's UTF-16 range covers, read the way `NSRange` would.
    static func text(_ text: String, in range: Range<Int>) -> String {
        let utf16 = text.utf16
        let lower = utf16.index(utf16.startIndex, offsetBy: range.lowerBound)
        let upper = utf16.index(utf16.startIndex, offsetBy: range.upperBound)
        return String(utf16[lower..<upper]) ?? "<split surrogate pair>"
    }
}

/// The web's `SmartAddRef`: `{ id }` for an existing record, `{ name }` for one
/// capture will create.
enum WebRef: Hashable, Sendable, CustomStringConvertible {
    case id(String)
    case name(String)

    var description: String {
        switch self {
        case .id(let id): "{ id: \(id) }"
        case .name(let name): "{ name: \(name) }"
        }
    }
}

/// The web's `SmartAddDraft`, rebuilt from the planner's resolution so the web
/// expectations can be asserted unchanged.
struct WebDraft: Hashable, Sendable {
    var cleanTitle: String
    var tags: [WebRef]
    var project: WebRef?
    var hasCompletedTokens: Bool
    var isValid: Bool
}

/// `parseSmartAdd(input, { projects, tags, contextProjectId, contextTagId })`.
func parseSmartAdd(
    _ input: String, state: GTDState = SmartAddFixtures.webState, contextProjectID: String? = nil,
    contextTagID: String? = nil
) -> WebDraft {
    let draft = CaptureDraft(
        text: input, contextProjectID: contextProjectID.map { ProjectID($0) },
        contextTagID: contextTagID.map { TagID($0) }
    )
    let resolution = CapturePlanner.resolve(draft, in: state)
    return WebDraft(
        cleanTitle: resolution.title, tags: resolution.tags.map { $0.webRef },
        project: resolution.project.map { $0.webRef },
        hasCompletedTokens: !resolution.tokens.isEmpty, isValid: resolution.problem == nil
    )
}

extension CapturePlanner.Classification {
    fileprivate var webRef: WebRef {
        switch self {
        case .existing(let id, _): .id(String(describing: id))
        case .new(let name): .name(name)
        }
    }
}

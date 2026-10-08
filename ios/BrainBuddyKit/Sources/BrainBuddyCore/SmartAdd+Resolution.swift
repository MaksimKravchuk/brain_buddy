import Foundation

/// How `CapturePlanner` turns a draft into a project, tags and a task, shared
/// by `preview` (drawn on every keystroke) and `plan` (on save) so the two can
/// never disagree.
///
/// Lengths are counted in Unicode scalars, because the server validates with
/// pydantic `max_length`, which is Python `len` (code points). The web counts
/// UTF-16 units and `String.count` counts grapheme clusters; both can disagree
/// with the server for emoji and combining marks.
extension CapturePlanner {
    enum Classification<ID: Hashable & Sendable>: Hashable, Sendable {
        case existing(ID, name: String)
        case new(name: String)

        var preview: ClassificationPreview {
            switch self {
            case .existing(_, let name): ClassificationPreview(name: name, isNew: false)
            case .new(let name): ClassificationPreview(name: name, isNew: true)
            }
        }
    }

    struct Resolution: Hashable, Sendable {
        var title: String
        var tokens: [SmartAddToken]
        var project: Classification<ProjectID>?
        var tags: [Classification<TagID>]
        /// Trimmed; only when the draft is for Waiting.
        var waitingFor: String?
        /// Nil when blank; otherwise exactly as typed.
        var details: String?
        /// The first problem in reading order: title, project, tags, waiting
        /// note, notes.
        var problem: GTDValidationError?
    }

    static func resolve(_ draft: CaptureDraft, in state: GTDState) -> Resolution {
        let parsed = SmartAddParser.parse(draft.text)
        let project = resolveProject(draft, tokens: parsed.tokens, in: state)
        let tags = resolveTags(draft, tokens: parsed.tokens, in: state)

        var waitingFor: String?
        var waitingProblem: GTDValidationError?
        if draft.list == .waiting {
            // Trimmed exactly as the reducer trims it, so a note the reducer
            // would call blank (only U+001C…U+001F, say) is blank here too.
            let trimmed = NameNormalizer.stripped(draft.waitingFor)
            if trimmed.isEmpty {
                waitingProblem = .waitingForRequired
            } else if trimmed.unicodeScalars.count > GTDLimits.waitingFor {
                waitingProblem = .waitingForTooLong
            }
            waitingFor = trimmed.isEmpty ? nil : trimmed
        }

        let details = isBlank(draft.details) ? nil : draft.details
        let detailsProblem: GTDValidationError? =
            (details?.unicodeScalars.count ?? 0) > GTDLimits.details ? .detailsTooLong : nil

        let titleLength = parsed.cleanTitle.unicodeScalars.count
        let titleProblem: GTDValidationError? =
            titleLength == 0 ? .emptyTitle : titleLength > GTDLimits.title ? .titleTooLong : nil

        return Resolution(
            title: parsed.cleanTitle, tokens: parsed.tokens, project: project.value, tags: tags.value,
            waitingFor: waitingFor, details: details,
            problem: titleProblem ?? project.problem ?? tags.problem ?? waitingProblem ?? detailsProblem
        )
    }

    // MARK: - Project

    /// The last `@project` token wins; superseded names are neither resolved
    /// nor created. Without a token the context project applies.
    private static func resolveProject(
        _ draft: CaptureDraft, tokens: [SmartAddToken], in state: GTDState
    ) -> (value: Classification<ProjectID>?, problem: GTDValidationError?) {
        guard let token = tokens.last(where: { $0.kind == .project }) else {
            guard let contextID = draft.contextProjectID else { return (nil, nil) }
            guard let record = state.projects[contextID] else { return (nil, .projectNotFound) }
            return (.existing(record.id, name: record.name), record.state == .active ? nil : .projectNotActive)
        }
        let name = NameNormalizer.display(droppingSigil(token.name, among: ["@"]))
        let key = NameNormalizer.project(name)
        guard !key.isEmpty else { return (nil, .emptyName) }

        // `Dictionary` order is not stable, so ties go to the oldest record.
        let projects = state.projects.values.sorted { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }
        let active = projects.filter { $0.state == .active }
        if let record = active.first(where: { NameNormalizer.project($0.name) == key })
            ?? active.first(where: { legacyProjectKey($0.name) == key })
        {
            return (.existing(record.id, name: record.name), nil)
        }
        // The server refuses a Smart Add name that belongs to an archived
        // project, so capture stops here (`CapturePreview.problemMessage` says
        // to unarchive it) rather than creating a second project with the same name.
        if let archived = projects.first(where: { $0.state == .archived && NameNormalizer.project($0.name) == key }) {
            return (.existing(archived.id, name: archived.name), .projectNotActive)
        }
        return (.new(name: name), name.unicodeScalars.count > GTDLimits.name ? .nameTooLong : nil)
    }

    // MARK: - Tags

    /// The context tag first (when still active), then each `#tag` token in
    /// order, de-duplicated by record and, for new tags, by normalized name.
    /// A deleted tag with the same name does not block: a new tag is created.
    private static func resolveTags(
        _ draft: CaptureDraft, tokens: [SmartAddToken], in state: GTDState
    ) -> (value: [Classification<TagID>], problem: GTDValidationError?) {
        var tags: [Classification<TagID>] = []
        var problem: GTDValidationError?
        var seenIDs: Set<TagID> = []
        var seenNewKeys: Set<String> = []

        if let contextID = draft.contextTagID, let record = state.tags[contextID], record.state == .active {
            tags.append(.existing(record.id, name: record.name))
            seenIDs.insert(record.id)
        }

        let tagTokens = tokens.filter { $0.kind == .tag }
        guard !tagTokens.isEmpty else { return (tags, problem) }
        let active = state.tags.values.filter { $0.state == .active }
            .sorted { ($0.createdAt, $0.id) < ($1.createdAt, $1.id) }
        var exact: [String: TagRecord] = [:]
        var legacy: [String: TagRecord] = [:]
        for record in active {
            if exact[NameNormalizer.tag(record.name)] == nil { exact[NameNormalizer.tag(record.name)] = record }
            if legacy[legacyTagKey(record.name)] == nil { legacy[legacyTagKey(record.name)] = record }
        }

        for token in tagTokens {
            let name = NameNormalizer.display(droppingSigil(token.name, among: ["#", "@"]))
            let key = NameNormalizer.tag(name)
            guard !key.isEmpty else {
                problem = problem ?? .emptyName
                continue
            }
            if let record = exact[key] ?? legacy[key] {
                if seenIDs.insert(record.id).inserted { tags.append(.existing(record.id, name: record.name)) }
            } else if seenNewKeys.insert(key).inserted {
                tags.append(.new(name: name))
                if name.unicodeScalars.count > GTDLimits.name { problem = problem ?? .nameTooLong }
            }
        }
        return (tags, problem)
    }

    // MARK: - Names

    /// The web strips one legacy sigil from a name before comparing it
    /// (`stripLegacySigil`: `#` or `@` for tags; `stripLegacyProjectSigil`:
    /// `@` for projects), both from what was typed (`#"#work"` is `work`) and
    /// from stored names (a tag stored as `#work` answers to `#work`). The
    /// exact `NameNormalizer` key is tried first, so a name the reducer would
    /// call a duplicate always resolves to the existing record.
    private static func droppingSigil(_ name: String, among sigils: Set<Unicode.Scalar>) -> String {
        guard let first = name.unicodeScalars.first, sigils.contains(first) else { return name }
        return String(name.unicodeScalars.dropFirst())
    }

    private static func legacyTagKey(_ name: String) -> String {
        NameNormalizer.tag(droppingSigil(storedDisplay(name), among: ["#", "@"]))
    }

    private static func legacyProjectKey(_ name: String) -> String {
        NameNormalizer.project(droppingSigil(storedDisplay(name), among: ["@"]))
    }

    private static func storedDisplay(_ name: String) -> String {
        NameNormalizer.display(name.precomposedStringWithCompatibilityMapping)
    }

    // MARK: - Whitespace

    private static func isBlank(_ value: String) -> Bool {
        value.unicodeScalars.allSatisfy(\.properties.isWhitespace)
    }
}

extension CapturePreview {
    /// The words for `problem`. An archived project that capture named (or started from)
    /// says how to go on (design X-06); every other problem keeps its own copy.
    public var problemMessage: String? {
        guard let problem else { return nil }
        if problem == .projectNotActive, let project {
            return "Unarchive “\(project.name)” before adding a task to it."
        }
        return problem.message
    }
}

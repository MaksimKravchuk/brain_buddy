import AppIntents
import BrainBuddyCore

/// `OpenList` for Siri and Shortcuts. Raw values match `OpenList` (the
/// server's task states); titles are the design system's list names, verbatim.
nonisolated enum OpenListAppEnum: String, AppEnum, CaseIterable {
    case inbox, next, waiting, someday

    static let typeDisplayRepresentation = TypeDisplayRepresentation(name: "List")

    static let caseDisplayRepresentations: [OpenListAppEnum: DisplayRepresentation] = [
        .inbox: DisplayRepresentation(title: "Inbox", image: .init(systemName: "tray")),
        .next: DisplayRepresentation(title: "Next actions", image: .init(systemName: "checklist")),
        .waiting: DisplayRepresentation(title: "Waiting for", image: .init(systemName: "clock")),
        .someday: DisplayRepresentation(title: "Someday / maybe", image: .init(systemName: "archivebox")),
    ]

    init(_ list: OpenList) {
        switch list {
        case .inbox: self = .inbox
        case .next: self = .next
        case .waiting: self = .waiting
        case .someday: self = .someday
        }
    }

    var openList: OpenList {
        switch self {
        case .inbox: .inbox
        case .next: .next
        case .waiting: .waiting
        case .someday: .someday
        }
    }
}

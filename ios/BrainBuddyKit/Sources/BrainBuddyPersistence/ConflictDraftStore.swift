import BrainBuddyCore
import Foundation

/// Where an unsent conflict decision waits between launches (spec 026 M-02.07, Mac D-02). Holds only
/// the choices of `ConflictDecisionDraft` (ids, versions, approvals), never the user's text, and
/// restoring one submits nothing. Shared by the iPhone and the Mac.
public protocol ConflictDraftStore: Sendable {
    /// The draft saved for `issueID`, or nil when there is none or it can't be read.
    func load(issueID: String) -> ConflictDecisionDraft?
    /// Saves `draft` durably; false when it couldn't be written (the draft stays in memory).
    @discardableResult func save(_ draft: ConflictDecisionDraft, issueID: String) -> Bool
    /// Forgets the draft for `issueID`: its issue was resolved.
    func clear(issueID: String)
    /// Forgets every draft whose issue is not in `issueIDs`.
    func prune(keeping issueIDs: Set<String>)
}

/// One small JSON file per issue under `directory`, written atomically.
public struct FileConflictDraftStore: ConflictDraftStore {
    public let directory: URL

    public init(directory: URL) { self.directory = directory }

    /// `<Application Support>/BrainBuddy/ConflictDrafts`, in this process's own container.
    public static func applicationSupport() -> FileConflictDraftStore {
        FileConflictDraftStore(directory: FileDocumentStore.applicationSupportDocumentURL(fileName: "ConflictDrafts"))
    }

    private static let suffix = ".json"

    /// The file for `issueID`: its UTF-8 bytes in hex, so no id can name a path.
    private func file(_ issueID: String) -> URL {
        directory.appendingPathComponent(
            issueID.utf8.map { String(format: "%02x", $0) }.joined() + Self.suffix, isDirectory: false)
    }

    public func load(issueID: String) -> ConflictDecisionDraft? {
        guard let data = try? Data(contentsOf: file(issueID)),
            let draft = try? JSONDecoder().decode(ConflictDecisionDraft.self, from: data), draft.issueID == issueID
        else { return nil }
        return draft
    }

    @discardableResult
    public func save(_ draft: ConflictDecisionDraft, issueID: String) -> Bool {
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            var options: Data.WritingOptions = [.atomic]
            #if os(iOS)
                options.insert(.completeFileProtectionUntilFirstUserAuthentication)
            #endif
            try JSONEncoder().encode(draft).write(to: file(issueID), options: options)
            return true
        } catch {
            return false
        }
    }

    public func clear(issueID: String) {
        try? FileManager.default.removeItem(at: file(issueID))
    }

    public func prune(keeping issueIDs: Set<String>) {
        let keep = Set(issueIDs.map { file($0).lastPathComponent })
        let names = (try? FileManager.default.contentsOfDirectory(atPath: directory.path)) ?? []
        for name in names where name.hasSuffix(Self.suffix) && !keep.contains(name) {
            try? FileManager.default.removeItem(at: directory.appendingPathComponent(name))
        }
    }
}

/// Drafts kept in memory only: previews and tests.
public final class InMemoryConflictDraftStore: ConflictDraftStore, @unchecked Sendable {
    // Every access is under `lock`.
    private let lock = NSLock()
    private var drafts: [String: ConflictDecisionDraft] = [:]

    public init() {}

    public func load(issueID: String) -> ConflictDecisionDraft? { lock.withLock { drafts[issueID] } }

    @discardableResult
    public func save(_ draft: ConflictDecisionDraft, issueID: String) -> Bool {
        lock.withLock { drafts[issueID] = draft }
        return true
    }

    public func clear(issueID: String) { lock.withLock { drafts[issueID] = nil } }

    public func prune(keeping issueIDs: Set<String>) {
        lock.withLock { drafts = drafts.filter { issueIDs.contains($0.key) } }
    }
}

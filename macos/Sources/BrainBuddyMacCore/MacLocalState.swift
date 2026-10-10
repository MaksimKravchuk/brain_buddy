import BrainBuddyCore
import CryptoKit
import Foundation

/// The Mac's device-only state, `mac-local.json` beside `store.json` (data-model E7). It is never
/// sent and holds no titles, names, notes, outcomes or email: only ids, instants, enums, counts,
/// file names and digests keyed by `installSalt`.
package struct MacLocalState: Codable, Hashable, Sendable {
    package static let currentVersion = 1

    package var version: Int
    /// 32 random bytes created with the file; the key of every digest here. Never leaves this Mac.
    package var installSalt: Data
    /// The first successful write of `store.json`, or a launch that found one; never cleared.
    package var workspaceFirstWrittenAt: Date?
    /// Nil only before the first 021 launch decided anything.
    package var legacyImport: LegacyImportRecord?
    /// `LegacyCookieCleanup` ran.
    package var legacyCleanupDoneAt: Date?
    package var waitingReviews: [String: TaskReviewMark]
    package var somedayReviews: [String: TaskReviewMark]
    package var projectReviews: [String: ProjectReviewMark]
    package var sidebar: Sidebar

    package struct Sidebar: Codable, Hashable, Sendable {
        /// X-06: the "Archived projects" disclosure, collapsed until the person opens it.
        package var archivedProjectsExpanded: Bool

        package init(archivedProjectsExpanded: Bool = false) {
            self.archivedProjectsExpanded = archivedProjectsExpanded
        }
    }

    package init(
        installSalt: Data, workspaceFirstWrittenAt: Date? = nil, legacyImport: LegacyImportRecord? = nil,
        legacyCleanupDoneAt: Date? = nil, waitingReviews: [String: TaskReviewMark] = [:],
        somedayReviews: [String: TaskReviewMark] = [:], projectReviews: [String: ProjectReviewMark] = [:],
        sidebar: Sidebar = Sidebar()
    ) {
        version = Self.currentVersion
        self.installSalt = installSalt
        self.workspaceFirstWrittenAt = workspaceFirstWrittenAt
        self.legacyImport = legacyImport
        self.legacyCleanupDoneAt = legacyCleanupDoneAt
        self.waitingReviews = waitingReviews
        self.somedayReviews = somedayReviews
        self.projectReviews = projectReviews
        self.sidebar = sidebar
    }

    /// A new state with a fresh salt.
    package static func fresh() -> MacLocalState {
        var generator = SystemRandomNumberGenerator()
        return MacLocalState(installSalt: Data((0..<32).map { _ in UInt8.random(in: 0...255, using: &generator) }))
    }

    private enum CodingKeys: String, CodingKey {
        case version, installSalt, workspaceFirstWrittenAt, legacyImport, legacyCleanupDoneAt
        case waitingReviews, somedayReviews, projectReviews, sidebar
    }

    package init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        version = try values.decode(Int.self, forKey: .version)
        installSalt = try values.decode(Data.self, forKey: .installSalt)
        workspaceFirstWrittenAt = try values.decodeIfPresent(Date.self, forKey: .workspaceFirstWrittenAt)
        legacyImport = try values.decodeIfPresent(LegacyImportRecord.self, forKey: .legacyImport)
        legacyCleanupDoneAt = try values.decodeIfPresent(Date.self, forKey: .legacyCleanupDoneAt)
        waitingReviews = try values.decodeIfPresent([String: TaskReviewMark].self, forKey: .waitingReviews) ?? [:]
        somedayReviews = try values.decodeIfPresent([String: TaskReviewMark].self, forKey: .somedayReviews) ?? [:]
        projectReviews = try values.decodeIfPresent([String: ProjectReviewMark].self, forKey: .projectReviews) ?? [:]
        sidebar = try values.decodeIfPresent(Sidebar.self, forKey: .sidebar) ?? Sidebar()
    }
}

/// The durable state of the one-time import of `local-gtd.json` (data-model E7.1).
package struct LegacyImportRecord: Codable, Hashable, Sendable {
    package enum State: String, Codable, Sendable {
        case none, inProgress, completed, unreadable, laterFileKept
    }

    package enum UnreadableReason: String, Codable, Sendable {
        case corrupt, newerVersion, verificationFailed
    }

    package struct Report: Codable, Hashable, Sendable {
        package var fileName: String
        package var adjustedCount: Int
        package var notCarriedCount: Int

        package init(fileName: String, adjustedCount: Int, notCarriedCount: Int) {
            self.fileName = fileName
            self.adjustedCount = adjustedCount
            self.notCarriedCount = notCarriedCount
        }
    }

    /// A previous-version file that appeared after the workspace existed (FR-033). Recorded once
    /// per Mac: an older copy that keeps writing never brings the notice back.
    package struct LaterFile: Codable, Hashable, Sendable {
        package var digest: String
        package var detectedAt: Date
        package var noticeSeenAt: Date?

        package init(digest: String, detectedAt: Date, noticeSeenAt: Date? = nil) {
            self.digest = digest
            self.detectedAt = detectedAt
            self.noticeSeenAt = noticeSeenAt
        }
    }

    package var state: State
    package var decidedAt: Date
    package var importerVersion: Int
    package var attemptID: UUID?
    package var importedLegacyDigest: String?
    package var importedAt: Date?
    package var backupFileName: String?
    package var legacyRenamedAt: Date?
    package var backupDeletedAt: Date?
    package var report: Report?
    package var unreadableReason: UnreadableReason?
    package var noticeSeenAt: Date?
    package var signedOutSinceImport: Bool
    package var laterFile: LaterFile?

    package init(
        state: State, decidedAt: Date, importerVersion: Int, attemptID: UUID? = nil, importedLegacyDigest: String? = nil,
        importedAt: Date? = nil, backupFileName: String? = nil, legacyRenamedAt: Date? = nil,
        backupDeletedAt: Date? = nil, report: Report? = nil, unreadableReason: UnreadableReason? = nil,
        noticeSeenAt: Date? = nil, signedOutSinceImport: Bool = false, laterFile: LaterFile? = nil
    ) {
        self.state = state
        self.decidedAt = decidedAt
        self.importerVersion = importerVersion
        self.attemptID = attemptID
        self.importedLegacyDigest = importedLegacyDigest
        self.importedAt = importedAt
        self.backupFileName = backupFileName
        self.legacyRenamedAt = legacyRenamedAt
        self.backupDeletedAt = backupDeletedAt
        self.report = report
        self.unreadableReason = unreadableReason
        self.noticeSeenAt = noticeSeenAt
        self.signedOutSinceImport = signedOutSinceImport
        self.laterFile = laterFile
    }
}

// MARK: - Review marks (data-model E7.2)

/// "Keep waiting" or "Keep in Someday": valid while the task's content stamp is unchanged and the
/// mark is less than 7 days old.
package struct TaskReviewMark: Codable, Hashable, Sendable {
    package var reviewedAt: Date
    package var stamp: String

    package init(reviewedAt: Date, stamp: String) {
        self.reviewedAt = reviewedAt
        self.stamp = stamp
    }
}

package enum ProjectReviewDecision: String, Codable, CaseIterable, Identifiable, Sendable {
    case keep, actionUpdated, deferred

    package var id: String { rawValue }
    package var title: String {
        switch self {
        case .keep: "Keep current plan"
        case .actionUpdated: "I changed an action"
        case .deferred: "Keep in Someday or Waiting"
        }
    }
}

package struct ProjectReviewMark: Codable, Hashable, Sendable {
    package var reviewedAt: Date
    package var decision: ProjectReviewDecision
    package var taskSignature: String

    package init(reviewedAt: Date, decision: ProjectReviewDecision, taskSignature: String) {
        self.reviewedAt = reviewedAt
        self.decision = decision
        self.taskSignature = taskSignature
    }
}

/// How a mark names its record: `s:<serverID>` once the server knows it, else `c:<client id>`.
package enum RecordKey {
    package static func of(_ task: TaskRecord) -> String {
        task.serverID.map { "s:\($0)" } ?? "c:\(task.id.rawValue)"
    }

    package static func of(_ project: ProjectRecord) -> String {
        project.serverID.map { "s:\($0)" } ?? "c:\(project.id.rawValue)"
    }

    /// Every key the record may still be stored under (the `c:` one until the next write re-keys it).
    static func candidates(serverID: String?, clientID: String) -> [String] {
        (serverID.map { ["s:\($0)"] } ?? []) + ["c:\(clientID)"]
    }
}

extension MacLocalState {
    /// The 7-day review cadence (`ContentView` before 021, `LocalGTDStore.swift:321-334`).
    package static let reviewValidity: TimeInterval = 7 * 24 * 60 * 60
    /// Marks older than this are pruned at every launch.
    package static let markRetention: TimeInterval = 30 * 24 * 60 * 60

    /// The keyed stamp of a task's user-visible content (CryptoKit `HMAC<SHA256>` keyed by
    /// `installSalt` over the kit's `RecordContentForm`).
    package func stamp(of task: TaskRecord, in state: GTDState) -> String {
        Self.hex(HMAC<SHA256>.authenticationCode(for: Data(RecordContentForm.bytes(of: task, in: state)), using: key))
    }

    /// The keyed signature of every task in a project, in any state.
    package func signature(ofProject id: ProjectID, in state: GTDState) -> String {
        Self.hex(HMAC<SHA256>.authenticationCode(for: Data(RecordContentForm.bytes(ofTasksIn: id, in: state)), using: key))
    }

    package func waitingReviewDue(_ task: TaskRecord, stamp: String, recordKeys: [String], now: Date) -> Bool {
        guard task.state == .waiting else { return false }
        guard let mark = mark(in: waitingReviews, candidates: recordKeys) else { return true }
        return mark.stamp != stamp || mark.reviewedAt.addingTimeInterval(Self.reviewValidity) <= now
    }

    package func somedayReviewDue(_ task: TaskRecord, stamp: String, recordKeys: [String], now: Date) -> Bool {
        guard task.state == .someday else { return false }
        guard let mark = mark(in: somedayReviews, candidates: recordKeys) else { return true }
        return mark.stamp != stamp || mark.reviewedAt.addingTimeInterval(Self.reviewValidity) <= now
    }

    package func validProjectMark(for project: ProjectRecord, signature: String, recordKeys: [String], now: Date) -> ProjectReviewMark? {
        guard let mark = mark(in: projectReviews, candidates: recordKeys), mark.taskSignature == signature,
              mark.reviewedAt.addingTimeInterval(Self.reviewValidity) > now else { return nil }
        return mark
    }

    package func projectChangedSinceReview(_ project: ProjectRecord, signature: String, recordKeys: [String]) -> Bool {
        guard let mark = mark(in: projectReviews, candidates: recordKeys) else { return false }
        return mark.taskSignature != signature
    }

    /// A keyed digest of arbitrary bytes, for the legacy file (never a fingerprint usable off this Mac).
    package func digest(of data: Data) -> String {
        Self.hex(HMAC<SHA256>.authenticationCode(for: data, using: key))
    }

    private var key: SymmetricKey { SymmetricKey(data: installSalt) }

    private static func hex<Code: Sequence>(_ code: Code) -> String where Code.Element == UInt8 {
        code.map { String(format: "%02x", $0) }.joined()
    }

    // MARK: Reading marks

    package func waitingMark(for task: TaskRecord) -> TaskReviewMark? {
        mark(in: waitingReviews, serverID: task.serverID, clientID: task.id.rawValue)
    }

    package func somedayMark(for task: TaskRecord) -> TaskReviewMark? {
        mark(in: somedayReviews, serverID: task.serverID, clientID: task.id.rawValue)
    }

    package func projectMark(for project: ProjectRecord) -> ProjectReviewMark? {
        mark(in: projectReviews, serverID: project.serverID, clientID: project.id.rawValue)
    }

    package func projectMark(recordKeys: [String]) -> ProjectReviewMark? {
        mark(in: projectReviews, candidates: recordKeys)
    }

    private func mark<Mark>(in marks: [String: Mark], serverID: String?, clientID: String) -> Mark? {
        mark(in: marks, candidates: RecordKey.candidates(serverID: serverID, clientID: clientID))
    }

    private func mark<Mark>(in marks: [String: Mark], candidates: [String]) -> Mark? {
        for key in candidates {
            if let mark = marks[key] { return mark }
        }
        return nil
    }

    /// The task needs its Waiting review: no mark, a changed task, or a mark 7 days old.
    package func waitingReviewDue(_ task: TaskRecord, in state: GTDState, now: Date) -> Bool {
        guard task.state == .waiting else { return false }
        return !isValid(waitingMark(for: task), for: task, in: state, now: now)
    }

    package func somedayReviewDue(_ task: TaskRecord, in state: GTDState, now: Date) -> Bool {
        guard task.state == .someday else { return false }
        return !isValid(somedayMark(for: task), for: task, in: state, now: now)
    }

    private func isValid(_ mark: TaskReviewMark?, for task: TaskRecord, in state: GTDState, now: Date) -> Bool {
        guard let mark else { return false }
        return mark.stamp == stamp(of: task, in: state) && mark.reviewedAt.addingTimeInterval(Self.reviewValidity) > now
    }

    /// The project's mark when it still holds: same task signature, less than 7 days old.
    package func validProjectMark(for project: ProjectRecord, in state: GTDState, now: Date) -> ProjectReviewMark? {
        guard let mark = projectMark(for: project) else { return nil }
        guard mark.taskSignature == signature(ofProject: project.id, in: state),
            mark.reviewedAt.addingTimeInterval(Self.reviewValidity) > now
        else { return nil }
        return mark
    }

    /// A mark exists but the project's tasks changed since.
    package func projectChangedSinceReview(_ project: ProjectRecord, in state: GTDState) -> Bool {
        guard let mark = projectMark(for: project) else { return false }
        return mark.taskSignature != signature(ofProject: project.id, in: state)
    }

    // MARK: Writing marks

    package mutating func markWaitingReviewed(_ task: TaskRecord, in state: GTDState, at now: Date) {
        let mark = TaskReviewMark(reviewedAt: now, stamp: stamp(of: task, in: state))
        Self.set(&waitingReviews, mark, task: task)
    }

    package mutating func markSomedayReviewed(_ task: TaskRecord, in state: GTDState, at now: Date) {
        let mark = TaskReviewMark(reviewedAt: now, stamp: stamp(of: task, in: state))
        Self.set(&somedayReviews, mark, task: task)
    }

    package mutating func markWaitingReviewed(_ task: TaskRecord, stamp: String, at now: Date) {
        Self.set(&waitingReviews, TaskReviewMark(reviewedAt: now, stamp: stamp), task: task)
    }

    package mutating func markSomedayReviewed(_ task: TaskRecord, stamp: String, at now: Date) {
        Self.set(&somedayReviews, TaskReviewMark(reviewedAt: now, stamp: stamp), task: task)
    }

    package mutating func markWaitingReviewed(_ stamp: String, recordKeys: [String], primaryRecordKey: String, at now: Date) {
        for key in recordKeys { waitingReviews[key] = nil }
        waitingReviews[primaryRecordKey] = TaskReviewMark(reviewedAt: now, stamp: stamp)
    }

    package mutating func markSomedayReviewed(_ stamp: String, recordKeys: [String], primaryRecordKey: String, at now: Date) {
        for key in recordKeys { somedayReviews[key] = nil }
        somedayReviews[primaryRecordKey] = TaskReviewMark(reviewedAt: now, stamp: stamp)
    }

    package mutating func markProjectReviewed(
        _ project: ProjectRecord, decision: ProjectReviewDecision, signature: String, at now: Date
    ) {
        for key in RecordKey.candidates(serverID: project.serverID, clientID: project.id.rawValue) {
            projectReviews[key] = nil
        }
        projectReviews[RecordKey.of(project)] = ProjectReviewMark(reviewedAt: now, decision: decision, taskSignature: signature)
    }

    package mutating func markProjectReviewed(
        decision: ProjectReviewDecision, signature: String, recordKeys: [String], primaryRecordKey: String, at now: Date
    ) {
        for key in recordKeys { projectReviews[key] = nil }
        projectReviews[primaryRecordKey] = ProjectReviewMark(reviewedAt: now, decision: decision, taskSignature: signature)
    }

    package mutating func clearProjectReview(_ project: ProjectRecord) {
        for key in RecordKey.candidates(serverID: project.serverID, clientID: project.id.rawValue) {
            projectReviews[key] = nil
        }
    }

    package mutating func clearProjectReview(recordKeys: [String]) {
        for key in recordKeys { projectReviews[key] = nil }
    }

    private static func set(_ marks: inout [String: TaskReviewMark], _ mark: TaskReviewMark, task: TaskRecord) {
        for key in RecordKey.candidates(serverID: task.serverID, clientID: task.id.rawValue) { marks[key] = nil }
        marks[RecordKey.of(task)] = mark
    }

    // MARK: Upkeep

    /// Marks older than 30 days go, whether or not anyone signed in again (at every launch).
    package mutating func pruneOldMarks(now: Date) {
        let cutoff = now.addingTimeInterval(-Self.markRetention)
        waitingReviews = waitingReviews.filter { $0.value.reviewedAt >= cutoff }
        somedayReviews = somedayReviews.filter { $0.value.reviewedAt >= cutoff }
        projectReviews = projectReviews.filter { $0.value.reviewedAt >= cutoff }
    }

    /// A record that gained a server id is stored under `s:<serverID>` from the next write on, so
    /// marks survive the upload at sign-in (FR-023).
    package mutating func rekey(in state: GTDState) {
        var taskServerIDs: [String: String] = [:]
        for task in state.tasks.values { if let serverID = task.serverID { taskServerIDs[task.id.rawValue] = serverID } }
        var projectServerIDs: [String: String] = [:]
        for project in state.projects.values {
            if let serverID = project.serverID { projectServerIDs[project.id.rawValue] = serverID }
        }
        waitingReviews = Self.rekeyed(waitingReviews, serverIDs: taskServerIDs, newer: { $0.reviewedAt > $1.reviewedAt })
        somedayReviews = Self.rekeyed(somedayReviews, serverIDs: taskServerIDs, newer: { $0.reviewedAt > $1.reviewedAt })
        projectReviews = Self.rekeyed(projectReviews, serverIDs: projectServerIDs, newer: { $0.reviewedAt > $1.reviewedAt })
    }

    private static func rekeyed<Mark>(
        _ marks: [String: Mark], serverIDs: [String: String], newer: (Mark, Mark) -> Bool
    ) -> [String: Mark] {
        var result: [String: Mark] = [:]
        for (key, mark) in marks {
            var target = key
            if key.hasPrefix("c:"), let serverID = serverIDs[String(key.dropFirst(2))] { target = "s:\(serverID)" }
            if let existing = result[target], newer(existing, mark) { continue }
            result[target] = mark
        }
        return result
    }

    /// After a full pull, keys that match no record go (a signed-out account's marks among them).
    package mutating func pruneUnmatched(in state: GTDState) {
        let taskKeys = Set(state.tasks.values.flatMap {
            RecordKey.candidates(serverID: $0.serverID, clientID: $0.id.rawValue)
        })
        let projectKeys = Set(state.projects.values.flatMap {
            RecordKey.candidates(serverID: $0.serverID, clientID: $0.id.rawValue)
        })
        waitingReviews = waitingReviews.filter { taskKeys.contains($0.key) }
        somedayReviews = somedayReviews.filter { taskKeys.contains($0.key) }
        projectReviews = projectReviews.filter { projectKeys.contains($0.key) }
    }
}

// MARK: - The file

/// `mac-local.json` (0600) under its own `flock` (`.mac-local.json.lock`), written atomically: a
/// temporary file, flushed, renamed over it, the folder flushed.
package final class MacLocalStateStore: Sendable {
    package static let fileName = "mac-local.json"

    package let fileURL: URL
    package let lockURL: URL

    package init(directory: URL) {
        fileURL = directory.appendingPathComponent(Self.fileName)
        lockURL = directory.appendingPathComponent(".\(Self.fileName).lock")
    }

    /// The stored state, or nil when there is none (never written, or removed). A file that cannot
    /// be read counts as absent; `update` sets it aside rather than overwriting it.
    package func load() -> MacLocalState? {
        guard let data = try? MacFiles.contents(of: fileURL) else { return nil }
        return try? Self.decoder.decode(MacLocalState.self, from: data)
    }

    /// Reads the latest state under the lock (a fresh one, with a new salt, when there is none),
    /// applies `transform`, writes it and returns it. An unreadable file is renamed to
    /// `mac-local.unreadable-<UTC>.json` first, never overwritten.
    @discardableResult
    package func update(_ transform: (inout MacLocalState) throws -> Void) throws -> MacLocalState {
        try MacFiles.createDirectory(fileURL.deletingLastPathComponent())
        let lock = try FileLock.acquire(lockURL)
        defer { lock.release() }
        var state: MacLocalState
        if let data = try MacFiles.contents(of: fileURL) {
            if let decoded = try? Self.decoder.decode(MacLocalState.self, from: data) {
                state = decoded
            } else {
                let aside = fileURL.deletingLastPathComponent()
                    .appendingPathComponent("mac-local.unreadable-\(LegacyFileNames.stamp(Date())).json")
                try MacFiles.renameExclusively(fileURL, to: aside)
                state = .fresh()
            }
        } else {
            state = .fresh()
        }
        try transform(&state)
        try MacFiles.writeAtomically(try Self.encoder.encode(state), to: fileURL)
        return state
    }

    private static var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }

    private static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}

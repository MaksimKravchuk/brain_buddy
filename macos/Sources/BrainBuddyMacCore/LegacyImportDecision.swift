import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

/// The files of the Mac's folder that the import decision looks at (data-model E7.1).
package struct LegacyImportFolder: Sendable {
    package let directory: URL

    package init(directory: URL) { self.directory = directory }

    package var legacy: URL { directory.appendingPathComponent(LegacyFileNames.legacy) }
    package var legacyLock: URL { directory.appendingPathComponent(LegacyFileNames.legacyLock) }
    package var store: URL { directory.appendingPathComponent(LegacyFileNames.store) }
    package func staging(_ attemptID: UUID) -> URL { directory.appendingPathComponent(LegacyFileNames.staging(attemptID)) }
    package func file(_ name: String) -> URL { directory.appendingPathComponent(name) }

    package var stagingFiles: [URL] { MacFiles.names(in: directory).filter(LegacyFileNames.isStaging).map(file) }
    package var backups: [URL] { MacFiles.names(in: directory).filter(LegacyFileNames.isBackup).map(file) }
    package var reports: [URL] { MacFiles.names(in: directory).filter(LegacyFileNames.isReport).map(file) }
    package var quarantined: [URL] { MacFiles.names(in: directory).filter(LegacyFileNames.isQuarantined).map(file) }

    /// Invariant 2: `store.json` exists, the workspace was written once, the import completed or
    /// kept a later file, or the folder holds a backup or a set-aside store (so it stays true when
    /// `mac-local.json` is lost). An import never targets a workspace in use.
    package func isInUse(_ state: MacLocalState?) -> Bool {
        if MacFiles.exists(store) || state?.workspaceFirstWrittenAt != nil { return true }
        if let record = state?.legacyImport, record.state == .completed || record.state == .laterFileKept { return true }
        return !backups.isEmpty || !quarantined.isEmpty
    }
}

/// What a launch found, as the decision table reads it.
package struct LegacyImportSituation: Hashable, Sendable {
    package var record: LegacyImportRecord?
    /// The keyed digest of `local-gtd.json`; nil when there is none.
    package var legacyDigest: String?
    package var storeExists: Bool
    package var inUse: Bool
    /// The staging file of the record's attempt exists.
    package var attemptStagingExists: Bool
    /// The record's backup exists.
    package var backupExists: Bool

    package init(
        record: LegacyImportRecord?, legacyDigest: String?, storeExists: Bool, inUse: Bool,
        attemptStagingExists: Bool = false, backupExists: Bool = false
    ) {
        self.record = record
        self.legacyDigest = legacyDigest
        self.storeExists = storeExists
        self.inUse = inUse
        self.attemptStagingExists = attemptStagingExists
        self.backupExists = backupExists
    }
}

/// The launch decision of data-model E7.1: first matching row wins; a situation the table does not
/// name never imports and never renames (invariant 7).
package enum LegacyImportDecision {
    package enum Action: Hashable, Sendable {
        /// Row 1 with no record: a fresh install.
        case recordNone
        /// Nothing to do with the file; open the workspace.
        case open
        /// Rows 2, 4, 5 and 12; the attempt's staging file goes first.
        case importLegacy(discardingAttempt: UUID?)
        /// A previous-version file beside a workspace in use: never imported, renamed or deleted.
        /// `markKept` records the state `laterFileKept` (rows 3, 7, 16 without a completed import).
        case keepLaterFile(markKept: Bool, discardingAttempt: UUID?)
        /// Rows 6 and 7 without a file: the attempt's staging file goes, the record becomes `none`.
        case discardAttempt(UUID?)
        /// Row 8: the verified staging file becomes `store.json`, then row 9.
        case finishStagingRename
        /// Row 9: the crash came between the two renames.
        case finishLegacyRename
        /// Row 11: the backup retention check only.
        case retention
    }

    package static func decide(_ s: LegacyImportSituation, importerVersion: Int) -> (row: Int, action: Action) {
        let present = s.legacyDigest != nil
        guard let record = s.record else {
            if !present { return (1, .recordNone) }
            return s.inUse ? (3, .keepLaterFile(markKept: true, discardingAttempt: nil)) : (2, .importLegacy(discardingAttempt: nil))
        }
        switch record.state {
        case .none:
            if !present { return (1, .open) }
            return s.inUse ? (3, .keepLaterFile(markKept: true, discardingAttempt: nil)) : (2, .importLegacy(discardingAttempt: nil))
        case .inProgress:
            if s.storeExists {
                return present
                    ? (7, .keepLaterFile(markKept: true, discardingAttempt: record.attemptID))
                    : (7, .discardAttempt(record.attemptID))
            }
            if !present { return (6, .discardAttempt(record.attemptID)) }
            return s.legacyDigest == record.importedLegacyDigest
                ? (4, .importLegacy(discardingAttempt: record.attemptID))
                : (5, .importLegacy(discardingAttempt: record.attemptID))
        case .completed:
            if record.legacyRenamedAt == nil, !s.storeExists, s.attemptStagingExists { return (8, .finishStagingRename) }
            if record.legacyRenamedAt == nil, present, s.legacyDigest == record.importedLegacyDigest, s.storeExists {
                // A backup already at the recorded name means the rename happened and only its record
                // was lost: the file now present is another copy, kept as found.
                return s.backupExists ? (10, .keepLaterFile(markKept: false, discardingAttempt: nil)) : (9, .finishLegacyRename)
            }
            if present {
                let named = record.legacyRenamedAt != nil || s.legacyDigest != record.importedLegacyDigest
                return (named ? 10 : 16, .keepLaterFile(markKept: false, discardingAttempt: nil))
            }
            return (11, .retention)
        case .unreadable:
            if !present { return (15, .open) }
            if s.legacyDigest == record.importedLegacyDigest {
                return !s.inUse && importerVersion > record.importerVersion
                    ? (12, .importLegacy(discardingAttempt: nil)) : (13, .open)
            }
            return (14, .keepLaterFile(markKept: false, discardingAttempt: nil))
        case .laterFileKept:
            if !present { return (15, .open) }
            return (14, .keepLaterFile(markKept: false, discardingAttempt: nil))
        }
    }
}

/// One X-05 alert (contracts/mac-legacy-import.md §5), shown once before the workspace opens.
package enum LegacyImportNotice: Hashable, Sendable {
    case unreadable(LegacyImportRecord.UnreadableReason, file: URL)
    case partlyCarried(report: URL)
    case laterFile(file: URL)

    package var file: URL {
        switch self {
        case .unreadable(_, let file), .laterFile(let file): file
        case .partlyCarried(let report): report
        }
    }

    /// The alert's copy: a title, the text before the selectable path, the path, the text after.
    package var title: String {
        switch self {
        case .unreadable(.verificationFailed, _): "Brain Buddy couldn't carry over your earlier tasks"
        case .unreadable: "Brain Buddy couldn't read your earlier tasks"
        case .partlyCarried: "Brain Buddy carried over your earlier tasks, except a few it couldn't read"
        case .laterFile: "Brain Buddy found tasks from the previous version"
        }
    }

    package var textBeforePath: String {
        switch self {
        case .unreadable(.corrupt, _): "The file from the previous version was left exactly as it was. It's here:"
        case .unreadable(.newerVersion, _):
            "They were saved by a newer version of Brain Buddy, so this version left the file exactly as it was."
        case .unreadable(.verificationFailed, _): "Your file is fine and was left exactly as it was. It's here:"
        case .partlyCarried:
            "They're listed in a report next to the file from the previous version, which stays on this Mac. It's here:"
        case .laterFile:
            "An older copy of Brain Buddy saved tasks on this Mac after the update. They were not added here, and the file was left exactly as it was. It's here:"
        }
    }

    package var textAfterPath: String? {
        switch self {
        case .unreadable(.corrupt, _):
            "Brain Buddy will start with an empty workspace. Keep the file if you'd like help recovering it."
        case .unreadable(.newerVersion, _): "Install the newer version to open the file again."
        case .unreadable(.verificationFailed, _):
            "This is a problem in Brain Buddy. Brain Buddy will start with an empty workspace. Keep the file: it still has all your earlier tasks."
        case .partlyCarried: nil
        case .laterFile: "Your current tasks are unchanged."
        }
    }

    /// The path as the person knows it: the home folder written as "~".
    package var displayPath: String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let path = file.path
        return path.hasPrefix(home + "/") ? "~" + path.dropFirst(home.count) : path
    }

    package static let continueTitle = "Continue"
    package static let showInFinderTitle = "Show in Finder"
}

/// Test-only hooks of the import (contracts/mac-legacy-import.md §6): records forced through the
/// "not carried" path, a tampered staging file, a simulated crash after a step.
package struct LegacyImportTestHooks: Sendable {
    package enum CrashPoint: Hashable, Sendable {
        case afterInProgress, afterStaging, afterVerification, afterCompleted, betweenRenames
    }

    package var notCarried: Set<String> = []
    package var tamperStaging: (@Sendable (inout StoreDocument) -> Void)?
    package var crash: CrashPoint?

    package init(
        notCarried: Set<String> = [], tamperStaging: (@Sendable (inout StoreDocument) -> Void)? = nil,
        crash: CrashPoint? = nil
    ) {
        self.notCarried = notCarried
        self.tamperStaging = tamperStaging
        self.crash = crash
    }
}

/// A crash the tests inject: the run stops where it is, files as they are.
package struct SimulatedCrash: Error, Hashable, Sendable {
    package var point: LegacyImportTestHooks.CrashPoint
}

/// What the launch's import step leaves for the app: the notices to show before the workspace opens.
package struct LegacyImportLaunchResult: Hashable, Sendable {
    package var row: Int
    package var notices: [LegacyImportNotice]
}

/// Launch step 2 (contracts/mac-app-host.md §1): the one-time import of `local-gtd.json` with its
/// durable state machine (data-model E7.1), the backup retention rule (E8), orphaned staging
/// cleanup (invariant 5) and the X-05 notices. Call it while holding the single-instance lock; it
/// takes the legacy `lockf` itself for the whole decision and import (invariant 6).
package final class LegacyImportCoordinator: Sendable {
    package static let backupRetention: TimeInterval = 30 * 24 * 60 * 60

    package let folder: LegacyImportFolder
    package let localState: MacLocalStateStore
    private let now: @Sendable () -> Date
    private let makeID: @Sendable () -> UUID
    private let log: any MacLogSink
    private let legacyLocking: any LegacyStoreLocking
    private let hooks: LegacyImportTestHooks
    private let importerVersion: Int

    package init(
        directory: URL, localState: MacLocalStateStore? = nil, now: @escaping @Sendable () -> Date = { Date() },
        makeID: @escaping @Sendable () -> UUID = { UUID() }, log: any MacLogSink = SystemMacLog(),
        legacyLocking: any LegacyStoreLocking = LockfLegacyStoreLocking(), hooks: LegacyImportTestHooks = LegacyImportTestHooks(),
        importerVersion: Int = LegacyStoreImporter.version
    ) {
        folder = LegacyImportFolder(directory: directory)
        self.localState = localState ?? MacLocalStateStore(directory: directory)
        self.now = now
        self.makeID = makeID
        self.log = log
        self.legacyLocking = legacyLocking
        self.hooks = hooks
        self.importerVersion = importerVersion
    }

    /// Decides, imports when the table says so, and returns the notices to show. Every path that
    /// fails leaves the legacy file as it was and `store.json` untouched or absent.
    package func run() throws -> LegacyImportLaunchResult {
        try MacFiles.createDirectory(folder.directory)
        let lock = try legacyLocking.acquire(folder.legacyLock)
        defer { lock.release() }
        let started = now()

        // The salt exists before any digest is taken; marks older than 30 days go at every launch.
        var state = try localState.update { $0.pruneOldMarks(now: started) }
        let legacyData = try MacFiles.contents(of: folder.legacy)
        let digest = legacyData.map { state.digest(of: $0) }
        let current = state.legacyImport
        let situation = LegacyImportSituation(
            record: current, legacyDigest: digest, storeExists: MacFiles.exists(folder.store), inUse: folder.isInUse(state),
            attemptStagingExists: current?.attemptID.map { MacFiles.exists(folder.staging($0)) } ?? false,
            backupExists: current?.backupFileName.map { MacFiles.exists(folder.file($0)) } ?? false
        )
        let (row, action) = LegacyImportDecision.decide(situation, importerVersion: importerVersion)
        log.log(.import, "launch decision row=\(row)")

        switch action {
        case .recordNone:
            state = try record(.init(state: .none, decidedAt: started, importerVersion: importerVersion))
        case .open:
            break
        case .importLegacy(let attempt):
            if let attempt { try MacFiles.remove(folder.staging(attempt)) }
            if let legacyData, let digest { state = try importLegacy(legacyData, digest: digest, previous: current) }
        case .keepLaterFile(let markKept, let attempt):
            if let attempt { try MacFiles.remove(folder.staging(attempt)) }
            if let digest { state = try keepLaterFile(digest: digest, markKept: markKept) }
        case .discardAttempt(let attempt):
            if let attempt { try MacFiles.remove(folder.staging(attempt)) }
            state = try record(.init(state: .none, decidedAt: started, importerVersion: importerVersion))
        case .finishStagingRename:
            if let attempt = current?.attemptID {
                try finishStagingRename(attempt)
                if digest != nil, digest == current?.importedLegacyDigest { state = try finishLegacyRename() }
            }
        case .finishLegacyRename:
            state = try finishLegacyRename()
        case .retention:
            break
        }

        // After the terminal decision: workspace first written, retention, orphaned staging files.
        state = try localState.update { current in
            if MacFiles.exists(self.folder.store), current.workspaceFirstWrittenAt == nil {
                current.workspaceFirstWrittenAt = self.now()
            }
        }
        if state.legacyImport?.state == .completed { state = try applyRetention(atSignOut: nil) }
        removeOrphanedStaging(keeping: state.legacyImport)
        return LegacyImportLaunchResult(row: row, notices: notices(for: state))
    }

    // MARK: Actions

    private func record(_ record: LegacyImportRecord) throws -> MacLocalState {
        try localState.update { $0.legacyImport = record }
    }

    private func keepLaterFile(digest: String, markKept: Bool) throws -> MacLocalState {
        let at = now()
        let state = try localState.update { state in
            var record = state.legacyImport ?? LegacyImportRecord(state: .none, decidedAt: at, importerVersion: self.importerVersion)
            if markKept {
                record.state = .laterFileKept
                record.decidedAt = at
                record.attemptID = nil
            }
            if record.laterFile == nil { record.laterFile = .init(digest: digest, detectedAt: at) }
            state.legacyImport = record
        }
        log.log(.import, "later file kept")
        return state
    }

    /// Row 2: read, plan, stage, verify, record, rename, rename (contracts/mac-legacy-import.md §1).
    private func importLegacy(_ data: Data, digest: String, previous: LegacyImportRecord?) throws -> MacLocalState {
        let started = Date()
        let importedAt = now()
        // A report left by an attempt that never completed belongs to no record.
        for report in folder.reports where report.lastPathComponent != previous?.report?.fileName {
            try MacFiles.remove(report)
        }
        let snapshot: LegacySnapshot
        do {
            snapshot = try LegacySnapshot.read(data)
        } catch {
            return try unreadable(error == .newerVersion ? .newerVersion : .corrupt, digest: digest, previous: previous)
        }

        let attemptID = makeID()
        var inProgress = LegacyImportRecord(
            state: .inProgress, decidedAt: importedAt, importerVersion: importerVersion, attemptID: attemptID,
            importedLegacyDigest: digest
        )
        inProgress.laterFile = previous?.laterFile
        _ = try record(inProgress)
        try crash(.afterInProgress)

        let plan: LegacyImportPlan
        do {
            plan = try LegacyStoreImporter.plan(snapshot, importedAt: importedAt, makeID: makeID, notCarried: hooks.notCarried)
        } catch {
            log.log(.import, "import defect step=\(error.step)")
            return try unreadable(.verificationFailed, digest: digest, previous: inProgress)
        }
        var document = plan.document
        hooks.tamperStaging?(&document)
        document.version = StoreDocument.currentVersion
        document.generation = 1
        let staging = folder.staging(attemptID)
        try MacFiles.writeNew(try StoreDocumentCoding.encode(document), to: staging)
        try crash(.afterStaging)

        let staged = try MacFiles.contents(of: staging) ?? Data()
        let problems = LegacyStoreImporter.verify(staged, against: plan.expectation, today: CalendarDay(date: importedAt))
        guard problems.isEmpty else {
            try MacFiles.remove(staging)
            log.log(.import, "import verification failed mismatches=\(problems.count)")
            return try unreadable(.verificationFailed, digest: digest, previous: inProgress)
        }
        try crash(.afterVerification)

        let replayed = try StoreDocumentCoding.decode(staged).replayed().state
        var report: LegacyImportRecord.Report?
        if !plan.adjustments.isEmpty || !plan.notCarried.isEmpty {
            let name = LegacyFileNames.report(importedAt)
            let text = LegacyStoreImporter.reportText(adjustments: plan.adjustments, notCarried: plan.notCarried, importedAt: importedAt)
            try MacFiles.writeAtomically(Data(text.utf8), to: folder.file(name))
            report = .init(fileName: name, adjustedCount: plan.adjustments.count, notCarriedCount: plan.notCarried.count)
        }
        var completed = inProgress
        completed.state = .completed
        completed.decidedAt = importedAt
        completed.importedAt = importedAt
        completed.backupFileName = LegacyFileNames.backup(importedAt)
        completed.report = report
        let marks = plan.marks
        _ = try localState.update { state in
            state.legacyImport = completed
            // §4: the receipts that were valid before the upgrade, stamped over the imported content.
            for mark in marks.waiting {
                guard let task = replayed.tasks[mark.task] else { continue }
                state.markWaitingReviewed(task, in: replayed, at: mark.reviewedAt)
            }
            for mark in marks.someday {
                guard let task = replayed.tasks[mark.task] else { continue }
                state.markSomedayReviewed(task, in: replayed, at: mark.reviewedAt)
            }
            for mark in marks.projects {
                guard let project = replayed.projects[mark.project] else { continue }
                state.markProjectReviewed(
                    project, decision: mark.decision, signature: state.signature(ofProject: mark.project, in: replayed),
                    at: mark.reviewedAt
                )
            }
        }
        try crash(.afterCompleted)

        do {
            try MacFiles.renameExclusively(staging, to: folder.store)
        } catch let error as MacFileError where error.isAlreadyExists {
            // A `store.json` this attempt did not create: never touched (invariant 1).
            try MacFiles.remove(staging)
            log.log(.import, "import found a workspace in use")
            return try keepLaterFile(digest: digest, markKept: true)
        }
        try crash(.betweenRenames)
        let state = try finishLegacyRename()
        let milliseconds = Int(Date().timeIntervalSince(started) * 1000)
        log.log(.import, "import completed \(plan.counts.logFields) durationMs=\(milliseconds)")
        return state
    }

    private func unreadable(
        _ reason: LegacyImportRecord.UnreadableReason, digest: String, previous: LegacyImportRecord?
    ) throws -> MacLocalState {
        var record = LegacyImportRecord(
            state: .unreadable, decidedAt: now(), importerVersion: importerVersion, importedLegacyDigest: digest,
            unreadableReason: reason
        )
        record.laterFile = previous?.laterFile
        log.log(.import, "import unreadable reason=\(reason.rawValue)")
        return try self.record(record)
    }

    /// Row 8: the verified staging file of the completed attempt becomes `store.json`, exclusively.
    private func finishStagingRename(_ attempt: UUID) throws {
        do {
            try MacFiles.renameExclusively(folder.staging(attempt), to: folder.store)
        } catch let error as MacFileError where error.isAlreadyExists {
            log.log(.import, "staging kept beside a workspace in use")
        }
    }

    /// Row 9 and the last step of an import: the imported file, and only it, becomes the backup,
    /// exclusively (invariant 3); `legacyRenamedAt` is recorded right after.
    private func finishLegacyRename() throws -> MacLocalState {
        guard let record = localState.load()?.legacyImport, record.state == .completed,
            let importedDigest = record.importedLegacyDigest, MacFiles.exists(folder.store),
            let data = try MacFiles.contents(of: folder.legacy), localState.load()?.digest(of: data) == importedDigest
        else { return try localState.update { _ in } }
        var name = record.backupFileName ?? LegacyFileNames.backup(record.importedAt ?? now())
        var attempt = 1
        while true {
            do {
                try MacFiles.renameExclusively(folder.legacy, to: folder.file(name))
                break
            } catch let error as MacFileError where error.isAlreadyExists && attempt < 100 {
                attempt += 1
                name = (record.backupFileName ?? "local-gtd.backup.json").replacingOccurrences(of: ".json", with: "-\(attempt).json")
            }
        }
        let renamedAt = now()
        return try localState.update { state in
            state.legacyImport?.legacyRenamedAt = renamedAt
            state.legacyImport?.backupFileName = name
        }
    }

    private func crash(_ point: LegacyImportTestHooks.CrashPoint) throws {
        if hooks.crash == point { throw SimulatedCrash(point: point) }
    }

    // MARK: Staging files (invariant 5)

    /// Deletes every staging file but the recorded in-progress or completed attempt's.
    private func removeOrphanedStaging(keeping record: LegacyImportRecord?) {
        let kept = (record?.state == .inProgress || record?.state == .completed) ? record?.attemptID : nil
        var removed = 0
        for file in folder.stagingFiles where kept.map({ file != folder.staging($0) }) ?? true {
            if (try? MacFiles.remove(file)) != nil { removed += 1 }
        }
        if removed > 0 { log.log(.import, "staging removed count=\(removed)") }
    }

    /// Sign-out deletes every staging file (invariant 5).
    package func removeAllStagingFiles() {
        for file in folder.stagingFiles { try? MacFiles.remove(file) }
    }

    // MARK: Backup retention (data-model E8)

    /// Whether the backup goes now: 30 days after the import, after a sign-out since, every record
    /// carried, and at a sign-out nothing of the first upload discarded.
    package static func backupIsDue(_ record: LegacyImportRecord, now: Date, atSignOutWithInitialUpload remaining: Int?) -> Bool {
        guard record.state == .completed, record.backupDeletedAt == nil, let importedAt = record.importedAt else { return false }
        guard importedAt.addingTimeInterval(backupRetention) <= now, record.signedOutSinceImport else { return false }
        guard (record.report?.notCarriedCount ?? 0) == 0 else { return false }
        if let remaining, remaining > 0 { return false }
        return true
    }

    @discardableResult
    private func applyRetention(atSignOut remaining: Int?) throws -> MacLocalState {
        guard let record = localState.load()?.legacyImport,
            Self.backupIsDue(record, now: now(), atSignOutWithInitialUpload: remaining)
        else { return try localState.update { _ in } }
        if let name = record.backupFileName { try MacFiles.remove(folder.file(name)) }
        if let report = record.report?.fileName { try MacFiles.remove(folder.file(report)) }
        let deletedAt = now()
        log.log(.import, "backup removed by retention")
        return try localState.update { $0.legacyImport?.backupDeletedAt = deletedAt }
    }

    /// The sign-out side of E7.1 and E8 (called by the sign-out flow, PR-09): records the sign-out,
    /// deletes the backup when it is due, and removes every staging file. Returns whether the backup
    /// was removed.
    @discardableResult
    package func didSignOut(initialUploadRemaining: Int) throws -> Bool {
        let before = localState.load()?.legacyImport?.backupDeletedAt
        _ = try localState.update { state in
            if state.legacyImport?.state == .completed { state.legacyImport?.signedOutSinceImport = true }
        }
        let state = try applyRetention(atSignOut: initialUploadRemaining)
        removeAllStagingFiles()
        return before == nil && state.legacyImport?.backupDeletedAt != nil
    }

    /// Whether the sign-out about to be confirmed would remove the backup (X-04 `signOutBackupRemoved`).
    package func backupWillBeRemovedAtSignOut(initialUploadRemaining: Int) -> Bool {
        guard var record = localState.load()?.legacyImport else { return false }
        record.signedOutSinceImport = true
        return Self.backupIsDue(record, now: now(), atSignOutWithInitialUpload: initialUploadRemaining)
    }

    /// The backup from before the update and the date the rule may delete it, read from its file
    /// name when `mac-local.json` was lost (then no sign-out is assumed).
    package func backup() -> (file: URL, keptUntil: Date)? {
        let record = localState.load()?.legacyImport
        if let record, record.state == .completed, record.backupDeletedAt == nil, let name = record.backupFileName,
            MacFiles.exists(folder.file(name))
        {
            let importedAt = record.importedAt ?? LegacyFileNames.backupDate(fromFileName: name) ?? now()
            return (folder.file(name), importedAt.addingTimeInterval(Self.backupRetention))
        }
        guard let file = folder.backups.first, let date = LegacyFileNames.backupDate(fromFileName: file.lastPathComponent) else {
            return nil
        }
        return (file, date.addingTimeInterval(Self.backupRetention))
    }

    // MARK: Notices (X-05)

    private func notices(for state: MacLocalState) -> [LegacyImportNotice] {
        guard let record = state.legacyImport else { return [] }
        var notices: [LegacyImportNotice] = []
        if record.state == .unreadable, record.noticeSeenAt == nil, let reason = record.unreadableReason {
            notices.append(.unreadable(reason, file: folder.legacy))
        }
        if record.state == .completed, (record.report?.notCarriedCount ?? 0) > 0, record.noticeSeenAt == nil,
            let report = record.report?.fileName
        {
            notices.append(.partlyCarried(report: folder.file(report)))
        }
        if let later = record.laterFile, later.noticeSeenAt == nil, MacFiles.exists(folder.legacy) {
            notices.append(.laterFile(file: folder.legacy))
        }
        return notices
    }

    /// "Continue" or "Show in Finder" was chosen: the notice is not shown again. A quit while the
    /// alert is open records nothing, so it shows at the next launch.
    package func recordNoticeSeen(_ notice: LegacyImportNotice) throws {
        let at = now()
        _ = try localState.update { state in
            switch notice {
            case .unreadable, .partlyCarried: state.legacyImport?.noticeSeenAt = at
            case .laterFile: state.legacyImport?.laterFile?.noticeSeenAt = at
            }
        }
    }
}

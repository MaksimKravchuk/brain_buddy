import BrainBuddyCore
import BrainBuddyPersistence
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// `mac-local.json`, the Mac's device-only state (data-model E7, E7.2; T094): written atomically
/// under its own lock, never holding content, with review marks keyed by record and stamped with a
/// keyed digest of the record's visible content.
@Suite("Mac local state")
struct MacLocalStateTests {
    private let now = TestClock.importTime

    /// A state with one Waiting task in a project with a tag, as the kit would hold it.
    private func sampleState(title: String = "Ask Sentinel-Title-91c4 for the keys", serverID: String? = nil) -> GTDState {
        var state = GTDState()
        state.projects["p1"] = ProjectRecord(
            id: "p1", name: "Sentinel-Project-5b2e", createdAt: now, desiredOutcome: "Sentinel-Outcome-0d77"
        )
        state.tags["t1"] = TagRecord(id: "t1", name: "calls", createdAt: now)
        state.tasks["w1"] = TaskRecord(
            id: "w1", serverID: serverID, title: title, details: "Sentinel-Notes-3a9f", state: .waiting, projectID: "p1",
            tagIDs: ["t1"], waitingFor: "Sentinel-Person-e61d", waitingSince: now, orderKey: 0, createdAt: now, updatedAt: now
        )
        return state
    }

    @Test("021-FR-023 the sidecar is written atomically under its own lock, 0600, and holds no titles, names, notes, outcomes or email")
    func fileIsPrivateAndContentFree() throws {
        let folder = TemporaryFolder()
        let store = MacLocalStateStore(directory: folder.url)
        let state = sampleState()
        let task = try #require(state.tasks["w1"])
        let project = try #require(state.projects["p1"])
        try store.update { local in
            local.markWaitingReviewed(task, in: state, at: now)
            local.markProjectReviewed(project, decision: .keep, signature: local.signature(ofProject: "p1", in: state), at: now)
            local.workspaceFirstWrittenAt = now
        }
        let data = try #require(folder.bytes(MacLocalStateStore.fileName))
        let text = String(decoding: data, as: UTF8.self)
        for sentinel in ["Sentinel-Title", "Sentinel-Project", "Sentinel-Outcome", "Sentinel-Notes", "Sentinel-Person", "@example.com", "calls"] {
            #expect(!text.contains(sentinel), "the sidecar holds \(sentinel)")
        }
        let attributes = try FileManager.default.attributesOfItem(atPath: folder.sidecar.path)
        #expect((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600)
        #expect(MacFiles.exists(store.lockURL), "written under .mac-local.json.lock")
        #expect(!folder.names.contains { $0.hasSuffix(".tmp") }, "no temporary file is left")
        #expect(store.load()?.installSalt.count == 32)
    }

    @Test("021-FR-023 a mark is keyed c:<client id> until the record has a server id, then re-keyed to s:<server id> on the next write")
    func recordKeysAndRekeying() throws {
        let folder = TemporaryFolder()
        let store = MacLocalStateStore(directory: folder.url)
        let local = sampleState()
        let task = try #require(local.tasks["w1"])
        #expect(RecordKey.of(task) == "c:w1")
        try store.update { $0.markWaitingReviewed(task, in: local, at: now) }
        #expect(store.load()?.waitingReviews.keys.sorted() == ["c:w1"])

        let uploaded = sampleState(serverID: "task_9f8e")
        let synced = try #require(uploaded.tasks["w1"])
        #expect(RecordKey.of(synced) == "s:task_9f8e")
        #expect(store.load()?.waitingMark(for: synced) != nil, "the c: key still answers until the re-key")
        try store.update { $0.rekey(in: uploaded) }
        #expect(store.load()?.waitingReviews.keys.sorted() == ["s:task_9f8e"])
        #expect(store.load()?.waitingReviewDue(synced, in: uploaded, now: now) == false, "the mark survives the upload")
    }

    @Test("021-FR-023 the stamp is a keyed HMAC of the content form: unchanged by server times and ids, changed by an edit, different under another salt")
    func stamps() throws {
        let state = sampleState()
        var task = try #require(state.tasks["w1"])
        let local = MacLocalState(installSalt: Data(repeating: 7, count: 32))
        let stamp = local.stamp(of: task, in: state)
        #expect(stamp.count == 64)
        task.updatedAt = now.addingTimeInterval(500)
        task.serverID = "task_1"
        task.serverRevision = 9
        var touched = state
        touched.tasks["w1"] = task
        #expect(local.stamp(of: task, in: touched) == stamp, "server times and ids are not content")
        task.title = "Ask for the keys again"
        touched.tasks["w1"] = task
        #expect(local.stamp(of: task, in: touched) != stamp)
        #expect(MacLocalState(installSalt: Data(repeating: 8, count: 32)).stamp(of: try #require(state.tasks["w1"]), in: state) != stamp)
    }

    @Test("021-FR-023 a mark holds while the stamp matches and for less than 7 days")
    func validity() throws {
        let state = sampleState()
        let task = try #require(state.tasks["w1"])
        var local = MacLocalState.fresh()
        #expect(local.waitingReviewDue(task, in: state, now: now))
        local.markWaitingReviewed(task, in: state, at: now)
        #expect(!local.waitingReviewDue(task, in: state, now: now.addingTimeInterval(6 * TestClock.day)))
        #expect(local.waitingReviewDue(task, in: state, now: now.addingTimeInterval(7 * TestClock.day)))
        var changed = state
        changed.tasks["w1"]?.waitingFor = "Someone else"
        #expect(local.waitingReviewDue(try #require(changed.tasks["w1"]), in: changed, now: now), "a changed task is due again")
    }

    @Test("021-FR-023 marks older than 30 days go at launch; after a full pull, marks of records that no longer exist go")
    func pruning() throws {
        let folder = TemporaryFolder()
        let state = sampleState()
        let task = try #require(state.tasks["w1"])
        let store = MacLocalStateStore(directory: folder.url)
        try store.update { local in
            local.markWaitingReviewed(task, in: state, at: now.addingTimeInterval(-31 * TestClock.day))
            local.somedayReviews["c:gone"] = TaskReviewMark(reviewedAt: now, stamp: "x")
            local.projectReviews["s:project_gone"] = ProjectReviewMark(reviewedAt: now, decision: .keep, taskSignature: "y")
        }
        // A launch prunes the old mark (the import step runs first at every launch).
        _ = try LegacyImportCoordinator.forTest(folder).run()
        let afterLaunch = try #require(store.load())
        #expect(afterLaunch.waitingReviews.isEmpty)
        #expect(afterLaunch.somedayReviews.count == 1 && afterLaunch.projectReviews.count == 1)

        try store.update { $0.pruneUnmatched(in: state) }
        let afterPull = try #require(store.load())
        #expect(afterPull.somedayReviews.isEmpty && afterPull.projectReviews.isEmpty)
    }

    @Test("021-FR-023 a sign-out removes the workspace but keeps the sidecar and its marks")
    func marksSurviveSignOut() async throws {
        let folder = TemporaryFolder()
        let state = sampleState()
        let task = try #require(state.tasks["w1"])
        try MacLocalStateStore(directory: folder.url).update { $0.markWaitingReviewed(task, in: state, at: now) }
        let store = FileDocumentStore(fileURL: folder.store)
        _ = try await store.update { $0.outbox = [] }
        try await store.destroy()
        #expect(!MacFiles.exists(folder.store))
        #expect(MacLocalStateStore(directory: folder.url).load()?.waitingReviews.count == 1)
    }

    @Test("021-FR-023 the Archived projects disclosure state is remembered")
    @MainActor
    func disclosureRemembered() async throws {
        let folder = TemporaryFolder()
        let host = WorkspaceHost(
            configuration: MacHostConfiguration(directory: folder.url, isDryRun: false), tokenStore: SpyTokenStore(),
            transport: CountingTransport()
        )
        let model = BrainBuddyModel(host: host)
        #expect(!model.localState.sidebar.archivedProjectsExpanded, "collapsed until opened")
        model.setArchivedProjectsExpanded(true)
        let reopened = BrainBuddyModel(host: host)
        #expect(reopened.localState.sidebar.archivedProjectsExpanded)
    }

    @Test("021-FR-023 an unreadable sidecar is set aside, never overwritten")
    func unreadableSidecarIsSetAside() throws {
        let folder = TemporaryFolder()
        try Data("not json".utf8).write(to: folder.sidecar)
        try MacLocalStateStore(directory: folder.url).update { $0.legacyCleanupDoneAt = now }
        #expect(folder.names.contains { $0.hasPrefix("mac-local.unreadable-") })
        #expect(MacLocalStateStore(directory: folder.url).load()?.legacyCleanupDoneAt == now)
    }
}

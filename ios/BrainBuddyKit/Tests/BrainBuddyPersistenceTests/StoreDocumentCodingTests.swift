import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyPersistence

@Suite struct TimestampTests {
    @Test func writesUTCWithMicroseconds() {
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: 0)) == "2001-01-01T00:00:00.000000Z")
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSince1970: 0)) == "1970-01-01T00:00:00.000000Z")
        #expect(
            ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: -0.25)) == "2000-12-31T23:59:59.750000Z"
        )
        #expect(
            ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: 812_345_678.123456))
                == "2026-09-29T03:34:38.123456Z"
        )
        // Foundation's distantPast is Julian 0001-01-01, proleptic Gregorian 0000-12-30.
        #expect(ISO8601Timestamp.string(from: Date.distantPast) == "0000-12-30T00:00:00.000000Z")
        #expect(ISO8601Timestamp.date(from: "0000-12-30T00:00:00.000000Z") == Date.distantPast)
        #expect(ISO8601Timestamp.string(from: Date.distantFuture) == "4001-01-01T00:00:00.000000Z")
    }

    @Test func roundsToTheNearestMicrosecond() {
        #expect(
            ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: 0.000_000_6)) == "2001-01-01T00:00:00.000001Z"
        )
        #expect(
            ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: 59.999_999_7)) == "2001-01-01T00:01:00.000000Z"
        )
    }

    @Test func refusesDatesOutsideYearsZeroTo9999() {
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: 3e11)) == nil)
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: -7e10)) == nil)
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: .infinity)) == nil)
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: .nan)) == nil)
    }

    @Test(arguments: [
        ("2001-01-01T00:00:00Z", 0.0),
        ("2001-01-01T00:00:00.000000Z", 0.0),
        ("2001-01-01T02:00:00+02:00", 0.0),
        ("2000-12-31T19:00:00.5-05:00", 0.5),
        ("2001-01-01T00:00:00.123Z", 0.123),
        ("2001-01-01T00:00:00.1234565Z", 0.123457),
        ("2001-01-01T00:00:00.123456789Z", 0.123457),
        ("2001-01-01T00:00:59.9999995Z", 60.0),
        ("2024-02-29T12:00:00Z", 730_900_800.0),
    ])
    func parsesOffsetsAndOtherPrecisions(text: String, expected: TimeInterval) {
        #expect(ISO8601Timestamp.date(from: text) == Date(timeIntervalSinceReferenceDate: expected))
    }

    @Test(arguments: [
        "", "2001-01-01", "2001-01-01T00:00:00", "2001-13-01T00:00:00Z", "2001-02-29T00:00:00Z",
        "2001-04-31T00:00:00Z", "2001-01-01T24:00:00Z", "2001-01-01T00:60:00Z", "2001-01-01T00:00:60Z",
        "2001-01-01T00:00:00.Z", "2001-01-01T00:00:00.1234567890Z", "2001-01-01 00:00:00Z",
        "2001-01-01T00:00:00Zjunk", "-001-01-01T00:00:00Z", "2001-01-01T00:00:00+2:00", "2001-01-01t00:00:00z",
        "+2001-01-01T00:00:00Z", "12001-01-01T00:00:00Z", "２００１-01-01T00:00:00Z",
    ])
    func rejectsMalformedTimestamps(text: String) {
        #expect(ISO8601Timestamp.date(from: text) == nil)
    }

    /// The calendar arithmetic agrees with Foundation's own ISO-8601 format
    /// (Gregorian years only: Foundation switches to Julian before 1582).
    @Test func calendarArithmeticMatchesFoundation() throws {
        var random = SplitMix64(seed: 0x0B5E_55ED)
        let lower: Int64 = -3_155_673_600  // about 1901
        let upper: Int64 = 6_311_433_600  // about 2201
        for _ in 0..<2_000 {
            let seconds = lower + Int64(random.next() % UInt64(upper - lower))
            let date = Date(timeIntervalSinceReferenceDate: TimeInterval(seconds))
            let ours = try #require(ISO8601Timestamp.string(from: date))
            let wholeSeconds = String(ours.prefix(19)) + "Z"
            #expect(wholeSeconds == date.formatted(Date.ISO8601FormatStyle()))
            #expect(try Date(wholeSeconds, strategy: .iso8601) == ISO8601Timestamp.date(from: ours))
        }
    }

    /// Any `Date` comes back within a microsecond, and from then on exactly,
    /// near today (where `Date()` values are) and across years 0–8000.
    @Test(arguments: [(-978_307_200.0, 4_102_444_800.0), (-63_113_904_000.0, 252_423_993_600.0)])
    func roundTripIsExactOnceNormalized(from lower: TimeInterval, span: TimeInterval) throws {
        var random = SplitMix64(seed: 42)
        for _ in 0..<5_000 {
            let interval = lower + span * (Double(random.next() >> 11) / Double(1 << 53))
            let original = Date(timeIntervalSinceReferenceDate: interval)
            let first = try #require(roundTrip(original))
            #expect(abs(first.timeIntervalSince(original)) < 0.000_001)
            #expect(roundTrip(first) == first)
        }
    }
}

@Suite struct StoreDocumentCodingTests {
    @Test func encodingIsDeterministicWithSortedKeys() throws {
        let document = Fixtures.richDocument()
        let first = try StoreDocumentCoding.encode(document)
        let second = try StoreDocumentCoding.encode(document)
        #expect(first == second)
        let text = try #require(String(data: first, encoding: .utf8))
        #expect(text.hasPrefix("{\"account\":"))
        #expect(text.hasSuffix("\"version\":2}"))
        #expect(text.contains("\"issuedAt\":\"2026-09-29T03:34:38.123456Z\""))
        #expect(text.contains("\"dueDate\":\"2026-10-02\""))
    }

    @Test func decodeRoundTripsEveryStoredType() throws {
        let document = Fixtures.richDocument()
        #expect(try StoreDocumentCoding.decode(StoreDocumentCoding.encode(document)) == document)
    }

    @Test func generationIsReadWithoutTheRestOfTheDocument() throws {
        #expect(try StoreDocumentCoding.generation(of: Data(#"{"version":1,"generation":12}"#.utf8)) == 12)
        let missing = #expect(throws: DocumentStoreError.self) {
            try StoreDocumentCoding.generation(of: Data(#"{"version":1}"#.utf8))
        }
        #expect(isUnreadable(missing))
        let unknownVersion = #expect(throws: DocumentStoreError.self) {
            try StoreDocumentCoding.generation(of: Data(#"{"version":0,"generation":2}"#.utf8))
        }
        #expect(isUnreadable(unknownVersion))
    }

    @Test func newerVersionsAreUnsupported() {
        let data = Data(#"{"version":3,"generation":7,"shape":"from the future"}"#.utf8)
        #expect(throws: DocumentStoreError.unsupportedVersion(3)) { try StoreDocumentCoding.decode(data) }
        #expect(throws: DocumentStoreError.unsupportedVersion(3)) { try StoreDocumentCoding.generation(of: data) }
    }

    /// A version-1 store as an app before spec 020 wrote it: every stored
    /// type, an outbox, issues, an account and sync metadata.
    static let version1Store = #"""
        {"account":{"displayName":"Sam","email":"sam@example.com","id":"user_1","linkedAt":"2026-09-25T00:13:20.500000Z","serverURL":"https:\/\/brain-buddy-frontend.fly.dev\/api"},"base":{"projects":{"project-1":{"color":"#0EA5E9","createdAt":"2026-09-25T00:13:20.500000Z","id":"project-1","name":"Home","serverID":"project_1","serverRevision":1,"state":"active"}},"tags":{"tag-1":{"createdAt":"2026-09-25T00:13:20.500000Z","id":"tag-1","name":"phone","state":"active"}},"tasks":{"task-1":{"childrenSyncedAt":"2026-09-25T00:13:20.500000Z","comments":[{"authorID":"user_1","body":"Left a message","createdAt":"2026-09-25T00:13:20.500000Z","id":"comment-1"}],"createdAt":"2026-09-25T00:13:20.500000Z","details":"Before Friday","dueDate":"2026-10-02","id":"task-1","orderKey":7,"priority":"high","projectID":"project-1","serverID":"task_1a2b3c4d5e6f","serverRevision":3,"state":"waiting","subtasks":[{"id":"subtask-1","orderKey":0,"state":"open","title":"Find the number"}],"tagIDs":["tag-1"],"title":"Call the plumber","updatedAt":"2026-09-26T03:46:40.000001Z","waitingFor":"Plumber","waitingSince":"2026-09-26T00:00:00.250000Z"},"task-2":{"comments":[],"createdAt":"2026-09-25T00:13:20.500000Z","id":"task-2","orderKey":0,"priority":"none","state":"next","subtasks":[],"tagIDs":[],"title":"Renovate the bathroom","updatedAt":"2026-09-25T00:13:20.500000Z"}}},"generation":4,"issues":[{"command":{"deleteTag":{"_0":"tag-1"}},"id":"6F0E1E0A-0B1C-4D2E-8F3A-4B5C6D7E8F90","message":"Not found","occurredAt":"2026-09-25T00:13:20.500000Z","referenceID":"ref-1"}],"outbox":[{"attempts":0,"command":{"createTask":{"_0":{"list":"next","priority":"none","tagIDs":[],"taskID":"task-3","title":"Call Bob"}}},"id":"0E7B8E3C-2C4A-4D6B-9F1E-3A5B7C9D1E2F","idempotencyKey":"00000000-0000-4000-8000-000000000091","issuedAt":"2026-09-29T03:34:38.123456Z"},{"attempts":2,"command":{"transitionTask":{"_0":{"action":"complete","taskID":"task-1"}}},"firstAttemptAt":"2026-09-25T00:13:20.500000Z","id":"7C8D9E0F-1A2B-4C3D-8E4F-5A6B7C8D9E0F","idempotencyKey":"00000000-0000-4000-8000-000000000092","issuedAt":"2026-09-29T03:34:38.123456Z","lastAttemptAt":"2026-09-29T03:34:38.123456Z","lastError":"timeout"}],"sync":{"lastPullAt":"2026-09-25T00:13:20.500000Z","lastPushAt":"2026-09-29T03:34:38.123456Z"},"version":1}
        """#

    @Test("020-FR-040 a version-1 store migrates to version 2 with empty review state and no data loss")
    func version1MigratesToVersion2() throws {
        let data = Data(Self.version1Store.utf8)
        let migrated = try StoreDocumentCoding.decode(data)
        #expect(migrated.version == 2)
        #expect(migrated.base.review == .empty)
        #expect(migrated.local == .empty)
        #expect(migrated.local.activatedAt == nil)
        #expect(migrated.local.formDrafts.isEmpty)
        #expect(migrated.local.lastObservedTimeZone == nil)
        #expect(migrated.local.linkedExtensionNotices.isEmpty)
        // No data loss: every record, operation, issue and setting survives.
        #expect(migrated.generation == 4)
        #expect(migrated.account?.email == "sam@example.com")
        #expect(migrated.base.tasks.count == 2 && migrated.base.projects.count == 1 && migrated.base.tags.count == 1)
        let task = try #require(migrated.base.tasks["task-1"])
        #expect(task.title == "Call the plumber" && task.serverRevision == 3 && task.waitingFor == "Plumber")
        #expect(task.subtasks.map(\.title) == ["Find the number"] && task.comments.map(\.body) == ["Left a message"])
        #expect(task.formulation == nil && task.consecutiveStalledFormulations == 0 && task.parked == nil)
        #expect(migrated.outbox.count == 2 && migrated.outbox[1].lastError == "timeout")
        guard case .createTask(let create) = migrated.outbox[0].command else {
            Issue.record("the queued creation is gone")
            return
        }
        #expect(create.title == "Call Bob" && create.newFormulationID == nil)
        #expect(migrated.issues.map(\.message) == ["Not found"])
        #expect(migrated.sync.lastPushAt != nil)
        // Written again, it is a plain version-2 document that reads back the same.
        #expect(try StoreDocumentCoding.decode(StoreDocumentCoding.encode(migrated)) == migrated)
        // The migration step only adds what version 2 needs.
        let step = try StoreDocumentCoding.migrate(data, fromVersion: 1)
        let text = String(decoding: step, as: UTF8.self)
        #expect(text.contains(#""version":2"#) && text.contains(#""local":{}"#) && text.contains(#""review":{}"#))
    }

    @Test("020-FR-040 review state and local state round-trip through the store format")
    func reviewStateRoundTrips() throws {
        var document = Fixtures.richDocument()
        let started = Date(timeIntervalSinceReferenceDate: 812_000_000)
        document.base.tasks["task-1"]?.formulation = FormulationClock(
            id: "form_00000000-0000-4000-8000-000000000001", startedAt: started, extendedAt: started,
            extensionReason: "Waiting for the quote", parkFloorAt: started
        )
        document.base.tasks["task-1"]?.consecutiveStalledFormulations = 2
        document.base.review.settings = ReviewSettings(thresholdDays: 21, timeZone: "Europe/Berlin", activatedAt: started, revision: 3)
        document.base.review.parkAcks = [ParkAck(taskID: "task-1", formulationID: "form_x", parkedAt: started)]
        document.local = LocalReviewState(
            activatedAt: started, explainerSeenLocally: true, issuedAutoParks: ["task-1": "form_x"],
            formDrafts: [.decisionForm(.reformulate, task: "task-1", formulation: "form_x"): FormDraft(text: "Email Bob", savedAt: started)],
            wywaLastShownDay: CalendarDay(year: 2026, month: 10, day: 9), serverClockOffset: -2.5,
            lastObservedTimeZone: "Europe/Berlin", linkedExtensionNotices: ["task-1"]
        )
        #expect(try StoreDocumentCoding.decode(StoreDocumentCoding.encode(document)) == document)
    }

    @Test(arguments: ["", "not json", "[]", #"{"generation":1}"#, #"{"version":"1"}"#, #"{"version":1}"#, #"{"version":0}"#])
    func malformedDocumentsAreUnreadable(text: String) {
        let error = #expect(throws: DocumentStoreError.self) { try StoreDocumentCoding.decode(Data(text.utf8)) }
        #expect(isUnreadable(error))
    }

    @Test func migrationIsIdentityForTheCurrentVersion() throws {
        let data = try StoreDocumentCoding.encode(Fixtures.richDocument())
        #expect(try StoreDocumentCoding.migrate(data, fromVersion: StoreDocument.currentVersion) == data)
        let tooOld = #expect(throws: DocumentStoreError.self) { try StoreDocumentCoding.migrate(data, fromVersion: 0) }
        #expect(isUnreadable(tooOld))
        #expect(throws: DocumentStoreError.unsupportedVersion(StoreDocument.currentVersion + 1)) {
            try StoreDocumentCoding.migrate(data, fromVersion: StoreDocument.currentVersion + 1)
        }
    }

    @Test func datesOutsideFourDigitYearsCannotBeEncoded() {
        var document = StoreDocument()
        document.sync.lastPullAt = Date(timeIntervalSinceReferenceDate: 3e11)
        let error = #expect(throws: DocumentStoreError.self) { try StoreDocumentCoding.encode(document) }
        #expect(isIO(error))
    }

    /// `PendingOperation.everSent` came later: older documents decode with it
    /// false, and it is written only when set, so other documents keep their bytes.
    @Test func everSentIsOptionalOnDiskAndWrittenOnlyWhenSet() throws {
        var document = Fixtures.richDocument()
        let before = try StoreDocumentCoding.encode(document)
        #expect(!String(decoding: before, as: UTF8.self).contains("everSent"))
        let legacy = try StoreDocumentCoding.decode(before)
        #expect(legacy.outbox.map(\.everSent) == [false, false])
        #expect(legacy == document)

        document.outbox[0].everSent = true
        let after = try StoreDocumentCoding.encode(document)
        #expect(String(decoding: after, as: UTF8.self).contains(#""everSent":true"#))
        let decoded = try StoreDocumentCoding.decode(after)
        #expect(decoded.outbox[0].everSent)
        #expect(decoded.outbox[0].hasBeenSent, "with no attempt under its current key")
        #expect(decoded == document)
    }

    @Test("021-FR-008 a store written before spec 021 decodes, its projects without outcome, archive time or marker")
    func storeBeforeSpec021Decodes() throws {
        let document = try StoreDocumentCoding.decode(Data(Self.version1Store.utf8))
        let project = try #require(document.base.projects["project-1"])
        #expect(project.name == "Home" && project.desiredOutcome == nil)
        #expect(project.archivedAt == nil && !project.archivedBeforeLossless)
        let text = String(decoding: try StoreDocumentCoding.encode(document), as: UTF8.self)
        #expect(!text.contains("desiredOutcome") && !text.contains("archivedBeforeLossless"), "other projects keep their bytes")
    }

    @Test("021-FR-008 021-FR-028 the project fields and the new commands round-trip inside operations and issues; the version stays")
    func spec021FieldsRoundTrip() throws {
        var document = Fixtures.richDocument()
        let archivedAt = Date(timeIntervalSinceReferenceDate: 812_345_678.5)
        document.base.projects["project-1"]?.desiredOutcome = "Shed built"
        document.base.projects["project-1"]?.archivedAt = archivedAt
        document.base.projects["project-1"]?.archivedBeforeLossless = true
        let commands: [GTDCommand] = [
            .createProject(.init(projectID: "p", name: "Trip", desiredOutcome: "Two weeks away")),
            .setProjectOutcome(project: "p", outcome: "Back"), .setProjectOutcome(project: "p", outcome: nil),
            .unarchiveProject(project: "p"),
        ]
        document.outbox += commands.map { PendingOperation(command: $0, issuedAt: archivedAt) }
        document.issues += commands.map { SyncIssue(command: $0, message: "why", referenceID: "ref", occurredAt: archivedAt) }

        let decoded = try StoreDocumentCoding.decode(StoreDocumentCoding.encode(document))
        #expect(decoded == document)
        let project = try #require(decoded.base.projects["project-1"])
        #expect(project.desiredOutcome == "Shed built" && project.archivedAt == archivedAt && project.archivedBeforeLossless)
        #expect(decoded.outbox.suffix(4).map(\.command) == commands && decoded.issues.suffix(4).map(\.command) == commands)
        #expect(StoreDocument.currentVersion == 2, "spec 021 adds no store version and no migration step")
    }

    @Test func errorMessagesAreSentences() {
        let errors: [DocumentStoreError] = [.unreadable("x"), .unsupportedVersion(2), .io("disk full")]
        for error in errors {
            #expect(error.message.hasSuffix("."))
        }
        #expect(DocumentStoreError.io("disk full").message.contains("disk full"))
    }
}

private func roundTrip(_ date: Date) -> Date? {
    ISO8601Timestamp.string(from: date).flatMap(ISO8601Timestamp.date(from:))
}

/// A tiny deterministic generator so the property tests are reproducible.
struct SplitMix64 {
    private var state: UInt64

    init(seed: UInt64) { state = seed }

    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }
}

import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyPersistence

#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#elseif canImport(Musl)
import Musl
#endif

@Suite struct FileDocumentStoreTests {
    // MARK: Reading and writing

    @Test func loadReturnsNilAndCreatesNothingWhenNoDocumentExists() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let folder = directory.appendingPathComponent("BrainBuddy", isDirectory: true)
        let store = FileDocumentStore(fileURL: folder.appendingPathComponent("store.json"))

        #expect(try await store.load() == nil)
        #expect(try await store.generation() == nil)
        #expect(!FileManager.default.fileExists(atPath: folder.path))
    }

    @Test func updateRoundTripsEveryStoredType() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)
        let rich = Fixtures.richDocument()

        let written = try await store.update { $0 = rich }

        var expected = rich
        expected.generation = 1
        #expect(written == expected)
        #expect(try await store.load() == expected)
        #expect(try await FileDocumentStore(fileURL: url).load() == expected)
    }

    @Test func updateStartsFromAFreshDocument() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let store = FileDocumentStore(fileURL: directory.appendingPathComponent("store.json"))

        #expect(try await store.update { _ in } == StoreDocument(generation: 1))
    }

    @Test func generationIncrementsOnEveryWrite() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let store = FileDocumentStore(fileURL: directory.appendingPathComponent("store.json"))

        for expected in 1...3 {
            let written = try await store.update { $0.outbox.append(Fixtures.operation(expected)) }
            #expect(written.generation == expected)
            #expect(try await store.generation() == expected)
        }
        // The store owns `generation` and `version`, whatever the transform does.
        let written = try await store.update { document in
            document.generation = 99
            document.version = 7
        }
        #expect(written.generation == 4)
        #expect(written.version == StoreDocument.currentVersion)
        #expect(try await store.load()?.outbox.count == 3)
    }

    @Test func transformErrorWritesNothing() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)

        await #expect(throws: Boom()) {
            try await store.update { document in
                document.outbox.append(Fixtures.operation(1))
                throw Boom()
            }
        }
        #expect(!FileManager.default.fileExists(atPath: url.path))

        _ = try await store.update { $0.outbox.append(Fixtures.operation(1)) }
        let before = try Data(contentsOf: url)
        await #expect(throws: Boom()) {
            try await store.update { document in
                document.outbox.removeAll()
                throw Boom()
            }
        }
        #expect(try Data(contentsOf: url) == before)
        #expect(try await store.generation() == 1)
    }

    @Test func updateReadsTheLatestFileRatherThanACachedCopy() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)
        _ = try await store.update { $0.outbox.append(Fixtures.operation(1)) }

        // Another writer replaces the file behind the store's back.
        var external = try #require(try await store.load())
        external.generation = 10
        external.outbox.append(Fixtures.operation(2))
        try StoreDocumentCoding.encode(external).write(to: url)

        let written = try await store.update { $0.outbox.append(Fixtures.operation(3)) }
        #expect(written.generation == 11)
        #expect(written.outbox.map(\.command) == [1, 2, 3].map { Fixtures.operation($0).command })
    }

    // MARK: Unreadable documents

    @Test(arguments: [
        "", "not json", "[1, 2, 3]", #"{"version":1}"#, #"{"version":1,"generation":3}"#, #"{"version":0}"#,
        #"{"version":1,"generation":1,"outbox":[],"issues":[],"sync":{},"base":{"tasks":{},"projects":{},"#
            + #""tags":{"t":{"id":"t","name":"x","state":"active","createdAt":"yesterday"}}}}"#,
    ])
    func unreadableFileIsNeverOverwritten(contents: String) async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let original = Data(contents.utf8)
        try original.write(to: url)
        let store = FileDocumentStore(fileURL: url)

        let loadError = await #expect(throws: DocumentStoreError.self) { try await store.load() }
        #expect(isUnreadable(loadError))
        let updateError = await #expect(throws: DocumentStoreError.self) {
            try await store.update { $0.outbox.append(Fixtures.operation(1)) }
        }
        #expect(isUnreadable(updateError))

        #expect(try Data(contentsOf: url) == original)
        #expect(try directoryListing(directory) == [".store.json.lock", "store.json"])
    }

    @Test func truncatedDocumentIsUnreadableAndKept() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)
        _ = try await store.update { $0 = Fixtures.richDocument() }
        let complete = try Data(contentsOf: url)
        let truncated = complete.prefix(complete.count / 2)
        try truncated.write(to: url)

        let updateError = await #expect(throws: DocumentStoreError.self) { try await store.update { _ in } }
        #expect(isUnreadable(updateError))
        let generationError = await #expect(throws: DocumentStoreError.self) { try await store.generation() }
        #expect(isUnreadable(generationError))
        #expect(try Data(contentsOf: url) == truncated)
    }

    @Test func newerVersionIsUnsupportedAndUntouched() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let original = Data(#"{"version":2,"generation":7,"somethingNew":true}"#.utf8)
        try original.write(to: url)
        let store = FileDocumentStore(fileURL: url)

        await #expect(throws: DocumentStoreError.unsupportedVersion(2)) { try await store.load() }
        await #expect(throws: DocumentStoreError.unsupportedVersion(2)) { try await store.generation() }
        await #expect(throws: DocumentStoreError.unsupportedVersion(2)) { try await store.update { _ in } }
        #expect(try Data(contentsOf: url) == original)
    }

    @Test func quarantineSetsAnUnreadableDocumentAside() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)
        let first = Data("garbage".utf8)
        try first.write(to: url)

        let firstAside = try #require(try await store.quarantineUnreadableDocument())
        #expect(firstAside.deletingLastPathComponent().path == directory.path)
        #expect(firstAside.lastPathComponent.hasPrefix("store.unreadable-"))
        #expect(firstAside.pathExtension == "json")
        #expect(try Data(contentsOf: firstAside) == first)
        #expect(!FileManager.default.fileExists(atPath: url.path))
        #expect(try await store.load() == nil)

        // Starting fresh is now possible.
        #expect(try await store.update { _ in }.generation == 1)

        // A document from a newer version can be set aside too, and a second
        // one in the same second gets its own name.
        let second = Data(#"{"version":9}"#.utf8)
        try second.write(to: url)
        let secondAside = try #require(try await store.quarantineUnreadableDocument())
        #expect(secondAside != firstAside)
        #expect(try Data(contentsOf: secondAside) == second)
        #expect(try Data(contentsOf: firstAside) == first)
    }

    @Test func quarantineLeavesAReadableDocumentAlone() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)
        #expect(try await store.quarantineUnreadableDocument() == nil)

        _ = try await store.update { $0.outbox.append(Fixtures.operation(1)) }
        let before = try Data(contentsOf: url)
        #expect(try await store.quarantineUnreadableDocument() == nil)
        #expect(try Data(contentsOf: url) == before)
    }

    // MARK: Several writers

    @Test func twoStoresOnOneFileSeeEachOthersWrites() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let app = FileDocumentStore(fileURL: url)
        let widget = FileDocumentStore(fileURL: url)

        _ = try await app.update { $0.outbox.append(Fixtures.operation(1)) }
        #expect(try await widget.generation() == 1)
        #expect(try await widget.load()?.outbox.count == 1)

        _ = try await widget.update { $0.outbox.append(Fixtures.operation(2)) }
        let seenByApp = try #require(try await app.load())
        #expect(seenByApp.generation == 2)
        #expect(seenByApp.outbox.map(\.command) == [1, 2].map { Fixtures.operation($0).command })
    }

    /// Three stores on one file stand in for the app, a widget and an App
    /// Intent: `flock` treats their descriptors exactly like separate
    /// processes, so without the lock these would lose updates.
    @Test func concurrentUpdatesNeverLoseAnUpdate() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let stores = (0..<3).map { _ in FileDocumentStore(fileURL: url) }
        let operations = (0..<50).map { Fixtures.operation($0) }

        try await withThrowingTaskGroup(of: Void.self) { group in
            for (index, operation) in operations.enumerated() {
                let store = stores[index % stores.count]
                group.addTask { _ = try await store.update { $0.outbox.append(operation) } }
            }
            try await group.waitForAll()
        }

        let document = try #require(try await stores[0].load())
        #expect(document.generation == 50)
        #expect(document.outbox.count == 50)
        #expect(Set(document.outbox.map(\.id)) == Set(operations.map(\.id)))
        #expect(try directoryListing(directory) == [".store.json.lock", "store.json"])
    }

    @Test func updateWaitsWhileAnotherProcessHoldsTheLock() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let store = FileDocumentStore(fileURL: directory.appendingPathComponent("store.json"))
        _ = try await store.update { _ in }

        // Take the lock the way another process would: through our own open
        // file description of the lock file.
        let descriptor = open(store.lockURL.path, O_RDWR)
        try #require(descriptor >= 0)
        try #require(flock(descriptor, LOCK_EX) == 0)

        let generationWhileLocked = LockedValue<Int?>(nil)
        let fileURL = store.fileURL
        let otherProcess = Thread {
            Thread.sleep(forTimeInterval: 0.3)
            generationWhileLocked.set(try? StoreDocumentCoding.generation(of: Data(contentsOf: fileURL)))
            flock(descriptor, LOCK_UN)
            close(descriptor)
        }
        let start = ContinuousClock.now
        otherProcess.start()
        let written = try await store.update { $0.sync.lastFailure = "written after the lock was released" }
        let waited = ContinuousClock.now - start

        #expect(generationWhileLocked.value == 1)
        #expect(written.generation == 2)
        #expect(waited >= .milliseconds(250))
    }

    // MARK: Files on disk

    @Test func filesAreOwnerOnly() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let folder = directory.appendingPathComponent("Group/Library/BrainBuddy", isDirectory: true)
        let url = folder.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)
        _ = try await store.update { _ in }
        _ = try await store.update { _ in }

        #expect(permissions(of: directory.appendingPathComponent("Group")) == 0o700)
        #expect(permissions(of: folder) == 0o700)
        #expect(permissions(of: url) == 0o600)
        #expect(permissions(of: store.lockURL) == 0o600)
    }

    @Test func writesLeaveNoTemporaryFiles() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let store = FileDocumentStore(fileURL: directory.appendingPathComponent("store.json"))
        for index in 0..<5 {
            _ = try await store.update { $0.outbox.append(Fixtures.operation(index)) }
        }

        #expect(try directoryListing(directory) == [".store.json.lock", "store.json"])
        #expect(store.lockURL.lastPathComponent == ".store.json.lock")
    }

    @Test func datesRoundTripToTheMicrosecond() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)
        let exact = Date(timeIntervalSinceReferenceDate: 812_345_678.123456)
        let milliseconds = Date(timeIntervalSinceReferenceDate: 812_345_678.123)
        let now = Date()

        let written = try await store.update { document in
            document.outbox = [Fixtures.operation(1, issuedAt: exact), Fixtures.operation(2, issuedAt: now)]
            document.sync.lastPullAt = milliseconds
        }
        let loaded = try #require(try await store.load())

        #expect(loaded == written)
        #expect(loaded.outbox[0].issuedAt == exact)
        #expect(loaded.sync.lastPullAt == milliseconds)
        #expect(abs(loaded.outbox[1].issuedAt.timeIntervalSince(now)) < 0.000_001)
        let json = try #require(String(data: Data(contentsOf: url), encoding: .utf8))
        #expect(json.contains("\"issuedAt\":\"2026-09-29T03:34:38.123456Z\""))
        #expect(json.contains("\"lastPullAt\":\"2026-09-29T03:34:38.123000Z\""))

        // Rewriting what was read changes nothing.
        let rewritten = try await store.update { _ in }
        #expect(rewritten.outbox == loaded.outbox)
        #expect(rewritten.sync == loaded.sync)
    }

    @Test func unencodableDocumentIsNotWritten() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)
        _ = try await store.update { _ in }
        let before = try Data(contentsOf: url)

        let error = await #expect(throws: DocumentStoreError.self) {
            try await store.update { $0.sync.lastPullAt = Date(timeIntervalSinceReferenceDate: 3e11) }
        }
        #expect(isIO(error))
        #expect(try Data(contentsOf: url) == before)
    }

    // MARK: Destroying

    @Test func destroyRemovesTheDocumentAndTheLock() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)
        try await store.destroy()  // nothing there yet: no-op

        _ = try await store.update { $0.outbox.append(Fixtures.operation(1)) }
        // A write that crashed half-way leaves its temporary file behind.
        try Data("partial".utf8).write(to: directory.appendingPathComponent(".store.json.1234.tmp"))
        try Data("keep".utf8).write(to: directory.appendingPathComponent("unrelated.txt"))

        try await store.destroy()
        #expect(try directoryListing(directory) == ["unrelated.txt"])
        #expect(try await store.load() == nil)
        #expect(try await store.generation() == nil)

        // A new lock file is created by the next write.
        #expect(try await store.update { _ in }.generation == 1)
        #expect(FileManager.default.fileExists(atPath: store.lockURL.path))
    }

    @Test func destroyRemovesAnUnreadableDocument() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        try Data("garbage".utf8).write(to: url)
        let store = FileDocumentStore(fileURL: url)

        try await store.destroy()
        #expect(!FileManager.default.fileExists(atPath: url.path))
        #expect(try await store.load() == nil)
    }

    /// A set-aside document is a full copy of someone's data: signing out
    /// ("remove from this iPhone") must not leave it behind.
    @Test func destroyAlsoRemovesSetAsideDocuments() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store = FileDocumentStore(fileURL: url)
        try Data("garbage".utf8).write(to: url)
        let aside = try #require(try await store.quarantineUnreadableDocument())
        try Data(#"{"version":9}"#.utf8).write(to: url)
        _ = try #require(try await store.quarantineUnreadableDocument())
        _ = try await store.update { $0.outbox.append(Fixtures.operation(1)) }
        try Data("keep".utf8).write(to: directory.appendingPathComponent("other.unreadable-1.json"))
        #expect(FileManager.default.fileExists(atPath: aside.path))

        try await store.destroy()
        #expect(try directoryListing(directory) == ["other.unreadable-1.json"])
    }

    @Test func destroyAfterACheckReadsTheLatestDocumentAndKeepsEverythingWhenRefused() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let app = FileDocumentStore(fileURL: url)
        let widget = FileDocumentStore(fileURL: url)
        _ = try await app.update { _ in }
        // Another process queues a change the app has not read.
        _ = try await widget.update { $0.outbox.append(Fixtures.operation(1)) }

        let store: any DocumentStore = app
        let seen = LockedValue<Int?>(nil)
        await #expect(throws: Boom.self) {
            try await store.destroy(after: { document in
                seen.set(document?.outbox.count)
                if document?.outbox.isEmpty == false { throw Boom() }
            })
        }
        #expect(seen.value == 1)
        #expect(try await app.load()?.outbox.count == 1)

        try await store.destroy(after: { _ in })
        #expect(try await app.load() == nil)
        #expect(try directoryListing(directory).isEmpty)
        // Nothing there: the check sees nil and there is nothing to remove.
        try await store.destroy(after: { #expect($0 == nil) })
    }

    @Test func storedAccountIsReadEvenFromADocumentThatCannotBeDecoded() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let store: any DocumentStore = FileDocumentStore(fileURL: url)
        #expect(await store.storedAccount() == nil)

        let account = try #require(Fixtures.richDocument().account)
        var json = try #require(
            try JSONSerialization.jsonObject(with: StoreDocumentCoding.encode(Fixtures.richDocument())) as? [String: Any]
        )
        json["version"] = 9
        json["outbox"] = [["something": "new"]]
        try JSONSerialization.data(withJSONObject: json).write(to: url)
        await #expect(throws: DocumentStoreError.unsupportedVersion(9)) { try await store.load() }
        #expect(await store.storedAccount() == account)

        try Data("garbage".utf8).write(to: url)
        #expect(await store.storedAccount() == nil)
    }

    @Test func otherStoresKeepWorkingAfterDestroy() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        let app = FileDocumentStore(fileURL: url)
        let widget = FileDocumentStore(fileURL: url)
        _ = try await widget.update { _ in }

        try await app.destroy()
        _ = try await widget.update { $0.outbox.append(Fixtures.operation(1)) }
        _ = try await app.update { $0.outbox.append(Fixtures.operation(2)) }

        let document = try #require(try await widget.load())
        #expect(document.generation == 2)
        #expect(document.outbox.count == 2)
    }

    // MARK: Locations

    @Test func applicationSupportLocationIsStable() {
        let url = FileDocumentStore.applicationSupportDocumentURL()
        #expect(url.lastPathComponent == "store.json")
        #expect(url.deletingLastPathComponent().lastPathComponent == "BrainBuddy")
        #expect(FileDocumentStore.applicationSupportDocumentURL(fileName: "other.json").lastPathComponent == "other.json")
    }

    @Test func fileURLIsStandardized() {
        let store = FileDocumentStore(fileURL: URL(fileURLWithPath: "/var/data/./b/../store.json"))
        #expect(store.fileURL.path == "/var/data/store.json")
        #expect(store.lockURL.path == "/var/data/.store.json.lock")
    }
}

private func directoryListing(_ directory: URL) throws -> [String] {
    try FileManager.default.contentsOfDirectory(atPath: directory.path).sorted()
}

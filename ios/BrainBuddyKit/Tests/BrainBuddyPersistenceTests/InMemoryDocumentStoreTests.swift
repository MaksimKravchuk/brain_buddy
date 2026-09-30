import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyPersistence

@Suite struct InMemoryDocumentStoreTests {
    @Test func emptyStoreStartsFromAFreshDocument() async throws {
        let store = InMemoryDocumentStore()
        #expect(try await store.load() == nil)
        #expect(try await store.generation() == nil)
        #expect(try await store.update { _ in } == StoreDocument(generation: 1))
    }

    @Test func seededDocumentIsLoadedAndGenerationContinues() async throws {
        let seed = Fixtures.richDocument()
        let store = InMemoryDocumentStore(document: seed)
        #expect(try await store.load() == seed)
        #expect(try await store.generation() == 4)

        let written = try await store.update { $0.outbox.append(Fixtures.operation(9)) }
        #expect(written.generation == 5)
        #expect(written.outbox.count == seed.outbox.count + 1)
        #expect(try await store.load() == written)
        #expect(try await store.generation() == 5)
    }

    @Test func transformErrorWritesNothing() async throws {
        let store = InMemoryDocumentStore(document: StoreDocument(generation: 2))
        await #expect(throws: Boom()) {
            try await store.update { document in
                document.outbox.append(Fixtures.operation(1))
                throw Boom()
            }
        }
        #expect(try await store.load() == StoreDocument(generation: 2))
    }

    @Test func writesNormalizeDatesLikeTheFileStore() async throws {
        let now = Date()
        let written = try await InMemoryDocumentStore().update { $0.sync.lastPushAt = now }
        let lastPushAt = try #require(written.sync.lastPushAt)
        #expect(abs(lastPushAt.timeIntervalSince(now)) < 0.000_001)
        #expect(try StoreDocumentCoding.decode(StoreDocumentCoding.encode(written)) == written)
    }

    @Test func unreadableContentsAreKeptUntilQuarantined() async throws {
        let garbage = Data("garbage".utf8)
        let store = InMemoryDocumentStore(contents: garbage)
        #expect(isUnreadable(await #expect(throws: DocumentStoreError.self) { try await store.load() }))
        #expect(isUnreadable(await #expect(throws: DocumentStoreError.self) { try await store.generation() }))
        #expect(isUnreadable(await #expect(throws: DocumentStoreError.self) { try await store.update { _ in } }))
        #expect(await store.quarantinedContents.isEmpty)

        #expect(try await store.quarantineUnreadableDocument() != nil)
        #expect(await store.quarantinedContents == [garbage])
        #expect(try await store.load() == nil)
        #expect(try await store.update { _ in }.generation == 1)
        #expect(try await store.quarantineUnreadableDocument() == nil)
    }

    @Test func newerVersionIsUnsupported() async throws {
        let store = InMemoryDocumentStore(contents: Data(#"{"version":3,"generation":1}"#.utf8))
        await #expect(throws: DocumentStoreError.unsupportedVersion(3)) { try await store.load() }
        await #expect(throws: DocumentStoreError.unsupportedVersion(3)) { try await store.update { _ in } }
    }

    @Test func readableRawContentsDecodeAndGrow() async throws {
        let encoded = try StoreDocumentCoding.encode(Fixtures.richDocument())
        let store = InMemoryDocumentStore(contents: encoded)
        #expect(try await store.generation() == 4)
        #expect(try await store.quarantineUnreadableDocument() == nil)
        #expect(try await store.update { _ in }.generation == 5)
    }

    @Test func concurrentUpdatesNeverLoseAnUpdate() async throws {
        let store = InMemoryDocumentStore()
        try await withThrowingTaskGroup(of: Void.self) { group in
            for index in 0..<50 {
                group.addTask { _ = try await store.update { $0.outbox.append(Fixtures.operation(index)) } }
            }
            try await group.waitForAll()
        }
        let document = try #require(try await store.load())
        #expect(document.generation == 50)
        #expect(document.outbox.count == 50)
    }

    @Test func destroyForgetsTheDocument() async throws {
        let store = InMemoryDocumentStore(document: Fixtures.richDocument())
        try await store.destroy()
        #expect(try await store.load() == nil)
        #expect(try await store.generation() == nil)
    }

    @Test func destroyForgetsWhatWasSetAside() async throws {
        let store = InMemoryDocumentStore(contents: Data("garbage".utf8))
        #expect(try await store.quarantineUnreadableDocument() != nil)
        try await store.destroy()
        #expect(await store.quarantinedContents.isEmpty)
    }

    @Test func destroyAfterACheckKeepsEverythingWhenRefused() async throws {
        let store: any DocumentStore = InMemoryDocumentStore(document: Fixtures.richDocument())
        await #expect(throws: Boom.self) {
            try await store.destroy(after: { if $0?.outbox.isEmpty == false { throw Boom() } })
        }
        #expect(try await store.load()?.outbox.count == 2)
        try await store.destroy(after: { #expect($0?.generation == 4) })
        #expect(try await store.load() == nil)
    }

    @Test func storedAccountIsReadFromUnreadableContentsToo() async throws {
        let account = try #require(Fixtures.richDocument().account)
        let readable: any DocumentStore = InMemoryDocumentStore(document: Fixtures.richDocument())
        #expect(await readable.storedAccount() == account)
        var json = try #require(
            try JSONSerialization.jsonObject(with: StoreDocumentCoding.encode(Fixtures.richDocument())) as? [String: Any]
        )
        json["version"] = 9
        let newer: any DocumentStore = InMemoryDocumentStore(contents: try JSONSerialization.data(withJSONObject: json))
        #expect(await newer.storedAccount() == account)
        #expect(await InMemoryDocumentStore(contents: Data("garbage".utf8)).storedAccount() == nil)
        #expect(await InMemoryDocumentStore().storedAccount() == nil)
    }

    /// Regression: a synchronous implementation would lose to the protocol's
    /// async default, silently refusing to quarantine.
    @Test func storesUseTheirOwnQuarantineThroughTheProtocol() async throws {
        let directory = try makeTemporaryDirectory()
        defer { removeTemporaryDirectory(directory) }
        let url = directory.appendingPathComponent("store.json")
        try Data("garbage".utf8).write(to: url)
        let stores: [any DocumentStore] = [
            InMemoryDocumentStore(contents: Data("garbage".utf8)), FileDocumentStore(fileURL: url),
        ]
        for store in stores {
            #expect(try await store.quarantineUnreadableDocument() != nil)
            #expect(try await store.load() == nil)
        }
    }

    @Test func storesWithoutQuarantineRefuseIt() async {
        let store: any DocumentStore = ReadOnlyStore()
        let error = await #expect(throws: DocumentStoreError.self) { try await store.quarantineUnreadableDocument() }
        #expect(isIO(error))
    }
}

/// A conformer that relies on the protocol's default quarantine.
private struct ReadOnlyStore: DocumentStore {
    func load() async throws(DocumentStoreError) -> StoreDocument? { nil }
    func update(_ transform: @Sendable (inout StoreDocument) throws -> Void) async throws -> StoreDocument {
        throw DocumentStoreError.io("read-only")
    }
    func generation() async throws(DocumentStoreError) -> Int? { nil }
    func destroy() async throws(DocumentStoreError) {}
}

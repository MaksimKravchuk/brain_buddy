import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

/// A `DocumentStore` wrapper whose writes a test can fail or hold at a gate,
/// and which records what it wrote. Everything else goes to `base`.
actor ControlledStore: DocumentStore {
    let base: any DocumentStore

    private(set) var loadCount = 0
    /// Every document a successful `update` returned, in order.
    private(set) var written: [StoreDocument] = []

    private var failure: DocumentStoreError?
    private var isHolding = false
    private var held: [CheckedContinuation<Void, Never>] = []
    private var holdWatchers: [CheckedContinuation<Void, Never>] = []
    private var loadWatchers: [CheckedContinuation<Void, Never>] = []
    private var isHoldingLoads = false
    private var heldLoads: [CheckedContinuation<Void, Never>] = []

    init(_ base: any DocumentStore = InMemoryDocumentStore()) {
        self.base = base
    }

    /// Makes every following write fail with `error` (nil: succeed again).
    func failWrites(with error: DocumentStoreError?) {
        failure = error
    }

    /// Makes following writes wait until `releaseWrites()`.
    func holdWrites() {
        isHolding = true
    }

    func releaseWrites() {
        isHolding = false
        let waiting = held
        held = []
        for continuation in waiting { continuation.resume() }
    }

    /// Returns once a write is waiting at the gate.
    func waitForHeldWrite() async {
        guard held.isEmpty else { return }
        await withCheckedContinuation { holdWatchers.append($0) }
    }

    /// Returns once `load()` has been called `count` times.
    func waitForLoads(_ count: Int) async {
        while loadCount < count {
            await withCheckedContinuation { loadWatchers.append($0) }
        }
    }

    /// Makes following loads read the document, then wait until `releaseLoads()`
    /// before returning it (a read that is overtaken by a write).
    func holdLoads() {
        isHoldingLoads = true
    }

    func releaseLoads() {
        isHoldingLoads = false
        let waiting = heldLoads
        heldLoads = []
        for continuation in waiting { continuation.resume() }
    }

    func load() async throws(DocumentStoreError) -> StoreDocument? {
        loadCount += 1
        let watchers = loadWatchers
        loadWatchers = []
        for watcher in watchers { watcher.resume() }
        let document = try await base.load()
        if isHoldingLoads {
            await withCheckedContinuation { heldLoads.append($0) }
        }
        return document
    }

    func update(_ transform: @Sendable (inout StoreDocument) throws -> Void) async throws -> StoreDocument {
        if isHolding {
            await withCheckedContinuation { continuation in
                held.append(continuation)
                let watchers = holdWatchers
                holdWatchers = []
                for watcher in watchers { watcher.resume() }
            }
        }
        if let failure { throw failure }
        let document = try await base.update(transform)
        written.append(document)
        return document
    }

    func generation() async throws(DocumentStoreError) -> Int? {
        try await base.generation()
    }

    func destroy() async throws(DocumentStoreError) {
        try await base.destroy()
    }

    func destroy(after check: @Sendable (StoreDocument?) throws -> Void) async throws {
        try await base.destroy(after: check)
    }

    func storedAccount() async -> LinkedAccount? {
        await base.storedAccount()
    }

    func quarantineUnreadableDocument() async throws(DocumentStoreError) -> URL? {
        try await base.quarantineUnreadableDocument()
    }
}

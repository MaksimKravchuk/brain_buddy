import BrainBuddyCore
import Foundation

public enum DocumentStoreError: Error, Hashable, Sendable {
    /// The file exists but cannot be decoded. It is never overwritten
    /// implicitly; the user decides (export, reset).
    case unreadable(String)
    /// Written by a newer app version.
    case unsupportedVersion(Int)
    case io(String)
}

extension DocumentStoreError {
    /// A sentence for the UI. The associated values are technical detail.
    public var message: String {
        switch self {
        case .unreadable:
            "The tasks saved on this device can't be read. Nothing has been changed or deleted."
        case .unsupportedVersion:
            "The tasks on this device were saved by a newer version of Brain Buddy. Update the app to open them."
        case .io(let reason):
            "The tasks on this device couldn't be read or saved (\(reason))."
        }
    }
}

/// Durable storage for the one `StoreDocument`. Implementations serialize
/// writers inside the process and, for the file store, across processes
/// (app, widget, App Intents) through an advisory lock.
public protocol DocumentStore: Sendable {
    /// The stored document, or nil when none exists yet.
    func load() async throws(DocumentStoreError) -> StoreDocument?

    /// Reads the latest document under the lock (a fresh one if none exists),
    /// applies `transform`, increments `generation`, and atomically replaces
    /// the file before returning the written document. If `transform` throws,
    /// nothing is written and the error is rethrown.
    func update(
        _ transform: @Sendable (inout StoreDocument) throws -> Void
    ) async throws -> StoreDocument

    /// Cheap check for writes by other processes.
    func generation() async throws(DocumentStoreError) -> Int?

    /// Removes the document (sign-out that discards local data), and any
    /// document set aside by `quarantineUnreadableDocument()`.
    func destroy() async throws(DocumentStoreError)

    /// Removes the document like `destroy()`, but only once `check` accepted
    /// the latest stored document (nil when there is none or it cannot be
    /// read), read under the same lock as the removal so no other process
    /// writes in between. When `check` throws, nothing is removed and its
    /// error propagates. Sign-out uses it to count changes a widget or App
    /// Intent queued that the app has not seen yet.
    func destroy(after check: @Sendable (StoreDocument?) throws -> Void) async throws

    /// The account linked in the stored document, read on its own, so it is
    /// also found in a document that cannot be decoded as a whole (damaged,
    /// or written by a newer version). Nil when there is none, or when not
    /// even that can be read.
    func storedAccount() async -> LinkedAccount?

    /// Sets an unreadable document (`.unreadable` or `.unsupportedVersion`)
    /// aside so the user can start fresh deliberately; the next `update`
    /// then starts from an empty document. Call it only after the user has
    /// confirmed. Returns where the old document now is, or nil when there
    /// was nothing to set aside (no document, or one that reads fine).
    func quarantineUnreadableDocument() async throws(DocumentStoreError) -> URL?
}

extension DocumentStore {
    /// Stores that cannot set a document aside refuse rather than pretend.
    /// A conformer that implements it must declare its version `async`
    /// (as the actors here do): a synchronous one does not replace this
    /// default, because async callers prefer the async overload.
    public func quarantineUnreadableDocument() async throws(DocumentStoreError) -> URL? {
        throw .io("this store cannot set an unreadable document aside")
    }

    /// Check, then remove: without a lock, another writer can land in between.
    public func destroy(after check: @Sendable (StoreDocument?) throws -> Void) async throws {
        let current: StoreDocument?
        do {
            current = try await load()
        } catch {
            current = nil
        }
        try check(current)
        try await destroy()
    }

    /// The account of a document that decodes; nil otherwise.
    public func storedAccount() async -> LinkedAccount? {
        do {
            return try await load()?.account
        } catch {
            return nil
        }
    }
}

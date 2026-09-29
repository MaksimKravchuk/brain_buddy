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

    /// Removes the document (sign-out that discards local data).
    func destroy() async throws(DocumentStoreError)

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
}

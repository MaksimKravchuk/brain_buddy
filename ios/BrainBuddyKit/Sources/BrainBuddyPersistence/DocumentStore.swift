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
}

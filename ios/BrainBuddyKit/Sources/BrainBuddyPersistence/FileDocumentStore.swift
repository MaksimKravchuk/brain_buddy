import BrainBuddyCore
import Foundation

/// The `StoreDocument` as one JSON file, shared by the app, its widgets and
/// App Intents (each in its own process) through an App Group container.
///
/// - Writes are read-modify-write under an exclusive advisory lock on a
///   sibling `.<name>.lock` file: the latest file is read (never a cached
///   copy, since another process may have written), transformed, written to
///   a temporary file, flushed, and renamed over the document.
/// - Reads (`load`, `generation`) take no lock; the rename makes every read
///   see a whole document.
/// - A file that exists but cannot be decoded is never overwritten or
///   deleted implicitly: `load` and `update` throw `.unreadable` (or
///   `.unsupportedVersion`) until the user chooses
///   `quarantineUnreadableDocument()` or `destroy()`.
/// - The directory is created 0700, the file is 0600, and on iOS the file is
///   `completeUntilFirstUserAuthentication` so extensions can read it while
///   the phone is locked.
///
/// The lock is held only inside one synchronous stretch of `update`,
/// `destroy` or `quarantineUnreadableDocument`, never across a suspension,
/// so keep `transform` short. On iOS each of those stretches runs inside an
/// expiring-activity assertion (`ExpiringActivity`), so the process is not
/// suspended while it holds the lock, whoever the writer is (the app, the
/// sync engine, a widget or an App Intent).
public actor FileDocumentStore: DocumentStore {
    /// The document file.
    public nonisolated let fileURL: URL
    let file: DocumentFile

    /// `fileURL` must be a file URL. Its directory is created on the first write.
    public init(fileURL: URL) {
        precondition(fileURL.isFileURL, "FileDocumentStore needs a file URL, got \(fileURL)")
        file = DocumentFile(url: fileURL)
        self.fileURL = file.url
    }

    /// The sibling file every writer locks.
    public nonisolated var lockURL: URL { file.lockURL }

    public func load() async throws(DocumentStoreError) -> StoreDocument? {
        guard let data = try file.readContents() else { return nil }
        return try StoreDocumentCoding.decode(data)
    }

    public func update(
        _ transform: @Sendable (inout StoreDocument) throws -> Void
    ) async throws -> StoreDocument {
        let activity = ExpiringActivity(reason: "Saving your changes")
        defer { activity.end() }
        try file.createDirectoryIfNeeded()
        let lock = try file.lock()
        defer { lock.release() }
        var current: StoreDocument?
        if let data = try file.readContents() {
            current = try StoreDocumentCoding.decode(data)
        }
        let (data, written) = try StoreDocumentCoding.prepareWrite(from: current, transform)
        try file.replaceContents(with: data)
        return written
    }

    public func generation() async throws(DocumentStoreError) -> Int? {
        guard let data = try file.readContents() else { return nil }
        return try StoreDocumentCoding.generation(of: data)
    }

    /// Removes the document, its lock file and every document set aside by
    /// `quarantineUnreadableDocument()`, readable or not.
    public func destroy() async throws(DocumentStoreError) {
        guard file.directoryExists() else { return }
        let activity = ExpiringActivity(reason: "Removing your data")
        defer { activity.end() }
        let lock = try file.lock()
        defer { lock.release() }
        try file.removeAll()
    }

    public func destroy(after check: @Sendable (StoreDocument?) throws -> Void) async throws {
        guard file.directoryExists() else { return try check(nil) }
        let activity = ExpiringActivity(reason: "Removing your data")
        defer { activity.end() }
        let lock = try file.lock()
        defer { lock.release() }
        let current = try file.readContents().flatMap { try? StoreDocumentCoding.decode($0) }
        try check(current)
        try file.removeAll()
    }

    public func storedAccount() async -> LinkedAccount? {
        guard let data = try? file.readContents() else { return nil }
        return StoreDocumentCoding.linkedAccount(in: data)
    }

    /// Renames an unreadable document to `<name>.unreadable-<UTC time>.json`
    /// in the same directory and returns that URL (to export or share). A
    /// document that reads fine is left alone and the result is nil.
    public func quarantineUnreadableDocument() async throws(DocumentStoreError) -> URL? {
        guard file.directoryExists() else { return nil }
        let activity = ExpiringActivity(reason: "Setting your data aside")
        defer { activity.end() }
        let lock = try file.lock()
        defer { lock.release() }
        guard let data = try file.readContents() else { return nil }
        if (try? StoreDocumentCoding.decode(data)) != nil { return nil }
        return try file.moveAside(stampedAt: Date())
    }
}

// MARK: Locations

extension FileDocumentStore {
    /// The document's file name inside `directoryName`.
    public static let defaultFileName = "store.json"
    /// The folder the app keeps its document in.
    public static let directoryName = "BrainBuddy"

    #if canImport(Darwin)
    /// `<App Group container>/Library/Application Support/BrainBuddy/store.json`,
    /// the location the app, its widgets and App Intents share. Nil when the
    /// App Group is not available to this process (missing entitlement).
    public static func appGroupDocumentURL(appGroupID: String, fileName: String = defaultFileName) -> URL? {
        guard let container = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupID)
        else { return nil }
        return container
            .appendingPathComponent("Library", isDirectory: true)
            .appendingPathComponent("Application Support", isDirectory: true)
            .appendingPathComponent(directoryName, isDirectory: true)
            .appendingPathComponent(fileName, isDirectory: false)
    }
    #endif

    /// `<Application Support>/BrainBuddy/store.json` in this process's own
    /// container: the fallback when there is no App Group (extensions cannot
    /// see it), and the location on Linux.
    public static func applicationSupportDocumentURL(fileName: String = defaultFileName) -> URL {
        // Never a temporary directory: the system may empty it.
        let support =
            FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory(), isDirectory: true)
        return support
            .appendingPathComponent(directoryName, isDirectory: true)
            .appendingPathComponent(fileName, isDirectory: false)
    }
}

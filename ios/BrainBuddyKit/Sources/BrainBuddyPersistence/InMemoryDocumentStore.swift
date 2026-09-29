import BrainBuddyCore
import Foundation

/// A `DocumentStore` in memory, for tests and SwiftUI previews. It behaves
/// like `FileDocumentStore` in everything but durability: `update` increments
/// `generation`, writes nothing when the transform throws, and returns the
/// document as it would read back from disk (the same JSON round trip, so
/// dates are rounded to microseconds exactly as on disk). Seed it with raw
/// `contents` to exercise the unreadable and unsupported-version paths.
public actor InMemoryDocumentStore: DocumentStore {
    private enum Contents: Sendable {
        case document(StoreDocument)
        /// Bytes as a file would hold them, decoded on every read.
        case bytes(Data)
    }

    private var contents: Contents?

    /// What `quarantineUnreadableDocument()` has set aside, oldest first.
    public private(set) var quarantinedContents: [Data] = []

    /// A store holding `document`, or empty. The seed is kept as given.
    public init(document: StoreDocument? = nil) {
        contents = document.map(Contents.document)
    }

    /// A store whose "file" holds `contents` verbatim, for example bytes that
    /// are not JSON or a document written by a newer version.
    public init(contents: Data) {
        self.contents = .bytes(contents)
    }

    public func load() async throws(DocumentStoreError) -> StoreDocument? {
        switch contents {
        case nil: return nil
        case .document(let document)?: return document
        case .bytes(let data)?: return try StoreDocumentCoding.decode(data)
        }
    }

    public func update(
        _ transform: @Sendable (inout StoreDocument) throws -> Void
    ) async throws -> StoreDocument {
        let current = try await load()
        let (_, written) = try StoreDocumentCoding.prepareWrite(from: current, transform)
        contents = .document(written)
        return written
    }

    public func generation() async throws(DocumentStoreError) -> Int? {
        switch contents {
        case nil: return nil
        case .document(let document)?: return document.generation
        case .bytes(let data)?: return try StoreDocumentCoding.generation(of: data)
        }
    }

    /// Forgets the document and whatever was set aside, like the file store.
    public func destroy() async throws(DocumentStoreError) {
        contents = nil
        quarantinedContents = []
    }

    public func destroy(after check: @Sendable (StoreDocument?) throws -> Void) async throws {
        let current: StoreDocument? =
            switch contents {
            case nil: nil
            case .document(let document)?: document
            case .bytes(let data)?: try? StoreDocumentCoding.decode(data)
            }
        try check(current)
        contents = nil
        quarantinedContents = []
    }

    public func storedAccount() async -> LinkedAccount? {
        switch contents {
        case nil: nil
        case .document(let document)?: document.account
        case .bytes(let data)?: StoreDocumentCoding.linkedAccount(in: data)
        }
    }

    /// Moves unreadable contents to `quarantinedContents` and returns a
    /// placeholder URL; nil when there is nothing unreadable to set aside.
    public func quarantineUnreadableDocument() async throws(DocumentStoreError) -> URL? {
        guard case .bytes(let data)? = contents, (try? StoreDocumentCoding.decode(data)) == nil else { return nil }
        quarantinedContents.append(data)
        contents = nil
        return URL(fileURLWithPath: "/in-memory/store.unreadable-\(quarantinedContents.count).json")
    }
}

import Foundation

/// A command applied on this device that the server has not acknowledged yet.
public struct PendingOperation: Identifiable, Hashable, Sendable, Codable {
    public var id: UUID
    public var command: GTDCommand
    /// When the user issued it. Replays use this as "now".
    public var issuedAt: Date
    /// Sent as `Idempotency-Key`. Kept while the request body is unchanged so a
    /// retry after an uncertain failure cannot apply twice; replaced whenever the
    /// body changes (for example a new `expected_revision` after a conflict).
    public var idempotencyKey: UUID
    public var attempts: Int
    /// First send with the current key. The server keeps keys for 24 hours.
    public var firstAttemptAt: Date?
    public var lastAttemptAt: Date?
    public var lastError: String?
    /// Sticky: some request for this operation may have reached the server,
    /// under this or an earlier key. A new key (after a conflict, or while a
    /// request is still in flight) resets `attempts`, never this.
    public var everSent: Bool

    public init(
        id: UUID = UUID(), command: GTDCommand, issuedAt: Date, idempotencyKey: UUID = UUID(),
        attempts: Int = 0, firstAttemptAt: Date? = nil, lastAttemptAt: Date? = nil, lastError: String? = nil,
        everSent: Bool = false
    ) {
        self.id = id
        self.command = command
        self.issuedAt = issuedAt
        self.idempotencyKey = idempotencyKey
        self.attempts = attempts
        self.firstAttemptAt = firstAttemptAt
        self.lastAttemptAt = lastAttemptAt
        self.lastError = lastError
        self.everSent = everSent
    }

    /// True once a request may have reached the server; such an operation must
    /// never be folded into another one.
    public var hasBeenSent: Bool { attempts > 0 || everSent }
}

extension PendingOperation {
    private enum CodingKeys: String, CodingKey {
        case id, command, issuedAt, idempotencyKey, attempts, firstAttemptAt, lastAttemptAt, lastError, everSent
    }

    /// Documents written before `everSent` existed decode with it false.
    public init(from decoder: any Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(UUID.self, forKey: .id)
        command = try values.decode(GTDCommand.self, forKey: .command)
        issuedAt = try values.decode(Date.self, forKey: .issuedAt)
        idempotencyKey = try values.decode(UUID.self, forKey: .idempotencyKey)
        attempts = try values.decode(Int.self, forKey: .attempts)
        firstAttemptAt = try values.decodeIfPresent(Date.self, forKey: .firstAttemptAt)
        lastAttemptAt = try values.decodeIfPresent(Date.self, forKey: .lastAttemptAt)
        lastError = try values.decodeIfPresent(String.self, forKey: .lastError)
        everSent = try values.decodeIfPresent(Bool.self, forKey: .everSent) ?? false
    }

    /// `everSent` is written only when true, so other documents keep their bytes.
    public func encode(to encoder: any Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(id, forKey: .id)
        try values.encode(command, forKey: .command)
        try values.encode(issuedAt, forKey: .issuedAt)
        try values.encode(idempotencyKey, forKey: .idempotencyKey)
        try values.encode(attempts, forKey: .attempts)
        try values.encodeIfPresent(firstAttemptAt, forKey: .firstAttemptAt)
        try values.encodeIfPresent(lastAttemptAt, forKey: .lastAttemptAt)
        try values.encodeIfPresent(lastError, forKey: .lastError)
        if everSent { try values.encode(everSent, forKey: .everSent) }
    }
}

/// A local change that could not be applied on the server and was set aside.
public struct SyncIssue: Identifiable, Hashable, Sendable, Codable {
    public var id: UUID
    public var command: GTDCommand
    public var message: String
    public var referenceID: String?
    public var occurredAt: Date

    public init(id: UUID = UUID(), command: GTDCommand, message: String, referenceID: String? = nil, occurredAt: Date) {
        self.id = id
        self.command = command
        self.message = message
        self.referenceID = referenceID
        self.occurredAt = occurredAt
    }
}

public struct LinkedAccount: Hashable, Sendable, Codable {
    public var id: String
    public var email: String
    public var displayName: String?
    /// API base, for example `https://brain-buddy-frontend.fly.dev/api`.
    public var serverURL: URL
    public var linkedAt: Date

    public init(id: String, email: String, displayName: String? = nil, serverURL: URL, linkedAt: Date) {
        self.id = id
        self.email = email
        self.displayName = displayName
        self.serverURL = serverURL
        self.linkedAt = linkedAt
    }
}

public struct SyncMetadata: Hashable, Sendable, Codable {
    public var lastPullAt: Date?
    public var lastPushAt: Date?
    public var lastFailure: String?
    public init(lastPullAt: Date? = nil, lastPushAt: Date? = nil, lastFailure: String? = nil) {
        self.lastPullAt = lastPullAt
        self.lastPushAt = lastPushAt
        self.lastFailure = lastFailure
    }
}

/// Everything persisted on the device, in one atomically replaced file.
/// The current state is derived: `OutboxReplayer.replay(outbox, onto: base)`.
/// Without a linked account `base` stays empty and the (compacted) outbox is
/// the user's data; linking an account uploads it.
public struct StoreDocument: Hashable, Sendable, Codable {
    public static let currentVersion = 1

    public var version: Int
    /// Incremented on every write, by any process sharing the file.
    public var generation: Int
    public var base: GTDState
    public var outbox: [PendingOperation]
    public var issues: [SyncIssue]
    public var account: LinkedAccount?
    public var sync: SyncMetadata

    public init(
        version: Int = StoreDocument.currentVersion, generation: Int = 0, base: GTDState = .empty,
        outbox: [PendingOperation] = [], issues: [SyncIssue] = [], account: LinkedAccount? = nil,
        sync: SyncMetadata = SyncMetadata()
    ) {
        self.version = version
        self.generation = generation
        self.base = base
        self.outbox = outbox
        self.issues = issues
        self.account = account
        self.sync = sync
    }
}

/// What the UI shows about synchronization. Status is always words, never a
/// colour alone (design system accessibility rule).
public enum SyncStatus: Hashable, Sendable {
    /// No account: everything lives on this device.
    case localOnly
    case idle(lastSyncedAt: Date?)
    case syncing
    /// The server is unreachable; changes are kept and sent later.
    case offline(lastSyncedAt: Date?)
    /// The session expired; changes are kept until the user signs in again.
    case needsSignIn
    case failing(message: String, referenceID: String?, lastSyncedAt: Date?)
}

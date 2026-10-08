import Foundation

/// The pre-021 Mac store, `local-gtd.json`, as `LocalGTDStore` wrote it (data-model E10). Input
/// only: nothing here is ever written. Fields the old app always wrote are required, so a file
/// missing one is damaged (`corrupt`); everything else decodes as leniently as the old app read it.
package struct LegacySnapshot: Decodable, Sendable {
    package var version: Int
    package var generation: Int
    package var tasks: [Task]
    package var projects: [Project]
    package var tags: [Tag]
    package var idempotency: [String: String]
    package var idempotencyReceipts: [String: IdempotencyReceipt]?
    package var waitingReviews: [String: TaskReviewReceipt]?
    package var somedayReviews: [String: TaskReviewReceipt]?

    package struct IdempotencyReceipt: Decodable, Sendable {
        package var fingerprint: String
    }

    package struct TaskReviewReceipt: Decodable, Sendable {
        package var taskRevision: Int
        package var reviewedAt: String
    }

    package struct Task: Decodable, Sendable {
        package var id: String
        package var title: String
        package var details: String?
        package var state: String
        package var lastOpenState: String?
        package var revision: Int
        package var projectID: String?
        package var tagIDs: [String]
        package var dueDate: String?
        package var priority: String
        package var waitingFor: String?
        package var waitingSince: String?
        package var completedAt: String?
        package var cancelledAt: String?
        package var orderKey: Int
        package var createdAt: String
        package var subtasks: [Subtask]
        package var comments: [Comment]
    }

    package struct Subtask: Decodable, Sendable {
        package var id: String
        package var title: String
        package var state: String
        package var orderKey: Int
        package var revision: Int
    }

    package struct Comment: Decodable, Sendable {
        package var id: String
        package var body: String
        package var actorID: String
        package var createdAt: String
        package var editedAt: String?
        package var revision: Int
    }

    package struct Project: Decodable, Sendable {
        package var id: String
        package var name: String
        package var color: String?
        package var state: String
        package var revision: Int
        package var desiredOutcome: String?
        package var lastReviewedAt: String?
        package var lastReviewDecision: String?
        package var lastReviewedTaskSignature: String?
    }

    package struct Tag: Decodable, Sendable {
        package var id: String
        package var name: String
        package var state: String
        package var revision: Int
    }

    /// Why a file could not be read as a legacy snapshot.
    package enum ReadError: Error, Hashable, Sendable {
        /// The JSON does not decode, or a required field is missing: the file itself is damaged.
        case corrupt
        /// Written by a newer version (`version > 1`).
        case newerVersion
    }

    /// Reads `data`: the version first, so a newer file is never called damaged, then the rest.
    package static func read(_ data: Data) throws(ReadError) -> LegacySnapshot {
        struct Header: Decodable { var version: Int }
        guard let header = try? JSONDecoder().decode(Header.self, from: data) else { throw .corrupt }
        guard header.version <= 1 else { throw .newerVersion }
        guard header.version == 1, let snapshot = try? JSONDecoder().decode(LegacySnapshot.self, from: data) else {
            throw .corrupt
        }
        return snapshot
    }

    /// The old store's timestamps: `ISO8601DateFormatter().string(from:)`, whole seconds, UTC.
    package static func date(_ text: String?) -> Date? {
        guard let text else { return nil }
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: text) { return date }
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter.date(from: text)
    }
}

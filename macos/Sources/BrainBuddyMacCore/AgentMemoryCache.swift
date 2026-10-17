import Foundation

/// A cached value that carries run content and so expires (030-FR-027).
package protocol AgentCacheExpiring: Sendable {
    var contentExpiresAt: Date? { get }
}

package enum AgentCacheBucket: Hashable, Sendable { case run, summary, connection }

package enum AgentCacheLookup<Value: Sendable>: Sendable {
    case hit(Value), expired, miss
}

/// Agent data held only in memory, for one signed-in account (030-FR-026, 030-FR-027). Nothing here
/// is `Codable` and nothing is logged or written. A write for another account is refused, and a
/// value past `contentExpiresAt` is dropped on the read that finds it, online or not.
@MainActor
package final class AgentMemoryCache {
    private var owner: String?
    private var values: [AgentCacheBucket: [String: any Sendable]] = [:]
    private var drafts: [String: String] = [:]
    private var expiredIDs: Set<String> = []

    package init(owner: String? = nil) { self.owner = owner }

    /// Sign-out, session end and account change: drop everything.
    package func clear() {
        (values, drafts, expiredIDs) = ([:], [:], [])
    }

    /// Follows the signed-in account; a different one (or none) empties the cache first.
    package func bind(owner new: String?) {
        if new != owner { clear() }
        owner = new
    }

    /// False, and nothing stored, when `owner` is not the bound account.
    @discardableResult
    package func put<Value: Sendable>(_ value: Value, id: String, bucket: AgentCacheBucket, owner: String) -> Bool {
        guard owner == self.owner else { return false }
        values[bucket, default: [:]][id] = value
        expiredIDs.remove(id)
        return true
    }

    package func get<Value: Sendable>(
        _ type: Value.Type, id: String, bucket: AgentCacheBucket, now: Date
    ) -> AgentCacheLookup<Value> {
        guard let stored = values[bucket]?[id] else { return expiredIDs.contains(id) ? .expired : .miss }
        if let expiring = stored as? any AgentCacheExpiring, let at = expiring.contentExpiresAt, now >= at {
            values[bucket]?[id] = nil
            drafts[id] = nil
            expiredIDs.insert(id)
            return .expired
        }
        return (stored as? Value).map { .hit($0) } ?? .miss
    }

    package func setDraft(_ text: String, runID: String, owner: String) {
        guard owner == self.owner else { return }
        drafts[runID] = text.isEmpty ? nil : text
    }

    package func draft(runID: String) -> String? { drafts[runID] }
}

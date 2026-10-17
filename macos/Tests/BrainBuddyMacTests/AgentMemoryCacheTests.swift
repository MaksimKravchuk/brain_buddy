import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyMacCore

private struct CachedRun: AgentCacheExpiring, Equatable {
    var title: String
    var contentExpiresAt: Date?
}

@MainActor
@Suite("030 Agent memory cache")
struct AgentMemoryCacheTests {
    private let now = Date(timeIntervalSince1970: 2_000_000)

    private func make(owner: String = "user_max") -> AgentMemoryCache { AgentMemoryCache(owner: owner) }

    private func run(_ cache: AgentMemoryCache, _ id: String = "run_1", at date: Date? = nil) -> AgentCacheLookup<CachedRun> {
        cache.get(CachedRun.self, id: id, bucket: .run, now: date ?? now)
    }

    @Test("030_FR_026 clear drops runs, summaries, connections and drafts")
    func clearDropsEverything() {
        let cache = make()
        cache.put(CachedRun(title: "t", contentExpiresAt: nil), id: "run_1", bucket: .run, owner: "user_max")
        cache.put("Running", id: "task_1", bucket: .summary, owner: "user_max")
        cache.put("Hermes", id: "conn_1", bucket: .connection, owner: "user_max")
        cache.setDraft("my answer", runID: "run_1", owner: "user_max")
        cache.clear()
        guard case .miss = run(cache) else { Issue.record("run survived clear()"); return }
        guard case .miss = cache.get(String.self, id: "task_1", bucket: .summary, now: now) else {
            Issue.record("summary survived clear()"); return
        }
        guard case .miss = cache.get(String.self, id: "conn_1", bucket: .connection, now: now) else {
            Issue.record("connection survived clear()"); return
        }
        #expect(cache.draft(runID: "run_1") == nil)
    }

    @Test("030_FR_026 a write for another account is refused")
    func refusesAnotherOwner() {
        let cache = make()
        let stored = cache.put(CachedRun(title: "t", contentExpiresAt: nil), id: "run_1", bucket: .run, owner: "user_other")
        #expect(!stored)
        cache.setDraft("x", runID: "run_1", owner: "user_other")
        #expect(cache.draft(runID: "run_1") == nil)
        guard case .miss = run(cache) else { Issue.record("another account's run was stored"); return }
    }

    @Test("030_FR_026 binding another account, or none, empties the cache")
    func bindingAnotherAccountClears() {
        let cache = make()
        cache.put(CachedRun(title: "t", contentExpiresAt: nil), id: "run_1", bucket: .run, owner: "user_max")
        cache.bind(owner: "user_max")
        guard case .hit = run(cache) else { Issue.record("same account must keep its runs"); return }
        cache.bind(owner: nil)
        guard case .miss = run(cache) else { Issue.record("sign-out must clear"); return }
        let stored = cache.put(CachedRun(title: "t", contentExpiresAt: nil), id: "run_1", bucket: .run, owner: "user_max")
        #expect(!stored, "an unbound cache accepts nothing")
    }

    @Test("030_FR_027 content is dropped and marked expired once now reaches contentExpiresAt, with no network")
    func expiredContentIsDropped() {
        let cache = make()
        let expiry = now.addingTimeInterval(60)
        cache.put(CachedRun(title: "secret", contentExpiresAt: expiry), id: "run_1", bucket: .run, owner: "user_max")
        cache.setDraft("draft", runID: "run_1", owner: "user_max")
        guard case .hit(let live) = run(cache, at: expiry.addingTimeInterval(-1)) else { Issue.record("not yet expired"); return }
        #expect(live.title == "secret")
        guard case .expired = run(cache, at: expiry) else { Issue.record("now == expiry must be expired"); return }
        guard case .expired = run(cache, at: now) else { Issue.record("the content must stay dropped"); return }
        #expect(cache.draft(runID: "run_1") == nil)
    }

    @Test("030_FR_027 a value without an expiry never expires")
    func noExpiryNeverExpires() {
        let cache = make()
        cache.put(CachedRun(title: "t", contentExpiresAt: nil), id: "run_1", bucket: .run, owner: "user_max")
        guard case .hit = run(cache, at: .distantFuture) else { Issue.record("expected a hit"); return }
    }

    @Test("030_SC_005 nothing in the cache is Codable")
    func nothingIsCodable() {
        let types: [Any.Type] = [AgentMemoryCache.self, AgentCacheBucket.self, AgentCacheLookup<String>.self]
        for type in types { #expect(!(type is any Codable.Type), "\(type) must not be Codable") }
    }

    @Test("030_FR_039 no title, agent name, address, question, secret or password reaches a log line")
    func logsCarryNoContent() async {
        let known = ["Call Sam about the van", "Hermes", "hermes.myhost.dev", "Which card holds?", "sk-secret-123", "hunter2-password"]
        let log = CapturingMacLog()
        let account = AccountFixtures.account()
        let model = AgentAvailability(account: account, remote: { _ in FakeAvailabilityRemote() }, log: log)
        let cache = make()
        for (index, value) in known.enumerated() {
            cache.put(CachedRun(title: value, contentExpiresAt: nil), id: "run_\(index)", bucket: .run, owner: account.id)
            cache.setDraft(value, runID: "run_\(index)", owner: account.id)
        }
        await model.refresh()
        await model.relayUnavailable()
        cache.clear()
        let lines = log.messages().joined(separator: "\n")
        #expect(!lines.isEmpty, "availability does log its stage and outcome")
        for value in known { #expect(!lines.contains(value), "\(value) leaked into a log line") }
        #expect(!lines.contains(account.email) && !lines.contains(account.id))
    }
}

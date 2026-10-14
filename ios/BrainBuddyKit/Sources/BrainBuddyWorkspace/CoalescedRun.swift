import Foundation

/// Single-flight, latest-wins: any number of `request()`s while the body runs lead to exactly one
/// more run after it, never one run per request.
@MainActor
final class CoalescedRun {
    private let body: @MainActor () async -> Void
    private var requested: UInt64 = 0
    private var completed: UInt64 = 0
    private var task: Task<Void, Never>?

    init(_ body: @escaping @MainActor () async -> Void) { self.body = body }

    var isRunning: Bool { task != nil }

    func request() {
        requested &+= 1
        guard task == nil else { return }
        task = Task { [weak self] in
            while let self, self.completed != self.requested {
                let target = self.requested
                await self.body()
                self.completed = target
            }
            self?.task = nil
        }
    }

    /// Returns once nothing is running or pending.
    func settle() async {
        while let task { await task.value }
    }
}

import Foundation

/// One dedicated thread that runs a workspace's blocking bridge calls, so they never park a
/// cooperative-pool thread while they wait on the store's single lock (the bridge serializes
/// every call on one connection anyway, so one thread loses no parallelism).
///
/// Two lanes: `urgent` work (the commit and the reads a save depends on) runs before any queued
/// `normal` work (query refreshes), so a refresh that is only waiting its turn never delays the
/// next write. A running call is never interrupted. Each lane is first-in first-out.
final class RustBridgeExecutor: Sendable {
    enum Lane: Sendable { case urgent, normal }

    private let queue = Queue()

    init() {
        let queue = queue
        let thread = Thread { queue.run() }
        thread.name = "app.brainbuddy.rust-bridge"
        thread.qualityOfService = .userInitiated
        thread.stackSize = 4 << 20
        thread.start()
    }

    deinit { queue.shutdown() }

    /// Runs `work` on the executor's thread and resumes with its outcome.
    func run<T: Sendable>(lane: Lane = .normal, _ work: @escaping @Sendable () throws -> T) async
        -> Result<T, RustBridgeError> {
        await withCheckedContinuation { continuation in
            queue.enqueue(lane) {
                do { continuation.resume(returning: .success(try work())) }
                catch { continuation.resume(returning: .failure(RustBridgeError(thrown: error))) }
            }
        }
    }

    /// Shared with the thread only; the executor object itself is not retained by it, so
    /// dropping the executor ends the thread.
    // Safe: every field is read and written under `condition`.
    private final class Queue: @unchecked Sendable {
        private let condition = NSCondition()
        private var urgent: [@Sendable () -> Void] = []
        private var normal: [@Sendable () -> Void] = []
        private var closed = false

        func enqueue(_ lane: Lane, _ job: @escaping @Sendable () -> Void) {
            condition.lock()
            if closed {
                condition.unlock()
                job()  // the executor is gone: run inline rather than strand the caller
                return
            }
            if lane == .urgent { urgent.append(job) } else { normal.append(job) }
            condition.signal()
            condition.unlock()
        }

        func shutdown() {
            condition.lock()
            closed = true
            condition.broadcast()
            condition.unlock()
        }

        func run() {
            while true {
                condition.lock()
                while urgent.isEmpty, normal.isEmpty, !closed { condition.wait() }
                let job: (@Sendable () -> Void)?
                if !urgent.isEmpty { job = urgent.removeFirst() }
                else if !normal.isEmpty { job = normal.removeFirst() }
                else { job = nil }
                condition.unlock()
                guard let job else { return }
                job()
            }
        }
    }
}

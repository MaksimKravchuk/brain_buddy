import Foundation

/// Launch step 1 (contracts/mac-app-host.md §1; research R6): one Brain Buddy process per folder.
/// The running copy holds an exclusive, non-blocking `flock` on `.instance.lock` for its lifetime;
/// the kernel drops it when the process ends, so a crash never leaves a stale lock. A second copy
/// asks the first to come forward and quits; only when that is not possible it shows design X-08.
package final class SingleInstanceGuard: Sendable {
    package static let lockFileName = ".instance.lock"

    /// Design X-08, a standard alert with one button.
    package enum AlreadyOpen {
        package static let title = "Brain Buddy is already open."
        package static let message = "Switch to the open window to keep working."
        package static let button = "OK"
    }

    package enum Claim: Sendable {
        /// This process is the only copy; keep the guard for the process lifetime.
        case owner(SingleInstanceGuard)
        /// Another copy runs. `broughtForward` is false when X-08 was shown instead.
        case secondCopy(broughtForward: Bool)
    }

    private let lock: FileLock

    private init(lock: FileLock) { self.lock = lock }

    /// The lock, or nil when another process holds it. The owner writes its process id into the
    /// lock file, so a second copy can bring exactly this process forward (a dry run in another
    /// folder is a different copy with a different lock).
    package static func acquire(directory: URL) throws -> SingleInstanceGuard? {
        try MacFiles.createDirectory(directory)
        guard let lock = try FileLock.tryAcquire(directory.appendingPathComponent(lockFileName)) else { return nil }
        try? lock.replaceContents(with: Data("\(getpid())\n".utf8))
        return SingleInstanceGuard(lock: lock)
    }

    /// The process id the running copy recorded, when it is readable.
    package static func ownerProcessID(directory: URL) -> Int32? {
        guard let data = try? MacFiles.contents(of: directory.appendingPathComponent(lockFileName)),
            let text = String(data: data, encoding: .utf8)
        else { return nil }
        return Int32(text.trimmingCharacters(in: .whitespacesAndNewlines))
    }

    /// Takes the lock, or hands off to the copy that has it: `bringOtherForward` activates the
    /// process the lock names (nil when unreadable) and returns false when that is impossible; only
    /// then `presentAlreadyOpen` shows X-08.
    package static func claim(
        directory: URL, bringOtherForward: (Int32?) -> Bool, presentAlreadyOpen: () -> Void,
        log: any MacLogSink = SystemMacLog()
    ) throws -> Claim {
        if let owner = try acquire(directory: directory) {
            log.log(.instance, "instance lock acquired")
            return .owner(owner)
        }
        if bringOtherForward(ownerProcessID(directory: directory)) {
            log.log(.instance, "second copy handed off")
            return .secondCopy(broughtForward: true)
        }
        log.log(.instance, "second copy could not reach the first")
        presentAlreadyOpen()
        return .secondCopy(broughtForward: false)
    }

    /// Ends the claim (tests; the app keeps it until it exits).
    package func release() { lock.release() }
}

import Foundation
import Synchronization

#if canImport(Darwin)
    import Darwin
#elseif canImport(Glibc)
    import Glibc
#endif

/// A file operation that failed. It names the operation and the `errno`, never a path or a file
/// name, so it can be logged by class (FR-030).
package struct MacFileError: Error, Hashable, Sendable, CustomStringConvertible {
    package var operation: String
    package var code: Int32

    package init(_ operation: String, code: Int32 = errno) {
        self.operation = operation
        self.code = code
    }

    package var description: String { "\(operation) failed (errno \(code))" }
    /// The destination of an exclusive rename exists.
    package var isAlreadyExists: Bool { code == EEXIST }
}

/// Injected failures of `MacFiles` operations, for tests: a disk that is full, a folder that
/// refuses a rename. A fault applies to files directly in one folder whose name starts with a
/// prefix, so tests in their own temporary folders never see each other's faults. Nothing in the
/// app injects one; with none injected, `check` only reads an empty list.
package enum MacFileFaults {
    package enum Operation: String, Sendable {
        case read, write, rename, remove
    }

    private struct Fault: Sendable {
        var id: UUID
        var operation: Operation
        var folder: String
        var namePrefix: String
        var code: Int32
    }

    private static let faults = Mutex<[Fault]>([])

    /// Makes `operation` on files in `folder` named `namePrefix…` fail with `code` until `clear`.
    @discardableResult
    package static func inject(
        _ operation: Operation, in folder: URL, namePrefix: String = "", code: Int32 = ENOSPC
    ) -> UUID {
        let fault = Fault(
            id: UUID(), operation: operation, folder: folder.standardizedFileURL.path, namePrefix: namePrefix, code: code
        )
        faults.withLock { $0.append(fault) }
        return fault.id
    }

    package static func clear(_ id: UUID) {
        faults.withLock { $0.removeAll { $0.id == id } }
    }

    static func check(_ operation: Operation, _ url: URL) throws {
        let folder = url.deletingLastPathComponent().standardizedFileURL.path
        let name = url.lastPathComponent
        let code = faults.withLock { faults in
            faults.first { $0.operation == operation && $0.folder == folder && name.hasPrefix($0.namePrefix) }?.code
        }
        if let code { throw MacFileError(operation.rawValue, code: code) }
    }
}

/// The POSIX steps the Mac's own files need: durable atomic writes, exclusive renames that never
/// replace a file, and the two kinds of lock (`flock` for the 021 files, `lockf` for the pre-021
/// store's protocol).
package enum MacFiles {
    package static func exists(_ url: URL) -> Bool {
        access(url.path, F_OK) == 0
    }

    /// Creates `directory` (and parents) as 0700 when it is missing; an existing one is left as is.
    package static func createDirectory(_ directory: URL) throws {
        var isDirectory: ObjCBool = false
        if FileManager.default.fileExists(atPath: directory.path, isDirectory: &isDirectory), isDirectory.boolValue {
            return
        }
        do {
            try FileManager.default.createDirectory(
                at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700]
            )
        } catch {
            throw MacFileError("create folder", code: EIO)
        }
    }

    /// The whole file, or nil when it does not exist.
    package static func contents(of url: URL) throws -> Data? {
        try MacFileFaults.check(.read, url)
        let descriptor = open(url.path, O_RDONLY | O_CLOEXEC)
        guard descriptor >= 0 else {
            if errno == ENOENT { return nil }
            throw MacFileError("open")
        }
        defer { close(descriptor) }
        var contents = Data()
        var chunk = [UInt8](repeating: 0, count: 64 * 1024)
        while true {
            let count = chunk.withUnsafeMutableBytes { read(descriptor, $0.baseAddress, $0.count) }
            if count == 0 { return contents }
            if count < 0 {
                if errno == EINTR { continue }
                throw MacFileError("read")
            }
            contents.append(contentsOf: chunk[0..<count])
        }
    }

    /// Writes `data` to a new temporary file beside `url` (0600), flushes it to storage, renames
    /// it over `url` and flushes the folder: a reader sees the old file or the new one, never a mix.
    package static func writeAtomically(_ data: Data, to url: URL) throws {
        try MacFileFaults.check(.write, url)
        let directory = url.deletingLastPathComponent()
        let temporary = directory.appendingPathComponent(".\(url.lastPathComponent).\(UUID().uuidString).tmp")
        try writeNew(data, to: temporary)
        guard rename(temporary.path, url.path) == 0 else {
            let error = MacFileError("replace")
            unlink(temporary.path)
            throw error
        }
        synchronizeDirectory(directory)
    }

    /// Writes `data` to `url`, which must not exist yet (O_EXCL), 0600, flushed to storage.
    package static func writeNew(_ data: Data, to url: URL) throws {
        try MacFileFaults.check(.write, url)
        let descriptor = open(url.path, O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, mode_t(0o600))
        guard descriptor >= 0 else { throw MacFileError("create") }
        var committed = false
        defer {
            if !committed { unlink(url.path) }
        }
        guard fchmod(descriptor, 0o600) == 0 else {
            let error = MacFileError("set permissions")
            close(descriptor)
            throw error
        }
        let failed: Int32? = data.withUnsafeBytes { buffer in
            guard var pointer = buffer.baseAddress else { return nil }
            var remaining = buffer.count
            while remaining > 0 {
                let written = write(descriptor, pointer, remaining)
                if written < 0 {
                    if errno == EINTR { continue }
                    return errno
                }
                pointer += written
                remaining -= written
            }
            return nil
        }
        if let failed {
            close(descriptor)
            throw MacFileError("write", code: failed)
        }
        if let code = synchronize(descriptor) {
            close(descriptor)
            throw MacFileError("flush", code: code)
        }
        guard close(descriptor) == 0 else { throw MacFileError("close") }
        committed = true
        synchronizeDirectory(url.deletingLastPathComponent())
    }

    /// Renames `source` to `destination` only when nothing exists at `destination` (data-model
    /// E7.1 invariants 1 and 3): `renamex_np` with `RENAME_EXCL` on macOS. Throws with
    /// `isAlreadyExists` when the destination exists; never replaces it.
    package static func renameExclusively(_ source: URL, to destination: URL) throws {
        try MacFileFaults.check(.rename, destination)
        #if canImport(Darwin)
            guard renamex_np(source.path, destination.path, UInt32(RENAME_EXCL)) == 0 else {
                throw MacFileError("rename")
            }
        #else
            // Linux (tests only): a hard link fails with EEXIST when the name is taken, then the
            // source name goes. Same folder, same file system, so the link cannot cross devices.
            guard link(source.path, destination.path) == 0 else { throw MacFileError("rename") }
            guard unlink(source.path) == 0 else { throw MacFileError("rename") }
        #endif
        synchronizeDirectory(destination.deletingLastPathComponent())
    }

    /// Removes `url`; an absent file is fine.
    package static func remove(_ url: URL) throws {
        try MacFileFaults.check(.remove, url)
        guard unlink(url.path) == 0 || errno == ENOENT else { throw MacFileError("remove") }
    }

    /// The names in `directory` (none when it does not exist).
    package static func names(in directory: URL) -> [String] {
        ((try? FileManager.default.contentsOfDirectory(atPath: directory.path)) ?? []).sorted()
    }

    package static func synchronizeDirectory(_ directory: URL) {
        let descriptor = open(directory.path, O_RDONLY | O_CLOEXEC)
        guard descriptor >= 0 else { return }
        _ = fsync(descriptor)
        close(descriptor)
    }

    /// Flushes a file to storage; returns errno on failure.
    private static func synchronize(_ descriptor: Int32) -> Int32? {
        #if canImport(Darwin)
            // fsync reaches only the drive's cache on Apple platforms; F_FULLFSYNC flushes that too.
            if fcntl(descriptor, F_FULLFSYNC) != -1 { return nil }
        #endif
        while fsync(descriptor) != 0 {
            if errno != EINTR { return errno }
        }
        return nil
    }
}

/// An exclusive `flock` on a lock file, held until `release()` (or the process ends: the kernel
/// drops it with the descriptor, so a crash leaves no stale lock). `flock` belongs to the open
/// file description, so two opens in one process exclude each other like two processes do.
package final class FileLock: Sendable {
    private let descriptor: Int32

    private init(descriptor: Int32) { self.descriptor = descriptor }

    /// Blocks until the lock is held.
    package static func acquire(_ lockURL: URL) throws -> FileLock {
        try lock(lockURL, flags: LOCK_EX)
    }

    /// Nil when another holder has it.
    package static func tryAcquire(_ lockURL: URL) throws -> FileLock? {
        do {
            return try lock(lockURL, flags: LOCK_EX | LOCK_NB)
        } catch let error as MacFileError where error.code == EWOULDBLOCK {
            return nil
        }
    }

    private static func lock(_ lockURL: URL, flags: Int32) throws -> FileLock {
        let descriptor = open(lockURL.path, O_CREAT | O_RDWR | O_CLOEXEC, mode_t(0o600))
        guard descriptor >= 0 else { throw MacFileError("open lock") }
        _ = fchmod(descriptor, 0o600)
        var result: Int32
        repeat {
            result = flock(descriptor, flags)
        } while result != 0 && errno == EINTR
        guard result == 0 else {
            let error = MacFileError("lock")
            close(descriptor)
            throw error
        }
        return FileLock(descriptor: descriptor)
    }

    /// Replaces the lock file's contents with `data` (the single-instance lock records its owner).
    package func replaceContents(with data: Data) throws {
        guard ftruncate(descriptor, 0) == 0 else { throw MacFileError("truncate lock") }
        let written = data.withUnsafeBytes { pwrite(descriptor, $0.baseAddress, $0.count, 0) }
        guard written == data.count else { throw MacFileError("write lock") }
    }

    package func release() {
        _ = flock(descriptor, LOCK_UN)
        close(descriptor)
    }
}

/// The pre-021 store's lock: `lockf` on `.local-gtd.json.lock`, which an older copy of the app
/// takes around each of its writes (`LocalGTDStore.mutate`). Holding it keeps that copy from
/// writing while the import reads and renames its file.
package protocol LegacyStoreLocking: Sendable {
    func acquire(_ lockURL: URL) throws -> any LegacyStoreLockHold
}

package protocol LegacyStoreLockHold: Sendable {
    func release()
}

package struct LockfLegacyStoreLocking: LegacyStoreLocking {
    package init() {}

    package func acquire(_ lockURL: URL) throws -> any LegacyStoreLockHold {
        let descriptor = open(lockURL.path, O_CREAT | O_RDWR | O_CLOEXEC, mode_t(0o600))
        guard descriptor >= 0 else { throw MacFileError("open legacy lock") }
        var result: Int32
        repeat {
            result = lockf(descriptor, F_LOCK, 0)
        } while result != 0 && errno == EINTR
        guard result == 0 else {
            let error = MacFileError("legacy lock")
            close(descriptor)
            throw error
        }
        return LockfHold(descriptor: descriptor)
    }

    private struct LockfHold: LegacyStoreLockHold {
        let descriptor: Int32

        func release() {
            _ = lockf(descriptor, F_ULOCK, 0)
            close(descriptor)
        }
    }
}

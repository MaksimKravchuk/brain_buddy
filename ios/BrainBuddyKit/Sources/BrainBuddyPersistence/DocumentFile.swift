import Foundation

#if canImport(Darwin)
import Darwin
#elseif canImport(Glibc)
import Glibc
#elseif canImport(Musl)
import Musl
#endif

/// The POSIX side of `FileDocumentStore`: the paths, the inter-process lock,
/// whole-file reads, and durable atomic replacement.
///
/// The lock is `flock` on a sibling `.<name>.lock` file. `flock` belongs to
/// the open file description, so two stores in one process exclude each other
/// exactly like two processes do, and closing one descriptor never drops a
/// lock held through another (both are traps of `lockf`/`fcntl` locks). The
/// document itself is never locked because every write replaces its inode.
struct DocumentFile: Sendable {
    let url: URL
    let path: String
    let directoryPath: String
    let lockPath: String
    let fileName: String

    init(url: URL) {
        let url = url.standardizedFileURL
        self.url = url
        fileName = url.lastPathComponent
        path = url.path
        let directory = url.deletingLastPathComponent()
        directoryPath = directory.path
        lockPath = directory.appendingPathComponent(".\(fileName).lock").path
    }

    var lockURL: URL { URL(fileURLWithPath: lockPath) }

    // MARK: Directory

    func directoryExists() -> Bool {
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(atPath: directoryPath, isDirectory: &isDirectory) && isDirectory.boolValue
    }

    /// Creates the directory (and missing parents) owner-only, 0700.
    /// An existing directory is left as it is.
    func createDirectoryIfNeeded() throws(DocumentStoreError) {
        guard !directoryExists() else { return }
        do {
            try FileManager.default.createDirectory(
                atPath: directoryPath, withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
        } catch {
            throw .io("could not create the folder for \(fileName): \(error.localizedDescription)")
        }
        Self.applyFileProtection(to: directoryPath)
    }

    // MARK: Lock

    /// Blocks until this process holds the exclusive lock. Callers must not
    /// suspend while holding it, and must `release()` it.
    func lock() throws(DocumentStoreError) -> FileLock {
        while true {
            var descriptor = open(lockPath, O_CREAT | O_EXCL | O_RDWR | O_CLOEXEC, mode_t(0o600))
            if descriptor >= 0 {
                _ = fchmod(descriptor, 0o600)
                Self.applyFileProtection(to: lockPath)
            } else if errno == EEXIST {
                descriptor = open(lockPath, O_RDWR | O_CLOEXEC)
                // Removed between the two opens (by `destroy()`): start over.
                if descriptor < 0, errno == ENOENT { continue }
            }
            guard descriptor >= 0 else { throw posixError("open lock for", fileName) }

            var result: Int32
            repeat {
                result = flock(descriptor, LOCK_EX)
            } while result != 0 && errno == EINTR
            guard result == 0 else {
                let error = posixError("lock", fileName)
                close(descriptor)
                throw error
            }

            // `destroy()` unlinks the lock file while holding it. If that
            // happened while we waited, we hold a lock on an orphaned file
            // that nobody else will ever contend for: retry on the current one.
            var held = stat()
            var current = stat()
            guard fstat(descriptor, &held) == 0 else {
                let error = posixError("inspect lock for", fileName)
                close(descriptor)
                throw error
            }
            if stat(lockPath, &current) == 0 {
                if held.st_dev == current.st_dev, held.st_ino == current.st_ino {
                    return FileLock(descriptor: descriptor)
                }
            } else if errno != ENOENT {
                let error = posixError("inspect lock for", fileName)
                close(descriptor)
                throw error
            }
            close(descriptor)
        }
    }

    // MARK: Reading

    /// The whole file, or nil when it does not exist. An empty file is
    /// returned as empty data (it is unreadable, not absent).
    func readContents() throws(DocumentStoreError) -> Data? {
        let descriptor = open(path, O_RDONLY | O_CLOEXEC)
        guard descriptor >= 0 else {
            if errno == ENOENT { return nil }
            throw posixError("open", fileName)
        }
        defer { close(descriptor) }
        var contents = Data()
        var chunk = [UInt8](repeating: 0, count: 64 * 1024)
        while true {
            let count = chunk.withUnsafeMutableBytes { read(descriptor, $0.baseAddress, $0.count) }
            if count == 0 { return contents }
            if count < 0 {
                if errno == EINTR { continue }
                throw posixError("read", fileName)
            }
            contents.append(contentsOf: chunk[0..<count])
        }
    }

    // MARK: Writing

    /// Writes `data` to a unique temporary file in the same directory,
    /// flushes it to storage, renames it over the document and flushes the
    /// directory. Readers see the old or the new document, never a mix.
    /// Call with the lock held.
    ///
    /// Once the rename has happened this does not throw: the write is
    /// committed, and reporting a failure would invite a second, duplicate
    /// write. The directory flush is therefore best effort.
    func replaceContents(with data: Data) throws(DocumentStoreError) {
        let temporaryName = ".\(fileName).\(UUID().uuidString).tmp"
        let temporaryPath = directoryPath + "/" + temporaryName
        let descriptor = open(temporaryPath, O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, mode_t(0o600))
        guard descriptor >= 0 else { throw posixError("create", temporaryName) }
        var committed = false
        defer {
            if !committed { unlink(temporaryPath) }
        }

        // The umask can only remove bits; make the mode exactly 0600.
        guard fchmod(descriptor, 0o600) == 0 else {
            let error = posixError("set permissions on", temporaryName)
            close(descriptor)
            throw error
        }
        if let code = Self.writeAll(data, to: descriptor) {
            close(descriptor)
            throw posixError("write", temporaryName, code: code)
        }
        if let code = Self.synchronize(descriptor) {
            close(descriptor)
            throw posixError("flush", temporaryName, code: code)
        }
        guard close(descriptor) == 0 else { throw posixError("close", temporaryName) }
        // The protection class belongs to the inode, so it survives the rename.
        Self.applyFileProtection(to: temporaryPath)

        guard rename(temporaryPath, path) == 0 else { throw posixError("replace", fileName) }
        committed = true
        Self.synchronizeDirectory(directoryPath)
    }

    // MARK: Removing

    /// Removes the document, leftovers of interrupted writes and the lock
    /// file. Call with the lock held; the lock file goes last, so a process
    /// waiting on it notices and retries on a new one (see `lock()`).
    func removeAll() throws(DocumentStoreError) {
        guard unlink(path) == 0 || errno == ENOENT else { throw posixError("remove", fileName) }
        let temporaryPrefix = ".\(fileName)."
        let names = (try? FileManager.default.contentsOfDirectory(atPath: directoryPath)) ?? []
        for name in names where name.hasPrefix(temporaryPrefix) && name.hasSuffix(".tmp") {
            unlink(directoryPath + "/" + name)
        }
        guard unlink(lockPath) == 0 || errno == ENOENT else { throw posixError("remove lock for", fileName) }
        Self.synchronizeDirectory(directoryPath)
    }

    /// Renames the document to `<name>.unreadable-<UTC timestamp>[-n].<ext>`
    /// next to it and returns the new location. Call with the lock held.
    func moveAside(stampedAt date: Date) throws(DocumentStoreError) -> URL {
        let stem = url.deletingPathExtension().lastPathComponent
        let suffix = url.pathExtension.isEmpty ? "" : "." + url.pathExtension
        let stamp = ISO8601Timestamp.compactString(from: date)
        var attempt = 1
        while true {
            let name = "\(stem).unreadable-\(stamp)\(attempt > 1 ? "-\(attempt)" : "")\(suffix)"
            let destination = directoryPath + "/" + name
            if access(destination, F_OK) != 0, errno == ENOENT {
                guard rename(path, destination) == 0 else { throw posixError("set aside", fileName) }
                Self.synchronizeDirectory(directoryPath)
                return URL(fileURLWithPath: destination)
            }
            attempt += 1
        }
    }

    // MARK: Helpers

    /// Returns errno on failure.
    private static func writeAll(_ data: Data, to descriptor: Int32) -> Int32? {
        data.withUnsafeBytes { buffer -> Int32? in
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
    }

    /// Flushes a file to storage; returns errno on failure.
    private static func synchronize(_ descriptor: Int32) -> Int32? {
        #if canImport(Darwin)
        // On Apple platforms fsync only reaches the drive's cache; F_FULLFSYNC
        // flushes that too. Fall back to fsync where it is unsupported.
        if fcntl(descriptor, F_FULLFSYNC) != -1 { return nil }
        #endif
        while fsync(descriptor) != 0 {
            if errno != EINTR { return errno }
        }
        return nil
    }

    /// Makes a rename in `path` durable. Best effort (see `replaceContents`).
    private static func synchronizeDirectory(_ path: String) {
        let descriptor = open(path, O_RDONLY | O_CLOEXEC)
        guard descriptor >= 0 else { return }
        _ = fsync(descriptor)
        close(descriptor)
    }

    /// Widgets and App Intents run while the phone is locked, so the store
    /// stays readable after the first unlock since boot. Best effort: new
    /// files already inherit the app's default class, which is this one.
    private static func applyFileProtection(to path: String) {
        #if os(iOS)
        try? FileManager.default.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: path
        )
        #endif
    }

    private func posixError(_ operation: String, _ name: String, code: Int32 = errno) -> DocumentStoreError {
        .io("\(operation) \(name) failed: \(String(cString: strerror(code)))")
    }
}

/// An exclusive `flock` held through `descriptor`.
struct FileLock {
    let descriptor: Int32

    func release() {
        _ = flock(descriptor, LOCK_UN)
        close(descriptor)
    }
}

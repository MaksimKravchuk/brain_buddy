import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

// The per-install runtime choice (spec 026, T044, PR-54 pilot). One small file in the folder the
// runtime's stores live in, so the app, the widgets and the App Intents of an install read the same
// answer: which workspace identity is the install's, and that its runtime is the shared Rust core.
// No file means the legacy runtime, which is what every install has until the pilot switch is on
// and an import succeeded. Only the app writes it, always by replacing the whole file.

/// Where one install keeps the runtime's files: `runtime/<hex of workspace id>/store.sqlite3` for
/// each workspace identity and `runtime/selection.json` for the choice. The identity is encoded, so
/// it cannot name another folder.
public struct RustRuntimeLocation: Hashable, Sendable {
    public let root: URL

    public init(root: URL) {
        self.root = root
    }

    /// The iOS App Group's folder (Application Support where there is none), beside `store.json`.
    public static func appGroup(_ appGroupID: String) -> RustRuntimeLocation {
        #if canImport(Darwin)
            let document =
                FileDocumentStore.appGroupDocumentURL(appGroupID: appGroupID)
                ?? FileDocumentStore.applicationSupportDocumentURL()
        #else
            let document = FileDocumentStore.applicationSupportDocumentURL()
        #endif
        return RustRuntimeLocation(root: document.deletingLastPathComponent().appendingPathComponent("runtime", isDirectory: true))
    }

    /// A host that keeps its files in one folder (the Mac).
    public static func directory(_ folder: URL) -> RustRuntimeLocation {
        RustRuntimeLocation(root: folder.appendingPathComponent("runtime", isDirectory: true))
    }

    public func identityDirectory(_ workspaceID: String) -> URL {
        let encoded = workspaceID.utf8.map { String(format: "%02x", $0) }.joined()
        return root.appendingPathComponent(encoded, isDirectory: true)
    }

    public func databaseURL(_ workspaceID: String) -> URL {
        identityDirectory(workspaceID).appendingPathComponent("store.sqlite3")
    }

    public var selectionURL: URL { root.appendingPathComponent("selection.json") }

    /// Present from before a legacy import starts until the selection that hands its store to the
    /// app is published (`RustRuntimeLauncher`): a store found with this file and no selection was
    /// never handed to any client.
    public var importPendingURL: URL { root.appendingPathComponent("import-pending") }
}

/// The install's choice: the Rust runtime over one workspace identity.
public struct RustRuntimeSelectionRecord: Codable, Equatable, Sendable {
    public static let currentVersion = 1

    public enum Runtime: String, Codable, Sendable {
        case rust
    }

    public var version: Int
    public var runtime: Runtime
    /// The identity whose store is the install's. An account-less identity is `local-<uuid>` (or
    /// `imported` for the one a legacy import filled); the account is a property of the store.
    public var workspaceID: String
    /// The account the store is linked to, for display and for the sync host; nil when account-less.
    public var account: LinkedAccount?
    /// This install's device identity for the sync protocol (random, allocated once per identity).
    public var deviceID: String
    public var selectedAt: Date
    /// The account-less Review release switch the selection was made with.
    public var reviewEnabled: Bool

    public init(workspaceID: String, account: LinkedAccount?, deviceID: String, selectedAt: Date, reviewEnabled: Bool = false) {
        version = Self.currentVersion
        runtime = .rust
        self.workspaceID = workspaceID
        self.account = account
        self.deviceID = deviceID
        self.selectedAt = selectedAt
        self.reviewEnabled = reviewEnabled
    }
}

public enum RustRuntimeSelectionError: Error, Equatable, Sendable {
    /// The file is there and cannot be read, or was written by a newer build. The install must not
    /// fall back to the legacy runtime: its work may be in the Rust store.
    case unreadable
    case notSaved
}

/// Reads and replaces the selection file. Widgets and App Intents only read.
public struct RustRuntimeSelectionStore: Sendable {
    public let location: RustRuntimeLocation

    public init(location: RustRuntimeLocation) {
        self.location = location
    }

    /// nil when the install has no selection (the legacy runtime).
    public func load() throws(RustRuntimeSelectionError) -> RustRuntimeSelectionRecord? {
        let data: Data
        do {
            data = try Data(contentsOf: location.selectionURL)
        } catch let error as CocoaError where error.code == .fileReadNoSuchFile || error.code == .fileNoSuchFile {
            return nil
        } catch let error as NSError where error.domain == NSPOSIXErrorDomain && error.code == Int(ENOENT) {
            return nil
        } catch {
            throw .unreadable
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        guard let record = try? decoder.decode(RustRuntimeSelectionRecord.self, from: data),
            record.version == RustRuntimeSelectionRecord.currentVersion, !record.workspaceID.isEmpty
        else { throw .unreadable }
        return record
    }

    public func save(_ record: RustRuntimeSelectionRecord) throws(RustRuntimeSelectionError) {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        do {
            try FileManager.default.createDirectory(at: location.root, withIntermediateDirectories: true)
            try encoder.encode(record).write(to: location.selectionURL, options: [.atomic])
        } catch {
            throw .notSaved
        }
    }

    public func clear() throws(RustRuntimeSelectionError) {
        do {
            try FileManager.default.removeItem(at: location.selectionURL)
        } catch let error as CocoaError where error.code == .fileNoSuchFile {
            return
        } catch {
            throw .notSaved
        }
    }
}

/// The local developer / TestFlight switch of the pilot: a key in the app's own `UserDefaults`,
/// off unless somebody turns it on (a debug Settings row, or a launch argument in a test). It is
/// not a server flag and the widgets never read it; they follow the selection file, which only an
/// import that succeeded writes. Turning it off does not undo a selection: the work is in the
/// Rust store by then.
public struct RustRuntimePilotSwitch: Sendable {
    public static let defaultsKey = "BBRustRuntimePilot"

    /// nil is the app's standard defaults; tests name a suite of their own.
    private let suiteName: String?

    public init(suiteName: String? = nil) {
        self.suiteName = suiteName
    }

    private var defaults: UserDefaults { suiteName.flatMap(UserDefaults.init(suiteName:)) ?? .standard }

    public var isEnabled: Bool { defaults.bool(forKey: Self.defaultsKey) }

    public func set(_ enabled: Bool) {
        defaults.set(enabled, forKey: Self.defaultsKey)
    }
}

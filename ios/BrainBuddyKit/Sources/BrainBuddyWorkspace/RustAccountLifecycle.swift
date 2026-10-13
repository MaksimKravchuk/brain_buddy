import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import Foundation

/// What a sign-out confirmation named, for the lifecycle port to check again under the store's
/// own lock (spec 026, FR-003, FR-011): nothing queued by a widget, App Intent or other process
/// since is removed unseen.
public struct RustSignOutConfirmation: Equatable, Sendable {
    public let unsent: Int
    public let issueIDs: Set<String>
    /// The runtime's projection generation when the unsent work was named. Every local write
    /// moves it, so work acknowledged and replaced by another process's write since (the same
    /// count, other commands) is told apart without exposing command contents.
    public let projectionGeneration: UInt64

    public init(unsent: Int, issueIDs: Set<String>, projectionGeneration: UInt64 = 0) {
        self.unsent = unsent
        self.issueIDs = issueIDs
        self.projectionGeneration = projectionGeneration
    }

    /// What a port checks under the store's lock: no more unsent work than named, and when any
    /// is left, the very generation it was named at.
    public func admits(pending: Int, generation: UInt64) -> Bool {
        pending <= unsent && (pending == 0 || generation == projectionGeneration)
    }
}

public struct RustSignInRequest: Sendable {
    public let serverURL: URL
    public let email: String
    public let password: String
    public let cancellation: SignInCancellation
    /// The binding being replaced; a different owner never inherits its unsent work.
    public let current: RustWorkspaceSelection
    /// The first sign-in of an account-less workspace: its local work is the explicit merge into
    /// the account (the sign-in sheet says so). False when signing in again to the linked account.
    public let mergesLocalWork: Bool
}

public struct RustSignInOutcome: Sendable {
    /// The binding for the account's workspace identity; its `account` is the linked one.
    public let selection: RustWorkspaceSelection
    public let deletionCancelled: Bool

    public init(selection: RustWorkspaceSelection, deletionCancelled: Bool = false) {
        self.selection = selection
        self.deletionCancelled = deletionCancelled
    }
}

public struct RustSignOutRequest: Sendable {
    public let current: RustWorkspaceSelection
    public let confirmed: RustSignOutConfirmation
}

/// The host's account lifecycle for a Rust-selected workspace. The workspace fences the binding
/// being replaced before it calls, so nothing that binding was waiting for can reach the next
/// one. Right before the irreversible link, `signIn` claims `request.cancellation.commit()` (a
/// `false` answer means Cancel came first: link nothing and throw). An implementation derives paths from the current App Group / workspace identity, never
/// transfers unsent work to another owner, throws without changing anything when it fails, and
/// on sign-out checks `confirmed` again under the store's lock
/// (`WorkspaceError.unsyncedChanges(count:)` when more was queued meanwhile).
public protocol RustAccountLifecyclePort: Sendable {
    func signIn(_ request: RustSignInRequest) async throws -> RustSignInOutcome
    /// Removes the account's local copy and returns the account-less binding.
    func signOut(_ request: RustSignOutRequest) async throws -> RustWorkspaceSelection
}

extension Workspace {
    /// Whether a first sign-in would merge local work into the account, which the sign-in sheet
    /// says. A selected runtime keeps account-less work as completed local commands, so its count
    /// of waiting changes alone would miss it.
    public var hasLocalWorkToMerge: Bool {
        guard isRustSelected else { return pendingChangeCount > 0 }
        return pendingChangeCount > 0 || rustHasLocalRecords
    }

    /// The runtime's database for one workspace identity inside the App Group (or, where there is
    /// none, Application Support): app, widgets and intents derive the same path, so they share
    /// the store's lock. The identity is encoded, so it cannot name another folder.
    public nonisolated static func rustDatabaseURL(appGroupID: String, workspaceID: String) -> URL {
        #if canImport(Darwin)
            let document =
                FileDocumentStore.appGroupDocumentURL(appGroupID: appGroupID)
                ?? FileDocumentStore.applicationSupportDocumentURL()
        #else
            let document = FileDocumentStore.applicationSupportDocumentURL()
        #endif
        let encoded = workspaceID.utf8.map { String(format: "%02x", $0) }.joined()
        return document.deletingLastPathComponent().appendingPathComponent("runtime", isDirectory: true)
            .appendingPathComponent(encoded, isDirectory: true).appendingPathComponent("store.sqlite3")
    }

    /// A widget or App Intent over the selected runtime: it saves through the store's lock and
    /// never owns sync. The retired document is never opened.
    public static func extensionWorkspace(over selection: RustWorkspaceSelection) -> Workspace {
        Workspace(store: InMemoryDocumentStore(), sync: nil, rust: selection.forExtension())
    }
}

extension RustWorkspaceSelection {
    /// The same runtime for a widget or App Intent: it saves through the store's lock like the
    /// app and never owns sync (its transport only reports unavailable).
    public func forExtension() -> RustWorkspaceSelection {
        RustWorkspaceSelection(runtime: runtime, facade: facade, transport: PendingRustSyncRuntimePort(),
            account: account, reviewEnabled: reviewEnabled, startup: .prepared)
    }

    func prepared() -> RustWorkspaceSelection {
        RustWorkspaceSelection(runtime: runtime, facade: facade, transport: transport, account: account,
            reviewEnabled: reviewEnabled, startup: .prepared)
    }
}

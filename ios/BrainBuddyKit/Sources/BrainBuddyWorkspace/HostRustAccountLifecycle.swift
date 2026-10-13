import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddySync
import Foundation

// The production `RustAccountLifecyclePort` (spec 026, T044, FR-003, FR-011). The workspace fences
// the binding it replaces before it calls; this type does the two things only a host can: talk to
// the server about the session, and change which store is the install's.
//
// Sign-in logs in, claims the cancellation right before the irreversible step, then has the core
// link the workspace to the account under the store's lock (`RustWorkspaceRuntime.linkAccount`)
// and records the account in the selection file. Local work is never moved: a workspace that holds
// some is not linked (the constructed import that would carry it into an account does not exist
// yet), and the person is told it is kept. Registering the device epoch with the server and
// binding the scope and device belong to the sync host (`RustTransportProvider`), whose first
// request does it from the same store.
//
// Sign-out records the server logout first, has the core re-check the confirmation under the
// store's lock and remove the account's copy in the same transaction (`removeAccountCopy`), then
// opens a new account-less identity, switches the selection to it and deletes the old file.

/// What a server login left behind, for the port to keep or undo.
public struct RustServerLogin: Sendable {
    public let account: LinkedAccount
    public let deletionCancelled: Bool
    /// The session this login replaced on the same server, put back if the login is abandoned.
    public let previousToken: String?

    public init(account: LinkedAccount, deletionCancelled: Bool = false, previousToken: String? = nil) {
        self.account = account
        self.deletionCancelled = deletionCancelled
        self.previousToken = previousToken
    }
}

/// A server logout that is recorded and not yet finished.
public struct RustSignOutTicket: Sendable {
    public let logout: PendingLogout?

    public init(logout: PendingLogout?) {
        self.logout = logout
    }
}

/// The server side of the account lifecycle. The real one is `APIRustAccountServer`; tests stub it.
public protocol RustAccountServer: Sendable {
    /// Logs in and stores the new session. Throws `SignInFailure` in words for the sign-in sheet.
    func login(serverURL: URL, email: String, password: String) async throws -> RustServerLogin
    /// Ends the session a login opened and puts the previous one back (Cancel won, or the link
    /// was refused). Never throws: what cannot be sent now waits as a pending logout.
    func abandon(_ login: RustServerLogin) async
    /// Records the logout of `account`'s session durably, before anything is removed.
    func beginSignOut(of account: LinkedAccount) async throws -> RustSignOutTicket
    /// The removal went through: forget the session here and tell the server (now, or when the
    /// network is back).
    func finishSignOut(_ ticket: RustSignOutTicket, of account: LinkedAccount) async
    /// Nothing was removed: the session stays valid.
    func cancelSignOut(_ ticket: RustSignOutTicket) async
}

public struct HostRustAccountLifecycle: RustAccountLifecyclePort {
    public static let localWorkKeptMessage =
        "Your tasks on this device can't be added to an account yet. They are kept here; nothing was changed."
    public static let differentAccountMessage = "This is a different account. Sign out first; your work is kept."
    public static let cancelledMessage = "This sign-in was cancelled."

    private let environment: RustRuntimeEnvironment

    public init(environment: RustRuntimeEnvironment) {
        self.environment = environment
    }

    // MARK: Sign in

    public func signIn(_ request: RustSignInRequest) async throws -> RustSignInOutcome {
        let current = request.current
        let selections = environment.selections
        guard let held = try? selections.load(), held.account?.id == current.account?.id else {
            throw WorkspaceError.signInFailed(message: "Brain Buddy couldn't read this device's account. Your work is kept.", referenceID: nil)
        }
        // Known before any session is opened: local work reaches an account only through the merge
        // the sign-in sheet announced (`mergesLocalWork`), never silently.
        if current.account == nil, !request.mergesLocalWork, try await holdsLocalWork(current.runtime) {
            throw WorkspaceError.signInFailed(message: Self.localWorkKeptMessage, referenceID: nil)
        }
        let login = try await environment.server.login(serverURL: request.serverURL, email: request.email, password: request.password)
        if let linked = current.account, linked.id != login.account.id {
            await environment.server.abandon(login)
            throw WorkspaceError.signInFailed(message: Self.differentAccountMessage, referenceID: nil)
        }
        // The one point where Cancel and the link are decided (spec 021, FR-001).
        guard Task.isCancelled == false, request.cancellation.isCommitted || request.cancellation.commit() else {
            await environment.server.abandon(login)
            throw WorkspaceError.signInFailed(message: Self.cancelledMessage, referenceID: nil)
        }
        // Saved first: a crash between the two steps is repaired by the next launch (the link is
        // idempotent). A link the core refuses puts the previous selection back.
        var linked = held
        linked.account = login.account
        do { try selections.save(linked) } catch {
            await environment.server.abandon(login)
            throw WorkspaceError.signInFailed(message: "Brain Buddy couldn't save your sign-in on this device.", referenceID: nil)
        }
        // The first sign-in of an account-less workspace carries its local work into the account:
        // one transaction binds the account and queues a new command per record. A crash before
        // it leaves the workspace as it was; a retry after it is `.alreadyLinked`, never a second
        // import. The sync host then sends the queued commands.
        let outcome: RustAccountMergeOutcome
        do {
            outcome = try await environment.linkAndMerge(
                current.runtime, account: login.account, deviceID: linked.deviceID, facade: current.facade,
                reviewEnabled: current.reviewEnabled)
        } catch {
            try? selections.save(held)
            await environment.server.abandon(login)
            throw WorkspaceError.signInFailed(message: "Couldn't sign in. Your work is kept.", referenceID: nil)
        }
        switch outcome {
        case .merged, .alreadyLinked: break
        case .otherAccount:
            try? selections.save(held)
            await environment.server.abandon(login)
            throw WorkspaceError.signInFailed(message: Self.differentAccountMessage, referenceID: nil)
        }
        let context = RustTransportContext(runtime: current.runtime, workspaceID: linked.workspaceID,
            databaseURL: environment.location.databaseURL(linked.workspaceID), account: login.account, deviceID: linked.deviceID,
            freshAuthentication: true, reviewEnabled: current.reviewEnabled)
        let selection = RustWorkspaceSelection(
            runtime: current.runtime, facade: current.facade, transport: environment.transports.transport(for: context),
            account: login.account, reviewEnabled: current.reviewEnabled, startup: .prepared)
        return RustSignInOutcome(selection: selection, deletionCancelled: login.deletionCancelled)
    }

    private func holdsLocalWork(_ runtime: RustWorkspaceRuntime) async throws -> Bool {
        let snapshot = try await runtime.snapshot()
        let queued = UInt64(snapshot.pending) ?? 1
        guard let rows = try? JSONSerialization.jsonObject(with: snapshot.records) else { return true }
        let empty: Bool =
            switch rows {
            case let rows as [Any]: rows.isEmpty
            case let rows as [String: Any]: rows.isEmpty
            default: false
            }
        return queued > 0 || !empty
    }

    // MARK: Sign out

    public func signOut(_ request: RustSignOutRequest) async throws -> RustWorkspaceSelection {
        let current = request.current
        let selections = environment.selections
        guard let held = try? selections.load() else {
            throw WorkspaceError.storage("Brain Buddy couldn't read this device's account. Your work is kept.")
        }
        let ticket: RustSignOutTicket
        if let account = current.account {
            // A session that cannot be recorded removes nothing: the device would say "signed out"
            // while the session stays valid on the server.
            ticket = try await environment.server.beginSignOut(of: account)
        } else {
            ticket = RustSignOutTicket(logout: nil)
        }
        let removal: RustAccountCopyRemoval
        do {
            removal = try await current.runtime.removeAccountCopy(
                maxUnsent: UInt64(request.confirmed.unsent), generation: request.confirmed.projectionGeneration,
                issueIDs: request.confirmed.issueIDs.sorted())
        } catch {
            await environment.server.cancelSignOut(ticket)
            throw error
        }
        if case .changed(let unsent, let issues) = removal {
            await environment.server.cancelSignOut(ticket)
            throw WorkspaceError.unsyncedChanges(count: Int(clamping: unsent + issues))
        }
        // The copy is gone from here on, whatever fails next. The next identity is made, selected
        // and only then is the old file deleted, so the install never has no store to open.
        let identity = environment.newIdentity()
        let fresh: RustWorkspaceRuntime
        do {
            fresh = try await environment.openRuntime(identity)
            try await fresh.establishAccountless()
        } catch {
            throw WorkspaceError.storage("Brain Buddy removed this account from the device but couldn't start an empty list. Restart Brain Buddy.")
        }
        let next = RustRuntimeSelectionRecord(
            workspaceID: identity, account: nil, deviceID: environment.makeID().uuidString.lowercased(),
            selectedAt: environment.now(), reviewEnabled: held.reviewEnabled)
        do { try selections.save(next) } catch {
            try? await fresh.close()
            throw WorkspaceError.storage("Brain Buddy removed this account from the device but couldn't start an empty list. Restart Brain Buddy.")
        }
        try? await current.runtime.close()
        try? FileManager.default.removeItem(at: environment.location.identityDirectory(held.workspaceID))
        if let account = current.account { await environment.server.finishSignOut(ticket, of: account) }
        let context = RustTransportContext(runtime: fresh, workspaceID: identity,
            databaseURL: environment.location.databaseURL(identity), account: nil, deviceID: next.deviceID,
            reviewEnabled: current.reviewEnabled)
        return RustWorkspaceSelection(
            runtime: fresh, facade: current.facade, transport: environment.transports.transport(for: context),
            account: nil, reviewEnabled: current.reviewEnabled, startup: .prepared)
    }
}

extension RustRuntimeEnvironment {
    /// The first-sign-in merge for one runtime (scope = the account's id, device = the install's).
    /// The instant is only the fallback: each record's command is decided at its own time.
    func linkAndMerge(
        _ runtime: RustWorkspaceRuntime, account: LinkedAccount, deviceID: String, facade: RustDomainFacade,
        reviewEnabled: Bool
    ) async throws -> RustAccountMergeOutcome {
        let zone = TimeZone.current.identifier
        let instant = now()
        let inputs = try facade.workspaceQueryInputs(at: instant, zone: zone, reviewExposed: reviewEnabled)
        guard let root = try JSONSerialization.jsonObject(with: inputs) as? [String: Any], let policy = root["policy"] else {
            throw RustBridgeError(code: "INVALID_REQUEST", field: "policy")
        }
        let context = RustWorkspaceContext(
            now: instant, timeZone: zone, actorID: facade.context.actorID,
            policy: try JSONSerialization.data(withJSONObject: policy, options: [.sortedKeys]))
        return try await runtime.linkAndMerge(
            accountID: account.id, scopeID: account.id, deviceID: deviceID, context: context)
    }
}

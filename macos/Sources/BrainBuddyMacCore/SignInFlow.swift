import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddySync
import BrainBuddyWorkspace
import Foundation
import Observation

/// Design X-03's words (contracts/mac-app-host.md §7).
package enum SignInCopy {
    package static let title = "Sign in to Brain Buddy"
    package static let subtitle = "Use the same tasks on this Mac, your iPhone and the web."
    package static let againTitle = "Sign in again"
    package static let againSubtitle =
        "Your session ended. Sign in again to keep syncing. Your changes are kept on this Mac until then."
    package static let againFooter = "Sign out first to use another account."
    package static let localTasks =
        "Your tasks on this Mac will be added to your account. Projects and tags with the same name become one. Tasks are never merged by title, so nothing is lost or doubled."
    package static let signIn = "Sign in"
    package static let signingIn = "Signing in…"
    package static let cancel = "Cancel"
    package static let advanced = "Advanced"
    package static let serverAddress = "Server address"
    package static let useDefaultServer = "Use the default server"
    package static let invalidServer = "Use an https server address. http works only for localhost."
    package static let wrongPassword = "Check your email and password."
    package static let noAnswer = "Brain Buddy didn't answer. Try again."
    package static let couldNotSave = "Brain Buddy couldn't save your sign-in on this Mac. Try again."
    package static let offline = "Can't reach the server. Check your connection."
    package static let offlineReassurance =
        "Signing in is the only thing that needs a connection. Everything else keeps working on this Mac."
    package static let failed = "Brain Buddy couldn't sign in. Try again."
    package static let deletionCancelledTitle = "Your account deletion was cancelled"
    package static let deletionCancelledDetail =
        "Signing in cancels a deletion you requested in the last 14 days. Delete your account again on the web if you still want to."
    package static let ok = "OK"
}

/// X-03's logic (contracts/mac-app-host.md §7, design X-03), with no view: the states, the single
/// request, Cancel while "Signing in…", the error words for this Mac, and the "account deletion
/// cancelled" note. The sheet (`SignInSheet.swift`) lays it out.
///
/// Security: the password lives only in this flow while the sheet is open and is handed to the
/// workspace, never logged or stored by the Mac. The session token never reaches this type: the kit
/// stores it in the Keychain, interactively only here, on the engine actor (off the main actor).
@MainActor
@Observable
package final class SignInFlow {
    package enum Mode: Equatable, Sendable {
        case signIn
        /// The session ended: the linked account's email and server, locked.
        case signInAgain(email: String, serverURL: URL)
    }

    package enum Phase: Equatable, Sendable {
        case editing
        /// One request is on its way; the fields are read-only, Cancel and Esc stay enabled.
        case signingIn
        /// The account is linked and its first sync runs: still "Signing in…", but Cancel and Esc no
        /// longer apply (the kit refuses a Cancel once the link won), so the sheet never reports as
        /// cancelled a sign-in that linked the account.
        case finishing
        /// Signed in, and the sign-in cancelled a pending account deletion: the note, then close.
        case deletionCancelledNote
        /// Signed in: the sheet closes.
        case finished
    }

    /// A sign-in error in this Mac's words, with the reference id to quote when there is one.
    package struct Message: Equatable, Sendable {
        package enum Kind: String, Equatable, Sendable {
            case wrongPassword, noAnswer, couldNotSave, offline, accountSwitchRefused, invalidServer, server
        }

        package var kind: Kind
        package var title: String
        package var detail: String?
        package var referenceID: String?
    }

    /// Signs in through the workspace (`Workspace.signIn(serverURL:email:password:cancellation:)`).
    package typealias SignIn = @MainActor @Sendable (URL, String, String, SignInCancellation) async throws -> Void

    package let mode: Mode
    /// "first sign-in with local tasks": the outbox holds account-less data.
    package let showsLocalTasksNotice: Bool
    package var email: String
    package var password: String
    package var serverAddress: String
    package var showsAdvanced = false
    package private(set) var phase: Phase = .editing
    package private(set) var message: Message?
    /// Where focus should go in the sheet; `focusSerial` changes whenever it should move.
    package private(set) var preferredFocus: FocusTarget
    package private(set) var focusSerial = 0
    /// Requests started (the single-flight evidence).
    @ObservationIgnored package private(set) var requestsStarted = 0

    @ObservationIgnored private let defaultServer: URL
    @ObservationIgnored private let isOnline: @MainActor () -> Bool
    @ObservationIgnored private let signIn: SignIn
    @ObservationIgnored private let deletionCancelled: @MainActor () -> Bool
    @ObservationIgnored private let acknowledgeDeletion: @MainActor () -> Void
    @ObservationIgnored private let log: any MacLogSink
    @ObservationIgnored private var attempt: Task<Void, Never>?
    /// The running attempt's Cancel against its link.
    @ObservationIgnored private var cancellation: SignInCancellation?
    @ObservationIgnored private var attemptID = 0

    package init(
        mode: Mode, hasLocalTasks: Bool, defaultServer: URL, isOnline: @escaping @MainActor () -> Bool,
        signIn: @escaping SignIn, deletionCancelled: @escaping @MainActor () -> Bool = { false },
        acknowledgeDeletion: @escaping @MainActor () -> Void = {}, log: any MacLogSink = SystemMacLog()
    ) {
        self.mode = mode
        self.defaultServer = defaultServer
        self.isOnline = isOnline
        self.signIn = signIn
        self.deletionCancelled = deletionCancelled
        self.acknowledgeDeletion = acknowledgeDeletion
        self.log = log
        password = ""
        switch mode {
        case .signIn:
            email = ""
            serverAddress = defaultServer.absoluteString
            showsLocalTasksNotice = hasLocalTasks
            preferredFocus = .signInEmail
        case .signInAgain(let email, let serverURL):
            self.email = email
            serverAddress = serverURL.absoluteString
            showsLocalTasksNotice = false
            preferredFocus = .signInPassword
        }
    }

    package var isLocked: Bool { mode != .signIn }
    package var title: String { isLocked ? SignInCopy.againTitle : SignInCopy.title }
    package var subtitle: String { isLocked ? SignInCopy.againSubtitle : SignInCopy.subtitle }
    package var footer: String? { isLocked ? SignInCopy.againFooter : nil }
    /// Read-only while signing in; the email and server always in "Sign in again".
    package var credentialsReadOnly: Bool { isSigningIn }
    package var accountFieldsReadOnly: Bool { isLocked || isSigningIn }
    package var submitTitle: String { isSigningIn ? SignInCopy.signingIn : SignInCopy.signIn }
    /// "Signing in…", with or without Cancel.
    package var isSigningIn: Bool { phase == .signingIn || phase == .finishing }
    /// Cancel and Esc: enabled but while the linked account's first sync finishes.
    package var canCancel: Bool {
        switch phase {
        case .finishing: false
        case .signingIn: !(cancellation?.isCommitted ?? false)
        case .editing, .deletionCancelledNote, .finished: true
        }
    }

    /// "Sign in" is the default and enabled once both fields are filled, and never twice at once.
    package var canSubmit: Bool {
        phase == .editing && !email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !password.isEmpty
            && !serverAddress.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    package func useDefaultServer() {
        guard !accountFieldsReadOnly else { return }
        serverAddress = defaultServer.absoluteString
    }

    /// "Sign in" (or Return): one request, never two at once.
    package func submit() {
        guard canSubmit else { return }
        guard let url = BrainBuddyAPI.serverURL(from: serverAddress) else {
            fail(Message(kind: .invalidServer, title: SignInCopy.invalidServer))
            return
        }
        message = nil
        phase = .signingIn
        requestsStarted += 1
        attemptID += 1
        let id = attemptID
        let email = email.trimmingCharacters(in: .whitespacesAndNewlines)
        let password = password
        let signIn = signIn
        let cancellation = SignInCancellation(onCommit: { [weak self] in Task { @MainActor in self?.linked(id) } })
        self.cancellation = cancellation
        log.log(.sync, "sign-in started")
        attempt = Task { @MainActor [weak self] in
            do {
                try await signIn(url, email, password, cancellation)
                self?.succeeded(id)
            } catch {
                self?.failed(id, error)
            }
        }
    }

    /// Waits for the request on its way (tests).
    package func waitForAttempt() async { await attempt?.value }

    /// Cancel or Esc. While "Signing in…" it stops the request, keeps the typed values, puts focus in
    /// Password and changes nothing (if the server's reply arrives after this, the kit ends that
    /// session at once and links nothing). Once the account is linked it does nothing: the sign-in
    /// finishes and the sheet closes signed in. Returns true when the sheet should close.
    @discardableResult
    package func cancel() -> Bool {
        if phase == .finishing { return false }
        guard phase == .signingIn else { return phase != .deletionCancelledNote || finishNote() }
        guard cancellation?.cancel() ?? true else {
            // The link won the race: saying "cancelled" now would be untrue.
            phase = .finishing
            return false
        }
        attemptID += 1
        attempt?.cancel()
        phase = .editing
        log.log(.sync, "sign-in cancelled")
        moveFocus(.signInPassword)
        return false
    }

    /// "OK", Return or Esc on the "account deletion cancelled" note.
    @discardableResult
    package func finishNote() -> Bool {
        guard phase == .deletionCancelledNote else { return false }
        acknowledgeDeletion()
        phase = .finished
        return true
    }

    /// The kit is saving the link: from now on the attempt finishes as a normal sign-in.
    private func linked(_ id: Int) {
        guard id == attemptID, phase == .signingIn else { return }
        phase = .finishing
    }

    private func succeeded(_ id: Int) {
        // A Cancel that won links nothing, so its attempt never gets here.
        guard id == attemptID else { return }
        attempt = nil
        cancellation = nil
        log.log(.sync, "sign-in finished outcome=signedIn")
        if deletionCancelled() {
            phase = .deletionCancelledNote
            moveFocus(.signInNote)
        } else {
            phase = .finished
        }
    }

    private func failed(_ id: Int, _ error: any Error) {
        guard id == attemptID else { return }
        attempt = nil
        cancellation = nil
        phase = .editing
        guard let message = Self.message(for: error, isOnline: isOnline()) else { return }
        fail(message)
    }

    private func fail(_ message: Message) {
        self.message = message
        log.log(.sync, "sign-in finished outcome=\(message.kind.rawValue)")
        moveFocus(.signInPassword)
    }

    private func moveFocus(_ target: FocusTarget) {
        preferredFocus = target
        focusSerial += 1
    }

    /// The kit's sign-in failure in this Mac's words (design X-03 error rows). Nil for a sign-in the
    /// person cancelled.
    package static func message(for error: any Error, isOnline: Bool) -> Message? {
        guard let error = error as? WorkspaceError else {
            return Message(kind: .server, title: SignInCopy.failed)
        }
        switch error {
        case .invalidServerURL:
            return Message(kind: .invalidServer, title: SignInCopy.invalidServer)
        case .signInFailed(let text, let reference):
            let reference = reference.flatMap { $0.isEmpty ? nil : $0 }
            switch text {
            case SyncEngine.signInCancelledMessage:
                return nil
            case APIError.tokenNotSavedMessage:
                return Message(kind: .couldNotSave, title: SignInCopy.couldNotSave, referenceID: reference)
            case SyncEngine.networkFailureMessage:
                return isOnline
                    ? Message(kind: .noAnswer, title: SignInCopy.noAnswer, referenceID: reference)
                    : Message(kind: .offline, title: SignInCopy.offline, detail: SignInCopy.offlineReassurance)
            case SignInCopy.wrongPassword:
                return Message(kind: .wrongPassword, title: text, referenceID: reference)
            case SyncCopy.accountSwitchRefused(device: .mac).sentence, SyncCopy.accountSwitchRefused(device: .iPhone).sentence:
                let refusal = SyncCopy.accountSwitchRefused(device: .mac)
                return Message(kind: .accountSwitchRefused, title: refusal.title, detail: refusal.detail)
            default:
                return Message(kind: .server, title: text, referenceID: reference)
            }
        case .unsyncedChanges, .storage, .signingIn:
            return Message(kind: .server, title: error.message)
        }
    }
}

import AuthenticationServices
import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddySync
import BrainBuddyWorkspace
import Foundation
import SwiftUI
import UIKit

/// Modern methods collect proof in memory; Workspace validates the immutable
/// owner and durable local work before installing any candidate session.
struct SignInSheet: View {
    private enum Step { case choice, password, recovery, code, newPassword, collision }
    private enum Field: Hashable { case email, password, code, newPassword, repeatPassword, server }
    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.dismiss) private var dismiss
    @State private var coordinator = ModernAuthCoordinator()
    @State private var step: Step = .choice
    @State private var email: String
    @State private var password = ""
    @State private var repeatedPassword = ""
    @State private var code = ""
    @State private var serverAddress: String
    @State private var showsAdvanced: Bool
    @State private var methods: AuthMethodsDTO?
    @State private var availabilityFailed = false
    @State private var isBusy = false
    @State private var failureMessage: String?
    @State private var failureReferenceID: String?
    @State private var notice: String?
    @State private var attempt: NativeSignInAttempt?
    @State private var proof: ModernAuthCoordinator.Proof?
    @State private var challenge: AuthChallengeDTO?
    @State private var recovery = false
    @State private var resetGrant: String?
    @State private var resetExpiry: Date?
    @State private var operation: Task<Void, Never>?
    @State private var operationID = UUID()
    @State private var showsDeletionCancelledNotice = false
    @FocusState private var focused: Field?

    init(email: String = "", serverURL: URL? = nil) {
        let address = serverURL?.absoluteString ?? SignInServerAddress.defaultString
        _email = State(initialValue: email)
        _serverAddress = State(initialValue: address)
        _showsAdvanced = State(initialValue: address != SignInServerAddress.defaultString)
    }

    private var serverURL: URL? {
        workspace.account?.serverURL ?? BrainBuddyAPI.serverURL(from: SignInServerAddress.url(from: serverAddress)?.absoluteString ?? "")
    }
    private var isOnline: Bool {
        if case .offline = workspace.syncStatus { return false }
        return coordinator.isOnline
    }
    private var api: BrainBuddyAPIClient? {
        serverURL.map { BrainBuddyAPIClient(baseURL: $0, tokenStore: InMemorySessionTokenStore()) }
    }
    private var privacyURL: URL? {
        guard let origin = methods?.webAccountOrigin,
            let url = NativeAccountDestination.url(origin: origin, ownerID: "privacy", deleting: false),
            var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else { return nil }
        components.path = "/privacy"
        components.query = nil
        return components.url
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(workspace.account == nil ? "Sign in or create an account" : "Sign in again")
                        .font(.headline)
                    Text("Your local tasks are kept if sign-in fails. Signing in merges them with your account.")
                        .font(BBFont.secondary).foregroundStyle(BBColor.textSecondary)
                    if let account = workspace.account {
                        Text("Use the account linked to this iPhone. Sign out first to use another account.")
                            .font(BBFont.secondary)
                        LabeledContent("Server", value: SettingsScreen.hostDescription(account.serverURL))
                    }
                    if !isOnline { Text("Your local tasks are kept. Connect to the internet to sign in.") }
                    if let notice { Text(notice).accessibilityAddTraits(.updatesFrequently) }
                }
                if let failureMessage {
                    Section {
                        EditorValidationMessage(text: failureMessage)
                        if let failureReferenceID { Text("Reference ID: \(failureReferenceID)").font(.footnote.monospaced()).textSelection(.enabled) }
                    }
                }
                entrySection
                if workspace.account == nil, step == .choice || step == .password || step == .recovery {
                    Section {
                        DisclosureGroup("Advanced", isExpanded: $showsAdvanced) {
                            TextField("Server address", text: $serverAddress)
                                .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
                                .focused($focused, equals: .server).frame(minHeight: 44)
                            Text("Use an https address. http works only for localhost, during development.").font(BBFont.meta)
                            Button("Use the default server") { serverAddress = SignInServerAddress.defaultString }.frame(minHeight: 44)
                        }
                    }.disabled(isBusy)
                }
                if let privacyURL { Section { Link("Privacy policy", destination: privacyURL).frame(minHeight: 44) } }
            }
            .navigationTitle(step == .recovery || step == .newPassword ? "Reset your password" : "Sign in")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { cancelAndDismiss() }.frame(minHeight: 44)
                }
            }
            .task(id: serverURL) { await loadMethods() }
            .onAppear { focused = .email }
            .onDisappear { cancelCurrentOperation(); coordinator.stopMonitoring() }
        }
        .interactiveDismissDisabled(isBusy || showsDeletionCancelledNotice)
        .alert("Your account deletion was cancelled", isPresented: $showsDeletionCancelledNotice) {
            Button("OK") { workspace.acknowledgeAccountDeletionNotice(); dismiss() }
        } message: {
            Text("Your tasks are kept. Signing in cancels a deletion requested in the last 14 days. Delete your account again on the web if you still want to.")
        }
    }

    @ViewBuilder private var entrySection: some View {
        switch step {
        case .choice:
            Section {
                if methods?.google == true {
                    GoogleSignInButton(isBusy: isBusy) { startProvider(.google) }
                        .disabled(isBusy || !isOnline)
                }
                if methods?.apple == true {
                    AppleSignInButton { startProvider(.apple) }
                        .frame(maxWidth: .infinity)
                        .frame(height: 44)
                        .disabled(isBusy || !isOnline)
                }
                if methods == nil {
                    Text(availabilityFailed ? "Couldn't load sign-in methods. Try again or use your password." : "Loading sign-in methods…")
                    Button("Retry") { Task { await loadMethods() } }.frame(minHeight: 44).disabled(isBusy || !isOnline)
                }
                if methods?.email == true {
                    emailField
                    action("Continue with email", enabled: !email.isEmpty) { requestCode(recovering: false) }
                }
                Button("Use your password") { step = .password; focused = .email }.frame(minHeight: 44).disabled(isBusy)
            }
        case .password:
            Section {
                emailField
                SecureField("Password", text: $password).textContentType(.password).focused($focused, equals: .password)
                    .frame(minHeight: 44).onSubmit { passwordSignIn() }
                action("Sign in", enabled: !email.isEmpty && !password.isEmpty) { passwordSignIn() }
                Button("Forgot password?") { password = ""; step = .recovery; focused = .email }.frame(minHeight: 44).disabled(isBusy)
                backButton
            }.disabled(isBusy)
        case .recovery:
            Section {
                emailField
                Text("If this address can be used, you'll receive a code. For an older unverified account, use its existing password and verify your email in account settings.")
                    .font(BBFont.secondary)
                action("Send recovery code", enabled: !email.isEmpty && methods?.email == true) { requestCode(recovering: true) }
                backButton
            }.disabled(isBusy)
        case .code:
            Section {
                Text(recovery ? "Confirm your recovery code" : "Check your email").font(.headline)
                Text("If this address can be used, you will receive a code. Use another email or method if it doesn't arrive.").font(BBFont.secondary)
                TextField("Email code", text: $code).textContentType(.oneTimeCode).keyboardType(.numberPad)
                    .focused($focused, equals: .code).frame(minHeight: 44)
                    .onChange(of: code) { _, new in code = String(new.filter { $0.isASCII && $0.isNumber }.prefix(6)) }
                action("Verify code", enabled: code.count == 6) { verifyCode() }
                if let challenge {
                    Text("Expires \(challenge.expiresAt.formatted(date: .omitted, time: .shortened))").font(BBFont.meta)
                    TimelineView(.periodic(from: .now, by: 1)) { context in
                        let seconds = max(0, Int(challenge.resendAt.timeIntervalSince(context.date).rounded(.up)))
                        Button(seconds > 0 ? "Resend in \(seconds)s" : "Resend code") { resendCode() }
                            .frame(minHeight: 44).disabled(seconds > 0 || isBusy || !isOnline || context.date >= challenge.expiresAt)
                    }
                }
                backButton
            }.disabled(isBusy)
        case .newPassword:
            Section {
                Text("At least 12 characters. Longer is better.")
                SecureField("New password", text: $password).textContentType(.newPassword).focused($focused, equals: .newPassword).frame(minHeight: 44)
                SecureField("Repeat password", text: $repeatedPassword).textContentType(.newPassword).focused($focused, equals: .repeatPassword).frame(minHeight: 44)
                Text("Your other sessions will end after the reset.").font(BBFont.secondary)
                action("Save password", enabled: password.count >= 12 && password == repeatedPassword) { savePassword() }
                backButton
            }.disabled(isBusy)
        case .collision:
            Section {
                Text("Connect to your existing account").font(.headline)
                Text("Sign in to your existing account, then explicitly connect this method in account settings. Matching email doesn't merge accounts.")
                Button("Sign in to existing account") { returnToChoice() }.frame(minHeight: 44)
                backButton
            }
        }
    }

    private var emailField: some View {
        TextField("Email", text: $email).textContentType(.username).keyboardType(.emailAddress)
            .textInputAutocapitalization(.never).autocorrectionDisabled().focused($focused, equals: .email).frame(minHeight: 44)
    }
    private var backButton: some View {
        Button("Use another method") { returnToChoice() }.frame(minHeight: 44).disabled(isBusy)
    }
    private func action(_ title: String, enabled: Bool = true, body: @escaping () -> Void) -> some View {
        Button(action: body) {
            HStack { if isBusy { ProgressView() }; Text(isBusy ? "Please wait…" : title) }.frame(maxWidth: .infinity, minHeight: 44)
        }.buttonStyle(.glassProminent).tint(BBColor.brandFill).disabled(!enabled || isBusy || !isOnline)
    }

    private func loadMethods() async {
        guard let api else { methods = nil; availabilityFailed = true; return }
        let url = api.baseURL
        methods = nil
        availabilityFailed = false
        do {
            let result = try await api.authMethods()
            guard serverURL == url, !Task.isCancelled else { return }
            methods = result
        } catch {
            if serverURL == url, !Task.isCancelled { availabilityFailed = true }
        }
    }

    private func run(_ body: @escaping @MainActor () async throws -> Void) {
        guard !isBusy, isOnline else { return }
        isBusy = true // Immediate local feedback, before scheduling any I/O.
        failureMessage = nil
        failureReferenceID = nil
        focused = nil
        let id = UUID()
        operationID = id
        operation = Task { @MainActor in
            do { try await body() } catch {
                guard operationID == id, !Task.isCancelled else { return }
                if let error = error as? WorkspaceError {
                    if error.message.contains("Start a fresh sign-in.") { returnToChoice() }
                    showFailure(error.message, reference: reference(error))
                }
                else if let error = error as? APIError {
                    if error.isUncertainOutcome { returnToChoice() }
                    showFailure(error.isUncertainOutcome ? "We couldn't confirm whether this finished. Your local tasks are kept. Use a fresh sign-in or recovery code." : error.message, reference: error.referenceID)
                }
                else if error is CancellationError || (error as? ASAuthorizationError)?.code == .canceled || (error as? ASWebAuthenticationSessionError)?.code == .canceledLogin {
                    stopAttempt()
                    showFailure("Sign-in was cancelled. Your local tasks are kept.", reference: nil)
                } else { showFailure((error as? ModernAuthCoordinator.Failure)?.message ?? "Couldn't sign in. Try again or use another connected method.", reference: nil) }
            }
            if operationID == id { isBusy = false; operation = nil }
        }
    }
    private func freshAttempt() async throws -> NativeSignInAttempt {
        if let attempt { await workspace.cancelSignIn(attempt) }
        guard let url = serverURL else { throw WorkspaceError.invalidServerURL }
        let result = try await workspace.beginSignIn(serverURL: url)
        if Task.isCancelled { await workspace.cancelSignIn(result); throw CancellationError() }
        attempt = result
        return result
    }
    private func passwordSignIn() {
        run {
            let current = try await freshAttempt()
            try await accept(try await workspace.completeSignIn(current, credential: .password(email: email.trimmingCharacters(in: .whitespacesAndNewlines), password: password)))
        }
    }
    private func requestCode(recovering: Bool) {
        run {
            _ = try await freshAttempt()
            let newProof = try ModernAuthCoordinator.newProof()
            proof = newProof
            recovery = recovering
            guard let api else { throw WorkspaceError.invalidServerURL }
            let result = try await api.requestEmailCode(email: email.trimmingCharacters(in: .whitespacesAndNewlines), purpose: recovering ? .recover : .login, clientChallenge: newProof.challenge)
            try Task.checkCancellation()
            challenge = result
            code = ""
            step = .code
            focused = .code
        }
    }
    private func resendCode() {
        run {
            guard let challenge, let proof, let api else { return }
            let result = try await api.resendEmailCode(challengeID: challenge.challengeID, verifier: proof.verifier)
            try Task.checkCancellation()
            self.challenge = result
            code = ""
            focused = .code
        }
    }
    private func verifyCode() {
        run {
            guard let attempt, let proof, let challenge else { return }
            try await accept(try await workspace.completeSignIn(attempt, credential: .emailCode(challengeID: challenge.challengeID, code: code, verifier: proof.verifier)))
        }
    }
    private func startProvider(_ provider: NativeAuthProvider) {
        run {
            let attempt = try await freshAttempt()
            let proof = try ModernAuthCoordinator.newProof()
            self.proof = proof
            guard let api else { throw WorkspaceError.invalidServerURL }
            let start = try await api.startProvider(provider, clientChallenge: proof.challenge)
            try Task.checkCancellation()
            let credential = try await coordinator.authenticate(provider: provider, start: start, verifier: proof.verifier)
            try Task.checkCancellation()
            try await accept(try await workspace.completeSignIn(attempt, credential: credential))
        }
    }
    private func accept(_ outcome: NativeSignInOutcome) async throws {
        try Task.checkCancellation()
        switch outcome {
        case .signedIn(let result):
            clearSecrets()
            attempt = nil
            toasts.show("Signed in as \(result.account.email)", actionTitle: nil, action: nil)
            if result.deletionCancelled { showsDeletionCancelledNotice = true }
            else { dismiss() }
        case .continuation(.verifyMailbox(let challenge)):
            self.challenge = challenge
            recovery = false
            step = .code
            code = ""
            focused = .code
        case .continuation(.resetReady(let grant, let expiry)):
            resetGrant = grant
            resetExpiry = expiry
            password = ""
            repeatedPassword = ""
            step = .newPassword
            focused = .newPassword
        case .continuation(.existingAccountRequired):
            stopAttempt()
            step = .collision
        default: throw ModernAuthCoordinator.Failure(message: "The server returned an unexpected sign-in response.")
        }
    }
    private func savePassword() {
        run {
            guard let grant = resetGrant, let expiry = resetExpiry, expiry > Date(), let proof, let api else {
                throw ModernAuthCoordinator.Failure(message: "That recovery proof has expired. Request a fresh code.")
            }
            do {
                try await api.resetPassword(grant: grant, verifier: proof.verifier, newPassword: password)
            } catch let error as APIError {
                if error.isUncertainOutcome {
                    returnToChoice()
                    step = .password
                    notice = "We couldn't confirm the reset. Sign in with your intended new password to check, or request fresh recovery."
                    return
                }
                throw error
            }
            try Task.checkCancellation()
            returnToChoice()
            step = .password
            notice = "Password reset. Sign in with your new password."
        }
    }
    private func stopAttempt() {
        coordinator.cancel()
        if let attempt { Task { await workspace.cancelSignIn(attempt) } }
        attempt = nil
        clearSecrets()
    }
    private func clearSecrets() {
        proof = nil; challenge = nil; resetGrant = nil; resetExpiry = nil
        code = ""; password = ""; repeatedPassword = ""
    }
    private func returnToChoice() {
        stopAttempt()
        step = .choice
        failureMessage = nil
        failureReferenceID = nil
        focused = .email
    }
    private func cancelAndDismiss() {
        cancelCurrentOperation()
        dismiss()
    }
    private func cancelCurrentOperation() {
        operationID = UUID()
        operation?.cancel()
        operation = nil
        stopAttempt()
        isBusy = false
    }
    private func reference(_ error: WorkspaceError) -> String? {
        if case .signInFailed(_, let reference) = error { return reference }
        return nil
    }
    private func showFailure(_ message: String, reference: String?) {
        failureMessage = message
        failureReferenceID = reference
        UIAccessibility.post(notification: .announcement, argument: message)
    }
}

// MARK: - Pure helpers (no SwiftUI)

/// Server address rules: https anywhere, http only for localhost (development).
enum SignInServerAddress {
    static var defaultString: String { string(AppConstants.defaultServerURL) }

    // `AppConstants.defaultServerURL` reads the same whether it is a URL or a String.
    private static func string(_ url: URL) -> String { url.absoluteString }
    private static func string(_ text: String) -> String { text }

    /// A usable API base URL, or nil. A missing scheme means https.
    static func url(from text: String) -> URL? {
        var candidate = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !candidate.isEmpty else { return nil }
        if !candidate.contains("://") { candidate = "https://" + candidate }
        guard let components = URLComponents(string: candidate),
            let scheme = components.scheme?.lowercased(),
            let host = components.host?.lowercased(), !host.isEmpty,
            let url = components.url
        else { return nil }
        switch scheme {
        case "https": return url
        case "http": return isLocalHost(host) ? url : nil
        default: return nil
        }
    }

    /// App Transport Security lets plain http reach only the unqualified
    /// `localhost`, so that is the one development host accepted.
    static func isLocalHost(_ host: String) -> Bool {
        host == "localhost"
    }
}

import AuthenticationServices
import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// "Confirm it's you" (spec 033 FR-004): every change on the Account screens first proves the
/// person is the account's owner, with a way to sign in this account already has: its password,
/// a code to its own email, or Apple or Google. The proof is for `action` only and lasts minutes.
/// No board draws this step; it uses the same glass sheet as boards 27 and 28.
struct AccountConfirmSheet: View {
    let model: AccountSecurityModel
    let action: AccountAction
    let onConfirmed: (RecentProof) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var coordinator = ModernAuthCoordinator()
    @State private var password = ""
    @State private var codeStep: AccountEmailCode?
    @State private var code = ""
    @State private var isBusy = false
    @State private var failure: AccountActionFailure?
    @FocusState private var passwordFocused: Bool

    private var options: AccountConfirmationOptions { model.confirmationOptions }
    private var email: String { model.methods?.email ?? "" }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.md)) {
                Text(codeStep == nil ? "Confirm it's you" : "Check your email")
                    .carryOnFont(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                if let codeStep {
                    codeEntry(codeStep)
                } else {
                    choices
                }
                if let failure {
                    EditorValidationMessage(text: failure.message)
                    if let reference = failure.referenceID {
                        Text("Reference ID: \(reference)")
                            .font(.footnote.monospaced())
                            .foregroundStyle(.coTextSecondary)
                            .textSelection(.enabled)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, CGFloat(CarryOnSpace.lg))
            .padding(.top, CGFloat(CarryOnSpace.lg))
            .padding(.bottom, CGFloat(CarryOnSpace.md))
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            BBGlassActionBar {
                if codeStep != nil || options.password {
                    Button {
                        if let codeStep { submit(codeStep) } else { confirmWithPassword() }
                    } label: {
                        HStack(spacing: CGFloat(CarryOnSpace.xs)) {
                            if isBusy { ProgressView() }
                            Text("Confirm")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.carryOnStrong)
                    .disabled(!canConfirm)
                }
                Button {
                    cancel()
                } label: {
                    Text("Cancel").frame(maxWidth: codeStep != nil || options.password ? nil : .infinity)
                }
                .buttonStyle(.carryOnQuiet)
            }
        }
        .bbScreenBackground()
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(isBusy)
        .onAppear { passwordFocused = options.password }
        .onDisappear { coordinator.cancel(); coordinator.stopMonitoring() }
    }

    // MARK: Steps

    @ViewBuilder private var choices: some View {
        Text("Continue as \(email). Only a way to sign in this account already has can confirm it. It lasts five minutes.")
            .carryOnFont(CarryOnTypeScale.meta)
            .foregroundStyle(.coTextSecondary)
        if options.password {
            SecureField("Current password", text: $password)
                .textContentType(.password)
                .focused($passwordFocused)
                .submitLabel(.done)
                .onSubmit { if canConfirm { confirmWithPassword() } }
                .accountField()
                .disabled(isBusy)
        }
        if options.emailCode {
            Button("Send a code to \(email)") { sendCode() }
                .accountLink()
                .disabled(isBusy)
        }
        ForEach(options.providers, id: \.self) { provider in
            Button("Confirm with \(provider == .apple ? "Apple" : "Google")") { confirm(with: provider) }
                .buttonStyle(.carryOnSecondary)
                .frame(maxWidth: .infinity)
                .disabled(isBusy || !coordinator.isOnline)
        }
        if options.isEmpty {
            Text("None of this account's ways to sign in can confirm it right now. Try again later.")
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
        }
        Text("Your account and tasks stay as they are if you cancel.")
            .carryOnFont(CarryOnTypeScale.meta)
            .foregroundStyle(.coTextSecondary)
    }

    @ViewBuilder private func codeEntry(_ step: AccountEmailCode) -> some View {
        Text("We sent a code to \(Text(step.email).foregroundStyle(.coTextPrimary).fontWeight(.semibold)).")
            .carryOnFont(CarryOnTypeScale.meta)
            .foregroundStyle(.coTextSecondary)
        CodeBoxesField(code: $code) { submit(step) }
            .disabled(isBusy)
        TimelineView(.periodic(from: .now, by: 1)) { context in
            let seconds = max(0, Int(step.challenge.resendAt.timeIntervalSince(context.date).rounded(.up)))
            Button(seconds > 0 ? "Send again in \(seconds)s" : "Send again") { resend(step) }
                .accountLink()
                .disabled(seconds > 0 || isBusy || context.date >= step.challenge.expiresAt)
        }
    }

    private var canConfirm: Bool {
        guard !isBusy else { return false }
        if codeStep != nil { return code.count == 6 }
        return !password.isEmpty
    }

    // MARK: Actions

    private func confirmWithPassword() {
        let entered = password
        run { try await model.confirm(password: entered, for: action) }
    }

    private func sendCode() {
        runStep { try await model.sendConfirmationCode(for: action) }
    }

    private func resend(_ step: AccountEmailCode) {
        runStep { try await model.resend(step) }
    }

    private func submit(_ step: AccountEmailCode) {
        guard canConfirm else { return }
        let entered = code
        run {
            guard case .confirmed(let proof) = try await model.submit(code: entered, for: step) else {
                throw AccountActionFailure.wrongAccount
            }
            return proof
        }
    }

    private func confirm(with provider: NativeAuthProvider) {
        run {
            let attempt = try await model.startProvider(provider, linking: false, action: action, proof: nil)
            let credential = try await coordinator.authenticate(provider: attempt.provider, start: attempt.start, verifier: attempt.verifier)
            return try await model.finishProviderConfirmation(credential)
        }
    }

    private func cancel() {
        coordinator.cancel()
        dismiss()
    }

    /// Runs one step that ends in a proof; on success the sheet closes and hands it over.
    private func run(_ body: @escaping @MainActor () async throws -> RecentProof) {
        perform {
            let proof = try await body()
            password = ""
            code = ""
            dismiss()
            onConfirmed(proof)
        }
    }

    /// Runs one step that sends or resends a code.
    private func runStep(_ body: @escaping @MainActor () async throws -> AccountEmailCode) {
        perform {
            codeStep = try await body()
            code = ""
        }
    }

    private func perform(_ body: @escaping @MainActor () async throws -> Void) {
        guard !isBusy else { return }
        isBusy = true
        failure = nil
        Task { @MainActor in
            defer { isBusy = false }
            do {
                try await body()
            } catch let error as AccountActionFailure {
                show(error)
            } catch let error as ModernAuthCoordinator.Failure {
                show(AccountActionFailure(message: error.message))
            } catch {
                // Cancelling Apple's or Google's own sheet is not a failure.
                let cancelled = error is CancellationError
                    || (error as? ASAuthorizationError)?.code == .canceled
                    || (error as? ASWebAuthenticationSessionError)?.code == .canceledLogin
                if !cancelled { show(AccountActionFailure(message: "Couldn't confirm it's you. Try again.")) }
            }
        }
    }

    private func show(_ error: AccountActionFailure) {
        failure = error
        UIAccessibility.post(notification: .announcement, argument: error.message)
    }
}

extension View {
    /// A text field on a surface-card, as on boards 05 and 27.
    func accountField() -> some View {
        carryOnFont(CarryOnTypeScale.body)
            .padding(.horizontal, CGFloat(CarryOnSpace.md))
            .frame(minHeight: 44)
            .background(.coSurfaceCard, in: RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous))
    }

    /// A small text link: meta, secondary, a 44 pt target.
    func accountLink() -> some View {
        buttonStyle(.plain)
            .carryOnFont(CarryOnTypeScale.meta)
            .foregroundStyle(.coTextSecondary)
            .frame(minHeight: 44, alignment: .leading)
            .contentShape(Rectangle())
    }
}

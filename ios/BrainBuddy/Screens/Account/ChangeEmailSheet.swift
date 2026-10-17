import AuthenticationServices
import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// Board 27: change the account's email in two steps (a code to the new address), or verify the
/// current one (the code step alone). Each step first asks "Confirm it's you" in a nested sheet.
/// The current address stays in use until the code is accepted.
struct ChangeEmailSheet: View {
    enum Mode {
        case change
        /// The code for the account's own address is already on its way.
        case verify(AccountEmailCode)
    }

    let model: AccountSecurityModel
    let onFinished: (String) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var newEmail = ""
    @State private var codeStep: AccountEmailCode?
    @State private var code = ""
    @State private var isConfirming = false
    @State private var isBusy = false
    @State private var failure: AccountActionFailure?
    @FocusState private var emailFocused: Bool
    private let isVerify: Bool

    init(model: AccountSecurityModel, mode: Mode, onFinished: @escaping (String) -> Void) {
        self.model = model
        self.onFinished = onFinished
        switch mode {
        case .change:
            isVerify = false
            _codeStep = State(initialValue: nil)
        case .verify(let step):
            isVerify = true
            _codeStep = State(initialValue: step)
        }
    }

    private var trimmedEmail: String { newEmail.trimmingCharacters(in: .whitespacesAndNewlines) }
    private var canContinue: Bool { !isBusy && trimmedEmail.contains("@") }
    private var canConfirm: Bool { !isBusy && code.count == 6 }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.md)) {
                Text(isVerify ? "Verify your email" : "Change your email")
                    .carryOnFont(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                if let codeStep {
                    codeEntry(codeStep)
                } else {
                    addressEntry
                }
                if let failure {
                    AccountFailureMessage(failure: failure)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, CGFloat(CarryOnSpace.lg))
            .padding(.top, CGFloat(CarryOnSpace.lg))
            .padding(.bottom, CGFloat(CarryOnSpace.md))
        }
        .safeAreaInset(edge: .bottom, spacing: 0) { actionBar }
        .bbScreenBackground()
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(isBusy)
        .onAppear { emailFocused = codeStep == nil }
        .sheet(isPresented: $isConfirming) {
            AccountConfirmSheet(model: model, action: .changeEmail) { proof in startChange(proof) }
        }
    }

    // MARK: Steps

    @ViewBuilder private var addressEntry: some View {
        TextField("New email", text: $newEmail)
            .textContentType(.emailAddress)
            .keyboardType(.emailAddress)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .focused($emailFocused)
            .submitLabel(.continue)
            .onSubmit { if canContinue { isConfirming = true } }
            .accountField()
            .disabled(isBusy)
        Text("Your current email stays in use until both steps succeed.")
            .carryOnFont(CarryOnTypeScale.body)
            .foregroundStyle(.coTextSecondary)
        Text("Step 1 of 2")
            .carryOnFont(CarryOnTypeScale.meta)
            .foregroundStyle(.coTextSecondary)
    }

    @ViewBuilder private func codeEntry(_ step: AccountEmailCode) -> some View {
        let address = Text(step.email).foregroundStyle(.coTextPrimary).fontWeight(.semibold)
        Group {
            if isVerify {
                Text("We sent a code to \(address).")
            } else {
                Text("We sent a code to \(address). Your current email stays in use until both steps succeed.")
            }
        }
        .carryOnFont(CarryOnTypeScale.body)
        .foregroundStyle(.coTextSecondary)
        CodeBoxesField(code: $code) { submit(step) }
            .disabled(isBusy)
        HStack {
            if !isVerify {
                Text("Step 2 of 2")
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
            }
            Spacer(minLength: 0)
            TimelineView(.periodic(from: .now, by: 1)) { context in
                let seconds = max(0, Int(step.challenge.resendAt.timeIntervalSince(context.date).rounded(.up)))
                Button(seconds > 0 ? "Send again in \(seconds)s" : "Send again") { resend(step) }
                    .accountLink()
                    .disabled(seconds > 0 || isBusy || context.date >= step.challenge.expiresAt)
            }
        }
    }

    private var actionBar: some View {
        BBGlassActionBar {
            Button {
                if let codeStep { submit(codeStep) } else { isConfirming = true }
            } label: {
                HStack(spacing: CGFloat(CarryOnSpace.xs)) {
                    if isBusy { ProgressView() }
                    Text(codeStep == nil ? "Continue" : "Confirm")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.carryOnStrong)
            .disabled(codeStep == nil ? !canContinue : !canConfirm)
            Button {
                dismiss()
            } label: {
                Text("Cancel")
            }
            .buttonStyle(.carryOnQuiet)
        }
    }

    // MARK: Actions

    private func startChange(_ proof: RecentProof) {
        let address = trimmedEmail
        perform {
            codeStep = try await model.startEmailChange(to: address, proof: proof)
            code = ""
        }
    }

    private func resend(_ step: AccountEmailCode) {
        perform {
            codeStep = try await model.resend(step)
            code = ""
        }
    }

    private func submit(_ step: AccountEmailCode) {
        guard canConfirm else { return }
        let entered = code
        perform {
            let message: String
            switch try await model.submit(code: entered, for: step) {
            case .changed(let email): message = "Email changed to \(email)."
            case .verified: message = "Email verified."
            case .confirmed: throw AccountActionFailure.wrongAccount
            }
            dismiss()
            onFinished(message)
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
            } catch {
                if let found = AccountActionFailure.describing(error) {
                    failure = found
                    UIAccessibility.post(notification: .announcement, argument: found.message)
                }
            }
        }
    }
}

/// A failed account action in words, with the reference id to quote when there is one.
struct AccountFailureMessage: View {
    let failure: AccountActionFailure

    var body: some View {
        EditorValidationMessage(text: failure.message)
        if let reference = failure.referenceID {
            Text("Reference ID: \(reference)")
                .font(.footnote.monospaced())
                .foregroundStyle(.coTextSecondary)
                .textSelection(.enabled)
        }
    }
}

extension AccountActionFailure {
    /// What to tell the person about `error`; nil when they cancelled Apple's or Google's own sheet.
    static func describing(_ error: any Error) -> AccountActionFailure? {
        if let failure = error as? AccountActionFailure { return failure }
        if let failure = error as? ModernAuthCoordinator.Failure {
            return AccountActionFailure(message: failure.message)
        }
        let cancelled = error is CancellationError
            || (error as? ASAuthorizationError)?.code == .canceled
            || (error as? ASWebAuthenticationSessionError)?.code == .canceledLogin
        return cancelled ? nil : AccountActionFailure(message: "Something went wrong. Try again.")
    }
}

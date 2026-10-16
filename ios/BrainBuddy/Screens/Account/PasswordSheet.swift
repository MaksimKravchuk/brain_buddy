import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// Adds or replaces the account's password. Save first asks "Confirm it's you" in a nested sheet,
/// then sets the password; other devices are signed out and this one stays.
struct PasswordSheet: View {
    let model: AccountSecurityModel
    let onSaved: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var password = ""
    @State private var repeated = ""
    @State private var attempted = false
    @State private var isConfirming = false
    @State private var isBusy = false
    @State private var failure: AccountActionFailure?
    @FocusState private var passwordFocused: Bool

    private var hasPassword: Bool { model.methods?.hasPassword == true }

    /// Shown only after the person tries to save.
    private var problem: String? {
        attempted ? AccountSecurityModel.passwordProblem(password, repeated: repeated) : nil
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.md)) {
                Text(hasPassword ? "Change password" : "Add password")
                    .carryOnFont(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                SecureField("New password", text: $password)
                    .textContentType(.newPassword)
                    .focused($passwordFocused)
                    .submitLabel(.next)
                    .accountField()
                    .disabled(isBusy)
                SecureField("Repeat password", text: $repeated)
                    .textContentType(.newPassword)
                    .submitLabel(.done)
                    .onSubmit { save() }
                    .accountField()
                    .disabled(isBusy)
                if let problem {
                    EditorValidationMessage(text: problem)
                } else {
                    Text("At least \(AccountSecurityModel.minimumPasswordLength) characters. Longer is better.")
                        .carryOnFont(CarryOnTypeScale.meta)
                        .foregroundStyle(.coTextSecondary)
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
        .safeAreaInset(edge: .bottom, spacing: 0) {
            BBGlassActionBar {
                Button {
                    save()
                } label: {
                    HStack(spacing: CGFloat(CarryOnSpace.xs)) {
                        if isBusy { ProgressView() }
                        Text("Save")
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(.carryOnStrong)
                .disabled(isBusy)
                Button {
                    dismiss()
                } label: {
                    Text("Cancel")
                }
                .buttonStyle(.carryOnQuiet)
            }
        }
        .bbScreenBackground()
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(isBusy)
        .onAppear { passwordFocused = true }
        .sheet(isPresented: $isConfirming) {
            AccountConfirmSheet(model: model, action: .password) { proof in setPassword(proof) }
        }
    }

    private func save() {
        guard !isBusy else { return }
        attempted = true
        failure = nil
        if AccountSecurityModel.passwordProblem(password, repeated: repeated) == nil { isConfirming = true }
    }

    private func setPassword(_ proof: RecentProof) {
        guard !isBusy else { return }
        let entered = password
        let again = repeated
        isBusy = true
        failure = nil
        Task { @MainActor in
            defer { isBusy = false }
            do {
                try await model.setPassword(entered, repeated: again, proof: proof)
                password = ""
                repeated = ""
                dismiss()
                onSaved()
            } catch {
                if let found = AccountActionFailure.describing(error) {
                    failure = found
                    UIAccessibility.post(notification: .announcement, argument: found.message)
                }
            }
        }
    }
}

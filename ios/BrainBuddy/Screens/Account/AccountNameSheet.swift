import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// Changing the name (spec 033 FR-003, board 25). An empty name clears it, so the account goes by
/// its email. A name needs no proof of identity.
struct AccountNameSheet: View {
    let model: AccountSecurityModel

    @Environment(\.dismiss) private var dismiss
    @State private var text: String
    @State private var isBusy = false
    @State private var failure: AccountActionFailure?
    @FocusState private var focused: Bool

    init(model: AccountSecurityModel) {
        self.model = model
        _text = State(initialValue: model.displayName)
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.sm)) {
                Text("Name")
                    .carryOnFont(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                TextField("Name", text: $text)
                    .textContentType(.name)
                    .focused($focused)
                    .submitLabel(.done)
                    .onSubmit { save() }
                    .accountField()
                    .disabled(isBusy)
                Text("Leave it empty to go by your email")
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                if let failure {
                    EditorValidationMessage(text: failure.message)
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
                .disabled(isBusy)
            }
        }
        .bbScreenBackground()
        .presentationDetents([.medium])
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(isBusy)
        .onAppear { focused = true }
    }

    private func save() {
        guard !isBusy else { return }
        isBusy = true
        failure = nil
        let entered = text
        Task { @MainActor in
            defer { isBusy = false }
            do throws(AccountActionFailure) {
                try await model.saveName(entered)
                dismiss()
            } catch {
                failure = error
                UIAccessibility.post(notification: .announcement, argument: error.message)
            }
        }
    }
}

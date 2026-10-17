import BrainBuddyDesign
import SwiftUI

/// Board 28: "Delete your account?" It says what happens before asking to confirm it is you.
/// "Delete" closes this sheet and reports it; the Account screen then presents the confirm step,
/// so two sheets are never stacked.
struct DeleteAccountSheet: View {
    let onDelete: () -> Void

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.sm)) {
                Text("Delete your account?")
                    .carryOnFont(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                Text("Your sessions end now. Your account and data are removed for good after 14 days.")
                    .carryOnFont(CarryOnTypeScale.body)
                    .foregroundStyle(.coTextPrimary)
                Text("Signing in during those 14 days cancels it.")
                    .carryOnFont(CarryOnTypeScale.body)
                    .foregroundStyle(.coTextPrimary)
                Text("Changes not yet sent from this iPhone stay here until you sign out.")
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, CGFloat(CarryOnSpace.lg))
            .padding(.top, CGFloat(CarryOnSpace.lg))
            .padding(.bottom, CGFloat(CarryOnSpace.md))
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            BBGlassActionBar {
                Button {
                    dismiss()
                } label: {
                    Text("Keep account").frame(maxWidth: .infinity)
                }
                .buttonStyle(.carryOnStrong)
                .keyboardShortcut(.defaultAction)
                Button {
                    dismiss()
                    onDelete()
                } label: {
                    Text("Delete").foregroundStyle(.coStatusDanger)
                }
                .buttonStyle(.carryOnQuiet)
            }
        }
        .bbScreenBackground()
        .presentationDetents([.medium])
        .presentationDragIndicator(.visible)
    }
}

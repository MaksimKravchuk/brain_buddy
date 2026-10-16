import BrainBuddyCore
import BrainBuddyDesign
import SwiftUI

/// What "Not now" (board 15) chose. Each is an action the task card already
/// has: setting the due date, moving to Waiting for (which asks who) or to
/// Someday / maybe, and editing the title.
enum NotNowChoice: Hashable {
    case pickDay, waiting, someday, changeStep
}

/// Board 15: "Not now. Then when?" for a next action. It asks instead of
/// hiding the task: four options, and "Keep it in Next actions", which only
/// closes the sheet. A choice is reported, then the sheet closes; the task
/// card acts on it once the sheet has gone, so a sheet it opens next (the date
/// picker, Move) is never presented over this one.
struct NotNowSheet: View {
    private let taskTitle: String
    private let onChoose: (NotNowChoice) -> Void

    @Environment(\.dismiss) private var dismiss

    init(taskTitle: String, onChoose: @escaping (NotNowChoice) -> Void) {
        self.taskTitle = taskTitle
        self.onChoose = onChoose
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xs)) {
                Text("Not now. Then when?")
                    .carryOnText(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                Text(taskTitle)
                    .carryOnText(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                    .padding(.bottom, CGFloat(CarryOnSpace.xs))
                option(
                    .pickDay, systemImage: BBSymbol.dueDate, title: "Pick a day",
                    detail: "Set a due day. It shows in Today then"
                )
                option(
                    .waiting, systemImage: OpenList.waiting.symbolName, title: "Waiting on someone",
                    detail: "Say who, and it moves to Waiting for"
                )
                option(
                    .someday, systemImage: OpenList.someday.symbolName, title: "Someday",
                    detail: "Off your plate, kept for the weekly review"
                )
                option(
                    .changeStep, systemImage: "stairs", title: "Change the step",
                    detail: "Rewrite it smaller, so you can start"
                )
            }
            .padding(.horizontal, CGFloat(CarryOnSpace.lg))
            .padding(.top, CGFloat(CarryOnSpace.lg))
            .padding(.bottom, CGFloat(CarryOnSpace.md))
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            BBGlassActionBar {
                Button {
                    dismiss()
                } label: {
                    Text("Keep it in Next actions")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.carryOnQuiet)
            }
        }
        .bbScreenBackground()
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    /// One option card: symbol, title, what it does, and a chevron.
    private func option(_ choice: NotNowChoice, systemImage: String, title: String, detail: String) -> some View {
        Button {
            onChoose(choice)
            dismiss()
        } label: {
            HStack(spacing: CGFloat(CarryOnSpace.sm)) {
                Image(systemName: systemImage)
                    .font(BBFont.body)
                    .foregroundStyle(.coTextPrimary)
                    .frame(width: BBMetrics.iconColumn)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 0) {
                    Text(title)
                        .carryOnText(CarryOnTypeScale.body)
                        .foregroundStyle(.coTextPrimary)
                    Text(detail)
                        .carryOnText(CarryOnTypeScale.meta)
                        .foregroundStyle(.coTextSecondary)
                }
                .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(BBFont.meta)
                    .foregroundStyle(.coTextSecondary)
                    .accessibilityHidden(true)
            }
            .padding(.vertical, CGFloat(CarryOnSpace.sm))
            .padding(.horizontal, CGFloat(CarryOnLayout.Row.paddingX))
            .frame(minHeight: BBMetrics.hitTarget)
            .background(
                .coSurfaceCard, in: RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous)
            )
            .contentShape(RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// Board 03: one question turns the capture into a step. "Make it my next step" (the only
/// terracotta) makes the step the item's text, keeps the captured words in its note and moves
/// it to Next actions; "Not yet" leaves it in the Inbox unchanged and opens the app.
struct FirstStepScreen: View {
    private typealias Layout = CarryOnLayout.FirstRun

    let taskID: TaskID

    @Environment(PhoneFirstRunFlow.self) private var flow
    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @State private var step = ""
    @State private var isSaving = false
    /// One id per attempt, so a retry after a failed save is the same command.
    @State private var editorID = UUID().uuidString
    @FocusState private var isFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text("From your Inbox")
                    .carryOnText(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                Text(captured)
                    .carryOnText(FirstRunType.large)
                    .foregroundStyle(.coTextPrimary)
                    .padding(.top, Layout.sourceGap)
                Text("What is the first step you could take?")
                    .carryOnText(FirstRunType.question)
                    .foregroundStyle(.coTextPrimary)
                    .padding(.top, Layout.questionGap)
                    .accessibilityAddTraits(.isHeader)
                FirstRunField(
                    label: "What is the first step you could take?", text: $step, style: FirstRunType.step,
                    focus: $isFocused
                )
                .submitLabel(.done)
                .onSubmit(makeNextStep)
                .padding(.top, Layout.stepFieldGap)
                Text("Small enough to start today. Not sure yet? Leave it in the Inbox.")
                    .carryOnText(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                    .padding(.top, Layout.hintGap)
            }
            .padding(.horizontal, Layout.side)
            .padding(.top, Layout.top)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .scrollBounceBehavior(.basedOnSize)
        .safeAreaInset(edge: .bottom, spacing: 0) {
            BBGlassActionBar {
                Button("Not yet") {
                    flow.notYet()
                }
                .buttonStyle(.carryOnQuiet)
                Button(action: makeNextStep) {
                    Text("Make it my next step")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.carryOnGlassPrimary)
                .disabled(isEmpty || isSaving)
            }
        }
        .task { isFocused = true }
    }

    /// The words as captured; the item's title if the flow no longer holds them.
    private var captured: String {
        flow.capturedText ?? workspace.task(taskID)?.title ?? ""
    }

    private var isEmpty: Bool { step.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    private func makeNextStep() {
        guard !isSaving, !isEmpty else { return }
        isSaving = true
        let step = step
        let editorID = editorID
        Task {
            let saved = await TaskCommandRunner.run(toasts) {
                _ = try await flow.makeNextStep(step, in: workspace, editorID: editorID)
            }
            if saved { self.editorID = UUID().uuidString }
            isSaving = false
        }
    }
}

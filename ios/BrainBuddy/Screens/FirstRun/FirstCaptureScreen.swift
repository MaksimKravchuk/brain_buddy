import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// Board 02: the first capture is the real one. The field has the keyboard at once; "Add to
/// Inbox" saves exactly the words written (no Smart Add) and asks for a first step; "Skip"
/// leaves an empty Inbox and opens the app.
struct FirstCaptureScreen: View {
    private typealias Layout = CarryOnLayout.FirstRun

    @Environment(PhoneFirstRunFlow.self) private var flow
    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @State private var text = ""
    @State private var isSaving = false
    /// One id per attempt, so a retry after a failed save is the same command.
    @State private var editorID = UUID().uuidString
    @FocusState private var isFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                Text("What feels heaviest?")
                    .carryOnText(CarryOnTypeScale.display)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                Text("Say it as it is. You sort it in a moment.")
                    .carryOnText(CarryOnTypeScale.body)
                    .foregroundStyle(.coTextSecondary)
                    .padding(.top, Layout.subtitleGap)
                FirstRunField(
                    label: "What feels heaviest?", text: $text, style: FirstRunType.large, axis: .vertical,
                    minHeight: Layout.fieldMinHeight, focus: $isFocused
                )
                .padding(.top, Layout.fieldGap)
                Text("It goes to your Inbox, as you wrote it.")
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
                Button("Skip") {
                    flow.skip()
                }
                .buttonStyle(.carryOnQuiet)
                Button(action: add) {
                    Text("Add to Inbox")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.carryOnStrong)
                .disabled(isEmpty || isSaving)
            }
        }
        .task { isFocused = true }
    }

    private var isEmpty: Bool { text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    private func add() {
        guard !isSaving, !isEmpty else { return }
        isSaving = true
        let text = text
        let editorID = editorID
        Task {
            let saved = await TaskCommandRunner.run(toasts) {
                _ = try await flow.capture(text, in: workspace, editorID: editorID)
            }
            if saved { self.editorID = UUID().uuidString }
            isSaving = false
        }
    }
}

import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// F-02 (029-FR-008 – 029-FR-010, 029-FR-031): the first step, asked in the inspector's own panel.
/// Return chooses "Make it my next step" once a step is written; Esc is "Not yet". A failed save
/// leaves the question and the item as they were (the window shows the existing save error).
struct FirstStepInspector: View {
    let firstRun: FirstRunModel
    let writer: any FirstRunTaskWriting
    /// The item as captured, shown above the question.
    let original: String
    @State private var step = ""
    @State private var saving = false
    @FocusState private var stepFocused: Bool

    private var ready: Bool { !saving && !step.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        MacInspectorPanel(width: TaskInspector.width(for: .inbox)) {
            VStack(alignment: .leading, spacing: 0) {
                MacInspectorEyebrow(projectName: nil, projectColor: nil, listName: FirstRunCopy.inspectorHeader)
                MacInspectorItemText(text: original)
                MacInspectorTitle(text: FirstRunCopy.question, serif: true, size: 24).padding(.top, 14)
                TextField("", text: $step)
                    .textFieldStyle(.plain)
                    .font(MacRowFont.title)
                    .foregroundStyle(.coTextPrimary)
                    .focused($stepFocused)
                    .onSubmit(make)
                    .disabled(saving)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                    .background(CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .overlay {
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .strokeBorder(stepFocused ? CarryOnColorStyle.coFocusRing : CarryOnColorStyle.coControlQuiet, lineWidth: 1.5)
                    }
                    .padding(.top, 12)
                    .accessibilityLabel(FirstRunCopy.question)
                MacInspectorBodyText(text: FirstRunCopy.helper, quiet: true, topPadding: 10)
            }
        } actionBar: {
            HStack(spacing: 8) {
                Button(FirstRunCopy.makeNextStep, action: make)
                    .buttonStyle(.carryOnPrimary)
                    .disabled(!ready)
                Button(FirstRunCopy.notYet) { firstRun.notYet() }
                    .buttonStyle(.carryOnQuiet)
                    .keyboardShortcut(.cancelAction)
                    .disabled(saving)
                Spacer(minLength: 0)
            }
        }
        .task { stepFocused = true }
    }

    private func make() {
        guard ready else { return }
        saving = true
        let written = step
        Task {
            _ = await firstRun.makeNextStep(written, using: writer)
            saving = false
        }
    }
}

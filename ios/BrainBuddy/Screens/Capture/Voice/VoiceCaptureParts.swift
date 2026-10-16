import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// One step heard: tap the title to edit it (committed on Return or when focus leaves), a 44 pt
/// × to remove it. The meta line names the project and day, for example "Garage · by Friday".
struct VoiceStepRow: View {
    let step: VoiceBrainDumpModel.Step
    let today: CalendarDay
    let rename: (String) -> Void
    let remove: () -> Void

    @State private var draft = ""
    @State private var isEditing = false
    @FocusState private var isFocused: Bool

    private var meta: String? {
        var parts: [String] = []
        if let project = step.project { parts.append(project.name) }
        if let day = step.dueDate {
            let label = DueChip.label(for: day, today: today)
            parts.append("by " + (["Today", "Tomorrow", "Yesterday"].contains(label) ? label.lowercased() : label))
        }
        return parts.isEmpty ? nil : parts.joined(separator: " \u{00B7} ")
    }

    var body: some View {
        HStack(spacing: CGFloat(CarryOnSpace.sm)) {
            Circle()
                .strokeBorder(CarryOnColorStyle.coStepDotOpen, lineWidth: 2)
                .frame(width: 22, height: 22)
                .accessibilityHidden(true)
            if isEditing {
                TextField("Step", text: $draft)
                    .carryOnFont(CarryOnTypeScale.body)
                    .foregroundStyle(.coTextPrimary)
                    .focused($isFocused)
                    .submitLabel(.done)
                    .onSubmit(commit)
                    .onChange(of: isFocused) { _, focused in if !focused { commit() } }
                    .accessibilityLabel("Step")
                    .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget, alignment: .leading)
            } else {
                Button(action: beginEditing) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(step.title)
                            .carryOnFont(CarryOnTypeScale.body)
                            .foregroundStyle(.coTextPrimary)
                        if let meta {
                            Text(meta)
                                .carryOnFont(CarryOnTypeScale.meta)
                                .foregroundStyle(.coTextSecondary)
                        }
                    }
                    .multilineTextAlignment(.leading)
                    .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget, alignment: .leading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(meta.map { "\(step.title), \($0)" } ?? step.title)
                .accessibilityAction(named: "Edit", beginEditing)
                .accessibilityAction(named: "Remove", remove)
            }
            Button(action: remove) {
                Image(systemName: "xmark")
                    .frame(width: BBMetrics.hitTarget, height: BBMetrics.hitTarget)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .foregroundStyle(.coTextSecondary)
            .accessibilityLabel("Remove \(step.title)")
        }
        .padding(.vertical, CGFloat(CarryOnSpace.xs) / 2)
        .padding(.leading, CGFloat(CarryOnSpace.sm) + 2)
        .padding(.trailing, CGFloat(CarryOnSpace.xs) / 2)
        .background(
            RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous)
                .fill(CarryOnColorStyle.coControlQuiet))
        .accessibilityElement(children: .contain)
    }

    private func beginEditing() {
        draft = step.title
        isEditing = true
        Task { isFocused = true }
    }

    private func commit() {
        guard isEditing else { return }
        isEditing = false
        let title = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        if !title.isEmpty, title != step.title { rename(title) }
    }
}

/// The round voice button's face: `voice-bg` with the mic in `voice-fg`; while listening, a 3 pt
/// `voice-live-ring` inset 2 pt and the board's six bars instead of the mic. Decorative: the
/// button around it carries the label.
struct VoiceButtonFace: View {
    let live: Bool
    var size: CGFloat = 50

    private static let barHeights: [CGFloat] = [8, 18, 26, 14, 22, 10]

    var body: some View {
        ZStack {
            Circle().fill(CarryOnColorStyle.coVoiceBg)
            if live {
                Circle().strokeBorder(CarryOnColorStyle.coVoiceLiveRing, lineWidth: 3).padding(2)
                HStack(spacing: 3) {
                    ForEach(Self.barHeights.indices, id: \.self) { index in
                        RoundedRectangle(cornerRadius: 2, style: .continuous)
                            .fill(CarryOnColorStyle.coVoiceFg)
                            .frame(width: 4, height: Self.barHeights[index])
                    }
                }
            } else {
                Image(systemName: "mic")
                    .font(.system(size: size * 0.4, weight: .medium))
                    .foregroundStyle(CarryOnColorStyle.coVoiceFg)
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// "Add {n} to Inbox": a `surface-card` pill, 50 pt tall, with a `text-primary` label.
struct VoiceAddLabel: View {
    let title: String

    var body: some View {
        Text(title)
            .carryOnFont(CarryOnTypeScale.bodyStrong)
            .foregroundStyle(.coTextPrimary)
            .lineLimit(1)
            .minimumScaleFactor(0.7)
            .padding(.horizontal, CGFloat(CarryOnSpace.md))
            .frame(height: 50)
            .background(Capsule().fill(CarryOnColorStyle.coSurfaceCard))
    }
}

/// What was heard, in quotes, with a thin caret in `text-primary` at the end while listening
/// (a run of the text itself, so it follows the last word as the line wraps).
struct VoiceHeardText: View {
    let text: String
    let showsCaret: Bool

    var body: some View {
        let caret = Text(showsCaret ? " \u{258F}" : "").foregroundStyle(CarryOnColorStyle.coTextPrimary)
        (Text("\u{201C}\(text)\u{201D}").foregroundStyle(CarryOnColorStyle.coTextSecondary) + caret)
            .carryOnFont(CarryOnTypeScale.meta)
            .accessibilityLabel("Heard: \(text)")
    }
}

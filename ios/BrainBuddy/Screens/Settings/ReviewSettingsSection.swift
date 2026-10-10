import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-23 (spec 020), increment 1: the threshold (7 / 14 / 21 / 28 days) in a
/// "Weekly review" section of Settings, shown while the review is exposed.
/// A change is saved at once through `Workspace.updateReviewSettings`
/// (offline too; it syncs later). Core raises the owner's park floor to
/// 7 days from now (FR-039), and the note says so with that date. Day and time
/// arrive with onboarding (a later slice).
struct ReviewSettingsSection: View {
    @Environment(Workspace.self) private var workspace
    /// Set after a change made here, until the screen closes.
    @State private var floorNote: String?
    @State private var problem: String?
    @State private var editorID = UUID().uuidString
    @State private var pendingThreshold: Int?
    @State private var isSaving = false

    init() {}

    var body: some View {
        if workspace.reviewExposed {
            ReviewSettingsContent(
                threshold: Binding(
                    get: { pendingThreshold ?? workspace.state.review.settings.thresholdDays },
                    set: { change(to: $0) }
                ),
                floorNote: floorNote, problem: problem
            )
        }
    }

    private func change(to days: Int) {
        guard days != workspace.state.review.settings.thresholdDays, !isSaving else { return }
        pendingThreshold = days
        isSaving = true
        Task { await changeDurably(to: days) }
    }

    @MainActor private func changeDurably(to days: Int) async {
        defer { isSaving = false }
        problem = nil
        do {
            try await workspace.updateReviewSettings(ReviewSettingsChange(thresholdDays: days), editorID: editorID)
        } catch {
            problem = TaskCommandRunner.message(for: error)
            return
        }
        pendingThreshold = nil
        floorNote = workspace.state.review.settings.ownerParkFloorAt.map {
            ReviewSettingsContent.floorNoteText(until: ReviewCopy.day($0, in: .current))
        }
    }
}

/// The section for given values (every state has a preview).
struct ReviewSettingsContent: View {
    @Binding var threshold: Int
    let floorNote: String?
    let problem: String?

    private static let thresholds = OwnerClockSettings.allowedThresholds.sorted()

    init(threshold: Binding<Int>, floorNote: String?, problem: String?) {
        _threshold = threshold
        self.floorNote = floorNote
        self.problem = problem
    }

    static func floorNoteText(until day: String) -> String {
        "Markers in Next update now. Because of this change, nothing moves to Someday before \(day)."
    }

    var body: some View {
        Section {
            Picker("Ask for a decision after", selection: $threshold) {
                ForEach(Self.thresholds, id: \.self) { days in
                    Text("\(days) days").tag(days)
                }
            }
            if let floorNote {
                Text(floorNote)
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
            }
            if let problem {
                InlineProblemText(message: problem)
            }
        } header: {
            Text(ReviewCopy.weeklyReview)
        } footer: {
            Text("Tasks move to Someday 7 days after they start asking.")
        }
    }
}

// MARK: - Previews (M-23 threshold states)

#Preview("M-23 default") {
    @Previewable @State var threshold = 14
    List {
        ReviewSettingsContent(threshold: $threshold, floorNote: nil, problem: nil)
    }
}

#Preview("M-23 threshold changed") {
    @Previewable @State var threshold = 7
    List {
        ReviewSettingsContent(
            threshold: $threshold, floorNote: ReviewSettingsContent.floorNoteText(until: "Fri 16 Oct"), problem: nil
        )
    }
}

#Preview("M-23 accessibility size") {
    @Previewable @State var threshold = 14
    List {
        ReviewSettingsContent(threshold: $threshold, floorNote: nil, problem: nil)
    }
    .environment(\.dynamicTypeSize, .accessibility5)
}

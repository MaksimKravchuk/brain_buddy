import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-20 (spec 020, FR-032, FR-034): the Someday pass. At most 7 tasks no
/// "keep" hides, never reviewed first; tasks auto-parked in the last 30 days
/// are left out because "While you were away" showed them. Keep in Someday
/// (looks again in 30 days), move to Next with a concrete first action, or
/// cancel; each has the Undo status line.
struct SomedayStep: View {
    let context: ReviewStepContext

    init(context: ReviewStepContext) {
        self.context = context
    }

    @Environment(Workspace.self) private var workspace

    var body: some View {
        ReviewItemStep(
            context: context, step: .someday, list: .someday, emptyTitle: ReviewCopy.nothingInSomeday,
            queue: { workspace.somedayDue(session: context.sessionID).shown },
            meta: { task in
                var parts = [task.projectID.flatMap { workspace.project($0)?.name } ?? ReviewCopy.noProject]
                if task.parked != nil { parts.append(ReviewCopy.markerParked) }
                return parts.joined(separator: " · ")
            },
            choices: [
                ReviewItemChoice(
                    decision: .keepSomeday, title: ReviewCopy.name(of: .keepSomeday),
                    subtitle: ReviewCopy.somedayKeepSubtitle
                ),
                ReviewItemChoice(decision: .returnToNext, title: ReviewCopy.moveToNext, prompt: ReviewCopy.somedayMovePrompt),
                ReviewItemChoice(decision: .cancel, title: ReviewCopy.name(of: .cancel)),
            ]
        )
    }
}

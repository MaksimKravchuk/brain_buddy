import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-11 (spec 020, FR-027 – FR-029): the review's entry from Lists. Quick
/// (about 5 minutes) or Full (about 20), the card for a review in progress on
/// any device, and a neutral line when an earlier review was closed. The
/// review itself opens full screen (`ReviewCover`), which puts onboarding,
/// "While you were away" and restart ahead of the steps when they are due.
struct ReviewEntryScreen: View {
    @Environment(Workspace.self) private var workspace
    @State private var launch: ReviewLaunch?

    init() {}

    var body: some View {
        let page = workspace.reviewPageState(.state)
        let summaryPage = workspace.reviewPageState(.summary(nil))
        let readiness = page.readiness == .ready ? summaryPage.readiness : page.readiness
        ReviewEntryContent(
            model: ReviewEntryModel(workspace: workspace),
            onContinue: { launch = .resume($0) }, onStart: { launch = .new($0) }
        )
        .navigationTitle(ReviewCopy.weeklyReview)
        .navigationBarTitleDisplayMode(.inline)
        .fullScreenCover(item: $launch) { launch in
            ReviewCover(launch: launch)
        }
        .overlay {
            if readiness != .ready {
                WorkspaceQueryContent(readiness: readiness, retry: {
                    Task { try? await workspace.prepareReviewRead(.state); try? await workspace.prepareReviewRead(.summary(nil)) }
                }) { EmptyView() }
            }
        }
        .task { try? await workspace.prepareReviewRead(.state); try? await workspace.prepareReviewRead(.summary(nil)) }
    }
}

/// What the entry shows, resolved once per render.
struct ReviewEntryModel: Hashable {
    struct Resume: Hashable {
        var id: ReviewSessionID
        var title: String
        var detail: String
    }

    var resume: Resume?
    var notice: String?
    var isOffline: Bool
    /// Why the check for a review on other devices failed, with its Ref.
    var problem: String?
    var reference: String?
}

extension ReviewEntryModel {
    @MainActor
    init(workspace: Workspace) {
        var resume: Resume?
        if let open = workspace.state.review.openSession {
            let steps = open.mode.steps
            let step = (steps.firstIndex(of: open.currentStep ?? steps[0]) ?? 0) + 1
            let startedDay =
                Calendar.current.isDateInToday(open.startedAt) ? "today" : ReviewCopy.day(open.startedAt, in: .current)
            resume = Resume(
                id: open.id, title: ReviewCopy.resumeTitle(mode: open.mode, step: step, of: steps.count),
                detail: ReviewCopy.resumeDetail(
                    startedDay: startedDay, time: ReviewCopy.time(open.startedAt, in: .current), origin: open.origin,
                    decisions: open.decisionCount
                )
            )
        }
        var notice: String?
        switch workspace.reviewEntryNotice() {
        case .replacedElsewhere(let origin, let decisions)?:
            notice = ReviewCopy.closedWhenSynced(origin: origin, decisions: decisions)
        case .closedAfterAWeek(let startedAt, let decisions)?:
            notice = ReviewCopy.closedAfterAWeek(on: ReviewCopy.day(startedAt, in: .current), decisions: decisions)
        case nil:
            break
        }
        var isOffline = false
        var problem: String?
        var reference: String?
        switch workspace.syncStatus {
        case .offline: isOffline = true
        case .failing(_, let referenceID, _):
            problem = ReviewCopy.entryCheckFailed
            reference = referenceID
        case .localOnly, .idle, .syncing, .needsSignIn: break
        }
        self.init(resume: resume, notice: notice, isOffline: isOffline, problem: problem, reference: reference)
    }
}

/// The entry for a given model (every state has a preview).
struct ReviewEntryContent: View {
    let model: ReviewEntryModel
    let onContinue: (ReviewSessionID) -> Void
    let onStart: (ReviewMode) -> Void

    @AccessibilityFocusState private var isHeadingFocused: Bool

    init(
        model: ReviewEntryModel, onContinue: @escaping (ReviewSessionID) -> Void,
        onStart: @escaping (ReviewMode) -> Void
    ) {
        self.model = model
        self.onContinue = onContinue
        self.onStart = onStart
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: BBSpacing.s5) {
                Text(model.resume == nil ? ReviewCopy.modePickerQuestion : ReviewCopy.weeklyReview)
                    .font(BBFont.display)
                    .foregroundStyle(BBColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityAddTraits(.isHeader)
                    .accessibilityFocused($isHeadingFocused)
                if let notice = model.notice {
                    Text(notice)
                        .font(BBFont.secondary)
                        .foregroundStyle(BBColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let resume = model.resume {
                    VStack(alignment: .leading, spacing: BBSpacing.s2) {
                        Text(resume.title)
                            .font(BBFont.bodyMedium)
                            .foregroundStyle(BBColor.textPrimary)
                        Text(resume.detail)
                            .font(BBFont.meta)
                            .foregroundStyle(BBColor.textTertiary)
                        ReviewChoiceRow(title: ReviewCopy.continueLabel, isProminent: true) { onContinue(resume.id) }
                    }
                    .padding(BBSpacing.s4)
                    .bbCard()
                    Text(ReviewCopy.startNewReview)
                        .font(BBFont.subtitle)
                        .foregroundStyle(BBColor.textSecondary)
                }
                ReviewChoiceRow(title: ReviewCopy.quickReview, subtitle: ReviewCopy.quickSummary) { onStart(.quick) }
                ReviewChoiceRow(title: ReviewCopy.fullReview, subtitle: ReviewCopy.fullSummary) { onStart(.full) }
                if model.isOffline {
                    Label(ReviewCopy.entryOffline, systemImage: "icloud.slash")
                        .font(BBFont.meta)
                        .foregroundStyle(BBColor.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let problem = model.problem {
                    InlineProblemText(message: problem)
                    if let reference = model.reference {
                        Text("Reference ID: \(reference)")
                            .font(BBFont.caption)
                            .foregroundStyle(BBColor.textTertiary)
                            .textSelection(.enabled)
                    }
                }
            }
            .padding(BBSpacing.s4)
        }
        .bbScreenBackground()
        .onAppear { isHeadingFocused = true }
    }
}

// MARK: - Previews (every M-11 state)

private extension ReviewEntryModel {
    static let picker = ReviewEntryModel(resume: nil, notice: nil, isOffline: false, problem: nil, reference: nil)

    static let resuming = ReviewEntryModel(
        resume: Resume(
            id: ReviewSessionID("review_preview"), title: "Full review · step 4 of 10",
            detail: "Started today at 12:40 on the web. 6 decisions made so far."
        ),
        notice: nil, isOffline: false, problem: nil, reference: nil
    )

    static let closedAfterAWeek = ReviewEntryModel(
        resume: nil, notice: ReviewCopy.closedAfterAWeek(on: "Fri 2 Oct", decisions: 6), isOffline: false,
        problem: nil, reference: nil
    )

    static let replacedOffline = ReviewEntryModel(
        resume: resuming.resume, notice: ReviewCopy.closedWhenSynced(origin: .web, decisions: 6), isOffline: true,
        problem: nil, reference: nil
    )

    static let checkFailed = ReviewEntryModel(
        resume: nil, notice: nil, isOffline: false, problem: ReviewCopy.entryCheckFailed, reference: "3f2c9a"
    )
}

#Preview("M-11 mode picker") {
    NavigationStack { ReviewEntryContent(model: .picker, onContinue: { _ in }, onStart: { _ in }) }
}

#Preview("M-11 resume") {
    NavigationStack { ReviewEntryContent(model: .resuming, onContinue: { _ in }, onStart: { _ in }) }
}

#Preview("M-11 earlier review closed after a week") {
    NavigationStack { ReviewEntryContent(model: .closedAfterAWeek, onContinue: { _ in }, onStart: { _ in }) }
}

#Preview("M-11 offline review replaced another") {
    NavigationStack { ReviewEntryContent(model: .replacedOffline, onContinue: { _ in }, onStart: { _ in }) }
}

#Preview("M-11 check failed") {
    NavigationStack { ReviewEntryContent(model: .checkFailed, onContinue: { _ in }, onStart: { _ in }) }
}

#Preview("M-11 accessibility size") {
    NavigationStack { ReviewEntryContent(model: .resuming, onContinue: { _ in }, onStart: { _ in }) }
        .environment(\.dynamicTypeSize, .accessibility5)
}

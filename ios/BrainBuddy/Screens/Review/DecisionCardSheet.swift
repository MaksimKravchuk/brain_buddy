import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

// MARK: - Opening the card

/// Opens the decision card (M-03) for a task. The screen that can present
/// the card provides it (`TaskListScreen`); where nobody does, a marker is
/// display-only and the row still opens the task.
struct OpenDecisionCardAction {
    let run: @MainActor (TaskID) -> Void

    init(_ run: @escaping @MainActor (TaskID) -> Void) {
        self.run = run
    }
}

private struct OpenDecisionCardKey: EnvironmentKey {
    static var defaultValue: OpenDecisionCardAction? { nil }
}

extension EnvironmentValues {
    /// How a marker chip opens the decision card, when its screen offers it.
    var openDecisionCard: OpenDecisionCardAction? {
        get { self[OpenDecisionCardKey.self] }
        set { self[OpenDecisionCardKey.self] = newValue }
    }
}

/// The task a decision card is shown for (`.sheet(item:)`).
struct DecisionCardTarget: Identifiable, Hashable {
    let taskID: TaskID
    var id: TaskID { taskID }
}

/// The review step around a card (M-16): decisions count in this run, "Not
/// now" replaces Close, and a decision hands over to the step, which shows
/// the Undo status line and the next card, instead of closing the card.
struct ReviewDecisionContext {
    let sessionID: ReviewSessionID
    let position: String
    let onDecided: (DecisionID, DecisionType, String) -> Void
    let onNotNow: () -> Void
}

// MARK: - The card

/// M-03 (spec 020): one task, one decision, as a large sheet outside a review
/// (FR-047, `ReviewPresentation.decisionCard(inReview: false)`). Seven
/// decisions in a fixed order, an optional stall reason that marks one of
/// them "Recommended" without disabling any (FR-007), the third-stall offer
/// (FR-005; iOS has no canvas, so only "Release to Someday"), and stale
/// protection (FR-011): when the task changed in any way since the card
/// opened (Core compares its revision and `updatedAt`), nothing is applied
/// and the card says so. When the review stops being exposed the card closes. Every rule is Core's; the card
/// dispatches through `Workspace.decide`, which applies offline and queues
/// the decision. Two-step decisions push their form (M-04).
struct DecisionCardSheet: View {
    let taskID: TaskID
    /// Inside a review (M-16); nil for the large sheet outside one.
    let review: ReviewDecisionContext?

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.dismiss) private var dismiss
    /// The wording the card was opened on: a change elsewhere makes it stale.
    @State private var opened: OpenedWording?
    @State private var stallReason: StallReason?
    @State private var path: [DecisionForm] = []
    /// A pushed form holds unsaved text (FR-052): swipe-down is blocked.
    @State private var formIsDirty = false
    @State private var problem: String?
    @State private var isStale = false
    @State private var hasDecided = false

    init(taskID: TaskID, review: ReviewDecisionContext? = nil) {
        self.taskID = taskID
        self.review = review
    }

    var body: some View {
        NavigationStack(path: $path) {
            root
                .navigationTitle("Decide")
                .navigationBarTitleDisplayMode(.inline)
                .safeAreaInset(edge: .top) {
                    if let review {
                        Text(review.position)
                            .font(BBFont.meta)
                            .foregroundStyle(BBColor.textTertiary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, BBSpacing.s4)
                    }
                }
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) {
                        Button(review == nil ? "Close" : ReviewCopy.notNow, action: closeCard)
                    }
                }
                .navigationDestination(for: DecisionForm.self) { form in
                    DecisionFormView(
                        form: form, taskID: taskID, formulationID: opened?.formulationID, stallReason: stallReason,
                        sessionID: review?.sessionID, isDirty: $formIsDirty,
                        onSaved: { decisionID, decision, title in
                            finish(decisionID, decision: decision, title: title)
                        },
                        onStale: {
                            isStale = true
                            path = []
                        },
                        onCloseCard: closeCard,
                        expectedTask: opened?.stamp
                    )
                }
        }
        // FR-047: a large sheet outside a review (ReviewPresentation.largeSheet).
        .presentationDetents([.large])
        .interactiveDismissDisabled(formIsDirty)
        .onAppear(perform: recordOpenedWording)
        .onChange(of: path) { _, newPath in
            if newPath.isEmpty { formIsDirty = false }
        }
        // The review switched off (`weekly_review_disabled`): the card goes,
        // nothing is decided, and an open form keeps its draft (it saves it on
        // the same change). `Workspace.decide` refuses meanwhile too.
        .onChange(of: workspace.reviewExposed) { _, exposed in
            if !exposed { dismiss() }
        }
    }

    @ViewBuilder private var root: some View {
        if hasDecided {
            // The sheet is closing; the task already changed under it.
            Color.clear
        } else if let task = workspace.task(taskID), !showsStale(task) {
            DecisionCardContent(
                model: DecisionCardModel(task: task, workspace: workspace), stallReason: $stallReason, problem: problem,
                onChoose: choose
            )
        } else {
            DecisionCardStaleView(
                was: opened?.title ?? "", now: workspace.task(taskID)?.title, stillAsks: currentlyAsks,
                onClose: closeCard, onDecideAgain: decideAgain
            )
        }
    }

    // MARK: Staleness (FR-011)

    private struct OpenedWording: Hashable {
        var title: String
        var formulationID: FormulationID?
        /// The task as shown: any change since makes a decision stale (Core decides).
        var stamp: ShownTask
    }

    private func recordOpenedWording() {
        guard opened == nil, let task = workspace.task(taskID) else { return }
        opened = OpenedWording(title: task.title, formulationID: task.formulation?.id, stamp: workspace.shownTask(of: task))
    }

    private func showsStale(_ task: TaskRecord) -> Bool {
        if isStale { return true }
        guard let opened else { return false }
        return task.state != .next || task.formulation?.id != opened.formulationID
    }

    private var currentlyAsks: Bool {
        workspace.formulationClass(of: taskID)?.asksForDecision == true
    }

    private func decideAgain() {
        guard let task = workspace.task(taskID) else { return }
        opened = OpenedWording(title: task.title, formulationID: task.formulation?.id, stamp: workspace.shownTask(of: task))
        isStale = false
        problem = nil
    }

    // MARK: Deciding

    private func choose(_ decision: DecisionType) {
        problem = nil
        if let form = DecisionForm(decision) {
            path.append(form)
            return
        }
        guard let task = workspace.task(taskID), !showsStale(task) else {
            isStale = true
            return
        }
        let title = task.title
        do {
            let decisionID = try workspace.decide(
                decision, on: taskID, stallReason: stallReason, sessionID: review?.sessionID,
                formulationID: opened?.formulationID, expectedTask: opened?.stamp
            )
            finish(decisionID, decision: decision, title: title)
        } catch {
            switch error {
            case .formulationChanged, .taskNotFound:
                isStale = true
            case .decisionNotAllowed:
                problem = ReviewCopy.decisionNotAllowed
            default:
                problem = error.message
            }
        }
    }

    /// Close, or "Not now" inside a review (the step sets the task aside).
    private func closeCard() {
        if let review { review.onNotNow() } else { dismiss() }
    }

    /// Closes the card and offers Undo (FR-048); in a review the step does both.
    private func finish(_ decisionID: DecisionID, decision: DecisionType, title: String) {
        hasDecided = true
        formIsDirty = false
        if let review {
            review.onDecided(decisionID, decision, title)
            return
        }
        dismiss()
        DecisionUndoToast.show(
            decisionID, decision: decision, title: title, taskID: taskID, workspace: workspace, toasts: toasts
        )
    }
}

// MARK: - Undo (FR-048)

/// The toast after a decision: it names what happened and offers Undo for
/// `UndoWindowPolicy`'s window. An Undo the task no longer allows (it changed
/// elsewhere) says where the task is now instead.
@MainActor
enum DecisionUndoToast {
    static func show(
        _ decisionID: DecisionID, decision: DecisionType, title: String, taskID: TaskID, workspace: Workspace,
        toasts: ToastCenter
    ) {
        let announcement = ReviewCopy.decisionAnnouncement(decision)
        // "Released to Someday. Undo available." → "Released to Someday".
        let reverts = String(announcement.prefix { $0 != "." })
        toasts.showUndo(
            ReviewCopy.decisionToast(decision, title: title), announcement: announcement,
            undoAccessibilityLabel: "\(ReviewCopy.undo): \(reverts) \(title)"
        ) {
            do {
                try workspace.undoDecision(decisionID)
            } catch {
                let current = workspace.task(taskID)
                toasts.show(ReviewCopy.undoUnavailable(title: current?.title ?? title, list: current?.openList))
            }
        }
    }
}

// MARK: - Card model

/// What the card shows for one task, resolved once per render.
struct DecisionCardModel: Hashable {
    var title: String
    var marker: FormulationClass
    /// "15 days in Next · Home", plus "· kept 7 more days on Mon 5 Oct".
    var meta: String
    /// FR-005: the third formulation in a row that stalled.
    var thirdStall: Bool
    /// Core's card decisions, in the design's order (M-03).
    var decisions: [DecisionType]
    /// FR-009: "Keep 7 more days" was used on this wording.
    var extensionUsed: Bool
    var isOffline: Bool
}

extension DecisionCardModel {
    @MainActor
    init(task: TaskRecord, workspace: Workspace) {
        let kind = workspace.formulationClass(of: task.id) ?? .none
        let extendedAt = task.formulation?.extendedAt
        var parts: [String] = []
        if let started = task.formulation?.startedAt {
            parts.append(ReviewCopy.daysInNext(since: started, now: workspace.reviewNow))
        }
        parts.append(task.projectID.flatMap { workspace.project($0)?.name } ?? ReviewCopy.noProject)
        if let extendedAt {
            // Shown in the device's current zone (ios-commands §6).
            parts.append(ReviewCopy.keptMoreDays(on: ReviewCopy.day(extendedAt, in: .current)))
        }
        let offline: Bool
        if case .offline = workspace.syncStatus { offline = true } else { offline = false }
        self.init(
            title: task.title, marker: kind, meta: parts.joined(separator: " · "),
            thirdStall: workspace.isThirdStall(task.id),
            decisions: StallReasonRecommendation.cardDecisions(extensionUsed: extendedAt != nil),
            extensionUsed: extendedAt != nil, isOffline: offline
        )
    }
}

// MARK: - Card content

/// The card's body for one model; value-driven, so every state has a preview.
struct DecisionCardContent: View {
    let model: DecisionCardModel
    @Binding var stallReason: StallReason?
    let problem: String?
    let onChoose: (DecisionType) -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    /// VoiceOver starts on the card title, as Process inbox does.
    @AccessibilityFocusState private var isTitleFocused: Bool

    init(
        model: DecisionCardModel, stallReason: Binding<StallReason?>, problem: String?,
        onChoose: @escaping (DecisionType) -> Void
    ) {
        self.model = model
        _stallReason = stallReason
        self.problem = problem
        self.onChoose = onChoose
    }

    private var recommended: DecisionType? { StallReasonRecommendation.decision(for: stallReason) }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: BBSpacing.s5) {
                header
                if model.thirdStall {
                    thirdStallOffer
                } else {
                    Text(ReviewCopy.cardFraming)
                        .font(BBFont.secondary)
                        .foregroundStyle(BBColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                reasons
                decisions
                if model.extensionUsed {
                    Text(ReviewCopy.extensionUsed)
                        .font(BBFont.meta)
                        .foregroundStyle(BBColor.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if let problem {
                    InlineProblemText(message: problem)
                }
                if model.isOffline {
                    Label(ReviewCopy.offlineDecisions, systemImage: "icloud.slash")
                        .font(BBFont.meta)
                        .foregroundStyle(BBColor.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(BBSpacing.s4)
        }
        .bbScreenBackground()
        .onAppear { isTitleFocused = true }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s2) {
            if let chip = ReviewMarkerChip(MarkerStyle.for(model.marker)) {
                chip
            }
            Text(model.title)
                .font(BBFont.title)
                .foregroundStyle(BBColor.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityAddTraits(.isHeader)
                .accessibilityFocused($isTitleFocused)
            Text(model.meta)
                .font(BBFont.meta)
                .foregroundStyle(BBColor.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var thirdStallOffer: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s3) {
            Text(ReviewCopy.thirdStall)
                .font(BBFont.secondary)
                .foregroundStyle(BBColor.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Button {
                onChoose(.someday)
            } label: {
                Text(ReviewCopy.cardTitle(.someday))
                    .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
            }
            .buttonStyle(.bordered)
        }
        .padding(BBSpacing.s4)
        .bbCard()
    }

    private var reasons: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s2) {
            Text(ReviewCopy.cardReasonsHeading)
                .font(BBFont.subtitle)
                .foregroundStyle(BBColor.textSecondary)
            BBFlowLayout(spacing: BBSpacing.s2, lineSpacing: BBSpacing.s2) {
                ForEach(ReviewCopy.stallReasonOrder, id: \.self) { reason in
                    ReasonChip(title: ReviewCopy.stallReasonLabel(reason), isSelected: stallReason == reason) {
                        // Tapping the chosen reason again clears it.
                        stallReason = stallReason == reason ? nil : reason
                    }
                }
            }
        }
    }

    private var decisions: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s2) {
            Text(ReviewCopy.cardDecisionsHeading)
                .font(BBFont.subtitle)
                .foregroundStyle(BBColor.textSecondary)
                .accessibilityAddTraits(.isHeader)
            ForEach(model.decisions, id: \.self) { decision in
                DecisionRow(
                    title: ReviewCopy.cardTitle(decision), subtitle: ReviewCopy.cardSubtitle(decision),
                    isRecommended: decision == recommended, stacksBadge: dynamicTypeSize.isAccessibilitySize
                ) {
                    onChoose(decision)
                }
            }
        }
    }
}

/// An optional stall reason; selection is announced as a trait, not colour.
private struct ReasonChip: View {
    let title: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(BBFont.secondary)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
                .foregroundStyle(isSelected ? BBColor.brandText : BBColor.textPrimary)
                .padding(.horizontal, BBSpacing.s3)
                .padding(.vertical, BBSpacing.s2)
                .frame(minHeight: BBMetrics.hitTarget)
                .background(
                    isSelected ? BBColor.brandSoft : BBColor.surfaceRaised,
                    in: RoundedRectangle(cornerRadius: BBRadius.chip, style: .continuous)
                )
                .overlay {
                    RoundedRectangle(cornerRadius: BBRadius.chip, style: .continuous)
                        .strokeBorder(isSelected ? BBColor.brandText : BBColor.hairline, lineWidth: isSelected ? 2 : 1)
                }
                .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

/// One decision; "Recommended" is a word and an outline, never colour alone.
private struct DecisionRow: View {
    let title: String
    let subtitle: String?
    let isRecommended: Bool
    let stacksBadge: Bool
    let action: () -> Void

    var body: some View {
        let layout = stacksBadge
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: BBSpacing.s1))
            : AnyLayout(HStackLayout(alignment: .center, spacing: BBSpacing.s2))
        Button(action: action) {
            layout {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(BBFont.bodyMedium)
                        .foregroundStyle(BBColor.textPrimary)
                    if let subtitle {
                        Text(subtitle)
                            .font(BBFont.meta)
                            .foregroundStyle(BBColor.textTertiary)
                    }
                }
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
                if !stacksBadge { Spacer(minLength: 0) }
                if isRecommended {
                    Text(ReviewCopy.recommended)
                        .font(BBFont.caption.weight(.semibold))
                        .foregroundStyle(BBColor.brandText)
                        .padding(.horizontal, BBSpacing.s2)
                        .padding(.vertical, 2)
                        .background(BBColor.brandSoft, in: Capsule())
                }
            }
            .padding(.horizontal, BBSpacing.s4)
            .padding(.vertical, BBSpacing.s3)
            .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
            .background(BBColor.surfaceRaised, in: RoundedRectangle(cornerRadius: BBRadius.row, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: BBRadius.row, style: .continuous)
                    .strokeBorder(isRecommended ? BBColor.brandText : BBColor.hairline, lineWidth: isRecommended ? 2 : 1)
            }
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityValue(isRecommended ? ReviewCopy.recommended : "")
    }
}

// MARK: - Stale (FR-011)

/// The task changed on another device after the card opened: nothing was
/// applied; the was/now wording and, if it still asks, "Decide again".
struct DecisionCardStaleView: View {
    let was: String
    let now: String?
    let stillAsks: Bool
    let onClose: () -> Void
    let onDecideAgain: () -> Void

    @AccessibilityFocusState private var isMessageFocused: Bool

    init(
        was: String, now: String?, stillAsks: Bool, onClose: @escaping () -> Void,
        onDecideAgain: @escaping () -> Void
    ) {
        self.was = was
        self.now = now
        self.stillAsks = stillAsks
        self.onClose = onClose
        self.onDecideAgain = onDecideAgain
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: BBSpacing.s4) {
                Text(stillAsks ? "\(ReviewCopy.stale) \(ReviewCopy.decideAgainHint)" : ReviewCopy.stale)
                    .font(BBFont.secondary)
                    .foregroundStyle(BBColor.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityFocused($isMessageFocused)
                VStack(alignment: .leading, spacing: BBSpacing.s2) {
                    LabeledContent(ReviewCopy.staleWas, value: was)
                    if let now {
                        LabeledContent(ReviewCopy.staleNow, value: now)
                    }
                }
                .font(BBFont.secondary)
                .padding(BBSpacing.s4)
                .bbCard()
                if !stillAsks {
                    Text(ReviewCopy.noLongerAsks)
                        .font(BBFont.meta)
                        .foregroundStyle(BBColor.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Button {
                    if stillAsks { onDecideAgain() } else { onClose() }
                } label: {
                    Text(stillAsks ? ReviewCopy.decideAgain : "Close")
                        .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
                }
                .buttonStyle(.borderedProminent)
            }
            .padding(BBSpacing.s4)
        }
        .bbScreenBackground()
        .onAppear { isMessageFocused = true }
    }
}

// MARK: - Previews (every M-03 state)

private extension DecisionCardModel {
    static let sample = DecisionCardModel(
        title: "Renovate the bathroom", marker: .asks, meta: "15 days in Next · Home", thirdStall: false,
        decisions: StallReasonRecommendation.cardDecisions(extensionUsed: false),
        extensionUsed: false, isOffline: false
    )

    static var extensionUsedSample: DecisionCardModel {
        var model = sample
        model.title = "Order the new kitchen tap"
        model.meta = "21 days in Next · Home · kept 7 more days on Mon 5 Oct"
        model.extensionUsed = true
        model.decisions = StallReasonRecommendation.cardDecisions(extensionUsed: true)
        return model
    }

    static var thirdStallSample: DecisionCardModel {
        var model = sample
        model.title = "Write the first page of the novel"
        model.meta = "14 days in Next · Writing"
        model.thirdStall = true
        return model
    }

    static var offlineSample: DecisionCardModel {
        var model = sample
        model.title = "Book a dentist appointment"
        model.meta = "17 days in Next · no project"
        model.isOffline = true
        return model
    }

    static var movesTomorrowSample: DecisionCardModel {
        var model = sample
        model.title = "Sort the paperwork drawer"
        model.marker = .movesTomorrow
        model.meta = "20 days in Next · Home"
        return model
    }
}

#Preview("M-03 default") {
    @Previewable @State var reason: StallReason? = nil
    NavigationStack {
        DecisionCardContent(model: .sample, stallReason: $reason, problem: nil, onChoose: { _ in })
            .navigationTitle("Decide")
            .navigationBarTitleDisplayMode(.inline)
    }
}

#Preview("M-03 reason → recommendation") {
    @Previewable @State var reason: StallReason? = .tooBig
    DecisionCardContent(model: .sample, stallReason: $reason, problem: nil, onChoose: { _ in })
}

#Preview("M-03 moves to Someday tomorrow") {
    @Previewable @State var reason: StallReason? = nil
    DecisionCardContent(model: .movesTomorrowSample, stallReason: $reason, problem: nil, onChoose: { _ in })
}

#Preview("M-03 extension already used") {
    @Previewable @State var reason: StallReason? = nil
    DecisionCardContent(model: .extensionUsedSample, stallReason: $reason, problem: nil, onChoose: { _ in })
}

#Preview("M-03 third stalled wording") {
    @Previewable @State var reason: StallReason? = nil
    DecisionCardContent(model: .thirdStallSample, stallReason: $reason, problem: nil, onChoose: { _ in })
}

#Preview("M-03 decision not allowed") {
    @Previewable @State var reason: StallReason? = nil
    DecisionCardContent(model: .sample, stallReason: $reason, problem: ReviewCopy.decisionNotAllowed, onChoose: { _ in })
}

#Preview("M-03 offline") {
    @Previewable @State var reason: StallReason? = .missingInfo
    DecisionCardContent(model: .offlineSample, stallReason: $reason, problem: nil, onChoose: { _ in })
}

#Preview("M-03 stale") {
    DecisionCardStaleView(
        was: "Renovate the bathroom", now: "Get 3 quotes for the bathroom", stillAsks: false, onClose: {},
        onDecideAgain: {}
    )
}

#Preview("M-03 decision applied, with Undo") {
    let toasts = ToastCenter()
    VStack {
        Spacer()
        ToastHost()
    }
    .environment(toasts)
    .onAppear {
        toasts.showUndo(
            ReviewCopy.decisionToast(.someday, title: "Renovate the bathroom"),
            announcement: ReviewCopy.decisionAnnouncement(.someday),
            undoAccessibilityLabel: "Undo: Released to Someday Renovate the bathroom"
        ) {}
    }
}

#Preview("M-03 undo didn't apply") {
    let toasts = ToastCenter()
    VStack {
        Spacer()
        ToastHost()
    }
    .environment(toasts)
    .onAppear {
        toasts.show(ReviewCopy.undoUnavailable(title: "Renovate the bathroom", list: .someday))
    }
}

#Preview("M-03 accessibility size") {
    @Previewable @State var reason: StallReason? = .tooBig
    DecisionCardContent(model: .sample, stallReason: $reason, problem: nil, onChoose: { _ in })
        .environment(\.dynamicTypeSize, .accessibility5)
}

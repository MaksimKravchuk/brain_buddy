import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-02 (spec 020): the "This wording" section at the top of task detail.
/// It states the formulation's age in words and is the "from the task, any
/// day" way into the decision card (FR-010). It is the only iOS place that
/// shows "Ageing" (owner decision 2, 2026-10-05). Everything is computed on
/// the device from Core (`Workspace.formulationClass`, `derivedInstants`), so
/// it has no loading, error or offline state of its own. Hidden while the
/// weekly review is not exposed, before activation (FR-051) and for tasks
/// with no clock.
struct FormulationSection: View {
    let task: TaskRecord
    let onDecide: () -> Void

    @Environment(Workspace.self) private var workspace

    init(task: TaskRecord, onDecide: @escaping () -> Void) {
        self.task = task
        self.onDecide = onDecide
    }

    var body: some View {
        if let state = FormulationSectionState(task: task, workspace: workspace) {
            Section {
                FormulationSectionContent(state: state, onDecide: onDecide)
            } header: {
                Text("This wording")
            }
        }
    }
}

/// What the section says, as values (so every state has a preview).
struct FormulationSectionState: Hashable {
    enum Kind: Hashable {
        case asks
        case movesTomorrow(day: String, time: String)
        case ageing(asksOn: String)
        case fresh
        case paused(until: String)
        case kept(reason: String?, keptOn: String, asksAgain: String, moves: String)
        case parked(on: String, at: String, afterDays: Int, archivedProject: String?)
    }

    var kind: Kind
    /// "15 days in Next"; nil where the design shows no age (paused, parked).
    var age: String?
}

extension FormulationSectionState {
    /// Nil when the section is not shown.
    @MainActor
    init?(task: TaskRecord, workspace: Workspace) {
        guard workspace.reviewExposed else { return nil }
        let zone = TimeZone.current
        if task.state == .someday, let parked = task.parked {
            // A pulled park carries no `clockBefore`; then the age is the
            // rule's: threshold plus the 7 days of asking.
            let threshold = workspace.state.review.settings.thresholdDays
            let started = parked.clockBefore?.startedAt
            let days =
                started.map { Int((parked.at.timeIntervalSince($0) / FormulationRule.day).rounded(.down)) }
                ?? threshold + Int(FormulationRule.parkAfterAsk / FormulationRule.day)
            let archived = task.projectID.flatMap { workspace.project($0) }.flatMap { $0.state == .archived ? $0.name : nil }
            self.init(
                kind: .parked(
                    on: ReviewCopy.day(parked.at, in: zone), at: ReviewCopy.time(parked.at, in: zone), afterDays: days,
                    archivedProject: archived
                ),
                age: nil
            )
            return
        }
        guard task.state == .next, let clock = task.formulation, let kind = workspace.formulationClass(of: task.id),
            let instants = workspace.derivedInstants(of: task.id)
        else { return nil }
        let age = DecisionCardCopy.daysInNext(since: clock.startedAt, now: workspace.reviewNow)
        switch kind {
        case .none:
            return nil
        case .asks:
            self.init(kind: .asks, age: age)
        case .movesTomorrow, .parkDue:
            self.init(
                kind: .movesTomorrow(
                    day: ReviewCopy.day(instants.parkDueAt, in: zone), time: ReviewCopy.time(instants.parkDueAt, in: zone)
                ),
                age: age
            )
        case .paused:
            self.init(kind: .paused(until: ReviewCopy.day(instants.pausedUntil ?? instants.start, in: zone)), age: nil)
        case .ageing, .fresh:
            if let extendedAt = clock.extendedAt {
                // FR-009: kept 7 more days, with the reason quoted back.
                self.init(
                    kind: .kept(
                        reason: clock.extensionReason, keptOn: ReviewCopy.day(extendedAt, in: zone),
                        asksAgain: ReviewCopy.day(instants.askAt, in: zone), moves: ReviewCopy.day(instants.parkDueAt, in: zone)
                    ),
                    age: age
                )
            } else if kind == .ageing {
                self.init(kind: .ageing(asksOn: ReviewCopy.day(instants.askAt, in: zone)), age: age)
            } else {
                self.init(kind: .fresh, age: age)
            }
        }
    }

    /// "Decide" is offered only where the card is for: asking tasks.
    var showsDecide: Bool {
        switch kind {
        case .asks, .movesTomorrow: true
        case .ageing, .fresh, .paused, .kept, .parked: false
        }
    }
}

/// The section's rows for one state; copy from Core's `ReviewCopy`.
struct FormulationSectionContent: View {
    let state: FormulationSectionState
    let onDecide: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: BBSpacing.s2) {
            if let chip {
                chip
            }
            if let age = state.age {
                Text(age)
                    .font(BBFont.secondary)
                    .foregroundStyle(BBColor.textSecondary)
            }
            if let quote {
                Text(quote)
                    .font(BBFont.secondary.italic())
                    .foregroundStyle(BBColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let explanation {
                Text(explanation)
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, BBSpacing.s1)
        .accessibilityElement(children: .combine)
        if state.showsDecide {
            Button(action: onDecide) {
                Label("Decide", systemImage: "questionmark.circle")
                    .frame(minHeight: BBMetrics.hitTarget)
            }
        }
    }

    private var chip: ReviewMarkerChip? {
        switch state.kind {
        case .asks:
            return ReviewMarkerChip(MarkerStyle.for(.asks))
        case .movesTomorrow:
            return ReviewMarkerChip(MarkerStyle.for(.movesTomorrow))
        case .ageing:
            return ReviewMarkerChip(MarkerStyle.for(.ageing))
        case .paused:
            return ReviewMarkerChip(MarkerStyle.for(.paused))
        case .fresh:
            return nil
        case .kept:
            return ReviewMarkerChip(
                text: ReviewCopy.counterLabel(.extended), symbol: "clock.arrow.circlepath", role: .neutral
            )
        case .parked:
            return ReviewMarkerChip(text: "Parked automatically", symbol: "archivebox", role: .neutral)
        }
    }

    /// The extension reason, quoted back (FR-009).
    private var quote: String? {
        guard case .kept(let reason?, _, _, _) = state.kind, !reason.isEmpty else { return nil }
        return "\u{201C}\(reason)\u{201D}"
    }

    private var explanation: String? {
        switch state.kind {
        case .asks:
            ReviewCopy.thisWordingAsks
        case .movesTomorrow(let day, let time):
            ReviewCopy.thisWordingMovesTomorrow(day: day, time: time)
        case .ageing(let asksOn):
            ReviewCopy.thisWordingWillAsk(on: asksOn)
        case .fresh:
            nil
        case .paused(let until):
            ReviewCopy.thisWordingPaused(until: until)
        case .kept(_, let keptOn, let asksAgain, let moves):
            ReviewCopy.thisWordingKept(on: keptOn, asksAgain: asksAgain, moves: moves)
                + " This wording can't be extended again."
        case .parked(let on, let at, let afterDays, let archivedProject):
            archivedProject.map {
                ReviewCopy.thisWordingParked(on: on, at: at, afterDays: afterDays) + " "
                    + ReviewCopy.thisWordingParkedProjectArchived(project: $0)
            } ?? ReviewCopy.thisWordingParked(on: on, at: at, afterDays: afterDays)
        }
    }
}

// MARK: - Previews (every M-02 state)

@MainActor
private func formulationPreview(_ state: FormulationSectionState) -> some View {
    Form {
        Section {
            FormulationSectionContent(state: state, onDecide: {})
        } header: {
            Text("This wording")
        }
    }
}

#Preview("M-02 asks for a decision") {
    formulationPreview(FormulationSectionState(kind: .asks, age: "15 days in Next"))
}

#Preview("M-02 ageing") {
    formulationPreview(FormulationSectionState(kind: .ageing(asksOn: "Wed 14 Oct"), age: "9 days in Next"))
}

#Preview("M-02 fresh") {
    formulationPreview(FormulationSectionState(kind: .fresh, age: "2 days in Next"))
}

#Preview("M-02 clock paused") {
    formulationPreview(FormulationSectionState(kind: .paused(until: "Fri 16 Oct"), age: nil))
}

#Preview("M-02 moves to Someday tomorrow") {
    formulationPreview(
        FormulationSectionState(kind: .movesTomorrow(day: "Sat 10 Oct", time: "09:14"), age: "20 days in Next")
    )
}

#Preview("M-02 kept 7 more days") {
    formulationPreview(
        FormulationSectionState(
            kind: .kept(
                reason: "Waiting to measure the sink first", keptOn: "Mon 5 Oct", asksAgain: "Mon 12 Oct",
                moves: "Mon 19 Oct"
            ),
            age: "18 days in Next"
        )
    )
}

#Preview("M-02 parked automatically") {
    formulationPreview(
        FormulationSectionState(kind: .parked(on: "Thu 8 Oct", at: "09:14", afterDays: 21, archivedProject: nil), age: nil)
    )
}

#Preview("M-02 parked, project archived") {
    formulationPreview(
        FormulationSectionState(
            kind: .parked(on: "Thu 8 Oct", at: "09:14", afterDays: 21, archivedProject: "Old flat"), age: nil
        )
    )
}

#Preview("M-02 accessibility size") {
    formulationPreview(FormulationSectionState(kind: .asks, age: "15 days in Next"))
        .environment(\.dynamicTypeSize, .accessibility5)
}

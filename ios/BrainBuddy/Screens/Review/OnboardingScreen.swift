import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI

/// M-12 (spec 020, FR-016, FR-018, FR-035): the first time the review opens.
/// Three points, the date before which nothing in Next moves, the review day
/// and time (default Friday 16:00) and the threshold (7 / 14 / 21 / 28, default
/// 14). Continue saves them with the device's zone and marks the person
/// onboarded, offline too; the rule text follows the chosen threshold. There
/// is no notification prompt: the reminder arrives later.
struct OnboardingScreen: View {
    let onDone: () -> Void

    @Environment(Workspace.self) private var workspace
    @State private var weekday = 5
    @State private var time = Date()
    @State private var threshold = ReviewSettings.defaultThreshold
    @State private var problem: String?
    @State private var hasLoaded = false

    init(onDone: @escaping () -> Void) {
        self.onDone = onDone
    }

    var body: some View {
        let settings = workspace.state.review.settings
        let grace = settings.graceUntil ?? workspace.reviewNow.addingTimeInterval(FormulationRule.activationGrace)
        OnboardingContent(
            weekday: $weekday, time: $time, threshold: $threshold,
            graceDay: ReviewCopy.day(grace, in: .current), problem: problem, reference: reference, isOffline: isOffline,
            onContinue: save
        )
        .onAppear {
            guard !hasLoaded else { return }
            hasLoaded = true
            weekday = settings.reviewWeekday
            threshold = settings.thresholdDays
            if let wall = ReviewClock.wallTime(settings.reviewTime) {
                time = Calendar.current.date(bySettingHour: wall.hour, minute: wall.minute, second: 0, of: Date()) ?? Date()
            }
        }
    }

    private var isOffline: Bool {
        if case .offline = workspace.syncStatus { return true }
        return false
    }

    /// The account rejected the settings: they stay on the device and are retried.
    private var reference: String? {
        if case .failing(_, let referenceID, _) = workspace.syncStatus { return referenceID }
        return nil
    }

    private func save() {
        let wall = Calendar.current.dateComponents([.hour, .minute], from: time)
        let text = String(format: "%02d:%02d", wall.hour ?? 16, wall.minute ?? 0)
        do {
            try workspace.completeReviewOnboarding(thresholdDays: threshold, reviewWeekday: weekday, reviewTime: text)
        } catch {
            problem = error.message
            return
        }
        onDone()
    }
}

/// The screen for given values (every state has a preview).
struct OnboardingContent: View {
    @Binding var weekday: Int
    @Binding var time: Date
    @Binding var threshold: Int
    let graceDay: String
    let problem: String?
    let reference: String?
    let isOffline: Bool
    let onContinue: () -> Void

    init(
        weekday: Binding<Int>, time: Binding<Date>, threshold: Binding<Int>, graceDay: String, problem: String?,
        reference: String?, isOffline: Bool, onContinue: @escaping () -> Void
    ) {
        _weekday = weekday
        _time = time
        _threshold = threshold
        self.graceDay = graceDay
        self.problem = problem
        self.reference = reference
        self.isOffline = isOffline
        self.onContinue = onContinue
    }

    var body: some View {
        ReviewStepFrame(title: ReviewCopy.onboardingTitle, primaryTitle: "Continue", onPrimary: onContinue) {
            VStack(alignment: .leading, spacing: BBSpacing.s3) {
                ForEach(ReviewCopy.onboardingPoints, id: \.self) { point in
                    Text(point)
                        .font(BBFont.body)
                        .foregroundStyle(BBColor.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(ReviewCopy.explainerRule(thresholdDays: threshold))
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(ReviewCopy.onboardingGrace(until: graceDay))
                    .font(BBFont.body)
                    .foregroundStyle(BBColor.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            VStack(alignment: .leading, spacing: BBSpacing.s3) {
                Picker(ReviewCopy.reviewDayLabel, selection: $weekday) {
                    ForEach(1...7, id: \.self) { day in
                        Text(ReviewCopy.weekdayName(day)).tag(day)
                    }
                }
                .pickerStyle(.menu)
                .frame(minHeight: BBMetrics.hitTarget)
                DatePicker(ReviewCopy.reviewTimeLabel, selection: $time, displayedComponents: .hourAndMinute)
                    .frame(minHeight: BBMetrics.hitTarget)
                Text(ReviewCopy.thresholdLabel)
                    .font(BBFont.subtitle)
                    .foregroundStyle(BBColor.textSecondary)
                Picker(ReviewCopy.thresholdLabel, selection: $threshold) {
                    ForEach(OwnerClockSettings.allowedThresholds.sorted(), id: \.self) { days in
                        Text("\(days)").tag(days)
                    }
                }
                .pickerStyle(.segmented)
            }
            if isOffline {
                Label(ReviewCopy.onboardingOffline, systemImage: "icloud.slash")
                    .font(BBFont.meta)
                    .foregroundStyle(BBColor.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let problem {
                InlineProblemText(message: problem)
            }
            if let reference {
                InlineProblemText(message: ReviewCopy.onboardingSaveFailed)
                Text("Reference ID: \(reference)")
                    .font(BBFont.caption)
                    .foregroundStyle(BBColor.textTertiary)
                    .textSelection(.enabled)
            }
        }
    }
}

// MARK: - Previews (every M-12 state)

#Preview("M-12 default") {
    @Previewable @State var weekday = 5
    @Previewable @State var time = Date()
    @Previewable @State var threshold = 14
    OnboardingContent(
        weekday: $weekday, time: $time, threshold: $threshold, graceDay: "Fri 23 Oct", problem: nil, reference: nil,
        isOffline: false, onContinue: {}
    )
    .environment(ToastCenter())
}

#Preview("M-12 threshold 7") {
    @Previewable @State var weekday = 5
    @Previewable @State var time = Date()
    @Previewable @State var threshold = 7
    OnboardingContent(
        weekday: $weekday, time: $time, threshold: $threshold, graceDay: "Fri 23 Oct", problem: nil, reference: nil,
        isOffline: false, onContinue: {}
    )
    .environment(ToastCenter())
}

#Preview("M-12 offline") {
    @Previewable @State var weekday = 5
    @Previewable @State var time = Date()
    @Previewable @State var threshold = 14
    OnboardingContent(
        weekday: $weekday, time: $time, threshold: $threshold, graceDay: "Fri 23 Oct", problem: nil, reference: nil,
        isOffline: true, onContinue: {}
    )
    .environment(ToastCenter())
}

#Preview("M-12 error with Ref") {
    @Previewable @State var weekday = 5
    @Previewable @State var time = Date()
    @Previewable @State var threshold = 14
    OnboardingContent(
        weekday: $weekday, time: $time, threshold: $threshold, graceDay: "Fri 23 Oct", problem: nil,
        reference: "3f2c9a", isOffline: false, onContinue: {}
    )
    .environment(ToastCenter())
}

#Preview("M-12 accessibility size") {
    @Previewable @State var weekday = 5
    @Previewable @State var time = Date()
    @Previewable @State var threshold = 14
    OnboardingContent(
        weekday: $weekday, time: $time, threshold: $threshold, graceDay: "Fri 23 Oct", problem: nil, reference: nil,
        isOffline: false, onContinue: {}
    )
    .environment(ToastCenter())
    .environment(\.dynamicTypeSize, .accessibility5)
}

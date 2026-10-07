import BrainBuddyCore
import Observation
import SwiftUI
import UIKit

/// App-wide toasts: one at a time, replaced by the next, dismissed after
/// about four seconds, and announced to VoiceOver.
@MainActor
@Observable
final class ToastCenter {
    struct Toast: Identifiable, Equatable {
        enum Kind: Equatable {
            case info
            case error
        }

        let id = UUID()
        let message: String
        let actionTitle: String?
        let kind: Kind
        /// Correlation / reference id for errors, shown so it can be reported.
        let referenceID: String?
        /// What VoiceOver announces instead of the default sentence (a
        /// weekly-review decision: "<decision>. Undo available.").
        var announcement: String? = nil
        /// The action button's accessible name ("Undo: Released to Someday
        /// Renovate the bathroom"); the visible title otherwise.
        var actionAccessibilityLabel: String? = nil
        /// How long it stays at least (`UndoWindowPolicy`); the default rule
        /// when nil. A toast with a minimum also stays while VoiceOver or
        /// Switch Control focus is on it.
        var minimumDuration: TimeInterval? = nil
    }

    /// The toast on screen, if any.
    private(set) var current: Toast?

    @ObservationIgnored private var action: (@MainActor () -> Void)?
    @ObservationIgnored private var dismissal: Task<Void, Never>?
    /// When the current toast appeared, and whether assistive focus holds it.
    @ObservationIgnored private var shownAt: Date?
    @ObservationIgnored private var isHeldByFocus = false

    init() {}

    /// Shows `message`, with an optional action button (for example "Undo").
    func show(_ message: String, actionTitle: String? = nil, action: (@MainActor () -> Void)? = nil) {
        present(Toast(message: message, actionTitle: action == nil ? nil : actionTitle, kind: .info, referenceID: nil), action: action)
    }

    /// Shows a failure, with its reference id when the server supplied one.
    func showError(_ message: String, referenceID: String? = nil) {
        present(Toast(message: message, actionTitle: nil, kind: .error, referenceID: referenceID), action: nil)
    }

    /// The Undo toast after a weekly-review decision (spec 020, FR-048):
    /// about 5 s, at least 10 s while VoiceOver or Switch Control runs and
    /// then until their focus leaves it (`UndoWindowPolicy`); VoiceOver hears
    /// `announcement` ("Released to Someday. Undo available."); the 44 × 44 pt
    /// Undo is named `undoAccessibilityLabel`.
    func showUndo(
        _ message: String, announcement: String, undoAccessibilityLabel: String, undo: @escaping @MainActor () -> Void
    ) {
        let minimum = UndoWindowPolicy.duration(
            voiceOver: UIAccessibility.isVoiceOverRunning, switchControl: UIAccessibility.isSwitchControlRunning
        )
        present(
            Toast(
                message: message, actionTitle: ReviewCopy.undo, kind: .info, referenceID: nil, announcement: announcement,
                actionAccessibilityLabel: undoAccessibilityLabel, minimumDuration: minimum
            ),
            action: undo
        )
    }

    /// Assistive focus entered or left the toast `id`. While focused, a toast
    /// with a minimum duration stays; once focus leaves it goes after the rest
    /// of its minimum, or a second later when that has passed.
    func setAssistiveFocus(_ isFocused: Bool, on id: Toast.ID) {
        guard let current, current.id == id, let minimum = current.minimumDuration else { return }
        if isFocused {
            isHeldByFocus = true
            dismissal?.cancel()
            dismissal = nil
            return
        }
        guard isHeldByFocus else { return }
        isHeldByFocus = false
        let elapsed = shownAt.map { Date().timeIntervalSince($0) } ?? minimum
        scheduleDismissal(of: current, after: .seconds(max(1, minimum - elapsed)))
    }

    /// Runs the current toast's action and dismisses it.
    func performAction() {
        let action = action
        dismiss()
        action?()
    }

    /// VoiceOver's magic tap (two-finger double tap): runs the toast's action,
    /// for example Undo, wherever focus is. Returns false when there is none.
    @discardableResult
    func performMagicTap() -> Bool {
        guard current?.actionTitle != nil, action != nil else { return false }
        performAction()
        return true
    }

    /// Dismisses the current toast, or only the toast `id` when given.
    func dismiss(_ id: Toast.ID? = nil) {
        guard let current, id == nil || current.id == id else { return }
        self.current = nil
        action = nil
        dismissal?.cancel()
        dismissal = nil
        shownAt = nil
        isHeldByFocus = false
    }

    private func present(_ toast: Toast, action: (@MainActor () -> Void)?) {
        dismissal?.cancel()
        current = toast
        self.action = action
        shownAt = Date()
        isHeldByFocus = false
        Self.announce(toast)
        scheduleDismissal(of: toast, after: Self.duration(for: toast))
    }

    private func scheduleDismissal(of toast: Toast, after visibleFor: Duration) {
        dismissal?.cancel()
        dismissal = Task { [weak self] in
            try? await Task.sleep(for: visibleFor)
            guard !Task.isCancelled else { return }
            self?.dismiss(toast.id)
        }
    }

    /// About four seconds; longer when there is an action to reach, and much
    /// longer with VoiceOver or Switch Control, which take more steps to reach
    /// it, so nobody loses an Undo to the timer. A toast that names its own
    /// minimum (a review decision's Undo) uses it.
    private static func duration(for toast: Toast) -> Duration {
        if let minimum = toast.minimumDuration { return .seconds(minimum) }
        if UIAccessibility.isVoiceOverRunning || UIAccessibility.isSwitchControlRunning { return .seconds(10) }
        if toast.actionTitle != nil || toast.kind == .error { return .seconds(5) }
        return .seconds(4)
    }

    /// What VoiceOver hears, for example "Completed. Undo is available."
    static func announcement(for toast: Toast) -> String {
        if let announcement = toast.announcement { return announcement }
        var text = sentence(toast.message)
        if let reference = toast.referenceID { text += " Reference ID \(reference)." }
        if let actionTitle = toast.actionTitle { text += " \(actionTitle) is available." }
        return text
    }

    /// `text` ending in sentence punctuation, so parts join without doubling it.
    private static func sentence(_ text: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let last = trimmed.last, !".!?…".contains(last) else { return trimmed }
        return trimmed + "."
    }

    private static func announce(_ toast: Toast) {
        let spoken = Self.announcement(for: toast)
        // A short delay keeps the announcement from being cut off by the focus
        // change that usually accompanies the action that caused the toast.
        Task {
            try? await Task.sleep(for: .milliseconds(150))
            UIAccessibility.post(notification: .announcement, argument: spoken)
        }
    }
}

extension View {
    /// Lets VoiceOver's magic tap run the current toast's action (Undo)
    /// from anywhere in this view.
    func toastMagicTap() -> some View {
        modifier(ToastMagicTap())
    }
}

private struct ToastMagicTap: ViewModifier {
    @Environment(ToastCenter.self) private var toasts

    func body(content: Content) -> some View {
        content.accessibilityAction(.magicTap) {
            _ = toasts.performMagicTap()
        }
    }
}

/// Floats the current toast as a Liquid Glass capsule at the bottom of its
/// container. Place it in an overlay whose safe area includes the tab bar and
/// capture accessory, so it sits just above them — or, on a screen with its
/// own bottom buttons, in the bottom inset just above those buttons, so it
/// never covers them.
struct ToastHost: View {
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack(alignment: .bottom) {
            if let toast = toasts.current {
                ToastCapsule(toast: toast)
                    .id(toast.id)
                    .transition(transition)
            }
        }
        .padding(.horizontal, BBSpacing.s4)
        .padding(.bottom, BBSpacing.s2)
        .animation(BBMotion.animation(.settle, reduceMotion: reduceMotion) ?? .linear(duration: 0.15), value: toasts.current?.id)
    }

    /// Slides up and fades; only fades with Reduce Motion on.
    private var transition: AnyTransition {
        reduceMotion ? AnyTransition.opacity : AnyTransition.move(edge: .bottom).combined(with: .opacity)
    }
}

private struct ToastCapsule: View {
    let toast: ToastCenter.Toast
    @Environment(ToastCenter.self) private var toasts
    /// VoiceOver / Switch Control focus on the action, which holds an Undo
    /// toast on screen until it leaves (FR-048).
    @AccessibilityFocusState private var isActionFocused: Bool

    init(toast: ToastCenter.Toast) {
        self.toast = toast
    }

    var body: some View {
        HStack(spacing: BBSpacing.s3) {
            if toast.kind == .error {
                Image(systemName: "exclamationmark.circle.fill")
                    .foregroundStyle(BBColor.danger)
                    .accessibilityHidden(true)
            }
            ToastText(toast: toast)
            if let actionTitle = toast.actionTitle {
                Button(actionTitle) { toasts.performAction() }
                    .buttonStyle(.borderless)
                    .font(BBFont.subtitle.weight(.semibold))
                    .foregroundStyle(BBColor.brandText)
                    .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget)
                    .contentShape(.rect)
                    .accessibilityLabel(toast.actionAccessibilityLabel ?? actionTitle)
                    .accessibilityFocused($isActionFocused)
                    .onChange(of: isActionFocused) { _, focused in
                        toasts.setAssistiveFocus(focused, on: toast.id)
                    }
            }
        }
        .padding(.leading, BBSpacing.s5)
        .padding(.trailing, toast.actionTitle == nil ? BBSpacing.s5 : BBSpacing.s3)
        .padding(.vertical, toast.actionTitle == nil ? BBSpacing.s3 : BBSpacing.s1)
        .frame(minHeight: BBMetrics.hitTarget)
        .glassEffect(.regular, in: .capsule)
        .accessibilityElement(children: .contain)
        .accessibilityAction(.escape) { toasts.dismiss(toast.id) }
    }
}

private struct ToastText: View {
    let toast: ToastCenter.Toast
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(toast: ToastCenter.Toast) {
        self.toast = toast
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(toast.message)
                .font(BBFont.subtitle)
                .foregroundStyle(.primary)
                // Never truncated at accessibility sizes (design "Mobile viability").
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 3)
            if let reference = toast.referenceID {
                Text("Reference ID: \(reference)")
                    .font(BBFont.caption)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }
}

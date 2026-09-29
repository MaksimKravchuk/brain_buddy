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
    }

    /// The toast on screen, if any.
    private(set) var current: Toast?

    @ObservationIgnored private var action: (@MainActor () -> Void)?
    @ObservationIgnored private var dismissal: Task<Void, Never>?

    init() {}

    /// Shows `message`, with an optional action button (for example "Undo").
    func show(_ message: String, actionTitle: String? = nil, action: (@MainActor () -> Void)? = nil) {
        present(Toast(message: message, actionTitle: action == nil ? nil : actionTitle, kind: .info, referenceID: nil), action: action)
    }

    /// Shows a failure, with its reference id when the server supplied one.
    func showError(_ message: String, referenceID: String? = nil) {
        present(Toast(message: message, actionTitle: nil, kind: .error, referenceID: referenceID), action: nil)
    }

    /// Runs the current toast's action and dismisses it.
    func performAction() {
        let action = action
        dismiss()
        action?()
    }

    /// Dismisses the current toast, or only the toast `id` when given.
    func dismiss(_ id: Toast.ID? = nil) {
        guard let current, id == nil || current.id == id else { return }
        self.current = nil
        action = nil
        dismissal?.cancel()
        dismissal = nil
    }

    private func present(_ toast: Toast, action: (@MainActor () -> Void)?) {
        dismissal?.cancel()
        current = toast
        self.action = action
        Self.announce(toast)
        let visibleFor = Self.duration(for: toast)
        dismissal = Task { [weak self] in
            try? await Task.sleep(for: visibleFor)
            guard !Task.isCancelled else { return }
            self?.dismiss(toast.id)
        }
    }

    /// About four seconds; longer when there is an action to reach or when
    /// VoiceOver is reading, so nobody loses an Undo to the timer.
    private static func duration(for toast: Toast) -> Duration {
        if UIAccessibility.isVoiceOverRunning { return .seconds(10) }
        if toast.actionTitle != nil || toast.kind == .error { return .seconds(5) }
        return .seconds(4)
    }

    /// What VoiceOver hears, for example "Completed. Undo is available."
    static func announcement(for toast: Toast) -> String {
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

/// Floats the current toast as a Liquid Glass capsule at the bottom of its
/// container. Place it in an overlay whose safe area includes the tab bar and
/// capture accessory, so it sits just above them.
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

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(toast.message)
                .font(BBFont.subtitle)
                .foregroundStyle(.primary)
                .lineLimit(3)
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

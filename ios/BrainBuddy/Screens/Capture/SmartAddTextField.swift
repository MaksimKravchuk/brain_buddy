import BrainBuddyCore
import SwiftUI
import UIKit

/// Smart Add text entry: a wrapping text field that highlights recognised
/// `@project` tokens in the brand colour (semibold) and `#tag` tokens in the
/// tag style (neutral fill). `tokens` come from `CapturePreview.tokens` and
/// use UTF-16 offsets, which map directly onto the text view's `NSRange`s.
///
/// Highlights are visual only. VoiceOver users hear the same information in
/// words from the preview chips ("Project Errands, new"), so nothing depends
/// on colour. The field focuses itself when it appears, Return calls
/// `onSubmit` instead of inserting a line break (titles are one line), and
/// smart quotes are off so `@"Two words"` keeps its straight quotes.
///
/// Built on `UITextView` rather than `TextEditor(text: Binding<AttributedString>)`
/// because re-styling ranges on every keystroke there resets typing
/// attributes and fights the editor; here attributes are applied to the text
/// storage in place, so the caret, selection and marked (IME) text are kept.
struct SmartAddTextField: View {
    @Binding private var text: String
    private let tokens: [SmartAddToken]
    private let placeholder: String
    private let onSubmit: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(
        text: Binding<String>, tokens: [SmartAddToken], placeholder: String = "What's on your mind?",
        onSubmit: @escaping () -> Void
    ) {
        _text = text
        self.tokens = tokens
        self.placeholder = placeholder
        self.onSubmit = onSubmit
    }

    var body: some View {
        SmartAddTextView(text: $text, tokens: tokens, dynamicTypeSize: dynamicTypeSize, onSubmit: onSubmit)
            .frame(minHeight: 44)
            .overlay(alignment: .topLeading) {
                if text.isEmpty {
                    Text(placeholder)
                        .foregroundStyle(.tertiary)
                        .padding(.vertical, SmartAddTextView.verticalInset)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
            }
    }
}

private struct SmartAddTextView: UIViewRepresentable {
    static let verticalInset: CGFloat = 10

    @Binding var text: String
    let tokens: [SmartAddToken]
    /// Passed in so a Dynamic Type change re-applies the scaled fonts.
    let dynamicTypeSize: DynamicTypeSize
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeUIView(context: Context) -> SmartAddUITextView {
        let view = SmartAddUITextView()
        view.delegate = context.coordinator
        view.backgroundColor = .clear
        view.isScrollEnabled = false
        view.textContainerInset = UIEdgeInsets(
            top: Self.verticalInset, left: 0, bottom: Self.verticalInset, right: 0)
        view.textContainer.lineFragmentPadding = 0
        view.font = .preferredFont(forTextStyle: .body)
        view.adjustsFontForContentSizeCategory = true
        view.autocapitalizationType = .sentences
        view.smartQuotesType = .no
        view.smartDashesType = .no
        view.returnKeyType = .default
        view.enablesReturnKeyAutomatically = true
        view.accessibilityLabel = "Task"
        view.accessibilityHint = "Type @ before a project and # before a tag."
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        view.text = text
        Self.applyHighlights(to: view, tokens: tokens)
        return view
    }

    func updateUIView(_ view: SmartAddUITextView, context: Context) {
        context.coordinator.parent = self
        if view.text != text {
            view.text = text
        }
        Self.applyHighlights(to: view, tokens: tokens)
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: SmartAddUITextView, context: Context) -> CGSize? {
        guard let width = proposal.width, width.isFinite, width > 0 else { return nil }
        let fitting = uiView.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        return CGSize(width: width, height: max(44, fitting.height))
    }

    /// Re-styles the whole text in place. Skipped while the keyboard is
    /// composing marked text, which must not be disturbed.
    static func applyHighlights(to view: UITextView, tokens: [SmartAddToken]) {
        guard view.markedTextRange == nil else { return }
        let storage = view.textStorage
        let length = storage.length
        let base = baseAttributes()
        let selection = view.selectedRange
        storage.beginEditing()
        storage.setAttributes(base, range: NSRange(location: 0, length: length))
        for token in tokens {
            let range = token.utf16Range
            guard range.lowerBound >= 0, range.upperBound <= length, !range.isEmpty else { continue }
            storage.addAttributes(
                attributes(for: token.kind, tint: view.tintColor),
                range: NSRange(location: range.lowerBound, length: range.count)
            )
        }
        storage.endEditing()
        if view.selectedRange != selection { view.selectedRange = selection }
        view.typingAttributes = base
    }

    private static func baseAttributes() -> [NSAttributedString.Key: Any] {
        [.font: UIFont.preferredFont(forTextStyle: .body), .foregroundColor: UIColor.label]
    }

    private static func attributes(for kind: SmartAddToken.Kind, tint: UIColor) -> [NSAttributedString.Key: Any] {
        switch kind {
        case .project:
            return [
                .foregroundColor: tint,
                .font: UIFontMetrics(forTextStyle: .body).scaledFont(for: .systemFont(ofSize: 17, weight: .semibold)),
            ]
        case .tag:
            return [
                .foregroundColor: UIColor.secondaryLabel,
                .backgroundColor: UIColor.tertiarySystemFill,
            ]
        }
    }

    @MainActor
    final class Coordinator: NSObject, UITextViewDelegate {
        var parent: SmartAddTextView

        init(parent: SmartAddTextView) {
            self.parent = parent
        }

        func textViewDidChange(_ textView: UITextView) {
            let value = textView.text ?? ""
            if value.contains(where: \.isNewline) {
                // A pasted line break becomes a space: a task title is one line.
                let flattened = value.split(whereSeparator: \.isNewline).joined(separator: " ")
                textView.text = flattened
                parent.text = flattened
            } else {
                parent.text = value
            }
        }

        func textView(
            _ textView: UITextView, shouldChangeTextIn range: NSRange, replacementText text: String
        ) -> Bool {
            if text == "\n" {
                parent.onSubmit()
                return false
            }
            return true
        }
    }
}

/// Becomes first responder once, when it first joins a window, so the
/// keyboard is up as soon as the capture sheet appears.
final class SmartAddUITextView: UITextView {
    private var hasRequestedFocus = false

    override func didMoveToWindow() {
        super.didMoveToWindow()
        guard window != nil, !hasRequestedFocus else { return }
        hasRequestedFocus = true
        Task { @MainActor [weak self] in
            self?.becomeFirstResponder()
        }
    }
}

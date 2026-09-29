import SwiftUI

/// A one-line headline, a plain-language hint and at most one action
/// ("explain then enable"), on the flat brand surface.
struct EmptyStateView: View {
    let title: String
    let message: String
    let systemImage: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil

    init(title: String, message: String, systemImage: String) {
        self.title = title
        self.message = message
        self.systemImage = systemImage
    }

    init(title: String, message: String, systemImage: String, actionTitle: String, action: @escaping () -> Void) {
        self.title = title
        self.message = message
        self.systemImage = systemImage
        self.actionTitle = actionTitle
        self.action = action
    }

    var body: some View {
        ContentUnavailableView {
            Label {
                Text(title)
                    .font(BBFont.title)
                    .foregroundStyle(BBColor.textPrimary)
            } icon: {
                Image(systemName: systemImage)
                    .foregroundStyle(BBColor.textPlaceholder)
            }
        } description: {
            Text(message)
                .font(BBFont.secondary)
                .foregroundStyle(BBColor.textTertiary)
        } actions: {
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(.borderedProminent)
                    .tint(BBColor.brand)
                    .controlSize(.large)
            }
        }
    }
}

#Preview("Empty inbox") {
    EmptyStateView(
        title: "Inbox zero",
        message: "Everything you capture lands here until you decide what it is.",
        systemImage: "tray"
    )
    .bbScreenBackground()
}

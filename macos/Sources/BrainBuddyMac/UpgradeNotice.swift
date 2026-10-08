import AppKit
import BrainBuddyMacCore

/// Design X-05, the one-time upgrade notice (contracts/mac-legacy-import.md §5): an app-modal alert
/// before the workspace opens, with the selectable path of the file it is about. "Continue" is the
/// default (Return) and has focus; "Show in Finder" reveals the file; Escape is not mapped, so the
/// notice is read once. The launch records it as seen only after a button was chosen, so a quit
/// while it is open shows it again next time.
@MainActor
enum UpgradeNotice {
    static func present(_ notice: LegacyImportNotice) {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = notice.title
        alert.informativeText = notice.textBeforePath
        alert.accessoryView = accessory(for: notice)
        let continueButton = alert.addButton(withTitle: LegacyImportNotice.continueTitle)
        continueButton.keyEquivalent = "\r"
        let finderButton = alert.addButton(withTitle: LegacyImportNotice.showInFinderTitle)
        finderButton.keyEquivalent = ""
        alert.window.initialFirstResponder = continueButton
        NSApp.activate()
        if alert.runModal() == .alertSecondButtonReturn {
            NSWorkspace.shared.activateFileViewerSelecting([notice.file])
        }
    }

    /// The path (selectable, wrapping anywhere so a long home folder only makes the alert taller)
    /// and the sentence after it.
    private static func accessory(for notice: LegacyImportNotice) -> NSView {
        let width: CGFloat = 300
        let path = NSTextField(wrappingLabelWithString: notice.displayPath)
        path.isSelectable = true
        path.font = .monospacedSystemFont(ofSize: NSFont.smallSystemFontSize, weight: .regular)
        path.lineBreakMode = .byCharWrapping
        path.preferredMaxLayoutWidth = width
        path.setAccessibilityLabel("File location: \(notice.displayPath)")
        var views: [NSView] = [path]
        if let after = notice.textAfterPath {
            let text = NSTextField(wrappingLabelWithString: after)
            text.font = .systemFont(ofSize: NSFont.smallSystemFontSize)
            text.preferredMaxLayoutWidth = width
            views.append(text)
        }
        let stack = NSStackView(views: views)
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 8
        let size = stack.fittingSize
        stack.frame = NSRect(x: 0, y: 0, width: width, height: max(size.height, 20))
        return stack
    }
}

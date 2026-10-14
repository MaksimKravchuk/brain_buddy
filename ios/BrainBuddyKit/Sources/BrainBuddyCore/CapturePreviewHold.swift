/// Keeps the capture sheet's last answered preview on screen while the next one is being computed.
///
/// On the shared runtime every keystroke changes the draft and so asks for a new preview. The sheet
/// must not swap itself for a loading screen in between: that would tear down the text field and
/// drop the keystrokes typed meanwhile. The sheet shows `shown(isReady:fresh:)` instead: the fresh
/// answer when there is one, otherwise the last one that was ready, otherwise an empty preview.
public struct CapturePreviewHold: Equatable, Sendable {
    public private(set) var lastReady: CapturePreview?

    public init(lastReady: CapturePreview? = nil) { self.lastReady = lastReady }

    /// The empty answer, for the moment before any preview is ready.
    public static let empty = CapturePreview(title: "", project: nil, tags: [], tokens: [], problem: nil)

    /// Remembers `preview` as the answer to hold, once its query is ready.
    public mutating func record(_ preview: CapturePreview, isReady: Bool) {
        if isReady { lastReady = preview }
    }

    /// What to draw now. `fresh` is only read when the query is ready.
    public func shown(isReady: Bool, fresh: () -> CapturePreview) -> CapturePreview {
        isReady ? fresh() : (lastReady ?? Self.empty)
    }
}

/// What the capture sheet does about a preview that is not ready. The text field and the sheet
/// chrome never depend on this; only the problem line does.
public enum CapturePreviewGate {
    /// A failed preview is the only state worth a line of its own; loading is silent.
    public static func failureMessage(isFailed: Bool) -> String? {
        isFailed ? "Couldn't check this task. Your text is kept. Try again." : nil
    }
}

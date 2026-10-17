import AppKit
import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyMacCore
import Carbon.HIToolbox
import SwiftUI

private let quickCaptureSignature: OSType = 0x42424350 // BBCP
private let quickCaptureHotKeyID: UInt32 = 1

/// The Carbon hot-key callback, a plain function so it converts to a C function pointer and holds
/// no state: it reaches the controller through `context`, the unretained pointer `start` passed,
/// which `stop()` invalidates by removing the handler first.
private func quickCaptureHotKeyPressed(
    _ call: EventHandlerCallRef?, _ event: EventRef?, _ context: UnsafeMutableRawPointer?
) -> OSStatus {
    guard let event, let context else { return OSStatus(eventNotHandledErr) }
    var identifier = EventHotKeyID()
    let result = GetEventParameter(
        event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
        nil, MemoryLayout<EventHotKeyID>.size, nil, &identifier
    )
    guard result == noErr, identifier.signature == quickCaptureSignature, identifier.id == quickCaptureHotKeyID else {
        return OSStatus(eventNotHandledErr)
    }
    let controller = Unmanaged<QuickCaptureController>.fromOpaque(context).takeUnretainedValue()
    Task { @MainActor in controller.show() }
    return noErr
}

/// The quick-capture panel: borderless and clear, so the card's glass is the whole window. A
/// borderless panel refuses key status by default; this one takes it so the field can be typed in.
private final class QuickCapturePanel: NSPanel {
    override var canBecomeKey: Bool { true }
}

@MainActor
final class QuickCaptureController: ObservableObject {
    @Published private(set) var registrationError: String?

    private weak var model: BrainBuddyModel?
    private var eventHandler: EventHandlerRef?
    private var hotKey: EventHotKeyRef?
    private var panel: NSPanel?
    private var previousApplication: NSRunningApplication?

    /// 029-FR-004: whether ⌃⌥⇧B is registered, for the first run's hint and tip.
    var hotkeyRegistered: Bool { hotKey != nil && registrationError == nil }

    func start(model: BrainBuddyModel) {
        self.model = model
        guard eventHandler == nil, hotKey == nil else { return }
        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)
        )
        let handlerResult = InstallEventHandler(
            GetApplicationEventTarget(), quickCaptureHotKeyPressed, 1, &eventType,
            Unmanaged.passUnretained(self).toOpaque(), &eventHandler
        )
        guard handlerResult == noErr else {
            registrationError = "Global Quick Capture shortcut could not be enabled. Use File › Quick Capture."
            return
        }
        let key = EventHotKeyID(signature: quickCaptureSignature, id: quickCaptureHotKeyID)
        let keyResult = RegisterEventHotKey(
            UInt32(kVK_ANSI_B), UInt32(controlKey | optionKey | shiftKey), key,
            GetApplicationEventTarget(), UInt32(kEventHotKeyExclusive), &hotKey
        )
        guard keyResult == noErr else {
            if let eventHandler { RemoveEventHandler(eventHandler) }
            eventHandler = nil
            registrationError = "⌃⌥⇧B is unavailable. Use File › Quick Capture."
            return
        }
        registrationError = nil
    }

    func stop() {
        close()
        if let hotKey { UnregisterEventHotKey(hotKey) }
        if let eventHandler { RemoveEventHandler(eventHandler) }
        hotKey = nil
        eventHandler = nil
        model = nil
        registrationError = nil
    }

    func show() {
        guard let model else { return }
        if let panel {
            panel.makeKeyAndOrderFront(nil)
            return
        }
        let frontmost = NSWorkspace.shared.frontmostApplication
        previousApplication = frontmost?.processIdentifier == NSRunningApplication.current.processIdentifier
            ? nil : frontmost
        let panel = QuickCapturePanel(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 160),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false
        )
        panel.title = "Quick Capture"
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        let shortcut = registrationError == nil ? "⌃⌥⇧B" : nil
        panel.contentView = NSHostingView(
            rootView: QuickCaptureView(model: model, shortcut: shortcut) { [weak self] in
                self?.close()
            }
            .environment(\.carryOnPlatform, .mac))
        panel.center()
        self.panel = panel
        panel.makeKeyAndOrderFront(nil)
    }

    private func close() {
        panel?.close()
        panel = nil
        if let previousApplication,
           !previousApplication.isTerminated, !previousApplication.isActive {
            NSApp.yieldActivation(to: previousApplication)
            _ = previousApplication.activate(from: .current, options: [])
        }
        previousApplication = nil
    }
}

/// Quick Capture (⌃⌥⇧B) to Inbox through the kit's capture: it applies at once on this Mac and
/// never waits for the network (FR-010). Drawn as board "12 Quick capture · Mac"
/// (`MacQuickCaptureCard`): Return saves, Esc closes.
@MainActor
private struct QuickCaptureView: View {
    let model: BrainBuddyModel
    /// The global shortcut, or nil when it could not be registered.
    let shortcut: String?
    let onClose: () -> Void

    @State private var title = ""
    @State private var error: String?
    @State private var editorID = UUID().uuidString
    @State private var isSaving = false
    @State private var confirmingDiscard = false
    @FocusState private var titleFocused: Bool

    private var cleanTitle: String { title.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        MacQuickCaptureCard(
            shortcut: shortcut, tokens: MacCaptureTokens.labels(in: title), error: error,
            saveDisabled: cleanTitle.isEmpty || !EditorLimits.fits(cleanTitle, EditorLimits.title), busy: isSaving,
            onSave: save, onClose: requestClose
        ) {
            TextField("What's on your mind?", text: $title)
                .textFieldStyle(.plain)
                .macQuickCaptureField()
                .disabled(isSaving)
                .focused($titleFocused)
                .onSubmit(save)
        }
        .task { titleFocused = true }
        .alert("Discard quick capture?", isPresented: $confirmingDiscard) {
            Button("Keep editing", role: .cancel) {}
            Button("Discard", role: .destructive, action: onClose)
        } message: {
            Text("This text has not been saved to Inbox.")
        }
    }

    private func requestClose() {
        guard !isSaving else { return }
        if title.isEmpty { onClose() } else { confirmingDiscard = true }
    }

    private func save() {
        guard !isSaving, !cleanTitle.isEmpty, EditorLimits.fits(cleanTitle, EditorLimits.title) else { return }
        let authored = cleanTitle
        let submittedEditorID = editorID
        isSaving = true
        Task {
            do {
                try await model.quickCaptureInbox(authored, editorID: submittedEditorID)
                onClose()
            } catch {
                self.error = (error as? GTDValidationError)?.message ?? "Brain Buddy couldn't save this change. Try again."
                isSaving = false
            }
        }
    }
}

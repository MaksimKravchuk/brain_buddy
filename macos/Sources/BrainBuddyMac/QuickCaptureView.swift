import AppKit
import Carbon.HIToolbox
import SwiftUI

private let quickCaptureSignature: OSType = 0x42424350 // BBCP
private let quickCaptureHotKeyID: UInt32 = 1

private let quickCaptureEventHandler: EventHandlerUPP = { _, event, context in
    guard let event, let context else { return OSStatus(eventNotHandledErr) }
    var identifier = EventHotKeyID()
    let result = GetEventParameter(
        event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
        nil, MemoryLayout<EventHotKeyID>.size, nil, &identifier
    )
    guard result == noErr,
          identifier.signature == quickCaptureSignature,
          identifier.id == quickCaptureHotKeyID else {
        return OSStatus(eventNotHandledErr)
    }
    let controller = Unmanaged<QuickCaptureController>.fromOpaque(context).takeUnretainedValue()
    Task { @MainActor in controller.show() }
    return noErr
}

@MainActor
final class QuickCaptureController: ObservableObject {
    @Published private(set) var registrationError: String?

    private weak var model: BrainBuddyModel?
    private var eventHandler: EventHandlerRef?
    private var hotKey: EventHotKeyRef?
    private var panel: NSPanel?
    private var previousApplication: NSRunningApplication?

    func start(model: BrainBuddyModel) {
        self.model = model
        guard eventHandler == nil, hotKey == nil else { return }
        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed)
        )
        let handlerResult = InstallEventHandler(
            GetApplicationEventTarget(), quickCaptureEventHandler, 1, &eventType,
            Unmanaged.passUnretained(self).toOpaque(), &eventHandler
        )
        guard handlerResult == noErr else {
            registrationError = "Global Quick Capture shortcut could not be enabled. Use the toolbar button."
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
            registrationError = "⌃⌥⇧B is unavailable. Use Quick Capture in the toolbar."
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
        guard let model, model.isLocalWorkspace else { return }
        if let panel {
            panel.makeKeyAndOrderFront(nil)
            return
        }
        let frontmost = NSWorkspace.shared.frontmostApplication
        previousApplication = frontmost?.processIdentifier == NSRunningApplication.current.processIdentifier
            ? nil : frontmost
        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: 480, height: 205),
            styleMask: [.titled, .nonactivatingPanel],
            backing: .buffered, defer: false
        )
        panel.title = "Quick Capture"
        panel.isFloatingPanel = true
        panel.hidesOnDeactivate = false
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.contentView = NSHostingView(rootView: QuickCaptureView(model: model) { [weak self] in
            self?.close()
        })
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

@MainActor
private struct QuickCaptureView: View {
    @ObservedObject var model: BrainBuddyModel
    let onClose: () -> Void

    @State private var title = ""
    @State private var saving = false
    @State private var error: String?
    @State private var confirmingDiscard = false
    @State private var pendingSave: (title: String, key: UUID)?
    @FocusState private var titleFocused: Bool

    private var cleanTitle: String { title.trimmingCharacters(in: .whitespacesAndNewlines) }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Capture to Inbox")
                .font(.title2.bold())
            TextField("What's on your mind?", text: $title)
                .textFieldStyle(.roundedBorder)
                .focused($titleFocused)
                .onSubmit { Task { await save() } }
                .disabled(saving)
            Text("You can clarify and organize it later.")
                .font(.caption)
                .foregroundStyle(.secondary)
            if let error {
                Text(error).font(.caption).foregroundStyle(.red)
            }
            HStack {
                Spacer()
                Button("Cancel") { requestClose() }
                    .keyboardShortcut(.cancelAction)
                    .disabled(saving)
                Button(saving ? "Saving…" : "Save to Inbox") { Task { await save() } }
                    .keyboardShortcut(.defaultAction)
                    .disabled(saving || cleanTitle.isEmpty || cleanTitle.count > 500)
            }
        }
        .padding(22)
        .frame(width: 480, height: 205)
        .task { titleFocused = true }
        .alert("Discard quick capture?", isPresented: $confirmingDiscard) {
            Button("Keep editing", role: .cancel) {}
            Button("Discard", role: .destructive, action: onClose)
        } message: {
            Text("This text has not been saved to Inbox.")
        }
    }

    private func requestClose() {
        if title.isEmpty { onClose() }
        else { confirmingDiscard = true }
    }

    private func save() async {
        guard !saving, !cleanTitle.isEmpty, cleanTitle.count <= 500 else { return }
        let key = pendingSave?.title == cleanTitle ? pendingSave!.key : UUID()
        pendingSave = (cleanTitle, key)
        saving = true
        error = nil
        do {
            try await model.quickCaptureInbox(cleanTitle, idempotencyKey: key)
            pendingSave = nil
            onClose()
        } catch {
            self.error = error.localizedDescription
        }
        saving = false
    }
}

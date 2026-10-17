import BrainBuddyCore
import BrainBuddyDesign
import SwiftUI

// The Mac capture surfaces in the Carry On design system (boards "10 Create task", "11 Voice
// capture" and "12 Quick capture · Mac"): the new-task card in the list, the list chooser, the voice
// sheet and the quick-capture panel. Presentation only: values, bindings and closures in; the text
// fields themselves are passed in by the caller, so these render with fixtures in snapshots.

/// Instrument faces at the capture boards' own sizes.
enum MacCaptureFont {
    /// Eyebrows, hints and footers: 12.
    static var meta: Font { MacRowFont.action(size: 12, weight: 400, relativeTo: .caption) }
    /// "Put it in", "Transcript": 12 semibold.
    static var label: Font { MacRowFont.action(size: 12, weight: 600, relativeTo: .caption) }
    /// Chips: 13.
    static var chip: Font { MacRowFont.action(size: 13, weight: 400, relativeTo: .caption) }
    /// The voice sheet's status line: 13.
    static var status: Font { MacRowFont.action(size: 13, weight: 400, relativeTo: .caption) }
    /// The quick-capture field and the transcript: 14.
    static var field: Font { MacRowFont.action(size: 14, weight: 400, relativeTo: .body) }
    /// The new task's title as typed: 19 semibold.
    static var title: Font { MacRowFont.action(size: 19, weight: 600, relativeTo: .title3) }
    /// "What feels heaviest?", "Add task to": Instrument Serif 22 (the type scale's title).
    static var question: Font { .carryOn(CarryOnTypeScale.title) }
}

// MARK: - Surface

/// What a floating capture card is drawn on: the system glass in the app, or a `surface-card`
/// stand-in where glass cannot render (an `ImageRenderer` snapshot).
enum MacCaptureSurfaceKind: Sendable {
    case glass, standIn
}

extension View {
    /// A floating capture card's surface at `cornerRadius`.
    @ViewBuilder
    func macCaptureSurface(cornerRadius: CGFloat, kind: MacCaptureSurfaceKind) -> some View {
        switch kind {
        case .glass:
            glassEffect(.regular, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
        case .standIn:
            background(
                CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
        }
    }

    /// The new task's title field: 19 semibold in text-primary.
    func macNewTaskTitleField() -> some View {
        font(MacCaptureFont.title).foregroundStyle(CarryOnColorStyle.coTextPrimary)
    }

    /// A 14 field on `field-bg`, radius 12, padding 9/12 (the Waiting for line).
    func macCaptureField() -> some View {
        font(MacCaptureFont.field)
            .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            .padding(.vertical, 9)
            .padding(.horizontal, 12)
            .background(CarryOnColorStyle.coFieldBg, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    /// The quick-capture field's text: 14 in text-primary (the field-bg plate is the card's).
    func macQuickCaptureField() -> some View {
        font(MacCaptureFont.field).foregroundStyle(CarryOnColorStyle.coTextPrimary)
    }
}

// MARK: - Small parts

/// A recognised Smart Add token (`#calls`, `@Garage`): text-primary on `field-token-bg`, radius 5,
/// padding 1/5.
struct MacCaptureToken: View {
    let text: String
    var font: Font = MacCaptureFont.meta

    var body: some View {
        Text(text)
            .font(font)
            .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            .lineLimit(1)
            .padding(.horizontal, 5)
            .padding(.vertical, 1)
            .background(CarryOnColorStyle.coFieldTokenBg, in: RoundedRectangle(cornerRadius: 5, style: .continuous))
    }
}

/// A 12 line in secondary, or in `status-danger` for a problem.
struct MacCaptureNote: View {
    let text: String
    var danger = false
    var topPadding: CGFloat = 8

    var body: some View {
        Text(text)
            .font(MacCaptureFont.meta)
            .foregroundStyle(danger ? CarryOnColorStyle.coStatusDanger : CarryOnColorStyle.coTextSecondary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, topPadding)
    }
}

/// The board's outlined chip ("+ Date" on board 10): no fill, a 1.5 ring in
/// `control-quiet-pressed`, secondary text. Here it says what a capture has none of.
struct MacOutlineChip: View {
    let text: String

    var body: some View {
        Text(text)
            .font(MacCaptureFont.chip)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .lineLimit(1)
            .padding(.horizontal, 12)
            .frame(height: 26)
            .overlay(Capsule().strokeBorder(CarryOnColorStyle.coControlQuietPressed, lineWidth: 1.5))
    }
}

/// A value and the words a choice chip shows for it.
struct MacChoice<Value: Hashable>: Hashable {
    let value: Value
    let title: String
}

extension MacChoice: Sendable where Value: Sendable {}

/// A single choice as a row of chips, 6 apart and wrapping. The row takes keyboard focus and the
/// left and right arrows move the choice, as the radio group and segmented control did.
struct MacChoiceChipRow<Value: Hashable>: View {
    let options: [MacChoice<Value>]
    @Binding var selection: Value
    @Environment(\.isEnabled) private var isEnabled

    var body: some View {
        MacInspectorFlow(spacing: 6) {
            ForEach(options, id: \.value) { option in
                let selected = option.value == selection
                Button {
                    selection = option.value
                } label: {
                    CarryOnChip(option.title, size: .quick, isSelected: selected)
                        .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .opacity(isEnabled ? 1 : 0.4)
                .accessibilityAddTraits(selected ? .isSelected : [])
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .focusable()
        .onKeyPress(.leftArrow) { move(by: -1) }
        .onKeyPress(.rightArrow) { move(by: 1) }
        .accessibilityElement(children: .contain)
    }

    private func move(by step: Int) -> KeyPress.Result {
        guard isEnabled, let current = options.firstIndex(where: { $0.value == selection }) else { return .ignored }
        let next = current + step
        if options.indices.contains(next) { selection = options[next].value }
        return .handled
    }
}

// MARK: - Voice button

/// The board's mic: `<rect x="9" y="3.5" width="6" height="11" rx="3"/>` and
/// `<path d="M5.5 11.5a6.5 6.5 0 0013 0M12 18v3"/>` on a 24 grid; the half circle is two cubic
/// quarters through (12, 18).
struct MacMicGlyph: Shape {
    func path(in rect: CGRect) -> Path {
        let unit = min(rect.width, rect.height) / 24
        func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
            CGPoint(x: rect.minX + x * unit, y: rect.minY + y * unit)
        }
        let handle: CGFloat = 6.5 * 0.5523
        var path = Path()
        path.addRoundedRect(
            in: CGRect(x: rect.minX + 9 * unit, y: rect.minY + 3.5 * unit, width: 6 * unit, height: 11 * unit),
            cornerSize: CGSize(width: 3 * unit, height: 3 * unit))
        path.move(to: point(5.5, 11.5))
        path.addCurve(to: point(12, 18), control1: point(5.5, 11.5 + handle), control2: point(12 - handle, 18))
        path.addCurve(to: point(18.5, 11.5), control1: point(12 + handle, 18), control2: point(18.5, 11.5 + handle))
        path.move(to: point(12, 18))
        path.addLine(to: point(12, 21))
        return path
    }
}

/// The round voice button's face: `voice-bg` with the mic in `voice-fg`; while listening, a 2.5
/// `voice-live-ring` and the board's six bars instead of the mic. Decorative.
struct MacVoiceButtonFace: View {
    let live: Bool
    var size: CGFloat = 34

    private static let barHeights: [CGFloat] = [6, 12, 18, 10, 15, 7]

    var body: some View {
        ZStack {
            Circle().fill(CarryOnColorStyle.coVoiceBg)
            if live {
                Circle().strokeBorder(CarryOnColorStyle.coVoiceLiveRing, lineWidth: 2.5)
                HStack(spacing: 2) {
                    ForEach(Self.barHeights.indices, id: \.self) { index in
                        RoundedRectangle(cornerRadius: 2, style: .continuous)
                            .fill(CarryOnColorStyle.coVoiceFg)
                            .frame(width: 3, height: Self.barHeights[index])
                    }
                }
            } else {
                MacMicGlyph()
                    .stroke(
                        CarryOnColorStyle.coVoiceFg,
                        style: StrokeStyle(lineWidth: 1.8 * 18 / 24, lineCap: .round, lineJoin: .round)
                    )
                    .frame(width: 18, height: 18)
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

// MARK: - New task (board 10)

/// The new-task card in the list: "New · goes to Next actions", the title field, then whatever the
/// draft needs (`details`). Padding 24/26, radius 22, on glass.
struct MacNewTaskCard<Field: View, Details: View>: View {
    let listTitle: String
    let surface: MacCaptureSurfaceKind
    let field: Field
    let details: Details

    init(
        listTitle: String, surface: MacCaptureSurfaceKind = .glass, @ViewBuilder field: () -> Field,
        @ViewBuilder details: () -> Details
    ) {
        self.listTitle = listTitle
        self.surface = surface
        self.field = field()
        self.details = details()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 6) {
                Text("New")
                Text("·")
                Text("goes to \(listTitle)")
            }
            .font(MacCaptureFont.meta)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .lineLimit(1)
            .accessibilityElement(children: .combine)
            field
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 10)
            details
        }
        .padding(.vertical, 24)
        .padding(.horizontal, 26)
        .frame(maxWidth: .infinity, alignment: .leading)
        .macCaptureSurface(cornerRadius: 22, kind: surface)
    }
}

/// What Smart Add will file the task under, as the board's chips: the project, then the tags
/// (13, 26 high, 6 apart). What it has none of is an outlined chip.
struct MacNewTaskClassification: View {
    let project: ClassificationPreview?
    let tags: [ClassificationPreview]
    var topPadding: CGFloat = 14

    /// The same in words, for VoiceOver: "Garage · #calls (new tag)".
    static func summary(project: ClassificationPreview?, tags: [ClassificationPreview]) -> String {
        let projectText = project.map { $0.isNew ? "\($0.name) (new project)" : $0.name } ?? "No project"
        let tagTexts = tags.map { $0.isNew ? "#\($0.name) (new tag)" : "#\($0.name)" }
        return ([projectText] + (tagTexts.isEmpty ? ["No tags"] : tagTexts)).joined(separator: " · ")
    }

    var body: some View {
        MacInspectorFlow(spacing: 6) {
            if let project {
                CarryOnChip(project.isNew ? "\(project.name) (new project)" : project.name)
            } else {
                MacOutlineChip(text: "No project")
            }
            if tags.isEmpty {
                MacOutlineChip(text: "No tags")
            } else {
                ForEach(Array(tags.enumerated()), id: \.offset) { _, tag in
                    CarryOnChip(tag.isNew ? "\(tag.name) (new tag)" : tag.name)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.top, topPadding)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Self.summary(project: project, tags: tags))
    }
}

/// The card's last line: the strong "Add" pill, any extra control, then the 12 secondary hint on the
/// right ("⌘N · Return adds").
struct MacNewTaskFooter<Extra: View>: View {
    let addEnabled: Bool
    let hint: String
    let onAdd: () -> Void
    let extra: Extra

    init(addEnabled: Bool, hint: String, onAdd: @escaping () -> Void, @ViewBuilder extra: () -> Extra) {
        self.addEnabled = addEnabled
        self.hint = hint
        self.onAdd = onAdd
        self.extra = extra()
    }

    var body: some View {
        HStack(spacing: 8) {
            Button(action: onAdd) { Text("Add") }
                .buttonStyle(.carryOnStrong)
                .disabled(!addEnabled)
                .accessibilityLabel("Add task")
            extra
            Spacer(minLength: 8)
            Text(hint)
                .font(MacCaptureFont.meta)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                .lineLimit(1)
        }
        .padding(.top, 18)
    }
}

extension MacNewTaskFooter where Extra == EmptyView {
    init(addEnabled: Bool, hint: String, onAdd: @escaping () -> Void) {
        self.init(addEnabled: addEnabled, hint: hint, onAdd: onAdd) { EmptyView() }
    }
}

/// "Add task to": the list a new task goes to when the view on screen is not a list (a date view
/// or history). "Put it in" and the four lists as chips; Continue and Cancel.
struct MacPutItInContent: View {
    @Binding var selection: OpenList
    let onContinue: () -> Void
    let onCancel: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Add task to")
                .font(MacCaptureFont.question)
                .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                .accessibilityAddTraits(.isHeader)
            Text("Put it in")
                .font(MacCaptureFont.label)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                .padding(.top, 16)
                .padding(.bottom, 8)
                .accessibilityHidden(true)
            MacChoiceChipRow(
                options: OpenList.allCases.map { MacChoice(value: $0, title: $0.title) }, selection: $selection
            )
            .accessibilityLabel("GTD list")
            HStack(spacing: 8) {
                Button("Continue", action: onContinue)
                    .buttonStyle(.carryOnStrong)
                    .keyboardShortcut(.defaultAction)
                Button("Cancel", action: onCancel)
                    .buttonStyle(.carryOnQuiet)
                    .keyboardShortcut(.cancelAction)
                Spacer(minLength: 0)
            }
            .padding(.top, 18)
        }
        .padding(24)
        .frame(width: 440, alignment: .topLeading)
    }
}

// MARK: - Voice capture (board 11)

/// Where the voice sheet is.
enum MacVoicePhase: Sendable, Equatable {
    case idle, recording, preparingModel, transcribing

    /// The status line beside the voice button.
    var status: String {
        switch self {
        case .idle: "Voice to task draft"
        case .recording: "Listening · on this Mac"
        case .preparingModel: "Loading local speech model…"
        case .transcribing: "Transcribing on this Mac…"
        }
    }

    var isWorking: Bool { self == .preparingModel || self == .transcribing }
}

/// A line under the voice sheet's language chips with one action (037 V-01c).
struct MacVoiceNote {
    let text: String
    let action: String
    let perform: () -> Void
}

/// The voice sheet: the round voice button (Record, or Stop & transcribe while listening) with its
/// status, the language, the editable transcript and the draft actions. 420 wide, padding 14,
/// radius 16. `transcript` is the editor; `more` the transcript's menu.
struct MacVoiceCaptureCard<Transcript: View, More: View>: View {
    let phase: MacVoicePhase
    let languages: [MacChoice<String>]
    @Binding var language: String
    let error: String?
    let hasTranscript: Bool
    let canUseTranscript: Bool
    let surface: MacCaptureSurfaceKind
    let onRecord: () -> Void
    let onStop: () -> Void
    let onDiscardRecording: () -> Void
    let onUseAsTask: (() -> Void)?
    let onClose: () -> Void
    /// False while the chosen language has no recogniser on this Mac (037 V-01c).
    let canRecord: Bool
    let note: MacVoiceNote?
    let transcript: Transcript
    let more: More

    init(
        phase: MacVoicePhase, languages: [MacChoice<String>], language: Binding<String>, error: String?,
        hasTranscript: Bool, canUseTranscript: Bool, surface: MacCaptureSurfaceKind = .glass,
        onRecord: @escaping () -> Void, onStop: @escaping () -> Void, onDiscardRecording: @escaping () -> Void,
        onUseAsTask: (() -> Void)?, onClose: @escaping () -> Void, canRecord: Bool = true, note: MacVoiceNote? = nil,
        @ViewBuilder transcript: () -> Transcript, @ViewBuilder more: () -> More
    ) {
        self.phase = phase
        self.languages = languages
        self._language = language
        self.error = error
        self.hasTranscript = hasTranscript
        self.canUseTranscript = canUseTranscript
        self.surface = surface
        self.onRecord = onRecord
        self.onStop = onStop
        self.onDiscardRecording = onDiscardRecording
        self.onUseAsTask = onUseAsTask
        self.onClose = onClose
        self.canRecord = canRecord
        self.note = note
        self.transcript = transcript()
        self.more = more()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            MacChoiceChipRow(options: languages, selection: $language)
                .disabled(phase != .idle)
                .accessibilityLabel("Language")
                .padding(.top, 14)
            if let note, phase == .idle {
                VStack(alignment: .leading, spacing: 6) {
                    MacSheetStatus(text: note.text, tone: .secondary, font: MacCaptureFont.status)
                    Button(note.action, action: note.perform).buttonStyle(.macText)
                }
                .padding(.top, 12)
            }
            if phase == .recording {
                HStack(spacing: 8) {
                    Button("Stop & transcribe", action: onStop)
                        .buttonStyle(.carryOnStrong)
                    Button("Discard", action: onDiscardRecording)
                        .buttonStyle(.carryOnQuiet)
                }
                .padding(.top, 12)
            }
            if let error {
                Text(error)
                    .font(MacCaptureFont.status)
                    .foregroundStyle(CarryOnColorStyle.coStatusDanger)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.top, 12)
            }
            if hasTranscript {
                HStack {
                    Text("Transcript")
                        .font(MacCaptureFont.label)
                        .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    Spacer(minLength: 8)
                    Text("Not saved yet")
                        .font(MacCaptureFont.meta)
                        .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                }
                .padding(.top, 14)
                .padding(.bottom, 8)
                transcript
                    .padding(.vertical, 9)
                    .padding(.horizontal, 12)
                    .background(
                        CarryOnColorStyle.coBgGround, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            }
            HStack(spacing: 8) {
                if let onUseAsTask {
                    Button("Use as task draft", action: onUseAsTask)
                        .buttonStyle(.carryOnStrong)
                        .disabled(!canUseTranscript)
                }
                Spacer(minLength: 0)
                if hasTranscript { more }
            }
            .padding(.top, 12)
        }
        .padding(14)
        .frame(width: 420, alignment: .topLeading)
        .macCaptureSurface(cornerRadius: 16, kind: surface)
    }

    private var header: some View {
        HStack(spacing: 12) {
            Button(action: phase == .recording ? onStop : onRecord) {
                MacVoiceButtonFace(live: phase == .recording, size: 36)
            }
            .buttonStyle(.plain)
            .disabled(phase.isWorking || (phase == .idle && !canRecord))
            .accessibilityLabel(phase == .recording ? "Stop & transcribe" : "Record")
            .help(phase == .recording ? "Stop & transcribe" : "Record")
            Text(phase.status)
                .font(MacCaptureFont.status)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                .lineLimit(1)
                .accessibilityAddTraits(phase == .idle ? .isHeader : [])
            if phase.isWorking {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityLabel(phase.status)
            }
            Spacer(minLength: 8)
            Button(action: onClose) {
                Text("Close")
                    .font(MacCaptureFont.meta)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
            .buttonStyle(.plain)
        }
    }
}

// MARK: - Quick capture (board 12)

/// The quick-capture panel's card: the mark and "What feels heaviest?" with the shortcut on the
/// right; the field on `field-bg`; then "Goes to Inbox" with the recognised tokens, and "Return to
/// save · Esc to close", which are the Save and Cancel buttons (Return and Esc). 520 wide, padding
/// 20, radius 26, on glass.
struct MacQuickCaptureCard<Field: View>: View {
    /// "⌃⌥⇧B", or nil when the global shortcut could not be registered.
    let shortcut: String?
    let tokens: [String]
    let error: String?
    let saveDisabled: Bool
    let busy: Bool
    let surface: MacCaptureSurfaceKind
    let onSave: () -> Void
    let onClose: () -> Void
    let field: Field

    init(
        shortcut: String?, tokens: [String], error: String?, saveDisabled: Bool, busy: Bool = false,
        surface: MacCaptureSurfaceKind = .glass, onSave: @escaping () -> Void, onClose: @escaping () -> Void,
        @ViewBuilder field: () -> Field
    ) {
        self.shortcut = shortcut
        self.tokens = tokens
        self.error = error
        self.saveDisabled = saveDisabled
        self.busy = busy
        self.surface = surface
        self.onSave = onSave
        self.onClose = onClose
        self.field = field()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                CarryOnMark(size: 26)
                Text("What feels heaviest?")
                    .font(MacCaptureFont.question)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    .lineLimit(1)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: 8)
                if let shortcut {
                    Text(shortcut)
                        .font(MacCaptureFont.meta)
                        .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                }
            }
            field
                .frame(maxWidth: .infinity, minHeight: 34, alignment: .leading)
                .padding(.vertical, 12)
                .padding(.horizontal, 14)
                .background(CarryOnColorStyle.coFieldBg, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                .padding(.top, 16)
            if let error {
                MacCaptureNote(text: error, danger: true)
            }
            HStack(spacing: 6) {
                Text("Goes to Inbox")
                ForEach(Array(tokens.enumerated()), id: \.offset) { _, token in
                    MacCaptureToken(text: token)
                }
                Spacer(minLength: 8)
                Button(action: onSave) { Text("Return to save") }
                    .buttonStyle(.plain)
                    .keyboardShortcut(.defaultAction)
                    .disabled(busy || saveDisabled)
                    .accessibilityLabel("Save to Inbox")
                Text("·").accessibilityHidden(true)
                Button(action: onClose) { Text("Esc to close") }
                    .buttonStyle(.plain)
                    .keyboardShortcut(.cancelAction)
                    .disabled(busy)
                    .accessibilityLabel("Cancel")
            }
            .font(MacCaptureFont.meta)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .lineLimit(1)
            .padding(.top, 12)
        }
        .padding(20)
        .frame(width: 520, alignment: .topLeading)
        .macCaptureSurface(cornerRadius: 26, kind: surface)
    }
}

/// The quick-capture footer's tokens.
enum MacCaptureTokens {
    /// The tokens Smart Add recognises in `text`, as the footer shows them ("@Garage", "#calls"),
    /// in text order without repeats. The capture itself parses the text again when it saves.
    static func labels(in text: String) -> [String] {
        var seen = Set<String>()
        var shown: [String] = []
        for token in SmartAddParser.parse(text).tokens {
            let label = (token.kind == .project ? "@" : "#") + token.name
            if seen.insert(label).inserted { shown.append(label) }
        }
        return shown
    }
}

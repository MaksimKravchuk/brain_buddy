import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// F-01 (029-FR-003 – 029-FR-007, 029-FR-031): the empty Inbox of a clean Mac. One focused field,
/// hint rows that are honest about the shortcut and speech, and the "no account" line. Presentation
/// only: the text is the window's capture draft, Return and Esc go to the first-run model.
struct WelcomeInboxView: View {
    @Binding var text: String
    let hotkeyAvailable: Bool
    let speechAvailable: Bool
    /// F-01.09: the existing capture error, shown under the field; the text stays in the field.
    let errorText: String?
    let onSubmit: () -> Void
    let onSkip: () -> Void
    let onMic: () -> Void
    @FocusState private var fieldFocused: Bool

    private var typed: Bool { !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                CarryOnMark(size: 44)
                Text(FirstRunCopy.appName).font(Self.serif(44)).foregroundStyle(.coTextPrimary)
            }
            Text(FirstRunCopy.heading)
                .font(Self.serif(36))
                .foregroundStyle(.coTextPrimary)
                .padding(.top, 28)
                .accessibilityAddTraits(.isHeader)
            Text(FirstRunCopy.intro)
                .font(MacRowFont.action(size: 15, weight: 400, relativeTo: .body))
                .foregroundStyle(.coTextSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 12)
            field.padding(.top, 24)
            if let errorText { MacCaptureNote(text: errorText, danger: true, topPadding: 4) }
            if typed {
                // F-01.02: the two lines sit 4 pt under the field.
                MacCaptureNote(text: FirstRunCopy.typingLine, topPadding: 4)
                MacCaptureNote(text: FirstRunCopy.typingKeys, topPadding: 0)
            }
            VStack(alignment: .leading, spacing: 10) { hints }.padding(.top, 20)
            Text(FirstRunCopy.noAccount)
                .font(MacRowFont.title)
                .foregroundStyle(.coTextSecondary)
                .padding(.top, 24)
        }
        .frame(maxWidth: 560, alignment: .leading)
        .padding(.horizontal, 28)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background {
            // F-01.07: Esc skips, empty or typed. Invisible, so only its shortcut shows.
            Button("Skip", action: onSkip)
                .keyboardShortcut(.cancelAction)
                .frame(width: 0, height: 0)
                .opacity(0)
                .accessibilityHidden(true)
        }
        .task { fieldFocused = true }
    }

    private var field: some View {
        HStack(spacing: 8) {
            TextField(FirstRunCopy.placeholder, text: $text)
                .textFieldStyle(.plain)
                .font(MacCaptureFont.field)
                .foregroundStyle(.coTextPrimary)
                .focused($fieldFocused)
                .onSubmit(onSubmit)
                .accessibilityLabel(FirstRunCopy.heading)
            if speechAvailable {
                Button(action: onMic) {
                    MacVoiceButtonFace(live: false, size: CarryOnLayout.MacWelcome.micSize)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Speak")
            }
        }
        .padding(.horizontal, 12)
        .frame(height: CarryOnLayout.MacWelcome.fieldHeight)
        .background(CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay {
            if fieldFocused {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(CarryOnColorStyle.coFocusRing, lineWidth: CarryOnLayout.FocusRing.width)
                    .padding(-(CarryOnLayout.FocusRing.offset + CarryOnLayout.FocusRing.width))
            }
        }
    }

    @ViewBuilder
    private var hints: some View {
        if hotkeyAvailable {
            hint(Text("⌃⌥⇧B"), FirstRunCopy.hotkeyHint, spoken: "Shortcut, Control Option Shift B. \(FirstRunCopy.hotkeyHint)")
        } else {
            Text(FirstRunCopy.hotkeyUnavailable).font(MacRowFont.title).foregroundStyle(.coTextSecondary)
        }
        if speechAvailable {
            hint(Image(systemName: "mic"), FirstRunCopy.speechHint, spoken: "Microphone. \(FirstRunCopy.speechHint)")
        }
    }

    /// A chip on `surface-token` with the shortcut or the mic glyph, then the words.
    private func hint<Chip: View>(_ chip: Chip, _ words: String, spoken: String) -> some View {
        HStack(spacing: 10) {
            chip
                .font(MacCaptureFont.chip)
                .foregroundStyle(.coTextPrimary)
                .frame(width: CarryOnLayout.MacWelcome.hintWidth, height: CarryOnLayout.Chip.macHeight)
                .background(CarryOnColorStyle.coChipBg, in: Capsule())
            Text(words).font(MacRowFont.title).foregroundStyle(.coTextPrimary)
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(spoken)
    }

    private static func serif(_ size: CGFloat) -> Font {
        CarryOnFonts.register()
        return .custom(CarryOnFontFace.voice.postScriptName(weight: 400), size: size, relativeTo: .largeTitle)
    }
}

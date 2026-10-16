#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyCore
    import BrainBuddyDesign
    import BrainBuddyDesignTestSupport
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac

    /// The Mac capture surfaces against their approved renders, light and dark: the new-task card
    /// and its list chooser (board 10), the voice sheet listening and with a transcript (board 11) and
    /// the quick-capture panel (board 12), composed from the capture components with the boards' own
    /// text. Text fields are AppKit-backed and do not render here, so each field is its text in the
    /// field's own style; the glass is drawn as its `surface-card` stand-in.
    @Suite("Carry On Mac capture snapshots")
    @MainActor
    struct CarryOnCaptureSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        private let languages = [
            MacChoice(value: "ru", title: "Russian"),
            MacChoice(value: "en", title: "English"),
            MacChoice(value: "auto", title: "Auto"),
        ]

        /// The card sits on the window's ground, as on the boards.
        private func onGround<Content: View>(_ content: Content) -> some View {
            content
                .padding(20)
                .background(CarryOnColorStyle.coBgGround)
        }

        @Test("The new-task card renders as approved", arguments: Appearance.allCases)
        func newTask(appearance: Appearance) {
            let view = onGround(
                MacNewTaskCard(listTitle: "Next actions", surface: .standIn) {
                    Text("Call Sam about the van @Garage #calls").macNewTaskTitleField()
                } details: {
                    MacCaptureNote(text: "“Call Sam about the van”")
                    MacNewTaskClassification(
                        project: ClassificationPreview(name: "Garage", isNew: false),
                        tags: [ClassificationPreview(name: "calls", isNew: false)])
                    MacNewTaskFooter(addEnabled: true, hint: "⌘N · Return adds", onAdd: {})
                })
            assertSnapshot(view, named: "mac-capture-newtask-\(appearance.rawValue)", scheme: appearance.scheme, width: 560)
        }

        @Test("The new-task card without a project or tags renders as approved", arguments: Appearance.allCases)
        func newTaskUnfiled(appearance: Appearance) {
            let view = onGround(
                MacNewTaskCard(listTitle: "Inbox", surface: .standIn) {
                    Text("Renew parking permit").macNewTaskTitleField()
                } details: {
                    MacNewTaskClassification(project: nil, tags: [])
                    MacNewTaskFooter(addEnabled: true, hint: "⌘N · Return adds", onAdd: {})
                })
            assertSnapshot(
                view, named: "mac-capture-newtask-unfiled-\(appearance.rawValue)", scheme: appearance.scheme, width: 560)
        }

        @Test("The list chooser renders as approved", arguments: Appearance.allCases)
        func putItIn(appearance: Appearance) {
            let view = MacPutItInContent(selection: .constant(OpenList.next), onContinue: {}, onCancel: {})
                .background(CarryOnColorStyle.coSurfaceCard)
            assertSnapshot(view, named: "mac-capture-putitin-\(appearance.rawValue)", scheme: appearance.scheme, width: 440)
        }

        @Test("The voice sheet while listening renders as approved", arguments: Appearance.allCases)
        func voiceListening(appearance: Appearance) {
            let view = onGround(
                MacVoiceCaptureCard(
                    phase: .recording, languages: languages, language: .constant("en"), error: nil,
                    hasTranscript: false, canUseTranscript: false, surface: .standIn,
                    onRecord: {}, onStop: {}, onDiscardRecording: {}, onUseAsTask: {}, onClose: {}
                ) {
                    EmptyView()
                } more: {
                    EmptyView()
                })
            assertSnapshot(
                view, named: "mac-capture-voice-listening-\(appearance.rawValue)", scheme: appearance.scheme, width: 460)
        }

        @Test("The voice sheet with a transcript renders as approved", arguments: Appearance.allCases)
        func voiceTranscript(appearance: Appearance) {
            let view = onGround(
                MacVoiceCaptureCard(
                    phase: .idle, languages: languages, language: .constant("en"), error: nil,
                    hasTranscript: true, canUseTranscript: true, surface: .standIn,
                    onRecord: {}, onStop: {}, onDiscardRecording: {}, onUseAsTask: {}, onClose: {}
                ) {
                    Text("The garage is a mess, Sam needs the van back by Friday, and I still haven’t found the tax letter")
                        .font(MacCaptureFont.field)
                        .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                        .frame(maxWidth: .infinity, alignment: .leading)
                } more: {
                    Text("More")
                        .font(MacRowFont.pill)
                        .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                })
            assertSnapshot(
                view, named: "mac-capture-voice-transcript-\(appearance.rawValue)", scheme: appearance.scheme, width: 460)
        }

        @Test("The quick-capture panel renders as approved", arguments: Appearance.allCases)
        func quick(appearance: Appearance) {
            let view = onGround(
                MacQuickCaptureCard(
                    shortcut: "⌃⌥⇧B", tokens: MacCaptureTokens.labels(in: "Call Sam #calls"), error: nil,
                    saveDisabled: false, surface: .standIn, onSave: {}, onClose: {}
                ) {
                    Text("Call Sam #calls").macQuickCaptureField()
                })
            assertSnapshot(view, named: "mac-capture-quick-\(appearance.rawValue)", scheme: appearance.scheme, width: 560)
        }

        @Test("The quick-capture footer shows each recognised token once, in text order")
        func quickCaptureTokens() {
            #expect(MacCaptureTokens.labels(in: "Call Sam @Garage #calls #calls") == ["@Garage", "#calls"])
            #expect(MacCaptureTokens.labels(in: "C# and max@example.com stay literal").isEmpty)
            #expect(MacCaptureTokens.labels(in: "").isEmpty)
        }
    }
#endif

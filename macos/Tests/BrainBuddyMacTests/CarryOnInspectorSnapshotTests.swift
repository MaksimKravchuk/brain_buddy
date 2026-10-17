#if canImport(SwiftUI) && os(macOS)
    import AppKit
    import BrainBuddyCore
    import BrainBuddyPersistence
    import BrainBuddyWorkspace
    import BrainBuddyDesign
    import BrainBuddyDesignTestSupport
    import SwiftUI
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore

    /// The Mac task inspector against its approved renders, light and dark: the boards' Next
    /// action, Inbox "What is it?", Waiting for, Someday, Done, Not now popover and empty inspector,
    /// composed from the inspector components with the boards' own text.
    @Suite("Carry On Mac inspector snapshots")
    @MainActor
    struct CarryOnInspectorSnapshotTests {
        enum Appearance: String, CaseIterable, Sendable {
            case light, dark

            var scheme: ColorScheme { self == .dark ? .dark : .light }
        }

        private let garage = CarryOnProjectColor.ochre
        private let allotment = CarryOnProjectColor.moss

        /// The card sits on the window's ground, as on the boards.
        private func onGround<Content: View>(_ content: Content) -> some View {
            content.background(CarryOnColorStyle.coBgGround)
        }

        @Test("The Next action inspector renders as approved", arguments: Appearance.allCases)
        func next(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(
                    height: 620,
                    content: {
                        MacInspectorEyebrow(projectName: "Garage", projectColor: garage, listName: "Next actions")
                        MacInspectorTitle(text: "Call Sam about the van")
                        MacInspectorChips(
                            projectName: "Garage", projectColor: garage, dueText: "Due Friday", tags: ["calls"])
                        MacInspectorSectionLabel("Why")
                        MacInspectorBodyText(text: "He needs the van back before the weekend. Ask when he can pick it up.")
                        MacInspectorSectionLabel("Steps inside")
                        VStack(alignment: .leading, spacing: 8) {
                            MacInspectorStepLine(title: "Find his new number", done: true)
                            MacInspectorStepLine(title: "Agree a day", done: false)
                        }
                        MacInspectorSectionLabel("Comments")
                        MacInspectorBodyText(text: "None yet", quiet: true)
                    },
                    actionBar: {
                        MacInspectorActionBar(
                            actions: [.primary("Done") {}, .secondary("Not now") {}],
                            trailingNote: "Saved as you type")
                    }))
            assertMacSnapshot(view, named: "mac-inspector-next-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("The Inbox inspector renders as approved", arguments: Appearance.allCases)
        func inbox(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(
                    width: 380, height: 620,
                    content: {
                        MacInspectorEyebrow.inbox(position: 1, of: 4)
                        MacInspectorItemText(text: "the garage is a mess and Sam needs the van back")
                        MacInspectorTitle(text: "What is it?", serif: true, size: 24)
                            .padding(.top, 14)
                            .padding(.bottom, 12)
                        MacInspectorChoiceRow(
                            title: "A step I can take", detail: "Write the first step, it goes to Next actions",
                            glyph: .board(.nextActions)) {}
                        MacInspectorChoiceRow(
                            title: "Bigger than one step", detail: "Make it a project with a first step",
                            glyph: .folder) {}
                        MacInspectorChoiceRow(
                            title: "Waiting on someone", detail: "Say who, it goes to Waiting for",
                            glyph: .board(.waitingFor)) {}
                        MacInspectorChoiceRow(
                            title: "Someday", detail: "Not now, keep it for later",
                            glyph: .board(.somedayMaybe)) {}
                    },
                    actionBar: {
                        MacInspectorActionBar(
                            actions: [.secondary("Done already") {}, .quiet("Not needed") {}],
                            trailingNote: "Skip")
                    }))
            assertMacSnapshot(view, named: "mac-inspector-inbox-\(appearance.rawValue)", scheme: appearance.scheme, width: 380)
        }

        /// Unlike the component-only board fixture above, this hosts the shipped inspector.
        @Test("021_FR_009 M16 ordinary Inbox exposes only clarification choices and footer", arguments: Appearance.allCases)
        func ordinaryInbox(appearance: Appearance) async throws {
            CarryOnFonts.register()
            let folder = TemporaryFolder()
            let clock = TestClock()
            let task = TaskRecord(
                id: "inbox-m16", title: "the garage is a mess and Sam needs the van back",
                details: "Preserved context", state: .inbox, tagIDs: ["calls"],
                dueDate: CalendarDay(year: 2026, month: 11, day: 2), orderKey: 0,
                createdAt: clock.now, updatedAt: clock.now,
                subtasks: [SubtaskRecord(id: "inside-m16", title: "Preserved step", orderKey: 0)],
                comments: [CommentRecord(id: "comment-m16", body: "Preserved comment", createdAt: clock.now)])
            let workspace = Workspace(
                store: InMemoryDocumentStore(document: StoreDocument(generation: 1, base: GTDState(tasks: [task.id: task]))),
                sync: nil, now: clock.provider)
            await workspace.load()
            let model = BrainBuddyModel(workspace: workspace, localStateStore: MacLocalStateStore(directory: folder.url), now: clock.provider)
            let view = TaskInspector(
                task: task, model: model, title: .constant(task.title), details: .constant(task.details ?? ""),
                waitingFor: .constant(""), projectID: .constant(task.projectID), tagIDs: .constant(task.tagIDs),
                dueDate: .constant(task.dueDate), problem: nil, editorDirty: false,
                inboxPosition: (1, 4), nextInboxID: "inbox-next", onCommand: { _ in },
                onFocusChange: { _ in }, onExtrasDirtyChange: { _ in })
                .environment(\.carryOnPlatform, .mac).environment(\.colorScheme, appearance.scheme)
                .frame(width: 380, height: 620)
            let host = NSHostingView(rootView: view)
            host.appearance = NSAppearance(named: appearance == .dark ? .darkAqua : .aqua)
            let size = NSSize(width: 380, height: 620)
            let window = NSWindow(
                contentRect: NSRect(origin: NSPoint(x: -10_000, y: -10_000), size: size),
                styleMask: [.borderless], backing: .buffered, defer: false)
            window.isReleasedWhenClosed = false
            window.contentView = host
            defer { window.close() }
            host.frame = NSRect(origin: .zero, size: size)
            host.layoutSubtreeIfNeeded()
            // Let AppKit commit the newly inserted SwiftUI subtree before caching its display.
            await withCheckedContinuation { continuation in
                DispatchQueue.main.async { continuation.resume() }
            }
            host.layoutSubtreeIfNeeded()
            host.displayIfNeeded()
            let nativeViews = descendants(host)
            #expect(!nativeViews.compactMap { $0 as? NSTextView }.contains { $0.string == task.details }, "M16 omits the Note editor")
            #expect(!nativeViews.contains { $0 is NSPopUpButton || $0 is NSDatePicker }, "M16 omits generic property editors")
            let extraEditors = nativeViews.compactMap { $0 as? NSTextField }.filter {
                ["New step", "Write a comment"].contains($0.placeholderString ?? "")
            }
            #expect(extraEditors.count == 2 && extraEditors.allSatisfy { !$0.isEnabled && !$0.canBecomeKeyView })
            #expect(workspace.task(task.id) == task, "Rendering must preserve all stored metadata")
            let scale = window.backingScaleFactor
            #expect(scale == 1 || scale == 2)
            let bitmap = try #require(NSBitmapImageRep(
                bitmapDataPlanes: nil, pixelsWide: Int(size.width * 2), pixelsHigh: Int(size.height * 2),
                bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0))
            bitmap.size = size
            host.cacheDisplay(in: host.bounds, to: bitmap)
            let brightness = stride(from: 0, to: bitmap.pixelsHigh, by: 10).flatMap { y in
                stride(from: 0, to: bitmap.pixelsWide, by: 10).compactMap { x in
                    bitmap.colorAt(x: x, y: y)?.usingColorSpace(.deviceRGB)?.redComponent
                }
            }
            try #require((brightness.max() ?? 0) - (brightness.min() ?? 0) > 0.2, "Native inspector capture must contain rendered content")
            let image = try #require(bitmap.cgImage)
            assertMacSnapshot(
                Image(decorative: image, scale: 2).frame(width: 380, height: 620),
                named: "mac-inspector-inbox-ordinary-\(appearance.rawValue)-native\(Int(scale))x",
                scheme: appearance.scheme, width: 380)
        }

        private func descendants(_ view: NSView) -> [NSView] {
            [view] + view.subviews.flatMap(descendants)
        }

        @Test("The Waiting for inspector renders as approved", arguments: Appearance.allCases)
        func waiting(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(
                    height: 520,
                    content: {
                        MacInspectorEyebrow(projectName: "Garage", projectColor: garage, listName: "Waiting for")
                        MacInspectorTitle(text: "Quote for the van")
                        MacInspectorPerson(name: "Sam", since: "Asked 3 days ago")
                        MacInspectorSectionLabel("Note")
                        MacInspectorBodyText(text: "He said he would send it after the inspection.")
                        MacInspectorChips(projectName: "Garage", projectColor: garage, dueText: "Due Friday")
                    },
                    actionBar: {
                        MacInspectorActionBar(actions: [.primary("Got it") {}, .quiet("Follow up") {}])
                    }))
            assertMacSnapshot(view, named: "mac-inspector-waiting-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("The Someday inspector renders as approved", arguments: Appearance.allCases)
        func someday(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(
                    height: 520,
                    content: {
                        MacInspectorEyebrow(projectName: "Allotment", projectColor: allotment, listName: "Someday")
                        MacInspectorTitle(text: "Build a cold frame", serif: true)
                        MacInspectorMetaText(text: "Here since March")
                        MacInspectorSectionLabel("Note")
                        MacInspectorBodyText(text: "Old windows from the neighbours could work.")
                        MacInspectorBodyText(
                            text: "Ready to start? Write the first step and it moves to Next actions.",
                            quiet: true, topPadding: 18)
                    },
                    actionBar: {
                        MacInspectorActionBar(actions: [.primary("Start it") {}, .quiet("Not needed") {}])
                    }))
            assertMacSnapshot(view, named: "mac-inspector-someday-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("The Done inspector renders as approved", arguments: Appearance.allCases)
        func done(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(
                    height: 520,
                    content: {
                        MacInspectorEyebrow(projectName: "Garage", projectColor: garage, listName: "Done on Monday")
                        MacInspectorTitle(text: "Clear the shelves", struck: true)
                        MacInspectorSectionLabel("Note")
                        MacInspectorBodyText(text: "Two boxes to the tip, one to the charity shop.")
                        MacInspectorMetaText(text: "Finished steps are read-only.", topPadding: 16)
                    },
                    actionBar: {
                        MacInspectorActionBar(actions: [.secondary("Reopen…") {}])
                    }))
            assertMacSnapshot(view, named: "mac-inspector-done-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("The Not now popover renders as approved", arguments: Appearance.allCases)
        func notNow(appearance: Appearance) {
            let view = onGround(
                MacNotNowPopoverContent(onPickDay: {}, onWaiting: {}, onSomeday: {}, onChangeStep: {})
                    .padding(20))
            assertMacSnapshot(view, named: "mac-inspector-notnow-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }

        @Test("The empty inspector renders as approved", arguments: Appearance.allCases)
        func empty(appearance: Appearance) {
            let view = onGround(
                MacInspectorPanel(height: 520) {
                    MacInspectorEmpty(text: "Select something to sort it.\nOr press Sort them one by one.")
                })
            assertMacSnapshot(view, named: "mac-inspector-empty-\(appearance.rawValue)", scheme: appearance.scheme, width: 340)
        }
    }
#endif

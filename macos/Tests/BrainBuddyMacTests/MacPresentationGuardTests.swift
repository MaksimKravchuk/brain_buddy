import Foundation
import Testing

/// The source-level guard of contracts/mac-app-host.md §8 (review c2, G16): outside
/// `MacPresentationRouter` and an explicit allow-list of person-started surfaces, no source of the
/// Mac app presents a sheet, alert, dialog or popover, plays a sound, posts a notification,
/// activates the app or moves keyboard focus; and no allowed call's condition reads the sync state.
/// So no sync state can interrupt the person (FR-017, SC-004). The allow-list names every file and
/// region: a new file is not allowed by default.
@Suite("Presentation guard")
struct MacPresentationGuardTests {
    /// Calls that present, interrupt or move focus.
    static let forbidden = [
        ".sheet(", ".alert(", ".confirmationDialog(", ".popover(", "NSAlert", "NSSound", "UNUserNotificationCenter",
        "NSApp.activate", "makeFirstResponder",
    ]

    /// What an allowed call's condition must never read.
    static let syncState = ["SyncSnapshot", "syncSnapshot", "syncStatus", "SyncStatus", "syncLine", "SyncLineState"]

    /// Whole files allowed to present: the router and the person-started surfaces of §8.
    static let allowedFiles: [String: String] = [
        "BrainBuddyMacCore/MacPresentationRouter.swift": "the presentation router",
        "BrainBuddyMac/MacPresentationRouter+SwiftUI.swift": "the router's SwiftUI side, the only place X-02, X-03 and X-04 are attached",
        "BrainBuddyMac/SignInSheet.swift": "X-03, opened by the person",
        "BrainBuddyMac/SignOutConfirmation.swift": "X-04, opened by the person",
        "BrainBuddyMac/UpgradeNotice.swift": "X-05, a launch notice",
        "BrainBuddyMac/UnreadableWorkspaceView.swift": "X-09, a launch notice, and its person-started confirmation",
        "BrainBuddyMac/ProjectReviewView.swift": "the Project review's confirmation",
        "BrainBuddyMac/QuickCaptureView.swift": "the quick-capture panel",
        "BrainBuddyMac/QuickOpenView.swift": "Quick Open",
    ]

    /// Marked regions (`// presentation-region: <name>` … `// presentation-region-end`) allowed in
    /// files that are otherwise not.
    static let allowedRegions: [String: Set<String>] = [
        "BrainBuddyMac/BrainBuddyMacApp.swift": ["X-08 already open", "launch stopped"],
        "BrainBuddyMac/ContentView.swift": [
            "X-06 focus after archive, unarchive or a failed write",
            "rename sheet focus",
            "new task focus",
            "task editor, rename, voice, move, reopen and discard sheets",
            "collection, tag and outcome sheets",
            "review and clarify sheets",
            "project creator sheet",
            "clarify confirmations",
            "cancel task confirmations",
        ],
    ]

    struct Violation: CustomStringConvertible, Equatable {
        var file: String
        var line: Int
        var reason: String
        var description: String { "\(file):\(line): \(reason)" }
    }

    /// `macos/Sources`, from this file's place in the checkout (or `BRAINBUDDY_REPO_ROOT`).
    static var sourcesRoot: URL {
        if let root = ProcessInfo.processInfo.environment["BRAINBUDDY_REPO_ROOT"] {
            return URL(fileURLWithPath: root).appendingPathComponent("macos/Sources")
        }
        return URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Sources")
    }

    /// Every Swift source of the app and its core, keyed "BrainBuddyMac/ContentView.swift".
    static func sources() throws -> [(name: String, text: String)] {
        var found: [(String, String)] = []
        for target in ["BrainBuddyMac", "BrainBuddyMacCore"] {
            let folder = sourcesRoot.appendingPathComponent(target)
            let names = try FileManager.default.contentsOfDirectory(atPath: folder.path).filter { $0.hasSuffix(".swift") }.sorted()
            for name in names {
                found.append(("\(target)/\(name)", try String(contentsOf: folder.appendingPathComponent(name), encoding: .utf8)))
            }
        }
        return found
    }

    /// The text of a line without its `//` comment.
    static func code(_ line: Substring) -> String {
        guard let range = line.range(of: "//") else { return String(line) }
        return String(line[..<range.lowerBound])
    }

    /// The names `@FocusState` declares in `text`.
    static func focusStateNames(_ text: String) -> [String] {
        var names: [String] = []
        for line in text.split(separator: "\n", omittingEmptySubsequences: false) {
            let code = Self.code(line)
            guard let at = code.range(of: "@FocusState") else { continue }
            let rest = code[at.upperBound...]
            guard let varRange = rest.range(of: "var ") else { continue }
            let name = rest[varRange.upperBound...].prefix { $0.isLetter || $0.isNumber || $0 == "_" }
            if !name.isEmpty { names.append(String(name)) }
        }
        return names
    }

    /// Whether `code` assigns to one of `names` (`name = …`, `name.wrappedValue = …`).
    static func assignsFocus(_ code: String, _ names: [String]) -> String? {
        for name in names {
            var search = code[...]
            while let range = search.range(of: name) {
                let before = range.lowerBound == code.startIndex ? nil : code[code.index(before: range.lowerBound)]
                let isWord = before.map { !($0.isLetter || $0.isNumber || $0 == "_" || $0 == "$" || $0 == ".") } ?? true
                var after = code[range.upperBound...]
                if after.hasPrefix(".wrappedValue") { after = after.dropFirst(".wrappedValue".count) }
                let trimmed = after.drop { $0 == " " }
                if isWord, trimmed.hasPrefix("="), !trimmed.hasPrefix("==") { return name }
                search = code[range.upperBound...]
            }
        }
        return nil
    }

    /// The guard itself: every violation in one file.
    static func violations(file: String, text: String) -> [Violation] {
        var violations: [Violation] = []
        let fileAllowed = allowedFiles[file] != nil
        let regionsAllowed = allowedRegions[file] ?? []
        let focusNames = focusStateNames(text)
        var region: (name: String, line: Int)?
        var regionReadsSyncState = false

        for (index, line) in text.split(separator: "\n", omittingEmptySubsequences: false).enumerated() {
            let number = index + 1
            if let marker = line.range(of: "// presentation-region: ") {
                let name = line[marker.upperBound...].trimmingCharacters(in: .whitespaces)
                if region != nil { violations.append(Violation(file: file, line: number, reason: "nested presentation region")) }
                if !regionsAllowed.contains(name) {
                    violations.append(Violation(file: file, line: number, reason: "region “\(name)” is not on the allow-list"))
                }
                region = (name, number)
                regionReadsSyncState = false
                continue
            }
            if line.contains("// presentation-region-end") {
                if let open = region, regionReadsSyncState {
                    violations.append(Violation(file: file, line: open.line, reason: "region “\(open.name)” reads the sync state"))
                }
                region = nil
                continue
            }
            let code = Self.code(line)
            let readsSyncState = syncState.contains { code.contains($0) }
            if region != nil, readsSyncState { regionReadsSyncState = true }
            if fileAllowed, readsSyncState {
                violations.append(Violation(file: file, line: number, reason: "an allowed presenter reads the sync state"))
            }
            guard !fileAllowed, region == nil else { continue }
            for token in forbidden where code.contains(token) {
                violations.append(Violation(file: file, line: number, reason: "\(token) outside the router and the allow-list"))
            }
            if let name = assignsFocus(code, focusNames) {
                violations.append(Violation(file: file, line: number, reason: "@FocusState \(name) assigned outside the router and the allow-list"))
            }
        }
        if let open = region { violations.append(Violation(file: file, line: open.line, reason: "region “\(open.name)” is never closed")) }
        return violations
    }

    @Test("021-SC-004 021-FR-017 no Mac source presents or moves focus outside the router and the allow-list")
    func sourcesPassTheGuard() throws {
        let sources = try Self.sources()
        let names = Set(sources.map(\.name))
        #expect(names.contains("BrainBuddyMac/ContentView.swift"), "the guard reads the real sources")
        #expect(names.contains("BrainBuddyMacCore/MacPresentationRouter.swift"))
        for file in Self.allowedFiles.keys.sorted() {
            #expect(names.contains(file), "the allow-list names \(file), which exists")
        }
        let violations = sources.flatMap { Self.violations(file: $0.name, text: $0.text) }
        #expect(violations.isEmpty, "\(violations.map(\.description).joined(separator: "\n"))")

        // Every allowed region is actually marked, so the list stays honest.
        for (file, regions) in Self.allowedRegions {
            let text = try #require(sources.first { $0.name == file }?.text)
            for region in regions { #expect(text.contains("// presentation-region: \(region)"), "\(file) marks “\(region)”") }
        }
    }

    @Test("021-SC-004 021-FR-017 a seeded violation in a scratch copy fails the guard")
    func seededViolationsFail() throws {
        let sources = try Self.sources()
        let content = try #require(sources.first { $0.name == "BrainBuddyMac/ContentView.swift" })
        let line = try #require(sources.first { $0.name == "BrainBuddyMac/SyncStatusLine.swift" })
        let core = try #require(sources.first { $0.name == "BrainBuddyMacCore/MacSyncController.swift" })
        let seeds: [(file: String, text: String)] = [
            // A sync state that presents an alert.
            (line.name, line.text + "\nlet seeded = Text(\"x\").alert(\"Sync failed\", isPresented: .constant(true)) {}\n"),
            // A sheet outside every region.
            (content.name, content.text + "\nlet seeded = Text(\"x\").sheet(isPresented: .constant(true)) { Text(\"y\") }\n"),
            // A popover from the core.
            (core.name, core.text + "\nlet seeded = 0 // .popover(\n"
                + "func seeded() { _ = \"\".popover(isPresented: true) }\n"),
            // Focus moved by a sync state.
            (line.name, line.text + "\nstruct Seeded { @FocusState var stolen: Bool\n func f() { stolen = true } }\n"),
            // A region that is not on the list.
            (content.name, content.text + "\n// presentation-region: sync failure alert\nlet seeded = 1\n// presentation-region-end\n"),
            // An allowed region whose condition reads the sync state.
            (
                content.name,
                content.text.replacingOccurrences(
                    of: "// presentation-region: project creator sheet",
                    with: "// presentation-region: project creator sheet\n        let seeded = model.syncLine"
                )
            ),
            // An allowed file that reads the sync state.
            ("BrainBuddyMac/SignInSheet.swift", "let seeded = workspace.syncSnapshot\n"),
            // A new file is not allowed by default.
            ("BrainBuddyMac/SyncFailureNotifier.swift", "import AppKit\nfunc notify() { NSSound.beep() }\n"),
            ("BrainBuddyMac/Activation.swift", "func front() { NSApp.activate() }\n"),
            ("BrainBuddyMac/Responder.swift", "func f(w: NSWindow) { w.makeFirstResponder(nil) }\n"),
            ("BrainBuddyMac/Notifier.swift", "let center = UNUserNotificationCenter.current()\n"),
        ]
        for seed in seeds {
            #expect(!Self.violations(file: seed.file, text: seed.text).isEmpty, "the guard catches the seed in \(seed.file)")
        }
        // The unchanged copies pass, so each failure above is the seed's.
        #expect(Self.violations(file: line.name, text: line.text).isEmpty)
        #expect(Self.violations(file: content.name, text: content.text).isEmpty)
        #expect(Self.violations(file: core.name, text: core.text).isEmpty)
    }
}

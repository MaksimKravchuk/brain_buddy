import AppKit
import BrainBuddyMacCore
import SwiftUI

/// The launch order of contracts/mac-app-host.md §1, steps 1 – 5 (T110):
/// 1. `SingleInstanceGuard`, here, before any file is read;
/// 2. – 5. `LegacyStoreImporter` (with its X-05 notices), `LegacyCookieCleanup`,
///    `WorkspaceHost`, `workspace.load()` (X-09 on `loadError`), run by `MacLaunch` from the
///    window's first task while static placeholders show.
/// Sync triggers start in PR-09.
@main
struct BrainBuddyMacApp: App {
    @State private var launch: MacLaunch
    /// Held for the life of the process; the kernel releases it when the process ends.
    private let instance: SingleInstanceGuard

    init() {
        NSApplication.shared.setActivationPolicy(.regular)
        let configuration: MacHostConfiguration
        do {
            configuration = try MacHostConfiguration.fromEnvironment()
        } catch {
            Self.stop(error.message)
        }
        let claim: SingleInstanceGuard.Claim
        do {
            claim = try SingleInstanceGuard.claim(
                directory: configuration.directory,
                bringOtherForward: { Self.bringForward(processID: $0) },
                presentAlreadyOpen: { Self.presentAlreadyOpen() }
            )
        } catch {
            Self.stop("Brain Buddy couldn't open its folder on this Mac. Nothing was changed.")
        }
        guard case .owner(let owner) = claim else { exit(0) }
        instance = owner
        _launch = State(initialValue: MacLaunch(environment: .live(configuration)))
    }

    var body: some Scene {
        Window("Brain Buddy", id: "main") {
            ContentView(launch: launch)
                .frame(minWidth: 720, minHeight: 480)
        }
        .defaultSize(width: 960, height: 640)
        .commands { ProjectMenuCommands() }
    }

    /// X-08 "default": the running copy, named by the lock, comes to the front.
    private static func bringForward(processID: Int32?) -> Bool {
        guard let processID, processID != ProcessInfo.processInfo.processIdentifier,
            let running = NSRunningApplication(processIdentifier: processID), !running.isTerminated
        else { return false }
        return running.activate(from: .current, options: [])
    }

    /// X-08 "unreachable": one standard alert, "OK", then this copy quits.
    private static func presentAlreadyOpen() {
        let alert = NSAlert()
        alert.messageText = SingleInstanceGuard.AlreadyOpen.title
        alert.informativeText = SingleInstanceGuard.AlreadyOpen.message
        alert.addButton(withTitle: SingleInstanceGuard.AlreadyOpen.button)
        NSApp.activate()
        alert.runModal()
    }

    /// A launch that cannot go on says why and quits without touching any file.
    private static func stop(_ message: String) -> Never {
        let alert = NSAlert()
        alert.messageText = "Brain Buddy couldn't start"
        alert.informativeText = message
        alert.addButton(withTitle: "OK")
        NSApp.activate()
        alert.runModal()
        exit(1)
    }
}

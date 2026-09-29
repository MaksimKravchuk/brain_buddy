import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import WidgetKit

/// How App Intents and widgets reach the shared store. Compiled into the app
/// and the widget extension.
///
/// Every caller gets a workspace that has just read the App Group file, so a
/// command is applied to the latest document, and the store's lock keeps the
/// write safe while the app or another extension writes too. Only the app
/// talks to the server: workspaces made here never sync.
@MainActor
enum SharedWorkspace {
    /// The app's own workspace, when an intent runs inside the app process.
    private static weak var appWorkspace: Workspace?

    /// The app calls this once it has created its workspace. App Intents that
    /// run in the app process (Siri, Shortcuts or Spotlight while the app is
    /// alive) then write through it, so the UI updates at once and the
    /// process has a single writer for the file.
    static func adopt(_ workspace: Workspace) {
        appWorkspace = workspace
    }

    /// A loaded workspace over the App Group store with sync disabled. Make
    /// one per intent or widget timeline and let it go afterwards: widget
    /// extensions have a tight memory budget.
    static func make() async -> Workspace {
        if let appWorkspace {
            await appWorkspace.reloadIfChangedExternally()
            return appWorkspace
        }
        let workspace = Workspace.live(appGroupID: SharedConstants.appGroupID, enableSync: false)
        await workspace.load()
        return workspace
    }

    /// Stops an intent from writing when the store could not be read, for
    /// example before the first unlock after a restart. The store never
    /// overwrites a document it cannot decode; this gives the person a reason.
    static func requireLoaded(_ workspace: Workspace) throws(BrainBuddyIntentError) {
        guard workspace.isLoaded, workspace.loadError == nil else {
            throw BrainBuddyIntentError(message: "We couldn't read your lists. Open Brain Buddy to check them.")
        }
    }

    /// Call after every write. Waits until the change is on disk (an extension
    /// can be suspended as soon as it returns), tells a running app to reload,
    /// and refreshes every widget. Throws when the change could not be saved,
    /// so Siri and Shortcuts never report a capture that was lost.
    static func didWrite(_ workspace: Workspace) async throws(BrainBuddyIntentError) {
        await workspace.flush()
        if let problem = workspace.storageError {
            throw BrainBuddyIntentError(message: problem)
        }
        CFNotificationCenterPostNotification(
            CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(SharedConstants.storeChangedNotification as CFString),
            nil,
            nil,
            true
        )
        WidgetCenter.shared.reloadAllTimelines()
    }
}

/// Whether the device is locked, found out from files alone, so it works in
/// the widget extension too (where `UIApplication` is not available).
///
/// A small probe file in the App Group has complete data protection, which
/// can only be read — or created — while the device is unlocked. The store
/// itself stays readable after the first unlock (Lock Screen capture needs
/// that), so it can't answer this.
enum DeviceLock {
    static func isLocked() -> Bool {
        let url = probeURL
        if (try? Data(contentsOf: url)) != nil { return false }
        // It exists but can't be read: its key is gone until the next unlock.
        if FileManager.default.fileExists(atPath: url.path) { return true }
        // Not created yet. Creating a complete-protection file also needs
        // the device unlocked, so failing to create it means locked.
        do {
            try Data([1]).write(to: url, options: [.completeFileProtection])
            return false
        } catch {
            return true
        }
    }

    private static var probeURL: URL {
        let directory =
            FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: SharedConstants.appGroupID)
            ?? FileManager.default.temporaryDirectory
        return directory.appendingPathComponent(".device-lock-probe", isDirectory: false)
    }
}

/// An error whose message Siri, Shortcuts and widgets show as written. GTD
/// rule failures carry `GTDValidationError.message`, which is already
/// user-facing copy.
struct BrainBuddyIntentError: Error, LocalizedError, CustomLocalizedStringResourceConvertible {
    let message: String

    init(message: String) {
        self.message = message
    }

    init(_ error: GTDValidationError) {
        self.message = error.message
    }

    var errorDescription: String? { message }

    var localizedStringResource: LocalizedStringResource { "\(message)" }
}

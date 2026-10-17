/// Every string of design.md § Copy for the Mac Settings window (spec 028-FR-022): sentence-case
/// English, states in words. The views and models read these; none is typed into a screen.
package enum AccountSettingsCopy {
    package static let tabNames = ["Account", "Agents", "Sync", VoiceSettingsCopy.tabName]

    package static let nameLabel = "Name"
    package static let stepsLabel = "Steps taken"
    package static let emailLabel = "Email"
    package static let appleLabel = "Apple"
    package static let googleLabel = "Google"
    package static let passwordLabel = "Password"
    package static let dataLabel = "Your data"

    package static let nameEmpty = "Not set"
    package static let verified = "Verified"
    package static let unverified = "Unverified"
    package static let unavailable = "Unavailable"
    package static let connected = "Connected"
    package static let connectedUnavailable = "Connected · unavailable"
    package static let notConnected = "Not connected"
    package static let passwordSet = "Set · also used for Mac sign-in"
    package static let passwordNotSet = "Not set"

    package static let dataValue = "A ZIP of everything, without secrets"
    package static let exportAction = "Export…"
    package static let exporting = "Exporting…"
    package static let cancel = "Cancel"
    package static let saved = "Saved."
    package static let exportOffline = "Couldn't export. Check your connection."
    package static let exportNotWritable = "Couldn't save the file there."
    package static let exportFailed = "Couldn't export."
    package static let tryAgain = "Try again"

    package static let loading = "Loading…"
    package static let methodsFailed = "Sign-in methods couldn't be loaded."
    package static let loadFailed = "Your account details couldn't be loaded."
    package static let rateLimited = "Try again in a few minutes."
    package static let offline = "Your account details need a connection."
    package static let sessionEnded = "Your session ended."
    package static let sessionEndedDetail = "Unsent changes stay on this Mac."
    package static let signInAgain = "Sign in again…"
    package static let notSignedIn = "Not signed in"
    package static let signIn = "Sign in…"
    package static let signOut = "Sign out…"

    package static let agentsText = "Agents are managed on the web for now."
    package static let agentsAction = "Open agents on the web…"
    package static let agentsUnavailable = "The agents page can't be opened right now."

    package static func email(_ email: String, verified: Bool?) -> String {
        "\(email) · \(verified.map { $0 ? Self.verified : Self.unverified } ?? unavailable)"
    }

    package static func reference(_ id: String) -> String { "Reference: \(id)" }
}

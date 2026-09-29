import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import SwiftUI
import UIKit

/// Signs in to a Brain Buddy server. Local data is uploaded to the account
/// and merged; nothing on the device is lost if signing in fails.
struct SignInSheet: View {
    private enum Field: Hashable {
        case email, password, server
    }

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.dismiss) private var dismiss

    @State private var email: String
    @State private var password = ""
    @State private var serverAddress: String
    @State private var showsAdvanced: Bool
    @State private var isSigningIn = false
    @State private var failureMessage: String?
    @State private var failureReferenceID: String?
    @FocusState private var focusedField: Field?

    /// `email` and `serverURL` prefill the form, for example when a session expired.
    init(email: String = "", serverURL: URL? = nil) {
        let defaultAddress = SignInServerAddress.defaultString
        let address = serverURL?.absoluteString ?? defaultAddress
        _email = State(initialValue: email)
        _serverAddress = State(initialValue: address)
        _showsAdvanced = State(initialValue: address != defaultAddress)
    }

    var body: some View {
        NavigationStack {
            Form {
                introSection
                if let failureMessage {
                    failureSection(failureMessage)
                }
                credentialsSection
                advancedSection
            }
            .navigationTitle("Sign in")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .disabled(isSigningIn)
                }
            }
            .safeAreaInset(edge: .bottom) { signInButton }
            .onAppear { focusedField = email.isEmpty ? Field.email : Field.password }
        }
        .interactiveDismissDisabled(isSigningIn)
    }

    // MARK: Sections

    private var introSection: some View {
        Section {
            VStack(alignment: .leading, spacing: 8) {
                Text("Sync with Brain Buddy on the web")
                    .font(.headline)
                Text(introExplanation)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .padding(.vertical, 4)
            .accessibilityElement(children: .combine)
        }
    }

    private var introExplanation: String {
        if workspace.account != nil {
            return "Your session ended. Sign in again to keep syncing — your changes are kept on this \(ThisDevice.name) until then."
        }
        return "What you've added on this \(ThisDevice.name) is uploaded to your account and merged with what's already there."
    }

    private func failureSection(_ message: String) -> some View {
        Section {
            VStack(alignment: .leading, spacing: 6) {
                EditorValidationMessage(text: message)
                if let failureReferenceID {
                    Text("Reference ID: \(failureReferenceID)")
                        .font(.footnote.monospaced())
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                }
            }
        }
    }

    private var credentialsSection: some View {
        Section {
            TextField("Email", text: $email)
                .textContentType(.username)
                .keyboardType(.emailAddress)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .submitLabel(.next)
                .focused($focusedField, equals: .email)
                .onSubmit { focusedField = .password }
            SecureField("Password", text: $password)
                .textContentType(.password)
                .submitLabel(.go)
                .focused($focusedField, equals: .password)
                .onSubmit { signIn() }
        }
        .disabled(isSigningIn)
    }

    private var advancedSection: some View {
        Section {
            DisclosureGroup("Advanced", isExpanded: $showsAdvanced) {
                TextField("Server address", text: $serverAddress)
                    .keyboardType(.URL)
                    .textContentType(.URL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .submitLabel(.go)
                    .focused($focusedField, equals: .server)
                    .onSubmit { signIn() }
                Text("Use an https address. http works only for localhost, during development.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                if serverAddress != SignInServerAddress.defaultString {
                    Button("Use the default server") {
                        serverAddress = SignInServerAddress.defaultString
                    }
                }
            }
        }
        .disabled(isSigningIn)
    }

    private var signInButton: some View {
        Button {
            signIn()
        } label: {
            HStack(spacing: 8) {
                if isSigningIn {
                    ProgressView()
                        .tint(.white)
                }
                Text(signInTitle)
            }
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.glassProminent)
        .controlSize(.large)
        .disabled(!canSubmit || isSigningIn)
        .padding(.horizontal, 20)
        .padding(.bottom, 12)
    }

    private var signInTitle: String { isSigningIn ? "Signing in…" : "Sign in" }

    private var canSubmit: Bool {
        !email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !password.isEmpty
            && !serverAddress.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    // MARK: Actions

    private func signIn() {
        guard canSubmit, !isSigningIn else { return }
        guard let url = SignInServerAddress.url(from: serverAddress) else {
            showsAdvanced = true
            focusedField = .server
            showFailure("\(WorkspaceError.invalidServerURL.message) http works only for localhost.", referenceID: nil)
            return
        }
        let address = email.trimmingCharacters(in: .whitespacesAndNewlines)
        let secret = password
        failureMessage = nil
        failureReferenceID = nil
        focusedField = nil
        isSigningIn = true
        Task {
            do {
                try await workspace.signIn(serverURL: url, email: address, password: secret)
                isSigningIn = false
                password = ""
                toasts.show("Signed in as \(address)", actionTitle: nil, action: nil)
                dismiss()
            } catch let error as WorkspaceError {
                isSigningIn = false
                handle(error)
            } catch {
                isSigningIn = false
                showFailure("Couldn't sign in. Check your connection and try again.", referenceID: nil)
            }
        }
    }

    private func handle(_ error: WorkspaceError) {
        switch error {
        case .signInFailed(let message, let referenceID):
            showFailure(message, referenceID: referenceID)
        case .invalidServerURL:
            showsAdvanced = true
            showFailure(error.message, referenceID: nil)
        default:
            showFailure(error.message, referenceID: nil)
        }
    }

    private func showFailure(_ message: String, referenceID: String?) {
        failureMessage = message
        failureReferenceID = referenceID
        UIAccessibility.post(notification: .announcement, argument: message)
    }
}

// MARK: - Pure helpers (no SwiftUI)

/// Server address rules: https anywhere, http only for localhost (development).
enum SignInServerAddress {
    static var defaultString: String { string(AppConstants.defaultServerURL) }

    // `AppConstants.defaultServerURL` reads the same whether it is a URL or a String.
    private static func string(_ url: URL) -> String { url.absoluteString }
    private static func string(_ text: String) -> String { text }

    /// A usable API base URL, or nil. A missing scheme means https.
    static func url(from text: String) -> URL? {
        var candidate = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !candidate.isEmpty else { return nil }
        if !candidate.contains("://") { candidate = "https://" + candidate }
        guard let components = URLComponents(string: candidate),
            let scheme = components.scheme?.lowercased(),
            let host = components.host?.lowercased(), !host.isEmpty,
            let url = components.url
        else { return nil }
        switch scheme {
        case "https": return url
        case "http": return isLocalHost(host) ? url : nil
        default: return nil
        }
    }

    static func isLocalHost(_ host: String) -> Bool {
        ["localhost", "127.0.0.1", "::1", "[::1]"].contains(host) || host.hasSuffix(".localhost")
    }
}

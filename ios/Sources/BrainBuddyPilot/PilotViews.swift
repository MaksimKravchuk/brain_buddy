#if canImport(SwiftUI)
import SwiftUI

@MainActor
public final class AuthenticationModel: ObservableObject {
    @Published public private(set) var user: SessionUser?
    @Published public private(set) var isWorking = false
    @Published public private(set) var errorMessage: String?
    private let client: BrainBuddyAPIClient

    public init(client: BrainBuddyAPIClient) { self.client = client }

    public func restore() async { await perform { try await self.client.currentUser() } }
    public func signIn(email: String, password: String) async {
        await perform { try await self.client.signIn(email: email, password: password) }
    }
    public func signUp(email: String, password: String, inviteCode: String) async {
        await perform { try await self.client.signUp(email: email, password: password, inviteCode: inviteCode) }
    }
    public func signOut() async {
        isWorking = true
        defer { isWorking = false }
        do { try await client.signOut(); user = nil; errorMessage = nil }
        catch { errorMessage = Self.message(for: error) }
    }

    private func perform(_ operation: () async throws -> SessionUser) async {
        isWorking = true
        defer { isWorking = false }
        do { user = try await operation(); errorMessage = nil }
        catch { user = nil; errorMessage = Self.message(for: error) }
    }

    private static func message(for error: Error) -> String {
        if case let BrainBuddyAPIClient.APIError.http(_, message) = error { return message }
        return "BrainBuddy is unavailable. Check your connection and try again."
    }
}

public struct AuthenticationView: View {
    @StateObject private var model: AuthenticationModel
    @State private var email = ""
    @State private var password = ""
    @State private var inviteCode = ""
    @State private var isSigningUp = false

    public init(model: AuthenticationModel) { _model = StateObject(wrappedValue: model) }

    public var body: some View {
        Form {
            if let user = model.user {
                Section("Signed in") {
                    Text(user.email)
                    Button("Sign out") { Task { await model.signOut() } }
                }
            } else {
                Section(isSigningUp ? "Use your invite" : "Sign in") {
                    TextField("Email", text: $email).textContentType(.emailAddress).textInputAutocapitalization(.never)
                    SecureField("Password", text: $password).textContentType(isSigningUp ? .newPassword : .password)
                    if isSigningUp { TextField("Invite code", text: $inviteCode).textContentType(.oneTimeCode) }
                    Button(isSigningUp ? "Create account" : "Sign in") {
                        Task {
                            if isSigningUp { await model.signUp(email: email, password: password, inviteCode: inviteCode) }
                            else { await model.signIn(email: email, password: password) }
                        }
                    }.disabled(model.isWorking)
                    Button(isSigningUp ? "I already have an account" : "I have an invite") { isSigningUp.toggle() }
                }
                if let error = model.errorMessage { Section { Text(error).foregroundStyle(.red) } }
                Section { NavigationLink("Password recovery or account deletion", destination: AccountHelpView()) }
            }
        }
        .navigationTitle("BrainBuddy")
        .task { if model.user == nil { await model.restore() } }
    }
}

public struct ResearchResultView: View {
    private let research: LocalServiceResearch

    public init(research: LocalServiceResearch) { self.research = research }

    public var body: some View {
        List {
            Section {
                Text(PilotBoundary.notice).font(.callout).foregroundStyle(.secondary)
            } header: { Text("Your decision stays with you") }

            ForEach(research.options) { option in
                Section(option.name) {
                    Text(option.summary)
                    LabeledContent("Uncertainty", value: option.uncertainty)
                    ForEach(Array(option.sources.enumerated()), id: \.offset) { _, source in
                        Link("Source: \(source.title)", destination: source.url)
                    }
                }
            }
        }
        .navigationTitle("Three options")
    }
}

public struct AccountHelpView: View {
    public init() {}

    public var body: some View {
        List {
            Section("Password recovery") {
                Text("Password reset is not available in this pilot. Contact the pilot coordinator to revoke the old account and issue a new invite. Do not send your password.")
            }
            Section("Delete account") {
                Text("In-app deletion is not supported by the current BrainBuddy API. Ask the pilot coordinator for deletion; they must confirm completion before you consider the account deleted.")
            }
        }
        .navigationTitle("Account help")
    }
}
#endif

import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// How you sign in (spec 033, board 26): the email and the ways to sign in, each with the one
/// thing you can do to it. Every change first asks "Confirm it's you", one sheet at a time.
struct SignInMethodsScreen: View {
    @Environment(AccountModels.self) private var accounts
    @Environment(Workspace.self) private var workspace

    var body: some View {
        if let account = workspace.account {
            SignInMethodsContent(model: accounts.model(for: account))
        } else {
            EmptyView()
        }
    }
}

private struct SignInMethodsContent: View {
    /// What a confirmation is for; the step that follows it.
    enum Pending {
        case verifyEmail
        case link(NativeAuthProvider)
        case remove(NativeAuthProvider)

        var action: AccountAction {
            switch self {
            case .verifyEmail: .verifyEmail
            case .link(let provider): .link(provider)
            case .remove(let provider): .unlink(provider)
            }
        }
    }

    /// The one sheet on screen; the next is set only after the last has closed.
    enum Step: Identifiable {
        case changeEmail
        case confirm(Pending)
        case verifyCode(AccountEmailCode)
        case password

        var id: String {
            switch self {
            case .changeEmail: "changeEmail"
            case .confirm: "confirm"
            case .verifyCode: "verifyCode"
            case .password: "password"
            }
        }
    }

    let model: AccountSecurityModel

    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.displayScale) private var displayScale
    @State private var step: Step?
    @State private var removing: NativeAuthProvider?
    @State private var coordinator = ModernAuthCoordinator()
    @State private var isBusy = false

    private var isOffline: Bool {
        if case .offline = workspace.syncStatus { return true }
        return false
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.md)) {
                header
                content
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, CGFloat(CarryOnSpace.md))
            .padding(.bottom, CGFloat(CarryOnSpace.lg))
        }
        .background(.coBgGround)
        // The screen's own big title is in the content, so the bar shows only "< Account".
        .navigationTitle("")
        .navigationBarTitleDisplayMode(.inline)
        .task { if model.methods == nil { await model.load() } }
        .onDisappear { coordinator.cancel(); coordinator.stopMonitoring() }
        .sheet(item: $step) { step in sheet(for: step) }
        .confirmationDialog(
            "Remove \(removing.map(Self.name) ?? "")?",
            isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }),
            titleVisibility: .visible,
            presenting: removing
        ) { provider in
            Button("Remove", role: .destructive) { step = .confirm(.remove(provider)) }
            Button("Keep method", role: .cancel) {}
        } message: { provider in
            Text("You won't be able to sign in with \(Self.name(provider)). Sessions started with it end, including this one if you used \(Self.name(provider)) here.")
        }
    }

    // MARK: Layout

    private var header: some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xs)) {
            Text("Sign in")
                .carryOnFont(CarryOnTypeScale.display)
                .foregroundStyle(.coTextPrimary)
                .accessibilityAddTraits(.isHeader)
            Text("How you get into Carry On on any device")
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
        }
    }

    @ViewBuilder private var content: some View {
        if let emailRow = model.emailRow {
            group("Email", rows: [emailRow])
            group("Ways to sign in", rows: model.signInRows)
            footnote("Forgot it? Sign out and choose Use a password, then Forgot password. A code goes to your email.")
            footnote("Every change here asks you to confirm it is you first. The last way to sign in cannot be removed.")
            if isOffline {
                footnote("Connect to the internet to change how you sign in.")
            }
        } else if case .failed(let failure) = model.phase {
            AccountFailureMessage(failure: failure)
            Button("Try again") { Task { await model.load() } }
                .buttonStyle(.carryOnSecondary)
        } else {
            ProgressView().frame(maxWidth: .infinity)
        }
    }

    private func group(_ title: String, rows: [AccountMethodRow]) -> some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xs)) {
            SettingsSectionHeader(title)
                .padding(.horizontal, CGFloat(CarryOnSpace.md))
                .padding(.top, CGFloat(CarryOnSpace.xs))
            VStack(spacing: 0) {
                ForEach(Array(rows.enumerated()), id: \.element.id) { index, row in
                    if index > 0 {
                        Rectangle()
                            .fill(.coBgGround)
                            .frame(height: 1 / displayScale)
                            .padding(.leading, CGFloat(CarryOnSpace.md))
                    }
                    methodRow(row)
                }
            }
            .background(
                .coSurfaceCard, in: RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous))
        }
    }

    private func methodRow(_ row: AccountMethodRow) -> some View {
        HStack(spacing: CGFloat(CarryOnSpace.sm)) {
            VStack(alignment: .leading, spacing: 0) {
                Text(row.title)
                    .carryOnFont(CarryOnTypeScale.body)
                    .foregroundStyle(.coTextPrimary)
                Text(row.detail)
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
            }
            .multilineTextAlignment(.leading)
            Spacer(minLength: 0)
            if let title = row.actionTitle {
                Button {
                    start(row)
                } label: {
                    CarryOnChip(title, tone: row.action == .remove ? .overdue : .plain)
                        .frame(minHeight: BBMetrics.hitTarget)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(isOffline || isBusy)
                .accessibilityLabel("\(title) \(row.title)")
            }
        }
        .padding(.vertical, CGFloat(CarryOnSpace.sm))
        .padding(.horizontal, CGFloat(CarryOnSpace.md))
        .frame(minHeight: BBMetrics.hitTarget)
    }

    private func footnote(_ text: String) -> some View {
        Text(text)
            .carryOnFont(CarryOnTypeScale.meta)
            .foregroundStyle(.coTextSecondary)
            .padding(.horizontal, CGFloat(CarryOnSpace.md))
    }

    // MARK: Sheets and steps

    @ViewBuilder private func sheet(for step: Step) -> some View {
        switch step {
        case .changeEmail:
            ChangeEmailSheet(model: model, mode: .change) { toasts.show($0, actionTitle: nil, action: nil) }
        case .verifyCode(let code):
            ChangeEmailSheet(model: model, mode: .verify(code)) { toasts.show($0, actionTitle: nil, action: nil) }
        case .password:
            PasswordSheet(model: model) {
                toasts.show("Password saved. Other devices have been signed out.", actionTitle: nil, action: nil)
            }
        case .confirm(let pending):
            AccountConfirmSheet(model: model, action: pending.action) { proof in confirmed(pending, proof: proof) }
        }
    }

    private func start(_ row: AccountMethodRow) {
        guard let action = row.action else { return }
        switch (row.kind, action) {
        case (.email, .verify): step = .confirm(.verifyEmail)
        case (.email, _): step = .changeEmail
        case (.password, _): step = .password
        case (.apple, .remove): removing = .apple
        case (.google, .remove): removing = .google
        case (.apple, _): step = .confirm(.link(.apple))
        case (.google, _): step = .confirm(.link(.google))
        }
    }

    private func confirmed(_ pending: Pending, proof: RecentProof) {
        switch pending {
        case .verifyEmail:
            run { step = .verifyCode(try await model.startEmailVerification(proof: proof)) }
        case .link(let provider):
            run { try await link(provider, proof: proof) }
        case .remove(let provider):
            run { try await remove(provider, proof: proof) }
        }
    }

    private func link(_ provider: NativeAuthProvider, proof: RecentProof) async throws {
        let attempt = try await model.startProvider(
            provider, linking: true, action: .link(provider), proof: proof)
        let credential = try await coordinator.authenticate(
            provider: attempt.provider, start: attempt.start, verifier: attempt.verifier)
        try await model.finishLink(credential)
        toasts.show("\(Self.name(provider)) connected.", actionTitle: nil, action: nil)
    }

    private func remove(_ provider: NativeAuthProvider, proof: RecentProof) async throws {
        let name = Self.name(provider)
        let signedOut = try await model.remove(provider, proof: proof)
        if signedOut {
            toasts.show("\(name) was removed. Sign in again with a way you still have.", actionTitle: nil, action: nil)
            await workspace.syncNow()
        } else {
            toasts.show("\(name) was removed.", actionTitle: nil, action: nil)
        }
    }

    /// Runs one step after a confirmation; a failure becomes a toast, a cancelled sheet is silent.
    private func run(_ body: @escaping @MainActor () async throws -> Void) {
        guard !isBusy else { return }
        isBusy = true
        Task { @MainActor in
            defer { isBusy = false }
            do {
                try await body()
            } catch {
                guard let failure = AccountActionFailure.describing(error) else { return }
                toasts.showError(failure.message, referenceID: failure.referenceID)
                // The request may have changed the account: look again before anything else.
                if failure.isUncertain { await model.load() }
            }
        }
    }

    private static func name(_ provider: NativeAuthProvider) -> String {
        provider == .apple ? "Apple" : "Google"
    }
}

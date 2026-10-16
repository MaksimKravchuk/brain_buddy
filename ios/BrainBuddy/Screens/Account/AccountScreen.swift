import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI
import UIKit

/// The Account screen (spec 033, board 25): who you are, how you sign in and your data. It renders
/// `AccountSecurityModel`; every rule about proofs and what a change may do lives there.
struct AccountScreen: View {
    @Environment(AccountModels.self) private var accounts
    @Environment(Workspace.self) private var workspace
    @Environment(ToastCenter.self) private var toasts
    @Environment(\.dismiss) private var dismiss

    @State private var isEditingName = false
    @State private var isShowingDelete = false
    /// Set by "Delete" so the confirm step is presented once the delete sheet has gone.
    @State private var deleteRequested = false
    @State private var confirming: PendingConfirmation?
    @State private var exportedFile: ExportedFile?
    @State private var isExporting = false
    @State private var isDeleting = false

    var body: some View {
        Group {
            if let account = workspace.account {
                content(model: accounts.model(for: account))
            } else {
                Color.clear
            }
        }
        .onChange(of: workspace.account == nil) { _, signedOut in
            if signedOut { dismiss() }
        }
    }

    private func content(model: AccountSecurityModel) -> some View {
        List {
            headerSection(model)
            switch model.phase {
            case .loading:
                Section { ProgressView().frame(maxWidth: .infinity) }.listRowBackground(cardBackground)
            case .failed(let failure):
                failedSection(failure, model: model)
            case .ready:
                profileSection(model)
                // Agents (spec 034) are added here.
                signInSection(model)
                dataSection(model)
            }
            AccountSignOutSection()
        }
        .listStyle(.insetGrouped)
        .carryOnFont(CarryOnTypeScale.body)
        .scrollContentBackground(.hidden)
        .background(.coBgGround)
        .navigationTitle("Account")
        .toolbarTitleDisplayMode(.inline)
        .task { await model.load() }
        .sheet(isPresented: $isEditingName) { AccountNameSheet(model: model) }
        .sheet(isPresented: $isShowingDelete, onDismiss: afterDeleteSheet) {
            DeleteAccountSheet { deleteRequested = true }
        }
        .sheet(item: $confirming) { pending in
            AccountConfirmSheet(model: model, action: pending.action) { proof in
                run(pending, proof: proof, model: model)
            }
        }
        .sheet(item: $exportedFile, onDismiss: removeExportedFile) { file in
            ActivityView(url: file.url).presentationDetents([.medium, .large])
        }
    }

    // MARK: Sections

    private func headerSection(_ model: AccountSecurityModel) -> some View {
        Section {
            AccountHeader(title: model.title, subtitle: model.subtitle)
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
        }
    }

    private func failedSection(_ failure: AccountActionFailure, model: AccountSecurityModel) -> some View {
        Section {
            Text(failure.message).foregroundStyle(.coTextPrimary)
            Button("Retry") { Task { await model.load() } }
        }
        .listRowBackground(cardBackground)
    }

    private func profileSection(_ model: AccountSecurityModel) -> some View {
        Section {
            Button { isEditingName = true } label: {
                valueRow(
                    "Name", detail: "Leave it empty to go by your email", value: model.displayName,
                    showsChevron: true)
            }
            .disabled(isOffline)
        } header: {
            SettingsSectionHeader("Profile")
        } footer: {
            offlineFooter
        }
        .listRowBackground(cardBackground)
    }

    private func signInSection(_ model: AccountSecurityModel) -> some View {
        Section {
            ForEach(model.summaryRows) { row in
                NavigationLink(value: AppRoute.signInMethods) {
                    valueRow(row.title, detail: nil, value: row.summary, showsChevron: false)
                }
            }
        } header: {
            SettingsSectionHeader("Sign in")
        }
        .listRowBackground(cardBackground)
    }

    private func dataSection(_ model: AccountSecurityModel) -> some View {
        Section {
            Button { confirming = PendingConfirmation(action: .export) } label: {
                HStack {
                    valueRow("Export a copy", detail: nil, value: "ZIP", showsChevron: true)
                    if isExporting { ProgressView() }
                }
            }
            .disabled(isOffline || isExporting || isDeleting)
            Button { isShowingDelete = true } label: {
                Text("Delete account…")
                    .foregroundStyle(.coStatusDanger)
                    .frame(maxWidth: .infinity, minHeight: 44, alignment: .leading)
            }
            .disabled(isOffline || isExporting || isDeleting)
        } header: {
            SettingsSectionHeader("Your data")
        }
        .listRowBackground(cardBackground)
    }

    /// One row: title (and a line under it) on the left, a value and optionally a chevron on the right.
    private func valueRow(_ title: String, detail: String?, value: String, showsChevron: Bool) -> some View {
        HStack(spacing: CGFloat(CarryOnSpace.xs)) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title).foregroundStyle(.coTextPrimary)
                if let detail {
                    Text(detail).carryOnFont(CarryOnTypeScale.meta).foregroundStyle(.coTextSecondary)
                }
            }
            Spacer(minLength: CGFloat(CarryOnSpace.xs))
            Text(value).carryOnFont(CarryOnTypeScale.meta).foregroundStyle(.coTextSecondary)
            if showsChevron {
                Image(systemName: "chevron.right")
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                    .accessibilityHidden(true)
            }
        }
        .frame(minHeight: 44)
        .contentShape(Rectangle())
    }

    @ViewBuilder private var offlineFooter: some View {
        if isOffline {
            Text("Connect to the internet to change your account.")
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
        }
    }

    private var cardBackground: some View {
        Rectangle().fill(.coSurfaceCard)
    }

    private var isOffline: Bool {
        if case .offline = workspace.syncStatus { return true }
        return false
    }

    // MARK: Actions

    /// The delete sheet has gone; only now is the confirm step presented.
    private func afterDeleteSheet() {
        guard deleteRequested else { return }
        deleteRequested = false
        confirming = PendingConfirmation(action: .delete)
    }

    private func run(_ pending: PendingConfirmation, proof: RecentProof, model: AccountSecurityModel) {
        switch pending.action {
        case .delete: delete(proof: proof, model: model)
        default: export(proof: proof, model: model)
        }
    }

    private func export(proof: RecentProof, model: AccountSecurityModel) {
        guard !isExporting else { return }
        isExporting = true
        Task { @MainActor in
            defer { isExporting = false }
            do throws(AccountActionFailure) {
                let archive = try await model.export(proof: proof)
                let url = FileManager.default.temporaryDirectory.appendingPathComponent(archive.suggestedFileName)
                do {
                    try archive.data.write(to: url, options: [.atomic, .completeFileProtection])
                } catch {
                    throw AccountActionFailure(message: "Couldn't save the export. Try again.")
                }
                exportedFile = ExportedFile(url: url)
            } catch {
                report(error, model: model)
            }
        }
    }

    private func delete(proof: RecentProof, model: AccountSecurityModel) {
        guard !isDeleting else { return }
        isDeleting = true
        Task { @MainActor in
            defer { isDeleting = false }
            do throws(AccountActionFailure) {
                let purgeAt = try await model.delete(proof: proof)
                let date = purgeAt.formatted(date: .abbreviated, time: .omitted)
                toasts.show(
                    "Account deletion requested. It's removed for good on \(date). Signing in before then cancels it.",
                    actionTitle: nil, action: nil)
                // Every session has ended; syncing lets the app notice and ask to sign in again.
                await workspace.syncNow()
                dismiss()
            } catch {
                report(error, model: model)
            }
        }
    }

    private func report(_ failure: AccountActionFailure, model: AccountSecurityModel) {
        toasts.showError(failure.message, referenceID: failure.referenceID)
        // The request may have changed the account; read it again before anything else.
        if failure.isUncertain { Task { await model.load() } }
    }

    private func removeExportedFile() {
        guard let url = exportedFile?.url else { return }
        try? FileManager.default.removeItem(at: url)
        exportedFile = nil
    }
}

/// Which confirm-it's-you step is on screen.
private struct PendingConfirmation: Identifiable {
    let action: AccountAction
    var id: String { action.rawValue }
}

/// An export written to a temporary file for the share sheet.
private struct ExportedFile: Identifiable {
    let url: URL
    var id: URL { url }
}

/// Board 25's top: an initials circle, the name in the serif face and the line under it.
private struct AccountHeader: View {
    let title: String
    let subtitle: String

    @ScaledMetric(relativeTo: .title) private var avatar: CGFloat = 56

    var body: some View {
        HStack(spacing: CGFloat(CarryOnSpace.sm)) {
            Text(title.first.map { String($0).uppercased() } ?? "?")
                .carryOnFont(CarryOnTypeScale.title)
                .foregroundStyle(.coTextPrimary)
                .frame(width: avatar, height: avatar)
                .background(.coControlQuiet, in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .carryOnFont(CarryOnTypeScale.display)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                Text(subtitle)
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, CGFloat(CarryOnSpace.md))
        .accessibilityElement(children: .combine)
    }
}

/// The system share sheet, so the person saves the export where they want.
private struct ActivityView: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}

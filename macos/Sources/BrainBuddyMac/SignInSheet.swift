import BrainBuddyMacCore
import SwiftUI

/// Design X-03, the sign-in sheet (contracts/mac-app-host.md §7), over `SignInFlow`: the
/// first-sign-in box when this Mac holds account-less tasks; the errors in this Mac's words with the
/// reference id to quote; "Sign in again" with the email and server locked; the fields read-only
/// while "Signing in…" runs, with Cancel and Esc still enabled until the account is linked (then
/// its first sync finishes and the sheet closes signed in); the "account deletion cancelled"
/// note before it closes. It is the only place macOS may ask for access to the saved sign-in: the
/// kit writes the token interactively only for this person-started sign-in.
struct SignInSheet: View {
    @Bindable var flow: SignInFlow
    let router: MacPresentationRouter
    let onClose: () -> Void
    @FocusState private var focus: Field?

    enum Field: Hashable {
        case email, password, note
    }

    var body: some View {
        Group {
            if flow.phase == .deletionCancelledNote {
                deletionCancelledNote
            } else {
                form
            }
        }
        .padding(24)
        .frame(width: 460)
        .interactiveDismissDisabled()
        .onChange(of: flow.phase) { _, phase in
            if phase == .finished { onClose() }
        }
        .onChange(of: flow.focusSerial, initial: true) { _, _ in
            focus = Self.field(for: flow.preferredFocus)
        }
        .routedFocus($focus, router: router) { Self.field(for: $0) }
        .onChange(of: flow.message) { _, message in
            // Sign-in errors are announced (alert role, design "Announcements").
            if let message { AccessibilityNotification.Announcement(message.title).post() }
        }
    }

    private static func field(for target: FocusTarget) -> Field? {
        switch target {
        case .signInEmail: .email
        case .signInPassword: .password
        case .signInNote: .note
        default: nil
        }
    }

    private var form: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(flow.title)
                .font(.title2.bold())
                .accessibilityAddTraits(.isHeader)
            Text(flow.subtitle)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            if flow.showsLocalTasksNotice {
                Label(SignInCopy.localTasks, systemImage: "info.circle")
                    .font(.callout)
                    .padding(12)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.accentColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
                    .fixedSize(horizontal: false, vertical: true)
            }
            if let message = flow.message {
                messageView(message)
            }
            TextField("Email", text: $flow.email)
                .textFieldStyle(.roundedBorder)
                .disabled(flow.accountFieldsReadOnly)
                .focused($focus, equals: .email)
            SecureField("Password", text: $flow.password)
                .textFieldStyle(.roundedBorder)
                .disabled(flow.credentialsReadOnly)
                .focused($focus, equals: .password)
                .onSubmit { flow.submit() }
            DisclosureGroup(SignInCopy.advanced, isExpanded: $flow.showsAdvanced) {
                VStack(alignment: .leading, spacing: 8) {
                    TextField(SignInCopy.serverAddress, text: $flow.serverAddress)
                        .textFieldStyle(.roundedBorder)
                        .disabled(flow.accountFieldsReadOnly)
                    Button(SignInCopy.useDefaultServer) { flow.useDefaultServer() }
                        .disabled(flow.accountFieldsReadOnly)
                }
                .padding(.top, 6)
            }
            if let footer = flow.footer {
                Text(footer)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Spacer()
                // Enabled while signing in too: it stops the request and keeps what was typed. Not
                // once the account is linked: that sign-in finishes, so Cancel would be untrue.
                Button(SignInCopy.cancel) {
                    if flow.cancel() { onClose() }
                }
                .keyboardShortcut(.cancelAction)
                .disabled(!flow.canCancel)
                Button {
                    flow.submit()
                } label: {
                    HStack(spacing: 6) {
                        if flow.isSigningIn {
                            ProgressView().controlSize(.small)
                        }
                        Text(flow.submitTitle)
                    }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(!flow.canSubmit)
            }
        }
    }

    /// An error above the fields, in amber words with its reference id (selectable, to quote).
    private func messageView(_ message: SignInFlow.Message) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Label(message.title, systemImage: "exclamationmark.triangle")
                .foregroundStyle(.orange)
            if let detail = message.detail {
                Text(detail).foregroundStyle(.secondary)
            }
            if let reference = message.referenceID {
                Text("Reference ID \(reference)")
                    .font(.caption.monospaced())
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityElement(children: .combine)
    }

    /// "signed in, account deletion cancelled": the same sheet, its form replaced by the note; "OK",
    /// Return or Esc closes it. Sync has already started behind it.
    private var deletionCancelledNote: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 8) {
                Label(SignInCopy.deletionCancelledTitle, systemImage: "info.circle")
                    .font(.headline)
                Text(SignInCopy.deletionCancelledDetail)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .padding(12)
            .background(Color.accentColor.opacity(0.12), in: RoundedRectangle(cornerRadius: 8))
            .accessibilityElement(children: .combine)
            HStack {
                Spacer()
                Button(SignInCopy.ok) {
                    if flow.finishNote() { onClose() }
                }
                .keyboardShortcut(.defaultAction)
                .focused($focus, equals: .note)
            }
        }
        .onExitCommand {
            if flow.finishNote() { onClose() }
        }
    }
}

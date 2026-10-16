import BrainBuddyDesign
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
        .padding(28)
        .frame(width: 460)
        .macSheetSurface()
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
        MacSignInForm(
            title: flow.title, subtitle: flow.subtitle, showsLocalTasksNotice: flow.showsLocalTasksNotice,
            message: flow.message.map { MacSignInMessage($0) }, footer: flow.footer, submitTitle: flow.submitTitle,
            isSigningIn: flow.isSigningIn, canCancel: flow.canCancel, canSubmit: flow.canSubmit,
            onCancel: { if flow.cancel() { onClose() } }, onSubmit: { flow.submit() }
        ) {
            TextField("Email", text: $flow.email)
                .textFieldStyle(.plain)
                .macSheetField()
                .disabled(flow.accountFieldsReadOnly)
                .focused($focus, equals: .email)
            SecureField("Password", text: $flow.password)
                .textFieldStyle(.plain)
                .macSheetField()
                .disabled(flow.credentialsReadOnly)
                .focused($focus, equals: .password)
                .onSubmit { flow.submit() }
            DisclosureGroup(isExpanded: $flow.showsAdvanced) {
                VStack(alignment: .leading, spacing: 8) {
                    TextField(SignInCopy.serverAddress, text: $flow.serverAddress)
                        .textFieldStyle(.plain)
                        .macSheetField()
                        .disabled(flow.accountFieldsReadOnly)
                    Button(SignInCopy.useDefaultServer) { flow.useDefaultServer() }
                        .buttonStyle(.macText)
                        .disabled(flow.accountFieldsReadOnly)
                }
                .padding(.top, 6)
            } label: {
                Text(SignInCopy.advanced)
                    .font(MacSheetFont.metaStrong)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
        }
    }

    /// "signed in, account deletion cancelled": the same sheet, its form replaced by the note; "OK",
    /// Return or Esc closes it. Sync has already started behind it.
    private var deletionCancelledNote: some View {
        VStack(alignment: .leading, spacing: 18) {
            MacSheetPlate {
                MacSheetStatus(
                    text: SignInCopy.deletionCancelledTitle, systemImage: "info.circle", tone: .primary)
                Text(SignInCopy.deletionCancelledDetail)
                    .font(MacSheetFont.body)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .accessibilityElement(children: .combine)
            HStack {
                Spacer()
                Button(SignInCopy.ok) {
                    if flow.finishNote() { onClose() }
                }
                .buttonStyle(.macStrongPill)
                .keyboardShortcut(.defaultAction)
                .focused($focus, equals: .note)
            }
        }
        .onExitCommand {
            if flow.finishNote() { onClose() }
        }
    }
}

/// A sign-in error's words: the title, the detail and the reference id to quote.
struct MacSignInMessage: Equatable {
    var title: String
    var detail: String?
    var referenceID: String?

    init(title: String, detail: String? = nil, referenceID: String? = nil) {
        self.title = title
        self.detail = detail
        self.referenceID = referenceID
    }

    init(_ message: SignInFlow.Message) {
        self.init(title: message.title, detail: message.detail, referenceID: message.referenceID)
    }
}

/// X-03's form, email and password only: the serif title and its line, the local-tasks note on a
/// `bg-ground` plate, the error in `status-warning` words with its reference id, the fields
/// (`fields`, passed in so a snapshot can render them), the footer, then Cancel (quiet, Esc) and
/// the strong "Sign in" (Return) with its progress while signing in.
struct MacSignInForm<Fields: View>: View {
    let title: String
    let subtitle: String
    let showsLocalTasksNotice: Bool
    let message: MacSignInMessage?
    let footer: String?
    let submitTitle: String
    let isSigningIn: Bool
    let canCancel: Bool
    let canSubmit: Bool
    let onCancel: () -> Void
    let onSubmit: () -> Void
    let fields: Fields

    init(
        title: String, subtitle: String, showsLocalTasksNotice: Bool, message: MacSignInMessage?, footer: String?,
        submitTitle: String, isSigningIn: Bool, canCancel: Bool, canSubmit: Bool,
        onCancel: @escaping () -> Void, onSubmit: @escaping () -> Void, @ViewBuilder fields: () -> Fields
    ) {
        self.title = title
        self.subtitle = subtitle
        self.showsLocalTasksNotice = showsLocalTasksNotice
        self.message = message
        self.footer = footer
        self.submitTitle = submitTitle
        self.isSigningIn = isSigningIn
        self.canCancel = canCancel
        self.canSubmit = canSubmit
        self.onCancel = onCancel
        self.onSubmit = onSubmit
        self.fields = fields()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            MacSheetHeader(title: title, subtitle: subtitle)
            if showsLocalTasksNotice {
                MacSheetPlate {
                    MacSheetStatus(
                        text: SignInCopy.localTasks, systemImage: "info.circle", tone: .primary, font: MacSheetFont.note)
                }
            }
            if let message {
                messageView(message)
            }
            fields
            if let footer {
                Text(footer)
                    .font(MacSheetFont.meta)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
            HStack(spacing: 8) {
                Spacer()
                // Enabled while signing in too: it stops the request and keeps what was typed. Not
                // once the account is linked: that sign-in finishes, so Cancel would be untrue.
                Button(SignInCopy.cancel, action: onCancel)
                    .buttonStyle(.macQuietPill)
                    .keyboardShortcut(.cancelAction)
                    .disabled(!canCancel)
                Button(action: onSubmit) {
                    HStack(spacing: 6) {
                        if isSigningIn {
                            ProgressView().controlSize(.small)
                        }
                        Text(submitTitle)
                    }
                }
                .buttonStyle(.macStrongPill)
                .keyboardShortcut(.defaultAction)
                .disabled(!canSubmit)
            }
            .padding(.top, 4)
        }
    }

    /// An error above the fields, in warning words with its reference id (selectable, to quote).
    private func messageView(_ message: MacSignInMessage) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            MacSheetStatus(text: message.title, systemImage: "exclamationmark.triangle", tone: .warning)
            if let detail = message.detail {
                Text(detail)
                    .font(MacSheetFont.body)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
            if let reference = message.referenceID {
                MacSheetReference(reference: reference)
            }
        }
        .fixedSize(horizontal: false, vertical: true)
        .accessibilityElement(children: .combine)
    }
}

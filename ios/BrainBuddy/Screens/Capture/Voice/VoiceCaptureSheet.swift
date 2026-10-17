import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI
import UIKit

/// Say a few things, watch the steps appear, add them to the Inbox (Carry On board 11).
///
/// A large sheet: Close and the language menu, "What feels heaviest?", what was heard, the steps,
/// and a glass bar with the voice button, a status word and "Add {n} to Inbox". It all runs on
/// this iPhone; everything shown and decided comes from `VoiceBrainDumpModel`, this file only
/// draws it and asks the platform for Settings, the toast and sync.
struct VoiceCaptureSheet: View {
    private let workspace: Workspace
    private let onSaved: () -> Void

    @Environment(ToastCenter.self) private var toasts
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var model: VoiceBrainDumpModel
    @State private var isConfirmingClose = false

    /// `onSaved` runs after the toast, so the capture sheet underneath can close too.
    init(workspace: Workspace, onSaved: @escaping () -> Void) {
        self.workspace = workspace
        self.onSaved = onSaved
        _model = State(
            initialValue: VoiceBrainDumpModel(
                speech: AppleSpeechCapture(), extractor: AppleStepExtractor(), port: workspace,
                language: VoiceLanguage.preferred(Locale.current.language.languageCode?.identifier)))
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                content
                    .padding(.horizontal, CGFloat(CarryOnSpace.lg))
                    .padding(.top, CGFloat(CarryOnSpace.xs))
                    .padding(.bottom, CGFloat(CarryOnSpace.md))
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .scrollBounceBehavior(.basedOnSize)
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            if showsBar { actionBar }
        }
        .bbScreenBackground()
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .interactiveDismissDisabled(model.needsCloseConfirmation)
        .task { await model.start() }
        .onDisappear { model.cancel() }
        .onChange(of: model.phase) { _, phase in phaseChanged(phase) }
        .onChange(of: model.steps.last?.id) { _, id in
            if id != nil, let title = model.steps.last?.title { AccessibilityNotification.Announcement(title).post() }
        }
        .confirmationDialog(VoiceBrainDumpCopy.discardTitle, isPresented: $isConfirmingClose, titleVisibility: .visible) {
            Button(VoiceBrainDumpCopy.discard, role: .destructive) { closeSheet() }
            Button(VoiceBrainDumpCopy.keepTalking, role: .cancel) {}
        } message: {
            Text(VoiceBrainDumpCopy.discardMessage)
        }
    }

    // MARK: Header

    private var header: some View {
        HStack {
            Button("Close") {
                if model.needsCloseConfirmation { isConfirmingClose = true } else { closeSheet() }
            }
            .keyboardShortcut(.cancelAction)
            .frame(minWidth: BBMetrics.hitTarget, minHeight: BBMetrics.hitTarget, alignment: .leading)
            .contentShape(Rectangle())
            Spacer(minLength: CGFloat(CarryOnSpace.xs))
            Menu {
                Picker("Language", selection: $model.language) {
                    ForEach(VoiceLanguage.allCases, id: \.self) { Text($0.title).tag($0) }
                }
            } label: {
                Text(model.language.title)
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                    .frame(minHeight: BBMetrics.hitTarget)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel("Language")
            .accessibilityValue(model.language.title)
        }
        .padding(.horizontal, CGFloat(CarryOnSpace.lg))
        .padding(.top, CGFloat(CarryOnSpace.sm))
    }

    // MARK: Body by phase

    @ViewBuilder private var content: some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.sm)) {
            switch model.phase {
            case .permissionDenied:
                Text(VoiceBrainDumpCopy.permissionDenied)
                    .carryOnFont(CarryOnTypeScale.body)
                    .foregroundStyle(.coTextPrimary)
                Button(VoiceBrainDumpCopy.openSettings) {
                    if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
                }
                .buttonStyle(.carryOnStrong)
            case .unavailable:
                Text(VoiceBrainDumpCopy.unavailable(model.language))
                    .carryOnFont(CarryOnTypeScale.body)
                    .foregroundStyle(.coTextPrimary)
                Button(VoiceBrainDumpCopy.tryLanguage(model.language.other)) {
                    model.language = model.language.other
                    Task { await model.start() }
                }
                .buttonStyle(.carryOnStrong)
            default:
                title
                if !model.heardText.isEmpty {
                    VoiceHeardText(text: model.heardText, showsCaret: model.phase == .listening)
                }
                if let message = model.errorMessage { InlineProblemText(message: message) }
                if model.steps.isEmpty {
                    if model.phase == .review {
                        Text(VoiceBrainDumpCopy.empty)
                            .carryOnFont(CarryOnTypeScale.body)
                            .foregroundStyle(.coTextSecondary)
                    }
                } else {
                    steps
                }
            }
        }
        .disabled(model.phase == .saving)
        .opacity(model.phase == .saving ? 0.5 : 1)
    }

    private var title: some View {
        Text(VoiceBrainDumpCopy.title)
            .carryOnFont(CarryOnTypeScale.title)
            .foregroundStyle(.coTextPrimary)
            .accessibilityAddTraits(.isHeader)
    }

    private var steps: some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xs)) {
            HStack {
                Text(VoiceBrainDumpCopy.stepsHeading).carryOnFont(CarryOnTypeScale.metaStrong).foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                Spacer(minLength: CGFloat(CarryOnSpace.xs))
                Text(VoiceBrainDumpCopy.notSavedYet).carryOnFont(CarryOnTypeScale.meta).foregroundStyle(.coTextSecondary)
            }
            ForEach(model.steps) { step in
                VoiceStepRow(
                    step: step, today: workspace.today,
                    rename: { model.rename(step.id, to: $0) },
                    remove: { model.remove(step.id) })
                    .transition(reduceMotion ? .identity : .opacity)
            }
            if model.phase == .review {
                Text(VoiceBrainDumpCopy.footer)
                    .carryOnFont(CarryOnTypeScale.meta).foregroundStyle(.coTextSecondary)
                    .frame(maxWidth: .infinity, alignment: .center).multilineTextAlignment(.center)
            }
        }
        .animation(BBMotion.animation(reduceMotion: reduceMotion), value: model.steps.map(\.id))
    }

    // MARK: Glass bar

    private var showsBar: Bool {
        switch model.phase {
        case .starting, .listening, .finishing, .review, .saving: true
        case .saved, .permissionDenied, .unavailable: false
        }
    }

    private var statusWord: String {
        switch model.phase {
        case .starting: VoiceBrainDumpCopy.starting
        case .listening: VoiceBrainDumpCopy.listening
        case .finishing: VoiceBrainDumpCopy.finishing
        case .saving: VoiceBrainDumpCopy.adding
        default: VoiceBrainDumpCopy.talkAgain
        }
    }

    private var actionBar: some View {
        let isListening = model.phase == .listening
        return BBGlassActionBar {
            Button {
                Task { if isListening { await model.stop() } else { await model.start() } }
            } label: {
                VoiceButtonFace(live: isListening, size: 50)
            }
            .buttonStyle(.plain)
            .disabled(!isListening && model.phase != .review)
            .accessibilityLabel(isListening ? VoiceBrainDumpCopy.stopListening : VoiceBrainDumpCopy.talk)
            Text(statusWord)
                .carryOnFont(CarryOnTypeScale.meta).foregroundStyle(.coTextSecondary)
                .lineLimit(1).minimumScaleFactor(0.7)
            Spacer(minLength: 0)
            Button {
                Task { await model.add() }
            } label: {
                VoiceAddLabel(title: model.addTitle)
            }
            .buttonStyle(.plain)
            .disabled(!model.canAdd)
            .opacity(model.canAdd ? 1 : 0.4)
        }
    }

    // MARK: Behaviour

    private func phaseChanged(_ phase: VoiceBrainDumpModel.Phase) {
        switch phase {
        case .saved(let count):
            let message = VoiceBrainDumpCopy.toast(count)
            toasts.show(message)
            AccessibilityNotification.Announcement(message).post()
            Task { await workspace.syncNow() }
            dismiss()
            onSaved()
        case .listening: AccessibilityNotification.Announcement(VoiceBrainDumpCopy.listening).post()
        default: break
        }
    }

    private func closeSheet() {
        model.cancel()
        dismiss()
    }
}

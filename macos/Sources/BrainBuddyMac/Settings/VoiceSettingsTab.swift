import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// Design S-05: which recogniser the voice sheet uses, and the optional Whisper download
/// (037-FR-006, -008). Plain values and closures, so every state renders without a download.
struct VoiceSettingsContent: View {
    let state: WhisperDownload.State
    let cancelling: Bool
    let onDownload: () -> Void
    let onCancel: () -> Void
    let onRemove: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            SettingsRow(label: VoiceSettingsCopy.speechLabel) {
                Text(VoiceSettingsCopy.speechValue).font(MacSheetFont.body)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            }
            MacSheetDivider().padding(.vertical, 8)
            SettingsRow(label: VoiceSettingsCopy.whisperLabel) {
                VStack(alignment: .leading, spacing: 4) {
                    whisperValue
                    Text(VoiceSettingsCopy.whisperDetail).font(MacSheetFont.meta)
                        .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            } trailing: {
                Button(action: action) { Text(Self.actionTitle(for: state)) }
                    .buttonStyle(.carryOnSecondary)
                    .disabled(cancelling)
            }
        }
        .padding(.vertical, 22).padding(.horizontal, 40)
    }

    @ViewBuilder private var whisperValue: some View {
        switch state {
        case .notDownloaded:
            Text(VoiceSettingsCopy.notDownloaded).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
        case .downloaded:
            Text(VoiceSettingsCopy.downloaded).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
        case .downloading(let fraction):
            VStack(alignment: .leading, spacing: 4) {
                Text(VoiceSettingsCopy.downloading(percent: Self.percent(fraction))).font(MacSheetFont.body)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                ProgressView(value: fraction).controlSize(.small).frame(maxWidth: 220)
            }
        case .failed(let reason):
            MacSheetStatus(text: VoiceSettingsCopy.failed(reason), tone: .danger, font: MacSheetFont.body)
        }
    }

    private func action() {
        switch state {
        case .notDownloaded, .failed: onDownload()
        case .downloading: onCancel()
        case .downloaded: onRemove()
        }
    }

    /// The one button S-05 shows for each state.
    static func actionTitle(for state: WhisperDownload.State) -> String {
        switch state {
        case .notDownloaded: VoiceSettingsCopy.download
        case .downloading: VoiceSettingsCopy.cancel
        case .downloaded: VoiceSettingsCopy.remove
        case .failed: VoiceSettingsCopy.tryAgain
        }
    }

    static func percent(_ fraction: Double) -> Int { Int((min(max(fraction, 0), 1) * 100).rounded(.down)) }
}

/// The live tab: the shared download, so the voice sheet sees Whisper appear or go at once.
struct VoiceSettingsTab: View {
    @ObservedObject var whisper: WhisperDownload

    var body: some View {
        VoiceSettingsContent(
            state: whisper.state, cancelling: whisper.cancelling,
            onDownload: { whisper.start() }, onCancel: { whisper.cancel() }, onRemove: { whisper.remove() })
    }
}

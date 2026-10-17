import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// G-06.01: the selected agent's details in 028's row style, then Test again, Replace credential… and
/// Edit… (030-FR-029, 030-FR-030, 030-FR-036). Every value but the copy is the agent's own text.
struct AgentDetailsView: View {
    static let labels = ["Status", "Address", "Credential", "Last contact", "Agent card", "Skills", "Updates", "Guarantee"]

    let rows: AgentDetailRows
    let isTesting: Bool
    let canTest: Bool
    let controlsEnabled: Bool
    /// Without a password on the account only the name can change, and the credential cannot be replaced.
    let canReplaceCredential: Bool
    var now: Date = Date()
    let onTest: () -> Void
    let onReplace: () -> Void
    let onEdit: () -> Void

    struct Line: Equatable, Identifiable {
        var label: String
        var value: String
        var id: String { label }
    }

    /// The rows that have a value, labelled; nil rows are not shown (G-06.01).
    var lines: [Line] {
        let values: [String?] = [
            rows.statusLine, rows.address, rows.credential, rows.lastContact.map { Self.contact($0, now: now) },
            rows.card, rows.skills, rows.updates, rows.guarantee,
        ]
        return zip(Self.labels, values).compactMap { label, value in value.map { Line(label: label, value: $0) } }
    }

    /// "Today 10:21", or the date and time for an earlier day.
    static func contact(_ date: Date, now: Date, calendar: Calendar = .current) -> String {
        let time = date.formatted(.dateTime.hour().minute())
        if calendar.isDate(date, inSameDayAs: now) { return "Today \(time)" }
        return "\(date.formatted(.dateTime.month(.abbreviated).day())) \(time)"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(lines) { line in
                SettingsRow(label: line.label) {
                    Text(line.value).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                        .textSelection(.enabled)
                }
            }
            HStack(spacing: 8) {
                Button(isTesting ? AgentsCopy.testing : AgentsCopy.testAgain, action: onTest).disabled(!canTest)
                if canReplaceCredential {
                    Button(AgentsCopy.replaceCredentialAction, action: onReplace).disabled(!controlsEnabled)
                }
                Button(AgentsCopy.edit, action: onEdit).disabled(!controlsEnabled)
            }
            .buttonStyle(.carryOnSecondary)
            .padding(.top, 10).padding(.leading, 164)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

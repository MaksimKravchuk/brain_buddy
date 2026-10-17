import BrainBuddyAgents
import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// G-06.01: M29's selected-agent heading and left-aligned metadata, then Test again, Replace credential… and
/// Edit… (030-FR-029, 030-FR-030, 030-FR-036). Every value but the copy is the agent's own text.
struct AgentDetailsView: View {
    private typealias Metrics = CarryOnLayout.MacAgents
    static let labels = ["Address", "Credential", "Last contact", "Agent card", "Skills", "Updates", "Guarantee"]

    let name: String
    let rows: AgentDetailRows
    let isTesting: Bool
    let canTest: Bool
    let controlsEnabled: Bool
    /// Without a password on the account only the name can change, and the credential cannot be replaced.
    let canReplaceCredential: Bool
    var statusStyle: CarryOnColorStyle = .coTextSecondary
    var statusDotStyle: CarryOnColorStyle = .coMarkOpen
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
            rows.address, rows.credential, rows.lastContact.map { Self.contact($0, now: now) },
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
            VStack(alignment: .leading, spacing: CarryOnSpace.xxs) {
                Text(name).carryOnText(CarryOnTypeScale.title)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary).accessibilityAddTraits(.isHeader)
                HStack(alignment: .firstTextBaseline, spacing: CarryOnSpace.xxs) {
                    Circle().fill(statusDotStyle).frame(width: Metrics.statusDot, height: Metrics.statusDot)
                        .accessibilityHidden(true)
                    Text(rows.statusLine).font(MacSheetFont.body).foregroundStyle(statusStyle)
                        .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                }
            }
            .padding(.bottom, CarryOnSpace.md)
            ForEach(lines) { line in
                HStack(alignment: .firstTextBaseline, spacing: 0) {
                    Text(line.label).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                        .frame(width: Metrics.labelWidth, alignment: .leading)
                    Text(line.value).font(MacSheetFont.body).foregroundStyle(CarryOnColorStyle.coTextPrimary)
                        .fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(minHeight: Metrics.rowHeight, alignment: .topLeading)
                .accessibilityElement(children: .combine)
            }
            ViewThatFits(in: .horizontal) {
                HStack(spacing: CarryOnSpace.xs) { buttons }
                VStack(alignment: .leading, spacing: CarryOnSpace.xs) { buttons }
            }
            .buttonStyle(.carryOnSecondary)
            .padding(.top, CarryOnSpace.sm)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Buttons never break a word: each keeps its natural width and the row drops to a column instead.
    @ViewBuilder private var buttons: some View {
        Button(isTesting ? AgentsCopy.testing : AgentsCopy.testAgain, action: onTest)
            .disabled(!canTest).lineLimit(1).fixedSize()
        if canReplaceCredential {
            Button(AgentsCopy.replaceCredentialAction, action: onReplace)
                .disabled(!controlsEnabled).lineLimit(1).fixedSize()
        }
        Button(AgentsCopy.edit, action: onEdit).disabled(!controlsEnabled).lineLimit(1).fixedSize()
    }
}

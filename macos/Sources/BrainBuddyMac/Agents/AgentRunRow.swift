import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// One run in All runs (G-02) or in Waiting for's Agents group (G-03): the step's title, then the meta
/// line. It selects the step and offers none of the list's task actions (030-FR-011).
struct AgentRunRow: View {
    enum Style { case canvas, waiting }

    let item: AgentRunItem
    let style: Style
    let now: Date
    let selected: Bool
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            MacTaskRowShell {
                EmptyView()
            } title: {
                VStack(alignment: .leading, spacing: 2) {
                    Text(item.stepTitle).font(MacRowFont.title).foregroundStyle(CarryOnColorStyle.coTextPrimary).lineLimit(1)
                    meta
                }
            } trailing: {
                EmptyView()
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .macRowSurface(selected: selected)
        .accessibilityLabel("\(item.stepTitle), \(item.agentName), \(item.state.label)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    /// Canvas: "<agent> · <detail>". Waiting for: "<agent> · " then the compact state, its word in the state's colour.
    @ViewBuilder private var meta: some View {
        switch style {
        case .canvas:
            Text(item.subtitle(now: now)).macRowMeta()
        case .waiting:
            let compact = item.compactState(now: now)
            let split = compact.range(of: " · ")
            HStack(spacing: 0) {
                Text("\(item.agentName) · ")
                Text(split.map { String(compact[..<$0.lowerBound]) } ?? compact).foregroundStyle(stateInk)
                Text(split.map { String(compact[$0.lowerBound...]) } ?? "")
            }
            .font(MacRowFont.meta)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .lineLimit(1)
        }
    }

    /// "Only your moves get colour": Needs you accent, Lost contact warning, Failed danger, the rest secondary.
    private var stateInk: CarryOnColorStyle {
        if item.state == .failed { return .coStatusDanger }
        switch item.group {
        case .needsYou: return .coTextAccent
        case .lostContact: return .coStatusWarning
        case .running, .queued, .toReview: return .coTextSecondary
        }
    }
}

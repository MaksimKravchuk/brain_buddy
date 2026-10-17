import BrainBuddyAPI
import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// One run in All runs (G-02) or Waiting for's Agents group (G-03); it selects the step, no task actions (030-FR-011).
struct AgentRunRow: View {
    enum Style { case canvas, waiting }

    let item: AgentRunItem
    let style: Style
    let now: Date
    let selected: Bool
    let onSelect: () -> Void
    /// Return: select the step and move focus to the inspector's run section (030-FR-040).
    let onOpen: () -> Void

    var body: some View {
        Button(action: onSelect) {
            switch style {
            case .canvas: card
            case .waiting: waitingRow
            }
        }
        .buttonStyle(.plain)
        .onKeyPress(.return) {
            onOpen()
            return .handled
        }
        .accessibilityLabel("\(item.stepTitle), \(item.agentName), \(item.state.label)")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    /// Board M22: a card on `surface-card` (radius 10, padding 10/12); Needs you has the accent dot and a semibold title.
    private var card: some View {
        let needsYou = item.state == .needsYou
        return VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                if needsYou { Circle().fill(CarryOnColorStyle.coStepDotCurrent).frame(width: 7, height: 7) }
                Text(item.stepTitle)
                    .font(needsYou ? MacRowFont.titleStrong : MacRowFont.title)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
            }
            Text(item.subtitle(now: now)).macRowMeta()
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(selected ? CarryOnColorStyle.coRowBgSelected : CarryOnColorStyle.coSurfaceCard,
                    in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .contentShape(Rectangle())
    }

    /// Board M23: the agent mark, the title, then "<agent> · <dot + state word> · <time>" at the end.
    private var waitingRow: some View {
        let compact = item.compactState(now: now)
        let split = compact.range(of: " · ")
        return MacTaskRowShell {
            MacBoardIconView(icon: .agentRun, size: 18).foregroundStyle(CarryOnColorStyle.coMarkOpen)
        } title: {
            Text(item.stepTitle).font(MacRowFont.title).foregroundStyle(CarryOnColorStyle.coTextPrimary).lineLimit(1)
        } trailing: {
            HStack(spacing: 0) {
                Text("\(item.agentName) · ")
                HStack(spacing: 6) {
                    Circle().fill(tone.dot).frame(width: 7, height: 7)
                    Text(split.map { String(compact[..<$0.lowerBound]) } ?? compact)
                }
                .foregroundStyle(tone.ink)
                Text(split.map { String(compact[$0.lowerBound...]) } ?? "")
            }
            .font(MacRowFont.meta)
            .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            .lineLimit(1)
        }
        .macRowSurface(selected: selected)
        .contentShape(Rectangle())
    }

    /// "Only your moves get colour": Needs you accent, Lost contact warning, Failed danger, the rest secondary.
    private var tone: (ink: CarryOnColorStyle, dot: CarryOnColorStyle) {
        if item.state == .failed { return (.coStatusDanger, .coStatusDanger) }
        switch item.group {
        case .needsYou: return (.coTextAccent, .coStepDotCurrent)
        case .lostContact: return (.coStatusWarning, .coStatusWarning)
        case .running, .queued, .toReview: return (.coTextSecondary, .coMarkOpen)
        }
    }
}

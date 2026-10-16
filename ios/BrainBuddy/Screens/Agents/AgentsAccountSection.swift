import BrainBuddyAPI
import BrainBuddyAgents
import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

/// Board M25 / design I-06: the "Agents" section of the signed-in account list. One row per connected
/// agent (glyph, name, status word with a dot, chevron) that pushes its details (M29), then
/// "+ Add new agent" (M30) when adding is allowed (034-FR-010, 030-FR-029, 030-FR-036).
///
/// Hidden while signed out. With the relay flag off the rows stay readable and Add is not offered
/// (034 design I-06; 030-FR-002).
struct AgentsAccountSection: View {
    @Environment(AgentsSession.self) private var agents: AgentsSession?
    @Environment(Workspace.self) private var workspace

    var body: some View {
        if let agents, agents.showsSettings {
            AgentsAccountSectionContent(agents: agents, account: workspace.account)
        }
    }
}

/// The inner half of the pair: it owns the `AgentSettingsModel`, which needs the account at init, and
/// `@Environment` values are not readable there.
private struct AgentsAccountSectionContent: View {
    let agents: AgentsSession
    let account: LinkedAccount?
    @State private var model: AgentSettingsModel

    init(agents: AgentsSession, account: LinkedAccount?) {
        self.agents = agents
        self.account = account
        _model = State(
            initialValue: AgentSettingsModel(
                account: account, availability: agents.availability, remote: { AgentsClient.make(for: $0) }))
    }

    var body: some View {
        Section {
            content
        } header: {
            SettingsSectionHeader("Agents")
        }
        .listRowBackground(Rectangle().fill(.coSurfaceCard))
        .task(id: account?.id) {
            model.update(account: account)
            await model.reload()
        }
    }

    @ViewBuilder private var content: some View {
        switch model.phase {
        case .notSignedIn, .sessionEnded:
            EmptyView()
        case .loading where model.connections.isEmpty:
            HStack {
                ProgressView()
                Spacer(minLength: 0)
            }
            .frame(minHeight: BBMetrics.hitTarget)
        case .failed(let notice):
            failure(notice)
        default:
            rows
        }
    }

    @ViewBuilder private var rows: some View {
        if model.phase == .offline {
            note(AgentsCopy.needsConnection)
        }
        if model.rows.isEmpty {
            note(AgentsCopy.noAgents)
        }
        ForEach(model.rows) { row in
            NavigationLink {
                AgentDetailsScreen(model: model, connectionID: row.id)
            } label: {
                AgentListRowView(row: row, tone: tone(of: row.id))
            }
        }
        if model.isPasswordless {
            note(AgentsCopy.noPassword)
        }
        if agents.canAddAgent {
            NavigationLink {
                AddAgentScreen(model: model)
            } label: {
                addRowLabel
            }
            .disabled(!model.canAdd)
        }
    }

    private var addRowLabel: some View {
        HStack(spacing: CGFloat(CarryOnSpace.sm)) {
            Image(systemName: "plus")
                .font(BBFont.body)
                .foregroundStyle(.coTextPrimary)
                .frame(width: BBMetrics.iconColumn)
                .accessibilityHidden(true)
            Text(verbatim: AgentsCopy.addNewAgent)
                .carryOnFont(CarryOnTypeScale.body)
                .foregroundStyle(.coTextPrimary)
        }
        .frame(minHeight: BBMetrics.hitTarget)
    }

    private func tone(of id: String) -> AgentStatusTone {
        model.connections.first { $0.id == id }.map(AgentStatusTone.of) ?? .warning
    }

    private func note(_ text: String) -> some View {
        Text(verbatim: text)
            .carryOnFont(CarryOnTypeScale.meta)
            .foregroundStyle(.coTextSecondary)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func failure(_ notice: AgentNotice) -> some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xxs)) {
            Text(verbatim: AgentsCopy.agentsFailed)
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coStatusDanger)
            if let reference = notice.reference {
                Text(verbatim: AgentsCopy.reference(reference))
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coTextSecondary)
                    .textSelection(.enabled)
            }
            Button(AgentsCopy.tryAgain) { Task { await model.reload() } }
                .buttonStyle(.carryOnQuiet)
        }
    }
}

/// One agent row: robot glyph, name, the status word led by its dot, and the chevron the link draws.
private struct AgentListRowView: View {
    let row: AgentListRow
    let tone: AgentStatusTone

    var body: some View {
        HStack(spacing: CGFloat(CarryOnSpace.sm)) {
            AgentSettingsGlyph(size: 20)
                .foregroundStyle(.coTextPrimary)
                .accessibilityHidden(true)
            Text(verbatim: row.name)
                .carryOnFont(CarryOnTypeScale.body)
                .foregroundStyle(.coTextPrimary)
                .lineLimit(1)
            Spacer(minLength: CGFloat(CarryOnSpace.xs))
            AgentStatusWord(text: row.status, tone: tone)
        }
        .frame(minHeight: BBMetrics.hitTarget)
        .accessibilityElement(children: .combine)
    }
}

/// The status word with its dot. The word carries the meaning; the dot only repeats it.
struct AgentStatusWord: View {
    let text: String
    let tone: AgentStatusTone

    var body: some View {
        HStack(spacing: CGFloat(CarryOnSpace.xxs)) {
            Circle()
                .fill(tone.dotColor)
                .frame(width: BBMetrics.projectDot, height: BBMetrics.projectDot)
                .accessibilityHidden(true)
            Text(verbatim: text)
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(tone.textColor)
                .lineLimit(1)
        }
    }
}

/// How a connection's status word is coloured (M25): grey for a tested-ready agent, the warning
/// colour for anything that needs a look (Stale, Not tested, Agent changed, Rate limited), and the
/// danger colour for a connection that cannot work (credentials rejected, unreachable, unsupported).
enum AgentStatusTone: Equatable {
    case ready, warning, danger

    static func of(_ dto: AgentConnectionDTO) -> AgentStatusTone {
        if dto.agentChanged || dto.lastTestErrorCode == "a2a_rate_limited" { return .warning }
        switch dto.status {
        case .ready: return dto.stale ? .warning : .ready
        case .untested: return .warning
        default: return .danger
        }
    }

    var dotColor: CarryOnColorStyle {
        switch self {
        case .ready: CarryOnColorStyle.coMarkOpen
        case .warning: CarryOnColorStyle.coStatusWarning
        case .danger: CarryOnColorStyle.coStatusDanger
        }
    }

    var textColor: CarryOnColorStyle {
        switch self {
        case .ready: CarryOnColorStyle.coTextSecondary
        case .warning: CarryOnColorStyle.coStatusWarning
        case .danger: CarryOnColorStyle.coStatusDanger
        }
    }
}

/// The robot of the agent rows (board M25, 24-unit grid): head 4,6 16 x 12 radius 4, eyes at 9.5 and
/// 14.5 / 12 radius 1.2, antenna 12,3 to 12,6, stroked 1.8.
struct AgentSettingsGlyph: View {
    var size: CGFloat = 20

    var body: some View {
        AgentSettingsGlyphShape()
            .stroke(style: StrokeStyle(lineWidth: size * 1.8 / 24, lineCap: .round, lineJoin: .round))
            .frame(width: size, height: size)
    }
}

struct AgentSettingsGlyphShape: Shape {
    func path(in rect: CGRect) -> Path {
        let unit = min(rect.width, rect.height) / 24
        func point(_ x: CGFloat, _ y: CGFloat) -> CGPoint {
            CGPoint(x: rect.minX + x * unit, y: rect.minY + y * unit)
        }
        var path = Path()
        path.addRoundedRect(
            in: CGRect(origin: point(4, 6), size: CGSize(width: 16 * unit, height: 12 * unit)),
            cornerSize: CGSize(width: 4 * unit, height: 4 * unit), style: .continuous)
        for eye in [CGFloat(9.5), CGFloat(14.5)] {
            path.addEllipse(
                in: CGRect(origin: point(eye - 1.2, 10.8), size: CGSize(width: 2.4 * unit, height: 2.4 * unit)))
        }
        path.move(to: point(12, 3))
        path.addLine(to: point(12, 6))
        return path
    }
}

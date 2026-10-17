import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyMacCore
import SwiftUI

/// G-02, board M22: every listed run grouped by what it needs, or one agent's (030-FR-007, 030-FR-008).
/// Grouping is on the client; no step moves.
struct AgentRunsCanvas: View {
    let model: BrainBuddyModel
    let filter: AgentRunsFilter
    let selectedTaskID: TaskID?
    let onSelect: (AgentRunItem) -> Void
    let onOpen: (AgentRunItem) -> Void

    private var store: AgentRunsStore { model.agentRuns }

    private var groups: [(group: AgentRunGroup, items: [AgentRunItem])] {
        store.sections.compactMap { section in
            let items = section.items.filter { filter == .all || filter == .agent($0.connectionID ?? "") }
            return items.isEmpty ? nil : (section.group, items)
        }
    }

    private var title: String {
        guard case .agent(let id) = filter, let name = model.listedRuns.first(where: { $0.connectionID == id })?.agentName else {
            return AgentsCopy.allRuns
        }
        return name
    }

    var body: some View {
        let shown = groups
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                MacListHeaderTitle(title: title, caption: AgentsCopy.runCount(shown.reduce(0) { $0 + $1.items.count }))
                    .accessibilityAddTraits(.isHeader)
                Text(AgentsCopy.allRunsSubtitle).foregroundStyle(.coTextSecondary).carryOnFont(CarryOnTypeScale.meta)
                if store.phase == .stale, let updated = store.lastUpdated {
                    Text(AgentsCopy.lastUpdated(updated.formatted(date: .omitted, time: .shortened)))
                        .foregroundStyle(.coTextSecondary).carryOnFont(CarryOnTypeScale.meta)
                }
            }
            .padding(.horizontal, 28).padding(.top, 28).padding(.bottom, 20)
            ScrollView {
                // Board M22: one column per group, side by side.
                HStack(alignment: .top, spacing: 12) {
                    ForEach(shown, id: \.group) { entry in
                        VStack(alignment: .leading, spacing: 6) {
                            Text("\(entry.group.title) · \(entry.items.count)")
                                .font(MacRowFont.sectionHeader).foregroundStyle(CarryOnColorStyle.coTextSecondary)
                                .padding(.bottom, 2).accessibilityAddTraits(.isHeader)
                            ForEach(entry.items) { run in
                                AgentRunRow(
                                    item: run, style: .canvas, now: Date(),
                                    selected: selectedTaskID != nil && selectedTaskID == model.stepID(forServerID: run.taskServerID),
                                    onSelect: { onSelect(run) }, onOpen: { onOpen(run) })
                            }
                        }
                        .frame(maxWidth: .infinity, alignment: .topLeading)
                    }
                }
                .padding(.horizontal, 28).padding(.bottom, 28)
            }
            .overlay { placeholder(isEmpty: shown.isEmpty) }
        }
        .frame(minWidth: 560, minHeight: 480)
        .background(.coBgGround)
    }

    /// Loading, failed and empty replace the groups (G-02.03, G-02.04, G-02.06).
    @ViewBuilder private func placeholder(isEmpty: Bool) -> some View {
        if isEmpty {
            switch store.phase {
            case .loading:
                Text(AgentsCopy.runsLoading).font(MacRowFont.title).foregroundStyle(.coTextSecondary)
            case .failed(let reference):
                VStack(spacing: 6) {
                    Text(AgentsCopy.runsFailed).font(MacRowFont.title).foregroundStyle(.coTextSecondary)
                    if let reference { Text(AgentsCopy.reference(reference)).macRowMeta() }
                    Button(AgentsCopy.tryAgain) { Task { await model.refreshAgents() } }.buttonStyle(.carryOnSecondary)
                }
            case .loaded, .stale:
                Text(AgentsCopy.allRunsEmpty).font(MacRowFont.title).foregroundStyle(.coTextSecondary)
            }
        }
    }
}

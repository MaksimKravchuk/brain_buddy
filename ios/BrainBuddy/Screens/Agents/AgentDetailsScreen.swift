import BrainBuddyAPI
import BrainBuddyAgents
import BrainBuddyDesign
import SwiftUI

/// Board M29 / design I-07: one agent's details, pushed from the Agents section (034-FR-011).
/// Status and sentence, Connection, what its agent card says, the start guarantee, and Test again,
/// Replace credential and Delete (030-FR-030, 030-FR-032, 030-FR-033). Every value but the copy is the
/// agent's own text, shown verbatim.
struct AgentDetailsScreen: View {
    let model: AgentSettingsModel
    let connectionID: String

    @Environment(\.dismiss) private var dismiss
    @State private var editor: AgentConnectionEditor?

    private var connection: AgentConnectionDTO? { model.connections.first { $0.id == connectionID } }

    var body: some View {
        ScrollView {
            if let connection {
                VStack(alignment: .leading, spacing: 0) {
                    header(connection)
                    connectionSection(connection)
                    cardSection(connection)
                    guaranteeLine(connection)
                    noticeLines
                    actions(connection)
                }
                .padding(.bottom, CGFloat(CarryOnSpace.lg))
            }
        }
        .bbScreenBackground()
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { model.select(connectionID) }
        .onChange(of: connection?.id) { _, id in
            if id == nil { dismiss() }
        }
        .sheet(
            isPresented: Binding(
                get: { editor != nil },
                set: { if !$0 { closeEditor() } })
        ) {
            if let editor { AgentCredentialSheet(editor: editor, onClose: closeEditor) }
        }
    }

    // MARK: header

    private func header(_ connection: AgentConnectionDTO) -> some View {
        HStack(alignment: .center, spacing: CGFloat(CarryOnSpace.sm)) {
            AgentSettingsGlyph(size: 28)
                .foregroundStyle(.coTextPrimary)
                .frame(width: BBMetrics.hitTarget, height: BBMetrics.hitTarget)
                .background(.coControlQuiet, in: RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xxs)) {
                Text(verbatim: connection.name)
                    .carryOnFont(CarryOnTypeScale.title)
                    .foregroundStyle(.coTextPrimary)
                    .accessibilityAddTraits(.isHeader)
                statusLine(connection)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, CGFloat(CarryOnSpace.md) + CGFloat(CarryOnSpace.xxs))
        .padding(.top, CGFloat(CarryOnSpace.xxs))
    }

    private func statusLine(_ connection: AgentConnectionDTO) -> some View {
        let word = AgentSettingsModel.status(of: connection)
        let ready = connection.readyForHandoff && connection.status == .ready && !connection.stale && !connection.agentChanged
        let sentence = ready ? AgentsCopy.readyForHandoff : AgentsCopy.statusDetail(AgentSettingsModel.connection(connection))
        return VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xxs)) {
            AgentStatusWord(text: word, tone: AgentStatusTone.of(connection))
            Text(verbatim: sentence)
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .accessibilityElement(children: .combine)
    }

    // MARK: sections

    private func connectionSection(_ connection: AgentConnectionDTO) -> some View {
        let details = AgentSettingsModel.details(connection)
        var lines: [(label: String, value: String)] = [
            ("Address", details.address),
            ("Credential", details.credential),
        ]
        if let contact = connection.lastContactAt { lines.append(("Last contact", Self.when(contact))) }
        if let tested = connection.lastTestedAt { lines.append(("Last tested", Self.when(tested))) }
        return group("Connection") { valueRows(lines) }
    }

    private func cardSection(_ connection: AgentConnectionDTO) -> some View {
        let card = connection.card
        var lines: [(label: String, value: String)] = []
        if let version = card?.version {
            let value = card?.protocolVersion.map { AgentsCopy.cardVersion(version, protocol: $0) } ?? version
            lines.append(("Version", value))
        }
        lines.append(("Streaming updates", Self.support(connection.capabilities.streaming)))
        lines.append(("Push notifications", Self.support(connection.capabilities.pushNotifications)))
        let skills = (card?.skills ?? []).compactMap(\.name).filter { !$0.isEmpty }
        return group("Read from its agent card") {
            valueRows(lines)
            if !skills.isEmpty {
                separator
                BBFlowLayout(spacing: CGFloat(CarryOnSpace.xs), lineSpacing: CGFloat(CarryOnSpace.xs)) {
                    ForEach(Array(skills.enumerated()), id: \.offset) { _, skill in
                        CarryOnChip(skill)
                    }
                }
                .padding(.horizontal, CGFloat(CarryOnLayout.Row.paddingX))
                .padding(.vertical, CGFloat(CarryOnSpace.sm))
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(Text(verbatim: skills.joined(separator: ", ")))
            }
        }
    }

    @ViewBuilder private func guaranteeLine(_ connection: AgentConnectionDTO) -> some View {
        let tier = AgentSettingsModel.details(connection).guarantee
        let parts = [tier.map { $0 + "." }, connection.cancellationDisclosure].compactMap { $0 }.filter { !$0.isEmpty }
        if !parts.isEmpty {
            Text(verbatim: parts.joined(separator: " "))
                .carryOnFont(CarryOnTypeScale.meta)
                .foregroundStyle(.coTextSecondary)
                .padding(.horizontal, CGFloat(CarryOnSpace.lg) + CGFloat(CarryOnSpace.xxs))
                .padding(.top, CGFloat(CarryOnSpace.xs))
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    @ViewBuilder private var noticeLines: some View {
        if let notice = model.notice {
            VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xxs)) {
                Text(verbatim: notice.message)
                    .carryOnFont(CarryOnTypeScale.meta)
                    .foregroundStyle(.coStatusDanger)
                if let reference = notice.reference {
                    Text(verbatim: AgentsCopy.reference(reference))
                        .carryOnFont(CarryOnTypeScale.meta)
                        .foregroundStyle(.coTextSecondary)
                        .textSelection(.enabled)
                }
            }
            .padding(.horizontal, CGFloat(CarryOnSpace.lg) + CGFloat(CarryOnSpace.xxs))
            .padding(.top, CGFloat(CarryOnSpace.sm))
        }
    }

    // MARK: actions

    private func actions(_ connection: AgentConnectionDTO) -> some View {
        VStack(spacing: CGFloat(CarryOnSpace.md)) {
            HStack(spacing: CGFloat(CarryOnSpace.xs)) {
                Button {
                    Task { await model.testAgain() }
                } label: {
                    Text(verbatim: model.isTesting ? AgentsCopy.testing : AgentsCopy.testAgain)
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.carryOnSecondary)
                .disabled(!model.canTest)
                if !model.isPasswordless {
                    Button {
                        open(.replaceCredential(connection))
                    } label: {
                        Text(verbatim: "Replace credential")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.carryOnSecondary)
                    .disabled(!model.controlsEnabled)
                }
            }
            // Deleting needs the current password, so a passwordless account is not offered it (030-FR-036).
            if !model.isPasswordless {
                Button {
                    open(.delete(connection))
                } label: {
                    Text(verbatim: "Delete \(connection.name)…")
                        .carryOnFont(CarryOnTypeScale.body)
                        .foregroundStyle(.coStatusDanger)
                        .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(!model.controlsEnabled)
            }
        }
        .padding(.horizontal, CGFloat(CarryOnSpace.md))
        .padding(.top, CGFloat(CarryOnSpace.md))
    }

    private func open(_ mode: AgentEditorMode) {
        guard editor == nil, model.controlsEnabled else { return }
        editor = AgentConnectionEditor(mode: mode, model: model)
    }

    private func closeEditor() {
        editor?.dismiss()
        editor = nil
    }

    // MARK: building blocks

    private func group<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: CGFloat(CarryOnSpace.xs)) {
            Text(verbatim: title)
                .carryOnFont(CarryOnTypeScale.metaStrong)
                .foregroundStyle(.coTextSecondary)
                .padding(.horizontal, CGFloat(CarryOnSpace.lg) + CGFloat(CarryOnSpace.xxs))
                .accessibilityAddTraits(.isHeader)
            VStack(alignment: .leading, spacing: 0) {
                content()
            }
            .background(
                .coSurfaceCard, in: RoundedRectangle(cornerRadius: CGFloat(CarryOnRadius.md), style: .continuous)
            )
            .padding(.horizontal, CGFloat(CarryOnSpace.md))
        }
        .padding(.top, CGFloat(CarryOnSpace.md))
    }

    private func valueRows(_ lines: [(label: String, value: String)]) -> some View {
        ForEach(Array(lines.enumerated()), id: \.offset) { index, line in
            if index > 0 { separator }
            HStack(alignment: .firstTextBaseline, spacing: CGFloat(CarryOnSpace.sm)) {
                Text(verbatim: line.label)
                    .carryOnFont(CarryOnTypeScale.body)
                    .foregroundStyle(.coTextPrimary)
                Spacer(minLength: CGFloat(CarryOnSpace.xs))
                Text(verbatim: line.value)
                    .carryOnFont(CarryOnTypeScale.body)
                    .foregroundStyle(.coTextSecondary)
                    .multilineTextAlignment(.trailing)
                    .textSelection(.enabled)
            }
            .padding(.horizontal, CGFloat(CarryOnLayout.Row.paddingX))
            .padding(.vertical, CGFloat(CarryOnSpace.sm) - 1)
            .accessibilityElement(children: .combine)
        }
    }

    private var separator: some View {
        Rectangle()
            .fill(.coBgGround)
            .frame(height: 1)
            .padding(.leading, CGFloat(CarryOnLayout.Row.paddingX))
    }

    // MARK: formatting

    static func support(_ supported: Bool) -> String { supported ? "Supported" : "Not supported" }

    /// "Today 10:21", or the day and time for an earlier day.
    static func when(_ date: Date, now: Date = Date(), calendar: Calendar = .current) -> String {
        let time = date.formatted(.dateTime.hour().minute())
        if calendar.isDate(date, inSameDayAs: now) { return "Today \(time)" }
        return "\(date.formatted(.dateTime.month(.abbreviated).day())) \(time)"
    }
}

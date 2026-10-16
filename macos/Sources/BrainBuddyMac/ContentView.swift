import AppKit
import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyMacCore
import BrainBuddyWorkspace
import Combine
import SwiftUI

// The main window over the kit `Workspace` (spec 021, T106): every rule is the kit's, every write
// applies at once on this Mac (FR-010), and the screen keys selection, scroll and focus by
// `EntityID`. `BrainBuddyModel` (BrainBuddyMacCore) holds navigation, the capture draft and the
// review marks; the views here only present it.

/// The window's root: static placeholders while the launch runs (X-05 "loading", after 300 ms),
/// the import-failed panel when the upgrade import could not finish (nothing opens until it does,
/// data-model E7.1 invariant 4), X-09 when `store.json` cannot be read, else the workspace.
struct ContentView: View {
    let launch: MacLaunch
    @State private var showsPlaceholders = false
    /// 029-FR-002: the first-run decision is made before the workspace window renders.
    @State private var firstRunDecided = false

    var body: some View {
        Group {
            if let host = launch.host, let model = launch.model, let sync = launch.sync {
                if host.workspace.loadError != nil {
                    // X-09: nothing syncs until the file can be read (mac-app-host §9).
                    UnreadableWorkspaceView(host: host)
                } else if !firstRunDecided {
                    LaunchPlaceholderView(visible: showsPlaceholders)
                } else {
                    WorkspaceView(model: model, sync: sync)
                        .task {
                            // Launch step 6, once per process.
                            let runtime = MacSyncRuntime.current ?? MacSyncRuntime(host: host, controller: sync)
                            MacSyncRuntime.current = runtime
                            await runtime.start()
                        }
                }
            } else if launch.importFailed {
                LegacyImportFailedView(launch: launch)
            } else {
                LaunchPlaceholderView(visible: showsPlaceholders)
            }
        }
        .onChange(of: launch.host != nil, initial: true) { _, ready in
            guard ready, !firstRunDecided else { return }
            if launch.host?.workspace.loadError == nil { launch.model?.decideFirstRun() }
            firstRunDecided = true
        }
        .task {
            await launch.run { notice in UpgradeNotice.present(notice) }
        }
        .task {
            try? await Task.sleep(for: .milliseconds(300))
            showsPlaceholders = true
        }
    }
}

/// Static list placeholders: no progress text, no motion (design "State inventory").
private struct LaunchPlaceholderView: View {
    let visible: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 12) {
                ForEach(0..<7, id: \.self) { _ in bar(width: 180) }
            }
            .padding(20)
            .frame(width: 320, alignment: .topLeading)
            Divider()
            VStack(alignment: .leading, spacing: 14) {
                bar(width: 260).frame(height: 26)
                ForEach(0..<6, id: \.self) { _ in bar(width: 520).frame(height: 38) }
            }
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .opacity(visible ? 1 : 0)
        .accessibilityHidden(true)
        .frame(minWidth: 720, minHeight: 480)
    }

    private func bar(width: CGFloat) -> some View {
        RoundedRectangle(cornerRadius: 6).fill(.quaternary).frame(maxWidth: width, minHeight: 14, maxHeight: 14)
    }
}

private enum PendingEditorNavigation {
    case destination(WorkspaceDestination)
    case quickOpen(QuickOpenTarget)
    case task(TaskID?)
    case complete(TaskID)
    case move(TaskID, TaskList)
    case reopen(TaskID)
    case cancel(TaskID)
    case newTask
    case reload
    case clearTaskFilters
    case createTask
    case reviewWaiting
    case reviewSomeday
    case reviewProjects
    case clarifyInbox
    /// The inspector's Inbox "Bigger than one step": the clarification's project path for this item.
    case clarifyAsProject(TaskID)
    case groupByProject(Bool)
    case showCancelled(Bool)
    case sort(TaskSort)
    /// "Sign out…" (X-02, X-07): X-04 opens only after this guard (design X-04 "unsaved edit or
    /// capture draft").
    case signOut
}

/// Where keyboard focus goes after an X-06 change.
private enum CanvasFocus: Hashable {
    case title, unarchive, retry
}

/// A section as shown: the kit's section with the hovered or edited row held in place
/// (`ListPresentationHold`, FR-009).
private struct PresentedSection: Identifiable {
    let id: String
    let title: String?
    let kind: TaskSection.Kind
    let rows: [TaskRecord]
    /// Rows kept on screen by the hold that the incoming list no longer has: shown dimmed.
    let departed: Set<TaskID>

    var isTerminal: Bool {
        switch kind {
        case .completed, .cancelled: true
        default: false
        }
    }
}

func tagTint(_ id: TagID) -> Color {
    let palette: [Color] = [.purple, .teal, .green, .orange, .pink]
    let hash = id.rawValue.utf8.reduce(UInt(0)) { ($0 &* 31) &+ UInt($1) }
    return palette[Int(hash % UInt(palette.count))]
}

func projectTint(_ hex: String?) -> Color {
    guard let hex, hex.hasPrefix("#"), hex.count == 7, let value = UInt32(hex.dropFirst(), radix: 16) else {
        return .accentColor
    }
    return Color(
        .sRGB, red: Double((value >> 16) & 0xff) / 255, green: Double((value >> 8) & 0xff) / 255,
        blue: Double(value & 0xff) / 255, opacity: 1
    )
}

extension WorkspaceView {
    static func plural(_ count: Int, _ noun: String) -> String { "\(count) \(noun)\(count == 1 ? "" : "s")" }
}

@MainActor @ViewBuilder
private func listQueryState(_ readiness: WorkspaceQueryReadiness, loading: String, retry: @escaping () -> Void) -> some View {
    switch readiness {
    case .ready:
        EmptyView()
    case .notRequested, .loading:
        ProgressView(loading)
    case .failed:
        MacSheetEmptyState(
            title: "Tasks couldn’t load", systemImage: "exclamationmark.triangle",
            description: "Try loading this list again."
        ) {
            Button("Retry", action: retry)
        }
    }
}

@MainActor
private func reviewPageUnavailable(
    _ title: String, systemImage: String, description: String, list: TaskList,
    model: BrainBuddyModel, reload: @escaping () -> Void
) -> some View {
    MacSheetEmptyState(title: title, systemImage: systemImage, description: description) {
        if model.reviewListPageState(list).hasNext {
            Button("Next page") {
                Task {
                    await model.nextReviewListPage(list)
                    reload()
                }
            }
        }
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
}

struct WorkspaceView: View {
    @Bindable var model: BrainBuddyModel
    /// X-01 – X-04 and X-07 over this workspace; every sync surface presents through its router.
    let sync: MacSyncController
    @State private var columns: NavigationSplitViewVisibility = .all
    /// The window's undo stack: Edit › Undo (⌘Z) takes back the last Done, Cancel or move.
    @Environment(\.undoManager) private var undoManager
    @Environment(\.openSettings) private var openSettings
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var quickCapture = QuickCaptureController()
    @State private var voicePresented = false
    @State private var selectedTaskID: TaskID?
    @State private var selectionAnchor: SelectionAnchor<TaskID>?
    @State private var scrollTarget: TaskID?
    /// The open task's fields, saved as you type (`TaskAutosave`).
    @State private var taskForm: TaskAutosave?
    /// The save of those fields in flight; a flush waits for it.
    @State private var autosaveRun: Task<Bool, Never>?
    /// The debounce: wakes when the pending field edits are due.
    @State private var autosaveTimer: Task<Void, Never>?
    /// A subtask or comment typed in the inspector but not added yet: it cannot save as you type.
    @State private var extrasDirty = false
    /// The inspector field being typed in, which an incoming change never overwrites.
    @State private var inspectorFocus: TaskInspectorField?
    /// The Inbox item the clarification opens on, in its project path.
    @State private var clarifyProjectStart: TaskID?
    @State private var taskSaveEditorID = UUID().uuidString
    @State private var quickRenameEditorID = UUID().uuidString
    @State private var collectionEditorID = UUID().uuidString
    @State private var collectionCreateEditorID = UUID().uuidString
    @State private var projectOutcomeEditorID = UUID().uuidString
    @State private var isSubmittingSheet = false
    @State private var reopenEditorID = UUID().uuidString
    @State private var moveWaitingEditorID = UUID().uuidString
    @State private var hoveredTaskID: TaskID?
    @State private var shownOrders: [String: [TaskID]] = [:]
    @State private var pendingEditorNavigation: PendingEditorNavigation?
    @State private var confirmingDiscard = false
    @State private var pendingVoiceTranscript: String?
    @State private var confirmingReplaceDraft = false
    @State private var choosingCaptureList = false
    @State private var focusCaptureAfterChoice = false
    @State private var captureListChoice: TaskList = .next
    @State private var addingCollection: NewCollection?
    @State private var collectionName = ""
    @State private var editingCollection: CollectionToEdit?
    @State private var editedCollectionName = ""
    @State private var renamingFromRefusal = false
    @State private var editingOutcomeProject: ProjectRecord?
    @State private var outcomeDraft = ""
    @State private var tagToDelete: TagRecord?
    @State private var confirmingTagDeletion = false
    @State private var reopeningTask: TaskRecord?
    @State private var reopenDestination: TaskList = .next
    @State private var reopenWaitingFor = ""
    @State private var movingTask: TaskRecord?
    @State private var moveWaitingFor = ""
    @State private var reviewingWaiting = false
    @State private var reviewingSomeday = false
    @State private var reviewingProjects = false
    @State private var clarifyingInbox = false
    @State private var quickOpenPresented = false
    @State private var pendingQuickOpenTarget: QuickOpenTarget?
    @State private var quickOpenedTaskID: TaskID?
    @State private var renamingTask: TaskRecord?
    @State private var quickRenameTitle = ""
    @State private var quickRenameError: String?
    @State private var capturingFirstItem = false
    @FocusState private var addFocused: Bool
    @FocusState private var quickRenameFocused: Bool
    @FocusState private var collectionNameFocused: Bool
    @FocusState private var canvasFocus: CanvasFocus?

    var body: some View {
        reviewSheets(collectionSheets(taskSheets(window)))
            .focusedSceneValue(\.closeTaskDetails, closeTaskDetailsAction)
    }

    private var sheetIsBusy: Bool { model.isSaving || isSubmittingSheet }

    /// Covers model preparation and post-save work as well as the durable write.
    private func performSheetSave(editorID: String, _ operation: @escaping @MainActor (String) async -> Void) {
        guard !sheetIsBusy else { return }
        isSubmittingSheet = true
        Task { @MainActor in
            defer { isSubmittingSheet = false }
            await operation(editorID)
        }
    }

    private var window: some View {
        NavigationSplitView(columnVisibility: $columns) {
            sidebar
                .navigationSplitViewColumnWidth(min: 310, ideal: 340, max: 400)
        } detail: {
            detailCanvas
                .inspector(isPresented: inspectorPresented) {
                    inspectorContent
                        .inspectorColumnWidth(min: inspectorWidth, ideal: inspectorWidth, max: inspectorWidth)
                }
        }
        .toolbar { toolbarContent }
        .searchable(text: $model.searchText, placement: .toolbar, prompt: "Search tasks")
        .onSubmit(of: .search) { requestNavigation(.reload) }
        .onChange(of: model.searchText) { _, value in
            if value.isEmpty { requestNavigation(.reload) }
        }
        .onChange(of: editorDirty) { _, dirty in model.taskEditInProgress = dirty }
        // presentation-region: X-06 focus after archive, unarchive or a failed write
        .onChange(of: model.projectStateChanges) { _, _ in
            if case .project = model.destination { canvasFocus = .title }
        }
        .onChange(of: model.storageFailureMessage) { _, message in
            guard let message else { return }
            canvasFocus = .retry
            AccessibilityNotification.Announcement(message).post()
        }
        .disabled(sheetIsBusy)
        // presentation-region-end
        // X-03 and X-04, attached through the router; "Sign out…" runs the unsaved-edit guard first.
        .routedSignInSheet(sync.router, onDismiss: { sync.closeSignIn() }) { _ in
            if let flow = sync.signIn {
                SignInSheet(flow: flow, router: sync.router, onClose: { sync.closeSignIn() })
            }
        }
        .routedSignOutConfirmation(sync.router, controller: sync)
        .onChange(of: sync.signOutRequests) { _, _ in requestNavigation(.signOut) }
        .onChange(of: selectedTaskID) { _, id in sync.triggers?.setOpenTask(id) }
        .focusedSceneValue(\.workspaceModel, model)
        .focusedSceneValue(\.macSyncController, sync)
        .onAppear(perform: windowAppeared)
        .onDisappear {
            quickCapture.stop()
            saveTaskEditsOnClose()
        }
        // "Saved as you type": nothing pending is left behind when the app goes to the background.
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didResignActiveNotification)) { _ in
            Task { await saveTaskEdits() }
        }
        .task { await model.prepareVisibleQueries() }
        .onChange(of: model.destination) { _, _ in Task { await model.prepareVisibleQueries() } }
        .onChange(of: model.appliedSearch) { _, _ in Task { await model.prepareVisibleQueries() } }
        .onChange(of: model.captureDraft) { _, draft in Task { await model.prepareCapturePreview(draft) } }
        .onChange(of: model.workspace.state) { _, _ in Task { await model.prepareVisibleQueries() } }
    }

    /// The agent-run hooks, kept off `window` so its modifier chain stays within the type checker's budget.
    private var agentAwareCanvas: some View {
        firstRunCanvas
            .task(id: model.workspace.account?.id) { await model.refreshAgents() }
            .task { await model.agentRuns.run() }
            .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in Task { await model.refreshAgents() } }
            .onChange(of: scenePhase) { _, phase in model.agentRuns.isWindowVisible = phase != .background }
            .onChange(of: model.agentAvailability.isOnline) { _, online in model.agentRuns.isOnline = online }
            .onChange(of: model.sidebarCounts) { _, _ in if model.showsAgentsSection { Task { await model.refreshAgentSteps() } } }
            .onChange(of: model.showsAgentsSection) { _, shown in if !shown, model.destination.isAgentRuns { requestNavigation(.destination(.list(.waiting))) } }
    }

    @ViewBuilder
    private var routedCanvas: some View {
        if case .agentRuns(let filter) = model.destination {
            AgentRunsCanvas(model: model, filter: filter, selectedTaskID: selectedTaskID, onSelect: selectRun)
                .onChange(of: selectedTaskID.flatMap { model.task($0) }) { _, task in
                    if let task, taskForm?.taskID != task.id { taskForm = TaskAutosave(task: task) }
                }
        } else {
            taskCanvas
        }
    }

    private func selectRun(_ run: AgentRunItem) {
        if let id = model.stepID(forServerID: run.taskServerID) { requestNavigation(.task(id)) }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        // X-01 "sidebar hidden": in attention states only, the line's words and glyph; nothing
        // about sync in the toolbar otherwise.
        ToolbarItem(placement: .navigation) {
            SyncToolbarStatusItem(controller: sync, sidebarHidden: columns == .detailOnly)
        }
        ToolbarItem(placement: .primaryAction) {
            if model.destination.isAgentRuns, model.canAddAgent {
                Button {
                    model.agentAvailability.requestAddAgent()
                    openSettings()
                } label: {
                    Label { Text(AgentsCopy.addNewAgent) } icon: { MacBoardIconView(icon: .plus, size: 15) }
                }
            }
        }
        ToolbarItemGroup(placement: .primaryAction) {
            Button {
                requestNavigation(.newTask)
            } label: {
                Label("New task", systemImage: "plus")
            }
            .keyboardShortcut("n", modifiers: [.command])
            Button {
                quickOpenPresented = true
            } label: {
                Label("Quick Open", systemImage: "magnifyingglass.circle")
            }
            .keyboardShortcut("o", modifiers: [.command])
            Button {
                quickCapture.show()
            } label: {
                Label("Quick Capture", systemImage: "square.and.pencil")
            }
            .keyboardShortcut("b", modifiers: [.control, .option, .shift])
            .help("Capture to Inbox from anywhere with ⌃⌥⇧B")
            Button {
                voicePresented = true
            } label: {
                Label("Voice to task draft", systemImage: "mic")
            }
        }
    }

    // MARK: Sidebar

    private var sidebar: some View {
        List {
            MacSidebarBrand()
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
                .selectionDisabled()
            ForEach(fixedSidebarSections) { section in
                if section.id == "dates", !firstRun.showsFirstRunSidebar { agentsSection }
                sidebarSection(section)
            }
            if !firstRun.showsFirstRunSidebar {
                projectsSection
                archivedProjectsSection
                tagsSection
            }
        }
        .listStyle(.sidebar)
        .navigationTitle("BrainBuddy")
        .safeAreaInset(edge: .bottom) { footer }
    }

    /// G-01, between Lists and Dates: All runs and the agents of the listed runs (board M22, DSAgents).
    @ViewBuilder
    private var agentsSection: some View {
        if model.showsAgentsSection {
            let runs = model.listedRuns
            let agents = Dictionary(runs.compactMap { run in run.connectionID.map { ($0, run.agentName) } }) { first, _ in first }
            Section {
                sidebarButton(
                    AgentsCopy.allRuns, symbol: "", destination: .agentRuns(.all), trailing: runs.isEmpty ? nil : "\(runs.count)")
                ForEach(agents.sorted { $0.value < $1.value }, id: \.key) { id, name in
                    sidebarButton(name, symbol: "", destination: .agentRuns(.agent(id)), trailing: "\(model.agentRuns.perAgentCounts[id] ?? 0)")
                }
            } header: {
                MacSidebarSectionHeader(title: AgentsCopy.sidebar)
            }
        }
    }

    /// F-04: Lists and Dates only while the first run shows.
    private var fixedSidebarSections: [SidebarSection] {
        let all = SidebarEntries.standard.sections
        return firstRun.showsFirstRunSidebar ? all.filter { $0.header == "Lists" || $0.header == "Dates" } : all
    }

    private var projectsSection: some View {
        Section {
            if model.projectsReadiness == .ready {
            ForEach(model.projects) { project in
                sidebarButton(
                    project.name, symbol: "circle.fill", destination: .project(project.id), tint: projectTint(project.color)
                )
                .contextMenu {
                    Button("Rename…") { beginRename(.project(project.id), name: project.name) }
                    Button("Archive project") { archive(project.id) }
                        .disabled(!model.canArchiveProject)
                        .help("Add or clear the current task draft before archiving")
                }
            }
            catalogPagination(archived: false)
            } else {
                querySidebarStatus(model.projectsReadiness)
            }
        } header: {
            MacSidebarSectionHeader(title: "Projects") {
                Button("Review") { requestNavigation(.reviewProjects) }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Review projects")
                Button {
                    collectionName = ""
                    addingCollection = .project
                } label: {
                    Image(systemName: "plus")
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Add project")
            }
        }
    }

    /// X-06 "sidebar section": "Archived projects · N", collapsible, starts collapsed, its state
    /// remembered in `mac-local.json`; the disclosure is a tab stop.
    @ViewBuilder
    private var archivedProjectsSection: some View {
        let archived = model.archivedProjects
        if model.archivedProjectsReadiness != .ready {
            Section {
                querySidebarStatus(model.archivedProjectsReadiness)
            } header: {
                MacSidebarSectionHeader(title: "Archived projects")
            }
        } else if !archived.isEmpty {
            let expanded = model.localState.sidebar.archivedProjectsExpanded
            Section {
                Button {
                    model.setArchivedProjectsExpanded(!expanded)
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: expanded ? "chevron.down" : "chevron.right")
                            .font(.caption.weight(.semibold))
                            .frame(width: 20)
                            .accessibilityHidden(true)
                        Text("Archived projects")
                            .carryOnFont(CarryOnTypeScale.body)
                        Spacer(minLength: 0)
                    }
                    .foregroundStyle(.coTextSecondary)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .focusable()
                .accessibilityLabel("Archived projects, \(expanded ? "expanded" : "collapsed")")
                if expanded {
                    ForEach(archived) { project in
                        sidebarButton(project.name, symbol: "archivebox", destination: .project(project.id))
                            .accessibilityLabel("\(project.name), archived")
                            .contextMenu {
                                Button("Unarchive project") { unarchive(project.id) }
                                Button("Rename…") { beginRename(.project(project.id), name: project.name) }
                            }
                    }
                    catalogPagination(archived: true)
                }
            }
        }
    }

    private var tagsSection: some View {
        Section {
            if model.tagsReadiness == .ready {
            ForEach(model.tags) { tag in
                Button {
                    requestNavigation(.destination(.tag(tag.id)))
                } label: {
                    Text("#\(tag.name)")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(tagTint(tag.id))
                        .padding(.horizontal, 9)
                        .padding(.vertical, 5)
                        .background(tagTint(tag.id).opacity(0.16), in: Capsule())
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain)
                .listRowBackground(tagRowBackground(tag.id))
                .contextMenu {
                    Button("Rename…") { beginRename(.tag(tag.id), name: tag.name) }
                    Button("Delete tag…", role: .destructive) {
                        tagToDelete = tag
                        confirmingTagDeletion = true
                    }
                    .disabled(editorDirty)
                }
            }
            tagCatalogPagination
            } else {
                querySidebarStatus(model.tagsReadiness)
            }
            Button {
                collectionName = ""
                addingCollection = .tag
            } label: {
                Label("New tag", systemImage: "plus")
                    .font(.caption)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(.quaternary, in: Capsule())
            }
            .buttonStyle(.plain)
        } header: {
            MacSidebarSectionHeader(title: "Tags")
        }
    }

    @ViewBuilder
    private func tagRowBackground(_ id: TagID) -> some View {
        if model.destination == .tag(id) {
            RoundedRectangle(cornerRadius: 7, style: .continuous).fill(.coSidebarRowSelected)
        } else {
            Color.clear
        }
    }

    @ViewBuilder
    private func querySidebarStatus(_ readiness: WorkspaceQueryReadiness) -> some View {
        switch readiness {
        case .ready:
            EmptyView()
        case .notRequested, .loading:
            Label("Loading…", systemImage: "arrow.triangle.2.circlepath")
                .font(.caption)
                .foregroundStyle(.secondary)
        case .failed:
            Button("Retry loading") { Task { await model.prepareVisibleQueries() } }
                .font(.caption)
        }
    }

    @ViewBuilder
    private func catalogPagination(archived: Bool) -> some View {
        let state = archived ? model.archivedProjectsPageState : model.projectsPageState
        if state.hasPrevious || state.hasNext {
            HStack {
                Button("Previous") {
                    Task {
                        await model.workspace.previousProjectsPage(archived: archived)
                        model.refreshQueryPresentation()
                    }
                }
                .disabled(!state.hasPrevious)
                Button("Next") {
                    Task {
                        await model.workspace.nextProjectsPage(archived: archived)
                        model.refreshQueryPresentation()
                    }
                }
                .disabled(!state.hasNext)
            }
            .font(.caption)
        }
    }

    @ViewBuilder
    private var tagCatalogPagination: some View {
        let state = model.tagsPageState
        if state.hasPrevious || state.hasNext {
            HStack {
                Button("Previous") {
                    Task { await model.workspace.previousTagsPage(); model.refreshQueryPresentation() }
                }
                .disabled(!state.hasPrevious)
                Button("Next") {
                    Task { await model.workspace.nextTagsPage(); model.refreshQueryPresentation() }
                }
                .disabled(!state.hasNext)
            }
            .font(.caption)
        }
    }

    /// X-01: the sync status line, the last stops in the sidebar's Tab order.
    private var footer: some View {
        SyncStatusLine(controller: sync)
    }

    @ViewBuilder
    private func sidebarSection(_ section: SidebarSection) -> some View {
        if let header = section.header {
            Section {
                sidebarRows(section.rows)
            } header: {
                MacSidebarSectionHeader(title: header)
            }
        } else {
            Section { sidebarRows(section.rows) }
        }
    }

    private func sidebarRows(_ rows: [SidebarRow]) -> some View {
        ForEach(rows) { row in
            switch row.kind {
            case .destination(let destination):
                sidebarButton(row.title, symbol: row.symbol, destination: destination)
            case .deferred(let note):
                deferredSidebarRow(row, note: note)
            }
        }
    }

    /// A visibly deferred feature (020-FR-041), the iOS `DeferredRow` pattern: shown,
    /// not interactive, and says so in words. No button, no selection, no destination;
    /// VoiceOver reads it as one static text element, "Weekly review, coming later".
    private func deferredSidebarRow(_ row: SidebarRow, note: String) -> some View {
        MacSidebarRowLabel(
            title: row.title, leading: .symbol(row.symbol), trailing: note, selected: false, muted: true
        )
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(row.accessibilityLabel)
        .accessibilityAddTraits(.isStaticText)
        .listRowBackground(Color.clear)
        .selectionDisabled()
    }

    /// A project's colour dot, else the board's own icon for a fixed destination, else the SF Symbol.
    private func leading(symbol: String, destination: WorkspaceDestination, tint: Color?) -> MacSidebarRowLabel.Leading {
        if let tint { return .dot(tint) }
        if let icon = MacBoardIcon(destination: destination) { return .icon(icon) }
        return .symbol(symbol)
    }

    private func sidebarButton(
        _ title: String, symbol: String, destination: WorkspaceDestination, tint: Color? = nil, trailing: String? = nil
    ) -> some View {
        let count: Int? = {
            guard case .list(let list) = destination, !firstRun.showsFirstRunSidebar else { return nil }
            guard model.countsReadiness == .ready else { return nil }
            // Waiting for counts its people and its listed agent runs: n + m (030-FR-009).
            return model.sidebarCounts.count(for: list) + (list == .waiting ? model.listedRuns.count : 0)
        }()
        return Button {
            requestNavigation(.destination(destination))
        } label: {
            MacSidebarRowLabel(
                title: title, leading: leading(symbol: symbol, destination: destination, tint: tint),
                trailing: count.map { "\($0)" } ?? trailing, selected: model.destination == destination
            )
        }
        .accessibilityLabel(count.map { "\(title), \($0) open tasks" } ?? title)
        .buttonStyle(.plain)
        .listRowBackground(Color.clear)
    }

    // MARK: Projects

    private func beginRename(_ kind: CollectionToEdit, name: String, fromRefusal: Bool = false) {
        model.error = nil
        collectionEditorID = UUID().uuidString
        editedCollectionName = name
        renamingFromRefusal = fromRefusal
        editingCollection = kind
    }

    private func archive(_ id: ProjectID) {
        Task { if await model.archiveProject(id), model.destination != .project(id) { selectedTaskID = nil } }
    }

    private func unarchive(_ id: ProjectID) {
        Task { _ = await model.unarchiveProject(id) }
    }

    fileprivate func createCollection(_ kind: NewCollection) {
        let name = collectionName
        performSheetSave(editorID: collectionCreateEditorID) { submittedEditorID in
            switch kind {
            case .project:
                if let id = await model.createProject(name, editorID: submittedEditorID) {
                    collectionCreateEditorID = UUID().uuidString
                    addingCollection = nil
                    collectionName = ""
                    requestNavigation(.destination(.project(id)))
                }
            case .tag:
                if let id = await model.createTag(name, editorID: submittedEditorID) {
                    collectionCreateEditorID = UUID().uuidString
                    addingCollection = nil
                    collectionName = ""
                    requestNavigation(.destination(.tag(id)))
                }
            }
        }
    }

    fileprivate static func isSignOut(_ navigation: PendingEditorNavigation) -> Bool {
        if case .signOut = navigation { return true }
        return false
    }

    // presentation-region: rename sheet focus
    fileprivate func renameCollection(_ kind: CollectionToEdit) {
        let name = editedCollectionName
        performSheetSave(editorID: collectionEditorID) { submittedEditorID in
            let saved: Bool
            switch kind {
            case .project(let id): saved = await model.renameProject(id, to: name, editorID: submittedEditorID)
            case .tag(let id): saved = await model.renameTag(id, to: name, editorID: submittedEditorID)
            }
            guard saved else { collectionNameFocused = true; return }
            collectionEditorID = UUID().uuidString
            editingCollection = nil
            if renamingFromRefusal {
                renamingFromRefusal = false
                canvasFocus = .unarchive
            }
        }
    }
    // presentation-region-end

    // MARK: Navigation

    /// The one way the window changes what it shows or does to a task. The open task's pending field
    /// edits save first ("Saved as you type"); only what cannot save — fields that are not valid or a
    /// save that failed, a subtask or comment not added yet, the capture draft — asks first.
    private func requestNavigation(_ next: PendingEditorNavigation) {
        guard selectedTaskID != nil, taskForm?.isDirty == true || autosaveRun != nil else {
            confirmOrApply(next)
            return
        }
        Task {
            if await saveTaskEdits() {
                confirmOrApply(next)
            } else {
                pendingEditorNavigation = next
                confirmingDiscard = true
            }
        }
    }

    private func confirmOrApply(_ next: PendingEditorNavigation) {
        let hasUnaddedExtras = selectedTaskID != nil && extrasDirty
        let hasCaptureDraft = !model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !model.waitingForDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if hasUnaddedExtras || (hasCaptureDraft && changesCaptureContext(next)) {
            pendingEditorNavigation = next
            confirmingDiscard = true
        } else {
            applyNavigation(next)
        }
    }

    /// The open task has unsaved fields or a subtask or comment not added yet.
    private var editorDirty: Bool { (taskForm?.isDirty ?? false) || extrasDirty }

    // MARK: Saved as you type

    /// Saves the open task's pending field edits now, with `moveTo` as one change when given (the
    /// list picker), through `saveTask` and the window's undo. Waits for a save in flight first.
    /// True when nothing is left unsaved.
    @discardableResult
    private func saveTaskEdits(moveTo list: TaskList? = nil) async -> Bool {
        while let running = autosaveRun { _ = await running.value }
        autosaveTimer?.cancel()
        guard var form = taskForm else { return true }
        guard let request = form.beginSave(moveTo: list, at: Date()) else { return !form.isDirty }
        taskForm = form
        let id = form.taskID
        let before = model.task(id)
        let editorID = taskSaveEditorID
        // The bookkeeping runs inside the task, so whoever awaits it sees the form settled.
        let run = Task { @MainActor () -> Bool in
            let saved = await model.saveTask(id, changes: request.changes, moveTo: request.moveTo, editorID: editorID)
            if saved {
                // A list change is undoable like a row move; field edits keep their own typing undo.
                registerUndo(before)
                taskSaveEditorID = UUID().uuidString
            }
            autosaveRun = nil
            if taskForm?.taskID == id {
                taskForm?.finishSave(succeeded: saved, current: model.task(id))
                // Typed while the save ran: those edits wait for their own pause.
                scheduleAutosave()
            }
            return saved
        }
        autosaveRun = run
        return await run.value
    }

    /// Restarts the debounce after an edit: the fields save once the person pauses.
    private func scheduleAutosave(after delay: TimeInterval? = nil) {
        autosaveTimer?.cancel()
        guard let deadline = taskForm?.deadline else { return }
        let wait = delay ?? max(0, deadline.timeIntervalSinceNow)
        autosaveTimer = Task { @MainActor in
            try? await Task.sleep(for: .seconds(wait))
            guard !Task.isCancelled else { return }
            autosaveTick()
        }
    }

    private func autosaveTick() {
        guard let form = taskForm, form.isDue(at: Date()) else { return }
        // Another write (a subtask, a sheet) holds the store: try again shortly.
        if autosaveRun == nil, model.isSaving || isSubmittingSheet {
            scheduleAutosave(after: 0.3)
            return
        }
        Task { await saveTaskEdits() }
    }

    /// One edit in the inspector: into the draft, then the debounce.
    private func editTaskForm<Value: Equatable>(_ field: WritableKeyPath<TaskEditDraft, Value>, _ value: Value) {
        guard taskForm != nil else { return }
        taskForm?.set(field, to: value, at: Date())
        scheduleAutosave()
    }

    private func formBinding<Value: Equatable>(_ field: WritableKeyPath<TaskEditDraft, Value>, _ fallback: Value) -> Binding<Value> {
        Binding(get: { taskForm?.draft[keyPath: field] ?? fallback }, set: { editTaskForm(field, $0) })
    }

    /// An optional text field shown as a plain one: empty is none.
    private func formTextBinding(_ field: WritableKeyPath<TaskEditDraft, String?>) -> Binding<String> {
        Binding(get: { taskForm?.draft[keyPath: field] ?? "" }, set: { editTaskForm(field, $0.isEmpty ? nil : $0) })
    }

    /// The window is closing: send what is pending without waiting on the view, which is going away.
    private func saveTaskEditsOnClose() {
        autosaveTimer?.cancel()
        guard var form = taskForm else { return }
        // A save in flight is sent again with the rest; the same values are harmless to repeat.
        if form.isSaving { form.finishSave(succeeded: false, current: nil) }
        guard let request = form.beginSave(at: Date()) else { return }
        let running = autosaveRun
        let id = form.taskID
        let editorID = taskSaveEditorID
        let model = self.model
        Task { @MainActor in
            if let running { _ = await running.value }
            _ = await model.saveTask(id, changes: request.changes, moveTo: request.moveTo, editorID: editorID)
        }
    }

    /// The list picker: a move other than Waiting saves at once with the pending fields; Waiting
    /// asks who first (the move sheet).
    private func changeList(_ task: TaskRecord, to list: TaskList) {
        guard list.taskState != task.state else { return }
        if list == .waiting {
            requestNavigation(.move(task.id, .waiting))
            return
        }
        Task {
            guard await saveTaskEdits(moveTo: list), model.task(task.id)?.state == list.taskState else { return }
            select(nil)
            release(task.id)
        }
    }

    fileprivate func changesCaptureContext(_ next: PendingEditorNavigation) -> Bool {
        switch next {
        case .destination(let destination): destination != model.destination
        case .quickOpen, .signOut: true
        case .newTask: isDateDestination || model.destination.isHistory || model.isArchivedProjectDestination
        default: false
        }
    }

    /// View › "Close task details" (⌘\) while a task is open; pending edits save first, as when choosing another task.
    private var closeTaskDetailsAction: CloseTaskDetailsAction? {
        guard selectedTaskID != nil else { return nil }
        return CloseTaskDetailsAction(close: { requestNavigation(.task(nil)) })
    }

    /// Puts the list change `before` → now on the window's undo stack (Edit › Undo, ⌘Z).
    private func registerUndo(_ before: TaskRecord?) {
        guard let before, let change = TaskListChange(before: before, after: model.task(before.id)), let undoManager else {
            return
        }
        undoManager.registerUndo(withTarget: model) { model in
            Task { await model.undo(change) }
        }
        undoManager.setActionName(change.actionName)
    }

    private func select(_ id: TaskID?) {
        autosaveTimer?.cancel()
        taskSaveEditorID = UUID().uuidString
        selectedTaskID = id
        taskForm = id.flatMap { model.task($0) }.map { TaskAutosave(task: $0) }
        selectionAnchor = id.map { SelectionAnchor(id: $0, in: visibleTaskIDs) }
        extrasDirty = false
        inspectorFocus = nil
    }

    fileprivate func applyNavigation(_ navigation: PendingEditorNavigation) {
        pendingEditorNavigation = nil
        if case .signOut = navigation {
            // X-04 now; the editor and the drafts stay as they are until the sign-out happens, so a
            // Cancel in X-04 loses nothing (`BrainBuddyModel.didSignOut` clears them after).
            sync.presentSignOut()
            return
        }
        switch navigation {
        case .destination(let destination):
            select(nil)
            quickOpenedTaskID = nil
            model.choose(destination)
        case .quickOpen(let target):
            select(nil)
            quickOpenedTaskID = nil
            openQuickOpenTarget(target)
        case .task(let id):
            if id != quickOpenedTaskID { quickOpenedTaskID = nil }
            select(id)
            if let id { Task { await model.loadTaskDetail(id) } }
        case .complete(let id):
            let before = model.task(id)
            Task {
                if await model.completeTask(id) {
                    registerUndo(before)
                    select(nil)
                    release(id)
                }
            }
        case .move(let id, let destination):
            if destination == .waiting {
                select(nil)
                release(id)
                model.error = nil
                moveWaitingEditorID = UUID().uuidString
                moveWaitingFor = ""
                movingTask = model.task(id)
            } else {
                let before = model.task(id)
                Task {
                    if await model.moveTask(id, to: destination) {
                        registerUndo(before)
                        select(nil)
                        release(id)
                    }
                }
            }
        case .reopen(let id):
            select(nil)
            release(id)
            model.error = nil
            reopenEditorID = UUID().uuidString
            reopenDestination = .next
            reopenWaitingFor = ""
            reopeningTask = model.task(id)
        case .cancel(let id):
            let before = model.task(id)
            Task {
                if await model.cancelTask(id) {
                    registerUndo(before)
                    select(nil)
                    release(id)
                }
            }
        case .newTask:
            select(nil)
            // presentation-region: new task focus
            if model.isArchivedProjectDestination {
                model.choose(.list(.next))
                addFocused = true
            } else if isDateDestination || model.destination.isHistory {
                addFocused = false
                captureListChoice = .next
                choosingCaptureList = true
            } else {
                addFocused = true
            }
            // presentation-region-end
        case .reload:
            select(nil)
            model.reload()
        case .clearTaskFilters:
            select(nil)
            model.clearTaskFilters()
        case .createTask:
            select(nil)
            Task { await model.createTask() }
        case .reviewWaiting:
            select(nil)
            reviewingWaiting = true
        case .reviewSomeday:
            select(nil)
            reviewingSomeday = true
        case .reviewProjects:
            select(nil)
            reviewingProjects = true
        case .clarifyInbox:
            select(nil)
            clarifyProjectStart = nil
            clarifyingInbox = true
        case .clarifyAsProject(let id):
            select(nil)
            release(id)
            clarifyProjectStart = id
            clarifyingInbox = true
        case .groupByProject(let value):
            select(nil)
            model.groupByProject = value
        case .showCancelled(let value):
            select(nil)
            model.showCancelled = value
        case .sort(let value):
            select(nil)
            model.sort = value
        case .signOut:
            break
        }
    }

    /// A change the person makes to a row lets that row go to its new place at once: the hold is
    /// for changes that arrive from elsewhere while the pointer rests on it (FR-009).
    private func release(_ id: TaskID) {
        if hoveredTaskID == id { hoveredTaskID = nil }
    }

    private func openQuickOpenTarget(_ target: QuickOpenTarget) {
        model.searchText = ""
        model.reload()
        switch target {
        case .list(let list): model.choose(.list(list))
        case .history(let state): model.choose(.history(state))
        case .project(let id): model.choose(.project(id))
        case .tag(let id): model.choose(.tag(id))
        case .task(let id):
            guard let task = model.task(id) else {
                model.error = GTDValidationError.taskNotFound.message
                return
            }
            model.choose(model.destination(showing: task))
            quickOpenedTaskID = id
            applyNavigation(.task(id))
        }
    }

    // MARK: The list

    private var isDateDestination: Bool {
        if case .date = model.destination { return true }
        return false
    }

    private var visibleTaskIDs: [TaskID] { model.tasks.map(\.id) }

    /// The kit's sections with the hovered row, or else the row being edited, held where it was
    /// (FR-009); the row being edited is also the selection anchor.
    private func presentedSections(_ sections: [TaskSection]) -> [PresentedSection] {
        let held = hoveredTaskID ?? selectedTaskID
        let sectionIDs = Set(sections.map(\.id))
        let home = held.flatMap { held in shownOrders.first { sectionIDs.contains($0.key) && $0.value.contains(held) }?.key }
        return sections.map { section in
            var incoming = section.tasks.map(\.id)
            if let held, let home, home != section.id { incoming.removeAll { $0 == held } }
            let order = section.id == home
                ? ListPresentationHold.order(onScreen: shownOrders[section.id] ?? [], incoming: incoming, held: held)
                : incoming
            let byID = Dictionary(section.tasks.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
            let rows = order.compactMap { byID[$0] ?? model.task($0) }
            let departed = Set(order.filter { byID[$0] == nil })
            return PresentedSection(id: section.id, title: sectionTitle(section), kind: section.kind, rows: rows, departed: departed)
        }
    }

    private func sectionTitle(_ section: TaskSection) -> String? {
        if case .project(let id?) = section.kind { return model.projectLabel(id) }
        return section.title
    }

    private var firstRun: FirstRunModel { model.firstRun }

    /// F-03 stands in for the list only on Next actions; any other list the person opens shows as usual.
    private var showsLanding: Bool { firstRun.phase == .landing && model.destination == .list(.next) }

    private func windowAppeared() {
        quickCapture.start(model: model)
        firstRun.hotkeyAvailable = quickCapture.hotkeyRegistered
        firstRun.speechAvailable = VoiceTranscriber.bundledModel() != nil
    }

    /// The detail column with the first-run hooks; they live here, not on `window`, so that
    /// modifier chain stays within the type checker's budget.
    private var detailCanvas: some View {
        agentAwareCanvas
            // 029-FR-013: an account linked at any step ends the first run.
            .onChange(of: model.workspace.account != nil) { _, linked in
                if linked { firstRun.accountLinked() }
            }
            .onChange(of: firstRun.phase) { _, phase in firstRunPhaseChanged(phase) }
    }

    /// F-01 replaces the empty Inbox; every other phase uses the list with F-02/F-03 around it.
    @ViewBuilder
    private var firstRunCanvas: some View {
        if firstRun.phase == .welcome {
            WelcomeInboxView(
                text: $model.draft, hotkeyAvailable: firstRun.hotkeyAvailable, speechAvailable: firstRun.speechAvailable,
                errorText: model.error, onSubmit: submitFirstCapture, onSkip: { firstRun.skip() },
                onMic: { voicePresented = true }
            )
            .frame(minWidth: 560, minHeight: 480)
            .background(.coBgGround)
        } else {
            routedCanvas
        }
    }

    /// F-01.03: Return adds one Inbox item with exactly the typed text; the draft clears only then.
    private func submitFirstCapture() {
        guard !capturingFirstItem else { return }
        capturingFirstItem = true
        let written = model.draft
        Task {
            defer { capturingFirstItem = false }
            if await firstRun.capture(written, using: model) { model.draft = "" }
        }
    }

    private func firstRunPhaseChanged(_ phase: FirstRunPhase) {
        switch phase {
        case .firstStep(let id):
            model.choose(.list(.inbox))
            select(id)
        case .landing:
            model.choose(.list(.next))
            select(nil)
        case .undecided, .welcome, .done:
            break
        }
    }

    /// F-03: the card and the tip stand in for the list's one row.
    @ViewBuilder
    private var landing: some View {
        if showsLanding {
            let step = model.tasks.first { $0.state == .next }
            LandingTip(
                step: step?.title, tip: firstRun.landingTip,
                onOpenStep: { if let step { requestNavigation(.task(step.id)) } },
                onDismiss: { firstRun.dismissTip() }
            )
            .padding(.horizontal, 28)
            .padding(.bottom, 16)
        }
    }

    private var taskCanvas: some View {
        let sections = showsLanding ? [] : presentedSections(model.sections)
        let orders = Dictionary(sections.map { ($0.id, $0.rows.map(\.id)) }, uniquingKeysWith: { first, _ in first })
        let onScreen = sections.flatMap { $0.rows.map(\.id) }
        return VStack(alignment: .leading, spacing: 0) {
            canvasHeader
            canvasMessages
            landing
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        canvasRows(sections, onScreen: onScreen)
                    }
                    .frame(maxWidth: 860)
                    .frame(maxWidth: .infinity)
                    .padding(.horizontal, 28)
                    .padding(.bottom, 28)
                }
                .onChange(of: scrollTarget) { _, target in
                    guard let target else { return }
                    proxy.scrollTo(target, anchor: .center)
                    scrollTarget = nil
                }
            }
            .overlay {
                if model.visibleReadiness != .ready {
                    queryState(model.visibleReadiness) { Task { await model.prepareVisibleQueries() } }
                } else {
                    emptyState(isEmpty: onScreen.isEmpty)
                }
            }
            if model.listPageState.hasPrevious || model.listPageState.hasNext {
                HStack {
                    Button("Previous page") {
                        Task {
                            await model.workspace.previousListPage(model.destination.query, options: model.visibleListOptions)
                            model.refreshQueryPresentation()
                        }
                    }
                    .buttonStyle(.carryOnSecondary)
                    .disabled(!model.listPageState.hasPrevious)
                    Text("More results").macRowMeta()
                    Button("Next page") {
                        Task {
                            await model.workspace.nextListPage(model.destination.query, options: model.visibleListOptions)
                            model.refreshQueryPresentation()
                        }
                    }
                    .buttonStyle(.carryOnSecondary)
                    .disabled(!model.listPageState.hasNext)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
            }
        }
        .frame(minWidth: 560, minHeight: 480)
        .background(.coBgGround)
        .onChange(of: orders, initial: true) { _, new in shownOrders = new }
        .onChange(of: onScreen) { _, ids in keepSelection(in: ids) }
        .onChange(of: selectedTaskID.flatMap { model.task($0) }) { _, task in
            guard let task else { return }
            if taskForm?.taskID == task.id {
                // A change from elsewhere (or this Mac's own save): never over the field being typed in.
                taskForm?.rebase(onto: task, typingIn: inspectorFocus)
            } else {
                taskForm = TaskAutosave(task: task)
            }
        }
    }

    // MARK: The inspector

    /// Open while a task is selected; closing it (⌘\, Esc, the column) is choosing no task.
    private var inspectorPresented: Binding<Bool> {
        Binding(
            get: { selectedTaskID != nil },
            set: { shown in if !shown { requestNavigation(.task(nil)) } }
        )
    }

    private var inspectorWidth: CGFloat {
        TaskInspector.width(for: selectedTaskID.flatMap { model.task($0) }?.state ?? .next)
    }

    @ViewBuilder
    private var inspectorContent: some View {
        if case .firstStep(let id) = firstRun.phase, let task = model.task(id) {
            FirstStepInspector(firstRun: firstRun, writer: model, original: task.title)
                .id(id)
        } else if let id = selectedTaskID, let task = model.task(id) {
            TaskInspector(
                task: task, model: model,
                title: formBinding(\.title, task.title),
                details: formTextBinding(\.details),
                waitingFor: formTextBinding(\.waitingFor),
                projectID: formBinding(\.projectID, task.projectID),
                tagIDs: formBinding(\.tagIDs, task.tagIDs),
                dueDate: formBinding(\.dueDate, task.dueDate),
                problem: taskForm?.isDirty == true ? taskForm?.problem : nil,
                editorDirty: editorDirty,
                inboxPosition: inboxPosition(of: task),
                nextInboxID: nextInboxID(after: task),
                onCommand: { inspectorCommand($0, task: task) },
                onFocusChange: { inspectorFocus = $0 },
                onExtrasDirtyChange: { extrasDirty = $0 }
            )
            .id(task.id)
        } else {
            MacInspectorPanel {
                MacInspectorEmpty(text: "Select something to sort it.")
            }
        }
    }

    /// The Inbox items on screen, in order.
    private var inboxIDsOnScreen: [TaskID] { model.tasks.filter { $0.state == .inbox }.map(\.id) }

    private func inboxPosition(of task: TaskRecord) -> (position: Int, total: Int)? {
        let inbox = inboxIDsOnScreen
        guard task.state == .inbox, let index = inbox.firstIndex(of: task.id) else { return nil }
        return (index + 1, inbox.count)
    }

    private func nextInboxID(after task: TaskRecord) -> TaskID? {
        let inbox = inboxIDsOnScreen
        guard task.state == .inbox, let index = inbox.firstIndex(of: task.id), index + 1 < inbox.count else { return nil }
        return inbox[index + 1]
    }

    /// Every inspector action that changes a task goes through `requestNavigation`, so the pending
    /// fields save first.
    private func inspectorCommand(_ command: TaskInspectorCommand, task: TaskRecord) {
        switch command {
        case .complete: requestNavigation(.complete(task.id))
        case .cancel: requestNavigation(.cancel(task.id))
        case .reopen: requestNavigation(.reopen(task.id))
        case .move(let list): requestNavigation(.move(task.id, list))
        case .changeList(let list): changeList(task, to: list)
        case .clarifyAsProject: requestNavigation(.clarifyAsProject(task.id))
        case .select(let id): requestNavigation(.task(id))
        case .save: Task { await saveTaskEdits() }
        case .close: requestNavigation(.task(nil))
        }
    }

    @ViewBuilder
    private func queryState(_ readiness: WorkspaceQueryReadiness, retry: @escaping () -> Void) -> some View {
        switch readiness {
        case .ready:
            EmptyView()
        case .notRequested, .loading:
            ProgressView("Loading tasks…")
        case .failed:
            ContentUnavailableView {
                Label("Tasks couldn’t load", systemImage: "exclamationmark.triangle")
            } description: {
                Text("Try loading this list again.")
            } actions: {
                Button("Retry", action: retry)
            }
        }
    }

    /// The selection survives a change from elsewhere: a deleted task's editor closes and the list
    /// scrolls to the row nearest to where it was (`SelectionAnchor`).
    private func keepSelection(in ids: [TaskID]) {
        guard let selected = selectedTaskID, !ids.contains(selected), model.task(selected) == nil else { return }
        let neighbour = selectionAnchor?.resolved(in: ids)
        select(nil)
        scrollTarget = neighbour
    }

    @ViewBuilder
    private func canvasRows(_ sections: [PresentedSection], onScreen: [TaskID]) -> some View {
        // The project's one next step is the one the app already names ("First Next action").
        let overview: ProjectOverview? = {
            if case .project(let id) = model.destination { return model.projectOverview(id) }
            return nil
        }()
        let currentStepID = overview?.nextAction?.id
        if let overview {
            projectOverviewCard(overview)
                .padding(.bottom, 16)
        }
        if model.destination == .list(.waiting), !model.listedRuns.isEmpty {
            // G-03: runs above the list's own rows, which become the People group; no step moves.
            sectionHeader(AgentsCopy.waitingAgents, top: 0)
            ForEach(model.listedRuns) { run in
                AgentRunRow(
                    item: run, style: .waiting, now: Date(),
                    selected: selectedTaskID != nil && selectedTaskID == model.stepID(forServerID: run.taskServerID),
                    onSelect: { selectRun(run) })
            }
            sectionHeader(AgentsCopy.waitingPeople, top: 14)
        }
        if let pinned = quickOpenedTaskID, selectedTaskID == pinned, !onScreen.contains(pinned), let task = model.task(pinned) {
            sectionHeader("Opened from Quick Open", top: 0)
            taskCard(task)
        }
        ForEach(sections.filter { !$0.isTerminal }) { section in
            if let title = section.title {
                sectionHeader(title, top: 8)
            }
            ForEach(section.rows) { task in
                taskCard(
                    task, departed: section.departed.contains(task.id), inProjectGroup: isProjectGroup(section.kind),
                    currentStepID: currentStepID)
            }
        }
        if !isDateDestination && !model.destination.isHistory && !model.isArchivedProjectDestination {
            smartAdd
                .padding(.top, 12)
        }
        ForEach(sections.filter(\.isTerminal)) { section in
            if let title = section.title {
                sectionHeader(title, top: 16)
            }
            ForEach(section.rows) { task in
                taskCard(task, departed: section.departed.contains(task.id))
            }
        }
    }

    private func isProjectGroup(_ kind: TaskSection.Kind) -> Bool {
        if case .project = kind { return true }
        return false
    }

    private func sectionHeader(_ title: String, top: CGFloat) -> some View {
        MacListSectionHeader(title: title, top: top)
    }

    @ViewBuilder
    private func emptyState(isEmpty: Bool) -> some View {
        if isEmpty {
            if sync.tasksStillArriving, !model.hasAppliedTaskFilter {
                // X-01 "first load, empty list": one static neutral line, no spinner over content.
                Text(SyncCopy.popoverFirstLoadEmpty)
                    .font(MacRowFont.title)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            } else if model.isArchivedProjectDestination || isPreLosslessProject {
                if model.hasAppliedTaskFilter {
                    filteredEmptyState
                } else if model.isArchivedProjectDestination {
                    MacEmptyState(
                        title: "No tasks in this project", systemImage: "archivebox",
                        description: "Unarchive this project to add tasks to it.")
                }
            } else if model.hasAppliedTaskFilter, case .project = model.destination {
                filteredEmptyState
            } else if isDateDestination || model.destination.isHistory {
                MacEmptyState(title: model.destination.isHistory ? "No history" : "No tasks", systemImage: "checkmark.circle")
            }
        }
    }

    private var filteredEmptyState: some View {
        MacEmptyState(
            title: "No matching tasks", systemImage: "magnifyingglass",
            description: "Clear the search to see this project's tasks.")
    }

    private var isPreLosslessProject: Bool {
        guard case .project(let id) = model.destination else { return false }
        return model.projectDisplay(id)?.showsPreLosslessLine ?? false
    }

    // MARK: Header

    private var canvasHeader: some View {
        VStack(alignment: .leading, spacing: 12) {
            titleRow
            if let refusal = model.unarchiveRefusal, model.destination == .project(refusal.projectID) {
                HStack(spacing: 10) {
                    Text(refusal.message)
                        .foregroundStyle(.coTextSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Button("Rename…") {
                        beginRename(
                            .project(refusal.projectID), name: model.project(refusal.projectID)?.name ?? "", fromRefusal: true
                        )
                    }
                }
                .carryOnFont(CarryOnTypeScale.meta)
            }
            if model.isArchivedProjectDestination {
                Text("Unarchive this project to add tasks to it.")
                    .foregroundStyle(.coTextSecondary)
                    .carryOnFont(CarryOnTypeScale.meta)
            }
            if !firstRun.showsFirstRunSidebar { listControls }
        }
        .padding(.horizontal, 28)
        .padding(.top, 28)
        .padding(.bottom, 20)
    }

    private var titleRow: some View {
        MacListHeaderTitle(title: destinationTitle, caption: taskCountCaption) {
            if case .project(let id) = model.destination, model.isArchived(id) {
                Label("Archived", systemImage: "archivebox")
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(.quaternary, in: Capsule())
                Button("Unarchive") { unarchive(id) }
                    .focused($canvasFocus, equals: .unarchive)
                    .accessibilityLabel("Unarchive \(model.project(id)?.name ?? "project")")
            }
        } titleView: { title in
            title
                .focusable()
                .focused($canvasFocus, equals: .title)
                .accessibilityAddTraits(.isHeader)
        }
    }

    private var listControls: some View {
        HStack(spacing: 16) {
            if model.destination == .list(.inbox) {
                Button("Clarify Inbox") { requestNavigation(.clarifyInbox) }
                    .buttonStyle(.carryOnSecondary)
            }
            if model.destination == .list(.waiting) {
                Button("Review Waiting for") { requestNavigation(.reviewWaiting) }
                    .buttonStyle(.carryOnSecondary)
            }
            if model.destination == .list(.someday) {
                Button("Review Someday") { requestNavigation(.reviewSomeday) }
                    .buttonStyle(.carryOnSecondary)
            }
            if model.destination == .list(.next) {
                Toggle(
                    "Group by project",
                    isOn: Binding(get: { model.groupByProject }, set: { requestNavigation(.groupByProject($0)) })
                )
                .fixedSize()
            }
            if !model.destination.isHistory {
                Toggle(
                    "Show cancelled",
                    isOn: Binding(get: { model.showCancelled }, set: { requestNavigation(.showCancelled($0)) })
                )
                .fixedSize()
            }
            Picker("Sort", selection: Binding(get: { model.sort }, set: { requestNavigation(.sort($0)) })) {
                ForEach(TaskSort.allCases, id: \.self) { value in
                    Text(value.title).tag(value)
                }
            }
            .frame(maxWidth: 170)
        }
        .font(.subheadline)
    }

    @ViewBuilder
    private var canvasMessages: some View {
        if let message = model.storageFailureMessage {
            HStack {
                Text(message).foregroundStyle(.red)
                Spacer()
                Button("Retry") { Task { await model.retrySaving() } }
                    .focused($canvasFocus, equals: .retry)
            }
            .padding(.horizontal, 28)
            .padding(.bottom, 12)
        }
        if let error = model.error, editingCollection == nil {
            HStack {
                Text(error).foregroundStyle(.red)
                Spacer()
                Button {
                    model.error = nil
                } label: {
                    Image(systemName: "xmark.circle")
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Dismiss message")
            }
            .padding(.horizontal, 28)
            .padding(.bottom, 12)
        }
        if let error = quickCapture.registrationError {
            Label(error, systemImage: "keyboard.badge.exclamationmark")
                .font(.caption)
                .foregroundStyle(.orange)
                .padding(.horizontal, 28)
                .padding(.bottom, 12)
        }
    }

    private var destinationTitle: String {
        switch model.destination {
        case .list(let list): list.title
        case .date(let date): date.title
        case .project(let id): model.project(id)?.name ?? "Project"
        case .tag(let id): "#" + (model.tag(id)?.name ?? "Tag")
        case .history(let state): state.title
        case .agentRuns: AgentsCopy.allRuns
        }
    }

    private var taskCountCaption: String {
        switch firstRun.phase {
        case .firstStep where model.destination == .list(.inbox): return FirstRunCopy.listHeader
        case .landing where showsLanding:
            return FirstRunCopy.landingHeader.replacingOccurrences(of: "\(destinationTitle) · ", with: "")
        case .undecided, .welcome, .firstStep, .landing, .done: break
        }
        if model.destination.isHistory { return Self.plural(model.listResult?.totalCount ?? 0, "task") }
        if model.destination == .list(.waiting), !model.listedRuns.isEmpty {
            return AgentsCopy.waitingHeader(people: model.openTaskCount, agents: model.listedRuns.count)
        }
        let open = Self.plural(model.openTaskCount, "open task")
        return model.isArchivedProjectDestination ? "Archived project · \(open)" : open
    }

    // MARK: Project overview

    private func projectOverviewCard(_ overview: ProjectOverview) -> some View {
        let project = overview.project
        let archived = overview.display.isArchived
        return VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("PROJECT OUTCOME")
                    .font(MacRowFont.sectionHeader)
                    .tracking(1.5)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                Spacer()
                if !archived {
                    Button(project.desiredOutcome == nil ? "Set outcome" : "Edit outcome") {
                        model.error = nil
                        outcomeDraft = project.desiredOutcome ?? ""
                        projectOutcomeEditorID = UUID().uuidString
                        editingOutcomeProject = project
                    }
                }
            }
            if let outcome = project.desiredOutcome, !outcome.isEmpty {
                Text(outcome)
                    .font(MacRowFont.titleStrong)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Text(archived ? "No desired outcome." : "Define what will be true when this project is done.")
                    .font(MacRowFont.title)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
            Divider()
            if let next = overview.nextAction {
                Label("First Next action", systemImage: "arrow.right.circle")
                    .font(MacRowFont.sectionHeader)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                Text(next.title)
                    .font(MacRowFont.title)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Text(projectNextExplanation(overview))
                    .font(MacRowFont.title)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            }
            if overview.display.showsPreLosslessLine {
                // FR-027: one neutral line; nothing says tasks were lost.
                Text("Archived before projects kept their tasks, so none are listed here. Those tasks are still in their lists.")
                    .font(MacRowFont.title)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(CarryOnColorStyle.coSurfaceCard, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private func projectNextExplanation(_ overview: ProjectOverview) -> String {
        let counts = overview.openCounts
        if (counts[.inbox] ?? 0) > 0 { return "No Next action yet · clarify an Inbox item in this project." }
        if (counts[.waiting] ?? 0) > 0 { return "No Next action yet · this project is waiting on a dependency." }
        if (counts[.someday] ?? 0) > 0 { return "No Next action yet · its open work is in Someday." }
        return "No open actions · review whether this project is complete."
    }

    // MARK: Task rows

    private func beginQuickRename(_ task: TaskRecord) {
        guard selectedTaskID == nil else { return }
        quickRenameTitle = task.title
        quickRenameError = nil
        model.error = nil
        quickRenameEditorID = UUID().uuidString
        renamingTask = task
    }

    fileprivate func saveQuickRename(_ task: TaskRecord) {
        guard !sheetIsBusy else { return }
        let title = quickRenameTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty, EditorLimits.fits(title, EditorLimits.title) else { return }
        guard let current = model.task(task.id) else {
            quickRenameError = GTDValidationError.taskNotFound.message
            return
        }
        if title == current.title {
            renamingTask = nil
            return
        }
        performSheetSave(editorID: quickRenameEditorID) { submittedEditorID in
            if await model.saveTask(task.id, changes: TaskChanges(title: .set(title)), editorID: submittedEditorID) {
                quickRenameEditorID = UUID().uuidString
                renamingTask = nil
                quickRenameError = nil
            } else {
                quickRenameError = model.error ?? "The task title could not be saved. Try again."
            }
        }
    }

    private func taskCard(
        _ task: TaskRecord, departed: Bool = false, inProjectGroup: Bool = false, currentStepID: TaskID? = nil
    ) -> some View {
        let selected = selectedTaskID == task.id
        return taskRowLine(task, selected: selected, showsProject: !inProjectGroup, isCurrent: currentStepID == task.id)
            .macRowSurface(selected: selected)
            .opacity(departed && !selected ? 0.55 : 1)
            .onHover { inside in
                if inside {
                    hoveredTaskID = task.id
                } else if hoveredTaskID == task.id {
                    hoveredTaskID = nil
                }
            }
            .id(task.id)
    }

    /// A row in the Carry On style: the mark, the title, then the trailing meta. The Inbox and Someday
    /// have no mark, so their complete control is the same open circle, shown at the end of the row
    /// while the pointer is over it or it is selected.
    @ViewBuilder
    private func taskRowLine(_ task: TaskRecord, selected: Bool, showsProject: Bool, isCurrent: Bool) -> some View {
        let kind = MacRowKind(state: task.state, isCurrent: isCurrent)
        MacTaskRowShell {
            if task.state.isTerminal {
                MacRowMark(kind: kind)
            } else if kind.hasMark {
                Button {
                    requestNavigation(.complete(task.id))
                } label: {
                    MacRowMark(kind: kind)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Complete \(task.title)")
            }
        } title: {
            if task.state.isTerminal {
                Button {
                    requestNavigation(.task(selected ? nil : task.id))
                } label: {
                    MacRowTitleText(title: task.title, kind: kind, selected: selected)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("View \(task.title)")
                .accessibilityAddTraits(selected ? .isSelected : [])
            } else {
                Button {
                    requestNavigation(.task(selected ? nil : task.id))
                } label: {
                    MacRowTitleText(title: task.title, kind: kind, selected: selected)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Edit \(task.title)")
                .accessibilityAddTraits(selected ? .isSelected : [])
                .contextMenu {
                    Button("Rename title…") { beginQuickRename(task) }
                        .disabled(selectedTaskID != nil)
                }
            }
        } trailing: {
            rowTrailing(task, selected: selected, showsProject: showsProject, kind: kind)
        }
    }

    @ViewBuilder
    private func rowTrailing(_ task: TaskRecord, selected: Bool, showsProject: Bool, kind: MacRowKind) -> some View {
        HStack(spacing: 12) {
            if !task.state.isTerminal, !kind.hasMark {
                Button {
                    requestNavigation(.complete(task.id))
                } label: {
                    MacRowMark(kind: .open)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Complete \(task.title)")
                .opacity(selected || hoveredTaskID == task.id ? 1 : 0)
            }
            if task.state == .waiting, let waitingFor = task.waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines),
                !waitingFor.isEmpty
            {
                // The person comes first, as on the board; the spoken label keeps the full sentence.
                HStack(spacing: 4) {
                    Text(waitingFor).accessibilityLabel("Waiting for \(waitingFor)")
                    if let since = task.waitingSince {
                        Text("· since")
                        Text(since, style: .date)
                    }
                }
                .macRowMeta(selected: selected)
            }
            if showsProject, let projectID = task.projectID, model.destination != .project(projectID) {
                Text(model.projectLabel(projectID))
                    .macRowMeta(selected: selected)
            }
            if let id = task.tagIDs.first, let tag = model.tag(id) {
                Text("#\(tag.name)")
                    .font(MacRowFont.meta)
                    .lineLimit(1)
                    .foregroundStyle(tagTint(id))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(tagTint(id).opacity(0.15), in: Capsule())
            }
            if task.tagIDs.count > 1 {
                Text("+\(task.tagIDs.count - 1)")
                    .macRowMeta(selected: selected)
            }
            if let due = task.dueDate {
                Text(due.isoString)
                    .macRowMeta(tone: MacDueTone(due: due, today: CalendarDay(date: Date())), selected: selected)
            }
            if task.state.isTerminal {
                Button("Reopen…") { requestNavigation(.reopen(task.id)) }
                    .fixedSize(horizontal: true, vertical: false)
                    .accessibilityLabel("Reopen \(task.title)")
            } else {
                Menu {
                    ForEach(TaskList.allCases.filter { $0.taskState != task.state }) { list in
                        Button {
                            requestNavigation(.move(task.id, list))
                        } label: {
                            Label(list.title, systemImage: list.symbol)
                        }
                    }
                } label: {
                    Image(systemName: "arrowshape.turn.up.right")
                }
                .menuStyle(.borderlessButton)
                .accessibilityLabel("Move \(task.title) to another GTD list")
                .help("Move to another GTD list")
            }
        }
    }

    // MARK: Smart Add

    private var capturePreviewStatus: String {
        if case .failed = model.capturePreviewReadiness { return "Preview couldn’t load" }
        return "Preparing preview…"
    }

    /// The new-task card (board "10 Create task"): ⌘N focuses its title field. Smart Add's preview
    /// files the draft under a project and tags, shown as chips once it is ready.
    private var smartAdd: some View {
        let preview = model.capturePreview
        let hasDraft = !model.draft.isEmpty
        let ready = model.capturePreviewReadiness == .ready
        return MacNewTaskCard(listTitle: model.selectedList.title) {
            TextField("Add a task", text: $model.draft)
                .textFieldStyle(.plain)
                .macNewTaskTitleField()
                .focused($addFocused)
                .onSubmit { requestNavigation(.createTask) }
        } details: {
            if model.selectedList == .waiting {
                TextField("Waiting for person, event, or condition", text: $model.waitingForDraft)
                    .textFieldStyle(.plain)
                    .macCaptureField()
                    .onSubmit { requestNavigation(.createTask) }
                    .padding(.top, 12)
            }
            if hasDraft || model.selectedList == .waiting {
                if ready, !preview.tokens.isEmpty, !preview.title.isEmpty {
                    MacCaptureNote(text: "“\(preview.title)”")
                }
                if ready {
                    MacNewTaskClassification(project: preview.project, tags: preview.tags)
                } else {
                    MacCaptureNote(text: capturePreviewStatus, topPadding: 14)
                }
                if ready, hasDraft, let problem = preview.problemMessage, preview.problem != .emptyTitle {
                    MacCaptureNote(text: problem, danger: true)
                }
                if model.hasAppliedTaskFilter || !model.searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    MacCaptureNote(text: "Current search may hide the new task from this list.")
                }
                MacNewTaskFooter(
                    addEnabled: ready && !addDisabled(preview), hint: "⌘N · Return adds",
                    onAdd: { requestNavigation(.createTask) }
                ) {
                    if case .failed = model.capturePreviewReadiness {
                        Button("Retry preview") { Task { await model.prepareCapturePreview(model.captureDraft) } }
                            .buttonStyle(.carryOnQuiet)
                    }
                }
            }
            if let notice = model.captureNotice {
                MacCaptureNote(text: notice, topPadding: 12)
                if model.hasAppliedTaskFilter {
                    Button("Clear search") { requestNavigation(.clearTaskFilters) }
                        .buttonStyle(.carryOnQuiet)
                        .padding(.top, 4)
                }
            }
        }
    }

    private func addDisabled(_ preview: CapturePreview) -> Bool {
        let waiting = model.waitingForDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        return !preview.isValid
            || (model.selectedList == .waiting && (waiting.isEmpty || !EditorLimits.fits(waiting, EditorLimits.waitingFor)))
    }
}

// MARK: - Sheets and confirmations

private enum NewCollection: String, Identifiable {
    case project, tag
    var id: String { rawValue }
}

private enum CollectionToEdit: Identifiable {
    case project(ProjectID), tag(TagID)

    var id: String {
        switch self {
        case .project(let id): "project:\(id.rawValue)"
        case .tag(let id): "tag:\(id.rawValue)"
        }
    }

    var isProject: Bool {
        if case .project = self { return true }
        return false
    }
}

// Every sheet and confirmation of the window, in one place: the presentations the person starts;
// none of them reads sync state.
extension WorkspaceView {
    fileprivate func taskSheets<Content: View>(_ content: Content) -> some View {
        content
            // presentation-region: task editor, rename, voice, move, reopen and discard sheets
            .sheet(
                isPresented: $quickOpenPresented,
                onDismiss: {
                    if let target = pendingQuickOpenTarget {
                        pendingQuickOpenTarget = nil
                        requestNavigation(.quickOpen(target))
                    }
                }
            ) {
                QuickOpenView(model: model) { target in
                    pendingQuickOpenTarget = target
                    quickOpenPresented = false
                } onClose: {
                    quickOpenPresented = false
                }
                .disabled(sheetIsBusy)
                .interactiveDismissDisabled(sheetIsBusy)
            }
            .sheet(item: $renamingTask) { task in
                quickRenameSheet(task)
                    .disabled(sheetIsBusy)
                    .interactiveDismissDisabled(sheetIsBusy)
            }
            .sheet(isPresented: $voicePresented) {
                VoiceCaptureView(onUseAsTask: { transcript in
                    if model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        model.draft = transcript
                        addFocused = true
                    } else {
                        pendingVoiceTranscript = transcript
                        confirmingReplaceDraft = true
                    }
                })
                .disabled(sheetIsBusy)
                .interactiveDismissDisabled(sheetIsBusy)
            }
            // Task fields save as you type; this asks only for what cannot save: fields that are not
            // valid or whose save failed, a subtask or comment not added yet, the capture draft.
            .confirmationDialog("Discard unsaved changes?", isPresented: $confirmingDiscard) {
                Button("Discard changes", role: .destructive) {
                    if let pending = pendingEditorNavigation {
                        // Sign-out removes the drafts only once it happens (X-04 can still be cancelled).
                        if changesCaptureContext(pending), !Self.isSignOut(pending) {
                            model.draft = ""
                            model.waitingForDraft = ""
                        }
                        if !Self.isSignOut(pending) {
                            taskForm = selectedTaskID.flatMap { model.task($0) }.map { TaskAutosave(task: $0) }
                            extrasDirty = false
                        }
                        applyNavigation(pending)
                    }
                }
                Button("Keep editing", role: .cancel) { pendingEditorNavigation = nil }
            } message: {
                Text(
                    selectedTaskID == nil
                        ? "The new task draft has not been saved."
                        : "Some changes to this task can't be saved as they are, or a subtask or comment isn't added yet. Subtasks and comments already saved will stay saved."
                )
            }
            .confirmationDialog("Replace the current task draft?", isPresented: $confirmingReplaceDraft) {
                Button("Replace draft", role: .destructive) {
                    if let transcript = pendingVoiceTranscript { model.draft = transcript }
                    pendingVoiceTranscript = nil
                    addFocused = true
                }
                Button("Keep draft", role: .cancel) { pendingVoiceTranscript = nil }
            } message: {
                Text("The existing draft will be replaced by the voice transcript.")
            }
            .sheet(
                isPresented: $choosingCaptureList,
                onDismiss: {
                    if focusCaptureAfterChoice {
                        focusCaptureAfterChoice = false
                        addFocused = true
                    }
                }
            ) {
                captureListSheet
                    .disabled(sheetIsBusy)
                    .interactiveDismissDisabled(sheetIsBusy)
            }
            .sheet(item: $reopeningTask) { task in
                reopenSheet(task)
                    .disabled(sheetIsBusy)
                    .interactiveDismissDisabled(sheetIsBusy)
            }
            .sheet(item: $movingTask) { task in
                moveToWaitingSheet(task)
                    .disabled(sheetIsBusy)
                    .interactiveDismissDisabled(sheetIsBusy)
            }
            // presentation-region-end
    }

    private func quickRenameSheet(_ task: TaskRecord) -> some View {
        let title = quickRenameTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        let invalid = title.isEmpty || !EditorLimits.fits(title, EditorLimits.title)
        return VStack(alignment: .leading, spacing: 14) {
            Text("Rename task").font(.title2.bold())
            TextField("Task title", text: $quickRenameTitle)
                .focused($quickRenameFocused)
                .onSubmit { saveQuickRename(task) }
            if !EditorLimits.fits(quickRenameTitle, EditorLimits.title) {
                Text("Use \(EditorLimits.title) characters or fewer.")
                    .font(.caption).foregroundStyle(.red)
            }
            if let quickRenameError {
                Text(quickRenameError).font(.caption).foregroundStyle(.red)
            }
            HStack {
                Spacer()
                Button("Cancel") { renamingTask = nil }
                    .keyboardShortcut(.cancelAction)
                Button("Save title") { saveQuickRename(task) }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(invalid)
            }
        }
        .padding(24)
        .frame(width: 420)
        // presentation-region: task editor, rename, voice, move, reopen and discard sheets
        .onAppear { quickRenameFocused = true }
        // presentation-region-end
    }

    private var captureListSheet: some View {
        MacPutItInContent(selection: $captureListChoice) {
            model.choose(.list(captureListChoice))
            focusCaptureAfterChoice = true
            choosingCaptureList = false
        } onCancel: {
            choosingCaptureList = false
        }
    }

    private func reopenSheet(_ task: TaskRecord) -> some View {
        let waiting = reopenWaitingFor.trimmingCharacters(in: .whitespacesAndNewlines)
        return VStack(alignment: .leading, spacing: 16) {
            Text("Reopen task").font(.title2.bold())
            Text(task.title)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            Picker("Destination", selection: $reopenDestination) {
                ForEach(TaskList.allCases) { list in
                    Text(list.title).tag(list)
                }
            }
            if reopenDestination == .waiting {
                TextField("Waiting for person, event, or condition", text: $reopenWaitingFor)
                    .textFieldStyle(.roundedBorder)
            }
            if let error = model.error {
                Text(error).font(.caption).foregroundStyle(.red)
            }
            HStack {
                Spacer()
                Button("Cancel") { reopeningTask = nil }
                    .keyboardShortcut(.cancelAction)
                Button("Reopen task") {
                    let destination = reopenDestination
                    let waitingFor = reopenWaitingFor
                    performSheetSave(editorID: reopenEditorID) { submittedEditorID in
                        if await model.reopenTask(task.id, to: destination, waitingFor: waitingFor, editorID: submittedEditorID) {
                            reopeningTask = nil
                            reopenEditorID = UUID().uuidString
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(
                    reopenDestination == .waiting && (waiting.isEmpty || !EditorLimits.fits(waiting, EditorLimits.waitingFor))
                )
            }
        }
        .padding(24)
        .frame(width: 380)
    }

    private func moveToWaitingSheet(_ task: TaskRecord) -> some View {
        let waiting = moveWaitingFor.trimmingCharacters(in: .whitespacesAndNewlines)
        return VStack(alignment: .leading, spacing: 16) {
            Text("Move to Waiting for").font(.title2.bold())
            Text(task.title)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            TextField("Who or what are you waiting for?", text: $moveWaitingFor)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel("Waiting for person, event, or condition")
            if let error = model.error {
                Text(error).font(.caption).foregroundStyle(.red)
            }
            HStack {
                Spacer()
                Button("Keep in \(task.state.openList?.title ?? "current list")") { movingTask = nil }
                    .keyboardShortcut(.cancelAction)
                Button("Move to Waiting for") {
                    let waitingFor = moveWaitingFor
                    performSheetSave(editorID: moveWaitingEditorID) { submittedEditorID in
                        let before = model.task(task.id)
                        if await model.moveTask(task.id, to: .waiting, waitingFor: waitingFor, editorID: submittedEditorID) {
                            registerUndo(before)
                            movingTask = nil
                            moveWaitingEditorID = UUID().uuidString
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(waiting.isEmpty || !EditorLimits.fits(waiting, EditorLimits.waitingFor))
            }
        }
        .padding(24)
        .frame(width: 390)
    }

    fileprivate func collectionSheets<Content: View>(_ content: Content) -> some View {
        content
            // presentation-region: collection, tag and outcome sheets
            .confirmationDialog("Delete tag?", isPresented: $confirmingTagDeletion) {
                Button("Delete tag", role: .destructive) {
                    guard let tag = tagToDelete, !editorDirty else { return }
                    Task { if await model.deleteTag(tag.id) { select(nil) } }
                }
                Button("Cancel", role: .cancel) { tagToDelete = nil }
            } message: {
                Text("This removes #\(tagToDelete?.name ?? "tag") from every task. The tasks stay.")
            }
            .sheet(item: $addingCollection) { kind in
                VStack(alignment: .leading, spacing: 16) {
                    Text(kind == .project ? "New project" : "New tag").font(.title2.bold())
                    TextField("Name", text: $collectionName)
                        .onSubmit { createCollection(kind) }
                    if let error = model.error {
                        Text(error).font(.caption).foregroundStyle(.red)
                    }
                    HStack {
                        Spacer()
                        Button("Cancel") { addingCollection = nil }
                            .keyboardShortcut(.cancelAction)
                        Button("Add") { createCollection(kind) }
                            .buttonStyle(.borderedProminent)
                            .keyboardShortcut(.defaultAction)
                            .disabled(collectionName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                }
                .padding(24)
                .frame(width: 340)
                .disabled(sheetIsBusy)
                .interactiveDismissDisabled(sheetIsBusy)
            }
            .sheet(item: $editingCollection) { kind in
                renameSheet(kind)
                    .disabled(sheetIsBusy)
                    .interactiveDismissDisabled(sheetIsBusy)
            }
            .sheet(item: $editingOutcomeProject) { project in
                outcomeSheet(project)
                    .disabled(sheetIsBusy)
                    .interactiveDismissDisabled(sheetIsBusy)
            }
            // presentation-region-end
    }

    // presentation-region: rename sheet focus
    /// The sidebar's rename sheet, also opened by "Rename…" in the X-06 refusal: the current name
    /// selected, the kit's duplicate-name error under the field with focus kept there; on success
    /// focus returns to "Unarchive" (no automatic unarchive).
    private func renameSheet(_ kind: CollectionToEdit) -> some View {
        let name = editedCollectionName.trimmingCharacters(in: .whitespacesAndNewlines)
        return VStack(alignment: .leading, spacing: 16) {
            Text(kind.isProject ? "Rename project" : "Rename tag").font(.title2.bold())
            TextField("Name", text: $editedCollectionName)
                .focused($collectionNameFocused)
                .onSubmit { renameCollection(kind) }
            if let error = model.error {
                Text(error).font(.caption).foregroundStyle(.red)
            }
            HStack {
                Spacer()
                Button("Cancel") {
                    model.error = nil
                    editingCollection = nil
                    if renamingFromRefusal {
                        renamingFromRefusal = false
                        canvasFocus = .unarchive
                    }
                }
                .keyboardShortcut(.cancelAction)
                Button("Save") { renameCollection(kind) }
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut(.defaultAction)
                    .disabled(name.isEmpty || !EditorLimits.fits(name, EditorLimits.name))
            }
        }
        .padding(24)
        .frame(width: 340)
        .onAppear { collectionNameFocused = true }
    }
    // presentation-region-end

    private func outcomeSheet(_ project: ProjectRecord) -> some View {
        let outcome = outcomeDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        return VStack(alignment: .leading, spacing: 14) {
            Text("Desired outcome").font(.title2.bold())
            Text(project.name).foregroundStyle(.secondary)
            Text("What will be true when this project is done?")
                .font(.subheadline)
            TextEditor(text: $outcomeDraft)
                .scrollContentBackground(.hidden)
                .frame(height: 110)
                .padding(8)
                .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
                .accessibilityLabel("Desired project outcome")
            if let error = model.error {
                Text(error).font(.caption).foregroundStyle(.red)
            }
            HStack {
                Spacer()
                Button("Cancel") { editingOutcomeProject = nil }
                    .keyboardShortcut(.cancelAction)
                Button("Save outcome") {
                    let authored = outcomeDraft
                    performSheetSave(editorID: projectOutcomeEditorID) { submittedEditorID in
                        if await model.saveProjectOutcome(project.id, to: authored, editorID: submittedEditorID) {
                            editingOutcomeProject = nil
                            projectOutcomeEditorID = UUID().uuidString
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(
                    outcome.isEmpty || !EditorLimits.fits(outcome, EditorLimits.outcome) || outcome == project.desiredOutcome
                )
            }
        }
        .padding(24)
        .frame(width: 480)
    }

    fileprivate func reviewSheets<Content: View>(_ content: Content) -> some View {
        content
            // presentation-region: review and clarify sheets
            .sheet(isPresented: $reviewingWaiting) {
                WaitingReviewView(model: model)
                    .disabled(sheetIsBusy)
            }
            .sheet(isPresented: $reviewingSomeday) {
                SomedayReviewView(model: model)
                    .disabled(sheetIsBusy)
            }
            .sheet(isPresented: $reviewingProjects) {
                ProjectReviewView(model: model) { id in
                    reviewingProjects = false
                    requestNavigation(.destination(.project(id)))
                }
                .disabled(sheetIsBusy)
                .interactiveDismissDisabled(sheetIsBusy)
            }
            .sheet(isPresented: $clarifyingInbox, onDismiss: { clarifyProjectStart = nil }) {
                InboxClarifyView(model: model, startAsProject: clarifyProjectStart)
                    .disabled(sheetIsBusy)
            }
            // presentation-region-end
    }
}

// MARK: - The File menu's project items

private struct WorkspaceModelKey: FocusedValueKey {
    typealias Value = BrainBuddyModel
}

extension FocusedValues {
    /// The window's model, for the menu commands (`ProjectMenuCommands`).
    var workspaceModel: BrainBuddyModel? {
        get { self[WorkspaceModelKey.self] }
        set { self[WorkspaceModelKey.self] = newValue }
    }
}

// MARK: - Inbox clarification and the Waiting and Someday reviews

private func validAnswer(_ value: String, limit: Int) -> Bool {
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    return !trimmed.isEmpty && EditorLimits.fits(trimmed, limit)
}

/// An answer that may be empty (the project's outcome); when it is not, it must fit.
private func validOptionalAnswer(_ value: String, limit: Int) -> Bool {
    let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
    return trimmed.isEmpty || EditorLimits.fits(trimmed, limit)
}

private enum InboxClarificationStep {
    case decision, nextTitle, waitingReason, waitingTitle
    case projectName, projectOutcome, projectAction
}

private struct InboxClarifyView: View {
    let model: BrainBuddyModel
    /// Opens on this Inbox item in its project path (the inspector's "Bigger than one step").
    var startAsProject: TaskID?
    @State private var startApplied = false
    @Environment(\.dismiss) private var dismiss
    @State private var items: [TaskRecord] = []
    @State private var index = 0
    @State private var loaded = false
    @State private var step: InboxClarificationStep = .decision
    @State private var proposedTitle = ""
    @State private var waitingReason = ""
    @State private var projectName = ""
    @State private var desiredOutcome = ""
    @State private var firstAction = ""
    /// The project chosen for the current item; applied with the decision, never at once, because
    /// giving an Inbox item a project takes it out of the Inbox before it is clarified.
    @State private var stagedProjectID: ProjectID?
    @State private var showingProjectCreator = false
    @State private var newProjectName = ""
    @State private var confirmingCancel = false
    @State private var confirmingClose = false
    @State private var editorID = UUID().uuidString
    @State private var newProjectEditorID = UUID().uuidString
    @State private var clarifyProjectID = ProjectID.random()
    @State private var isSubmitting = false

    private var isBusy: Bool { model.isSaving || isSubmitting }

    private func performSave(editorID: String, _ operation: @escaping @MainActor (String) async -> Void) {
        guard !isBusy else { return }
        isSubmitting = true
        Task { @MainActor in
            defer { isSubmitting = false }
            await operation(editorID)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Clarify Inbox").font(.title2.bold())
                    Text(loaded ? (items.isEmpty ? "No items" : "\(min(index + 1, items.count)) of \(items.count)") : "One item at a time")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Close clarification") {
                    if step == .decision { dismiss() } else { confirmingClose = true }
                }
                .keyboardShortcut(.cancelAction)
            }
            if !loaded {
                ProgressView("Loading Inbox…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.reviewListReadiness(.inbox) != .ready {
                listQueryState(model.reviewListReadiness(.inbox), loading: "Loading Inbox…", retry: load)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if items.isEmpty {
                reviewPageUnavailable("Inbox is clear", systemImage: "tray",
                    description: "Capture new items without classifying them first.", list: .inbox, model: model, reload: load)
            } else if index >= items.count {
                reviewPageUnavailable("Clarification pass complete", systemImage: "checkmark.circle",
                    description: "Items left in Inbox can be revisited later.", list: .inbox, model: model, reload: load)
            } else {
                let item = items[index]
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        capturedItem(item)
                        if step == .decision {
                            decisionButtons(item)
                        } else {
                            clarificationQuestion(for: item)
                        }
                        if let error = model.error {
                            Text(error).font(.caption).foregroundStyle(.red)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(24)
        .frame(width: 640, height: index < items.count && step == .decision ? 640 : 430)
        .onAppear(perform: load)
        .disabled(isBusy)
        .interactiveDismissDisabled(isBusy || step != .decision)
        // presentation-region: project creator sheet
        .sheet(isPresented: $showingProjectCreator) {
            projectCreator
                .disabled(isBusy)
                .interactiveDismissDisabled(isBusy)
        }
        // presentation-region-end
        // presentation-region: clarify confirmations
        .confirmationDialog("Cancel this Inbox item?", isPresented: $confirmingCancel) {
            Button("Cancel task", role: .destructive) {
                guard index < items.count else { return }
                let taskID = items[index].id
                performSave(editorID: editorID) { submittedEditorID in
                    if await model.cancelTask(taskID, editorID: submittedEditorID) { advance() }
                }
            }
            Button("Keep in Inbox", role: .cancel) {}
        } message: {
            Text("This moves the item to history. No project or action is created.")
        }
        .confirmationDialog("Discard clarification draft?", isPresented: $confirmingClose) {
            Button("Discard draft", role: .destructive) { dismiss() }
            Button("Keep editing", role: .cancel) {}
        } message: {
            Text("The Inbox item remains unchanged. Unsaved answers will be lost.")
        }
        // presentation-region-end
    }

    private func capturedItem(_ item: TaskRecord) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("CAPTURED ITEM")
                .font(.caption.bold())
                .tracking(1.5)
                .foregroundStyle(.secondary)
            Text(item.title).font(.title3.weight(.semibold))
            if let details = item.details, !details.isEmpty {
                Text(details).foregroundStyle(.secondary).lineLimit(4)
            }
            if let due = item.dueDate {
                Text("Due · \(due.isoString)").font(.caption).foregroundStyle(.secondary)
            }
            if !item.tagIDs.isEmpty {
                let names = item.tagIDs.compactMap { model.tag($0)?.name }
                Text("Tags · \(names.map { "#\($0)" }.joined(separator: "  "))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
    }

    /// The staged project, if any, with the changes a decision already sends.
    private func withStagedProject(_ changes: TaskChanges = TaskChanges()) -> TaskChanges {
        var merged = changes
        if let stagedProjectID { merged.projectID = .set(stagedProjectID) }
        return merged
    }

    /// "No project", the active projects and "New project…". The choice is applied with Next,
    /// Waiting for or Someday; a new project, cancelling and leaving the item ignore it.
    private var projectMenu: some View {
        HStack(spacing: 10) {
            Text("Project · optional").font(.subheadline).foregroundStyle(.secondary)
            Menu {
                Button("No project") { stagedProjectID = nil }
                ForEach(model.projects) { project in
                    Button {
                        stagedProjectID = project.id
                    } label: {
                        if stagedProjectID == project.id {
                            Label(project.name, systemImage: "checkmark")
                        } else {
                            Text(project.name)
                        }
                    }
                }
                Divider()
                Button("New project…") { showingProjectCreator = true }
            } label: {
                Text(stagedProjectID.map { model.projectLabel($0) } ?? "No project")
            }
            .menuStyle(.button)
            .fixedSize()
            .accessibilityLabel("Project")
            .accessibilityValue(stagedProjectID.map { model.projectLabel($0) } ?? "None")
        }
    }

    private var projectCreator: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("New project").font(.title2.bold())
            TextField("Project name", text: $newProjectName)
                .textFieldStyle(.roundedBorder)
            if let error = model.error {
                Text(error).font(.caption).foregroundStyle(.red)
            }
            HStack {
                Spacer()
                Button("Cancel") {
                    newProjectName = ""
                    model.error = nil
                    showingProjectCreator = false
                }
                .keyboardShortcut(.cancelAction)
                Button("Add project") {
                    let authored = newProjectName
                    performSave(editorID: newProjectEditorID) { submittedEditorID in
                        if let id = await model.createProject(authored, editorID: submittedEditorID) {
                            newProjectEditorID = UUID().uuidString
                            stagedProjectID = id
                            newProjectName = ""
                            showingProjectCreator = false
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(newProjectName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(22)
        .frame(width: 340)
    }

    @ViewBuilder
    private func decisionButtons(_ item: TaskRecord) -> some View {
        projectMenu
        Text("What is this?").font(.headline)
        VStack(alignment: .leading, spacing: 9) {
            Button("Already a concrete action → Next") {
                let changes = withStagedProject()
                performSave(editorID: editorID) { submittedEditorID in
                    if await model.saveTask(item.id, changes: changes, moveTo: .next, editorID: submittedEditorID) { advance() }
                }
            }
            Button("Rewrite as a Next action…") {
                proposedTitle = item.title
                step = .nextTitle
            }
            Button("Waiting on someone or something…") {
                waitingReason = ""
                proposedTitle = item.title
                step = .waitingReason
            }
            Button("A project with several steps…") {
                projectName = item.title
                desiredOutcome = ""
                firstAction = ""
                step = .projectName
            }
            .disabled(item.projectID != nil)
            Button("Someday / maybe") {
                let changes = withStagedProject()
                performSave(editorID: editorID) { submittedEditorID in
                    if await model.saveTask(item.id, changes: changes, moveTo: .someday, editorID: submittedEditorID) { advance() }
                }
            }
            Button("No longer relevant…", role: .destructive) { confirmingCancel = true }
            Button("Leave in Inbox for now") { advance() }
        }
        .buttonStyle(.bordered)
        Text("Reference-only material stays in Inbox until there is a dedicated place for it.")
            .font(.caption)
            .foregroundStyle(.secondary)
    }

    @ViewBuilder
    private func clarificationQuestion(for item: TaskRecord) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(question).font(.headline)
            switch step {
            case .nextTitle, .waitingTitle:
                TextField("Concrete action", text: $proposedTitle)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Concrete action")
            case .waitingReason:
                TextField("Person, event, or condition", text: $waitingReason)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("Waiting for person, event, or condition")
            case .projectName:
                TextField("Project name", text: $projectName)
                    .textFieldStyle(.roundedBorder)
            case .projectOutcome:
                TextEditor(text: $desiredOutcome)
                    .scrollContentBackground(.hidden)
                    .frame(height: 95)
                    .padding(8)
                    .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
                    .accessibilityLabel("Desired project outcome, optional")
                Text("Optional. Leave it empty to add the outcome later.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            case .projectAction:
                TextField("First Next action", text: $firstAction)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityLabel("First Next action")
            case .decision:
                EmptyView()
            }
            if step == .projectAction {
                Text(projectSummary)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text("Existing notes, tags, and date stay on the resulting Next action.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            HStack {
                Button("Back") { step = previousStep }
                Spacer()
                Button(
                    step == .projectAction
                        ? "Create project and Next action"
                        : (step == .nextTitle || step == .waitingTitle ? "Save decision" : "Continue")
                ) {
                    submit(item)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!isValidAnswer)
            }
        }
    }

    private var projectSummary: String {
        let name = projectName.trimmingCharacters(in: .whitespacesAndNewlines)
        let outcome = desiredOutcome.trimmingCharacters(in: .whitespacesAndNewlines)
        return outcome.isEmpty ? name : "\(name) → \(outcome)"
    }

    private var question: String {
        switch step {
        case .decision: "What is this?"
        case .nextTitle: "What is the concrete next action?"
        case .waitingReason: "Who or what are you waiting for?"
        case .waitingTitle: "What is the waiting item?"
        case .projectName: "What will you call this project?"
        case .projectOutcome: "What will be true when it is done?"
        case .projectAction: "What is the first concrete action?"
        }
    }

    private var previousStep: InboxClarificationStep {
        switch step {
        case .decision, .nextTitle, .waitingReason, .projectName: .decision
        case .waitingTitle: .waitingReason
        case .projectOutcome: .projectName
        case .projectAction: .projectOutcome
        }
    }

    private var isValidAnswer: Bool {
        switch step {
        case .decision: false
        case .nextTitle, .waitingTitle: validAnswer(proposedTitle, limit: EditorLimits.title)
        case .waitingReason: validAnswer(waitingReason, limit: EditorLimits.waitingFor)
        case .projectName: validAnswer(projectName, limit: EditorLimits.name)
        case .projectOutcome: validOptionalAnswer(desiredOutcome, limit: EditorLimits.outcome)
        case .projectAction: validAnswer(firstAction, limit: EditorLimits.title)
        }
    }

    private func load() {
        loaded = false
        Task {
            items = await model.loadInboxClarificationTasks()
            index = 0
            loaded = true
            step = .decision
            stagedProjectID = nil
            startOnRequestedItem()
        }
    }

    /// Once: the requested item, at "What will you call this project?", as "A project with several
    /// steps…" starts it.
    private func startOnRequestedItem() {
        guard !startApplied, let start = startAsProject else { return }
        startApplied = true
        guard let found = items.firstIndex(where: { $0.id == start }) else { return }
        index = found
        let item = items[found]
        guard item.projectID == nil else { return }
        projectName = item.title
        desiredOutcome = ""
        firstAction = ""
        step = .projectName
    }

    private func submit(_ item: TaskRecord) {
        guard !isBusy, isValidAnswer else { return }
        switch step {
        case .decision:
            break
        case .nextTitle:
            let title = proposedTitle.trimmingCharacters(in: .whitespacesAndNewlines)
            let changes = withStagedProject(title == item.title ? TaskChanges() : TaskChanges(title: .set(title)))
            performSave(editorID: editorID) { submittedEditorID in
                if await model.saveTask(item.id, changes: changes, moveTo: .next, editorID: submittedEditorID) { advance() }
            }
        case .waitingReason:
            step = .waitingTitle
        case .waitingTitle:
            let title = proposedTitle.trimmingCharacters(in: .whitespacesAndNewlines)
            let reason = waitingReason.trimmingCharacters(in: .whitespacesAndNewlines)
            let changes = withStagedProject(
                TaskChanges(title: title == item.title ? .unchanged : .set(title), waitingFor: .set(reason))
            )
            performSave(editorID: editorID) { submittedEditorID in
                if await model.saveTask(item.id, changes: changes, moveTo: .waiting, editorID: submittedEditorID) { advance() }
            }
        case .projectName:
            step = .projectOutcome
        case .projectOutcome:
            step = .projectAction
        case .projectAction:
            let outcome = desiredOutcome.trimmingCharacters(in: .whitespacesAndNewlines)
            let projectName = projectName.trimmingCharacters(in: .whitespacesAndNewlines)
            let firstAction = firstAction.trimmingCharacters(in: .whitespacesAndNewlines)
            let submittedProjectID = clarifyProjectID
            performSave(editorID: editorID) { submittedEditorID in
                if await model.clarifyInboxAsProject(item.id, projectName: projectName,
                    outcome: outcome.isEmpty ? nil : outcome, firstAction: firstAction,
                    projectID: submittedProjectID, editorID: submittedEditorID) { advance() }
            }
        }
    }

    private func advance() {
        editorID = UUID().uuidString
        clarifyProjectID = .random()
        index += 1
        step = .decision
        stagedProjectID = nil
        model.error = nil
    }
}

private enum WaitingReviewDecision {
    case followUp, returnToNext
}

/// Waiting for, one item at a time; "Keep waiting" marks it in `mac-local.json` and it returns
/// after seven days or a change (FR-023).
private struct WaitingReviewView: View {
    let model: BrainBuddyModel
    @Environment(\.dismiss) private var dismiss
    @State private var items: [TaskRecord] = []
    @State private var index = 0
    @State private var loaded = false
    @State private var decision: WaitingReviewDecision?
    @State private var actionTitle = ""
    @State private var confirmingCancel = false
    @State private var editorID = UUID().uuidString
    @State private var followUpTaskID = TaskID.random()
    @State private var isSubmitting = false

    private var isBusy: Bool { model.isSaving || isSubmitting }

    private func performSave(editorID: String, _ operation: @escaping @MainActor (String) async -> Void) {
        guard !isBusy else { return }
        isSubmitting = true
        Task { @MainActor in
            defer { isSubmitting = false }
            await operation(editorID)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            MacReviewHeader(
                title: "Review Waiting for",
                caption: loaded ? (items.isEmpty ? "No items due" : "\(min(index + 1, items.count)) of \(items.count)") : "One item at a time",
                onClose: { dismiss() })
            if !loaded {
                ProgressView("Loading Waiting…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.reviewListReadiness(.waiting) != .ready {
                listQueryState(model.reviewListReadiness(.waiting), loading: "Loading Waiting…", retry: load)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if items.isEmpty {
                reviewPageUnavailable("Waiting review is up to date", systemImage: "hourglass",
                    description: "Reviewed items return after seven days or when their task changes.", list: .waiting, model: model, reload: load)
            } else if index >= items.count {
                reviewPageUnavailable("Waiting review complete", systemImage: "checkmark.circle",
                    description: "The items you checked remain in their chosen GTD lists.", list: .waiting, model: model, reload: load)
            } else {
                let item = items[index]
                card(item)
                if let decision {
                    decisionForm(item, decision: decision)
                } else {
                    choices(item)
                }
                if let error = model.error {
                    Text(error).font(MacSheetFont.meta).foregroundStyle(CarryOnColorStyle.coStatusDanger)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(24)
        .frame(width: 640, height: 480)
        .macSheetSurface()
        .disabled(isBusy)
        .interactiveDismissDisabled(isBusy)
        .onAppear(perform: load)
        // presentation-region: cancel task confirmations
        .confirmationDialog("Cancel this task?", isPresented: $confirmingCancel) {
            Button("Cancel task", role: .destructive) {
                guard index < items.count else { return }
                let taskID = items[index].id
                performSave(editorID: editorID) { submittedEditorID in
                    if await model.cancelTask(taskID, editorID: submittedEditorID) { advance() }
                }
            }
            Button("Keep task", role: .cancel) {}
        } message: {
            Text("The task will move to history. No message will be sent.")
        }
        // presentation-region-end
    }

    private func card(_ item: TaskRecord) -> some View {
        MacWaitingReviewCard(
            title: item.title, details: item.details,
            waitingFor: item.waitingFor,
            since: item.waitingSince.map { "Since \($0.formatted(date: .abbreviated, time: .omitted))" },
            project: item.projectID.map { "Project · \(model.projectLabel($0))" })
    }

    private func decisionForm(_ item: TaskRecord, decision: WaitingReviewDecision) -> some View {
        let archived = model.isArchived(item.projectID)
        return VStack(alignment: .leading, spacing: 10) {
            MacReviewQuestion(text: decision == .followUp ? "What will you do to follow up?" : "What is the next action now?")
            TextField("Concrete next action", text: $actionTitle)
                .textFieldStyle(.plain)
                .macSheetField()
                .accessibilityLabel("Concrete next action")
                .onSubmit { submit(item, decision: decision) }
            MacReviewLine(
                text: decision == .followUp
                    ? (archived
                        ? "Unarchive this project before creating a follow-up in it."
                        : "Creates a separate Next action in the same project. This item stays in Waiting and returns to review after seven days or a change.")
                    : "Moves this item to Next actions and clears its active waiting details.",
                small: true)
            HStack(spacing: 8) {
                Button("Back") { self.decision = nil }
                    .buttonStyle(.carryOnQuiet)
                Spacer()
                Button(decision == .followUp ? "Create follow-up" : "Move to Next actions") {
                    submit(item, decision: decision)
                }
                .buttonStyle(.carryOnStrong)
                .disabled(!validAnswer(actionTitle, limit: EditorLimits.title) || (decision == .followUp && archived))
            }
        }
    }

    @ViewBuilder
    private func choices(_ item: TaskRecord) -> some View {
        let archived = model.isArchived(item.projectID)
        MacReviewQuestion(text: "What should happen next?")
        HStack(spacing: 8) {
            Button("Keep waiting") {
                performSave(editorID: editorID) { _ in
                    if await model.keepWaiting(item) { advance() }
                }
            }
            .help("Review again after seven days or when this task changes")
            Button("Create follow-up…") {
                actionTitle = ""
                decision = .followUp
            }
            .disabled(archived)
            Button("Returned to me…") {
                actionTitle = item.title
                decision = .returnToNext
            }
            Button("No longer relevant…", role: .destructive) { confirmingCancel = true }
        }
        .buttonStyle(.carryOnSecondary)
        if archived {
            MacReviewLine(text: "Unarchive the project to add a follow-up there.", small: true)
        }
    }

    private func load() {
        loaded = false
        Task {
            items = await model.loadWaitingReviewTasks()
            index = 0
            loaded = true
            decision = nil
        }
    }

    private func submit(_ item: TaskRecord, decision: WaitingReviewDecision) {
        guard !isBusy, validAnswer(actionTitle, limit: EditorLimits.title) else { return }
        let title = actionTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        switch decision {
        case .followUp:
            let submittedTaskID = followUpTaskID
            performSave(editorID: editorID) { submittedEditorID in
                if await model.createFollowUp(for: item.id, title: title, taskID: submittedTaskID, editorID: submittedEditorID, shownTask: item) { advance() }
            }
            return
        case .returnToNext:
            let changes = title == item.title ? TaskChanges() : TaskChanges(title: .set(title))
            performSave(editorID: editorID) { submittedEditorID in
                if await model.saveTask(item.id, changes: changes, moveTo: .next, editorID: submittedEditorID) { advance() }
            }
            return
        }
    }

    private func advance() {
        editorID = UUID().uuidString
        followUpTaskID = .random()
        index += 1
        decision = nil
        actionTitle = ""
        model.error = nil
    }
}

/// Someday / maybe, one item at a time; "Keep in Someday" marks it in `mac-local.json` (FR-023).
private struct SomedayReviewView: View {
    let model: BrainBuddyModel
    @Environment(\.dismiss) private var dismiss
    @State private var items: [TaskRecord] = []
    @State private var index = 0
    @State private var loaded = false
    @State private var enteringNext = false
    @State private var actionTitle = ""
    @State private var confirmingCancel = false
    @State private var editorID = UUID().uuidString
    @State private var isSubmitting = false

    private var isBusy: Bool { model.isSaving || isSubmitting }

    private func performSave(editorID: String, _ operation: @escaping @MainActor (String) async -> Void) {
        guard !isBusy else { return }
        isSubmitting = true
        Task { @MainActor in
            defer { isSubmitting = false }
            await operation(editorID)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            MacReviewHeader(
                title: "Review Someday",
                caption: loaded ? (items.isEmpty ? "No items due" : "\(min(index + 1, items.count)) of \(items.count)") : "One item at a time",
                onClose: { dismiss() })
            if !loaded {
                ProgressView("Loading Someday…")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.reviewListReadiness(.someday) != .ready {
                listQueryState(model.reviewListReadiness(.someday), loading: "Loading Someday…", retry: load)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if items.isEmpty {
                reviewPageUnavailable("Someday review is up to date", systemImage: "calendar.badge.checkmark",
                    description: "Reviewed items return after seven days or when their task changes.", list: .someday, model: model, reload: load)
            } else if index >= items.count {
                reviewPageUnavailable("Someday review complete", systemImage: "checkmark.circle",
                    description: "Deferred items stay in Someday; selected next actions move to Next.", list: .someday, model: model, reload: load)
            } else {
                let item = items[index]
                ScrollView {
                    card(item)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .scrollIndicators(.visible)
                if enteringNext {
                    nextForm(item)
                } else {
                    choices(item)
                }
                if let error = model.error {
                    Text(error).font(MacSheetFont.meta).foregroundStyle(CarryOnColorStyle.coStatusDanger)
                }
            }
        }
        .padding(24)
        .frame(width: 640, height: 440)
        .macSheetSurface()
        .disabled(isBusy)
        .interactiveDismissDisabled(isBusy)
        .onAppear(perform: load)
        // presentation-region: cancel task confirmations
        .confirmationDialog("Cancel this task?", isPresented: $confirmingCancel) {
            Button("Cancel task", role: .destructive) {
                guard index < items.count else { return }
                let taskID = items[index].id
                performSave(editorID: editorID) { submittedEditorID in
                    if await model.cancelTask(taskID, editorID: submittedEditorID) { advance() }
                }
            }
            Button("Keep task", role: .cancel) {}
        } message: {
            Text("The task will move to history. No message will be sent.")
        }
        // presentation-region-end
    }

    private func card(_ item: TaskRecord) -> some View {
        MacSomedayReviewCard(
            title: item.title, details: item.details,
            project: item.projectID.map { "Project · \(model.projectLabel($0))" })
    }

    private func nextForm(_ item: TaskRecord) -> some View {
        let archived = model.isArchived(item.projectID)
        return VStack(alignment: .leading, spacing: 10) {
            MacReviewQuestion(text: "What is the concrete next action?")
            TextField("Concrete next action", text: $actionTitle)
                .textFieldStyle(.plain)
                .macSheetField()
                .accessibilityLabel("Concrete next action")
                .onSubmit { activate(item) }
            MacReviewLine(
                text: archived
                    ? "Unarchive this project before moving its task to Next actions."
                    : "The title and GTD list change together. Project, tags, notes, and due date remain attached.",
                small: true)
            HStack(spacing: 8) {
                Button("Back") { enteringNext = false }
                    .buttonStyle(.carryOnQuiet)
                Spacer()
                Button("Move to Next actions") { activate(item) }
                    .buttonStyle(.carryOnStrong)
                    .disabled(!validAnswer(actionTitle, limit: EditorLimits.title) || archived)
            }
        }
    }

    @ViewBuilder
    private func choices(_ item: TaskRecord) -> some View {
        let archived = model.isArchived(item.projectID)
        MacReviewQuestion(text: "Is this relevant now?")
        HStack(spacing: 8) {
            Button("Keep in Someday") {
                performSave(editorID: editorID) { _ in
                    if await model.keepSomeday(item) { advance() }
                }
            }
            .help("Review again after seven days or when this task changes")
            Button("Make it a Next action…") {
                actionTitle = item.title
                enteringNext = true
            }
            .disabled(archived)
            Button("No longer relevant…", role: .destructive) { confirmingCancel = true }
        }
        .buttonStyle(.carryOnSecondary)
        if archived {
            MacReviewLine(text: "Unarchive the project to activate this task.", small: true)
        }
    }

    private func load() {
        loaded = false
        Task {
            items = await model.loadSomedayReviewTasks()
            index = 0
            loaded = true
            enteringNext = false
        }
    }

    private func activate(_ task: TaskRecord) {
        guard !isBusy, validAnswer(actionTitle, limit: EditorLimits.title), !model.isArchived(task.projectID) else { return }
        let title = actionTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        performSave(editorID: editorID) { submittedEditorID in
            if await model.activateSomeday(task.id, title: title, editorID: submittedEditorID) { advance() }
        }
    }

    private func advance() {
        editorID = UUID().uuidString
        index += 1
        enteringNext = false
        actionTitle = ""
        model.error = nil
    }
}

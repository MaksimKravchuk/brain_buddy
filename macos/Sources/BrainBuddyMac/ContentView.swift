import AppKit
import BrainBuddyCore
import BrainBuddyMacCore
import BrainBuddyWorkspace
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

    var body: some View {
        Group {
            if let host = launch.host, let model = launch.model, let sync = launch.sync {
                if host.workspace.loadError != nil {
                    // X-09: nothing syncs until the file can be read (mac-app-host §9).
                    UnreadableWorkspaceView(host: host)
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
    case groupByProject(Bool)
    case showCancelled(Bool)
    case priorityFilter(PriorityFilter)
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

@ViewBuilder
private func listQueryState(_ readiness: WorkspaceQueryReadiness, loading: String, retry: @escaping () -> Void) -> some View {
    switch readiness {
    case .ready:
        EmptyView()
    case .notRequested, .loading:
        ProgressView(loading)
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

@MainActor
private func reviewPageUnavailable(
    _ title: String, systemImage: String, description: String, list: TaskList,
    model: BrainBuddyModel, reload: @escaping () -> Void
) -> some View {
    VStack(spacing: 12) {
        ContentUnavailableView(title, systemImage: systemImage, description: Text(description))
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
    @StateObject private var quickCapture = QuickCaptureController()
    @State private var voicePresented = false
    @State private var selectedTaskID: TaskID?
    @State private var selectionAnchor: SelectionAnchor<TaskID>?
    @State private var scrollTarget: TaskID?
    @State private var editDraft: TaskEditDraft?
    @State private var editorDirty = false
    @State private var editorCanSave = false
    @State private var editorSaveRequest = 0
    @State private var taskSaveEditorID = UUID().uuidString
    @State private var quickRenameEditorID = UUID().uuidString
    @State private var collectionEditorID = UUID().uuidString
    @State private var collectionCreateEditorID = UUID().uuidString
    @State private var projectOutcomeEditorID = UUID().uuidString
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
    @FocusState private var addFocused: Bool
    @FocusState private var quickRenameFocused: Bool
    @FocusState private var collectionNameFocused: Bool
    @FocusState private var canvasFocus: CanvasFocus?

    var body: some View {
        reviewSheets(collectionSheets(taskSheets(window)))
    }

    private var window: some View {
        NavigationSplitView(columnVisibility: $columns) {
            sidebar
                .navigationSplitViewColumnWidth(min: 310, ideal: 340, max: 400)
        } detail: {
            taskCanvas
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
        .disabled(model.isSaving)
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
        .onAppear { quickCapture.start(model: model) }
        .onDisappear { quickCapture.stop() }
        .task { await model.prepareVisibleQueries() }
        .onChange(of: model.destination) { _, _ in Task { await model.prepareVisibleQueries() } }
        .onChange(of: model.appliedSearch) { _, _ in Task { await model.prepareVisibleQueries() } }
        .onChange(of: model.appliedPriority) { _, _ in Task { await model.prepareVisibleQueries() } }
        .onChange(of: model.captureDraft) { _, draft in Task { await model.prepareCapturePreview(draft) } }
        .onChange(of: model.workspace.state) { _, _ in Task { await model.prepareVisibleQueries() } }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        // X-01 "sidebar hidden": in attention states only, the line's words and glyph; nothing
        // about sync in the toolbar otherwise.
        ToolbarItem(placement: .navigation) {
            SyncToolbarStatusItem(controller: sync, sidebarHidden: columns == .detailOnly)
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
            Picker(
                "Priority",
                selection: Binding(get: { model.priorityFilter }, set: { requestNavigation(.priorityFilter($0)) })
            ) {
                ForEach(PriorityFilter.allCases) { option in
                    Text(option.title).tag(option)
                }
            }
            .pickerStyle(.menu)
            .accessibilityLabel("Filter by priority")
        }
    }

    // MARK: Sidebar

    private var sidebar: some View {
        List {
            ForEach(SidebarEntries.standard.sections) { section in
                sidebarSection(section)
            }
            projectsSection
            archivedProjectsSection
            tagsSection
        }
        .listStyle(.sidebar)
        .navigationTitle("BrainBuddy")
        .safeAreaInset(edge: .bottom) { footer }
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
            HStack {
                Text("Projects")
                Spacer()
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
            Section("Archived projects") { querySidebarStatus(model.archivedProjectsReadiness) }
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
                        Spacer(minLength: 0)
                    }
                    .foregroundStyle(.secondary)
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
                .listRowBackground(model.destination == .tag(tag.id) ? Color.accentColor.opacity(0.22) : Color.clear)
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
            Text("Tags")
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
            Section(header) { sidebarRows(section.rows) }
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
        HStack(spacing: 10) {
            Image(systemName: row.symbol)
                .font(.system(size: 14, weight: .semibold))
                .frame(width: 20)
                .accessibilityHidden(true)
            Text(row.title)
                .lineLimit(1)
                .layoutPriority(1)
            Spacer(minLength: 0)
            Text(note)
                .font(.caption)
                .lineLimit(1)
        }
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 3)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(row.accessibilityLabel)
        .accessibilityAddTraits(.isStaticText)
        .listRowBackground(Color.clear)
        .selectionDisabled()
    }

    private func sidebarButton(
        _ title: String, symbol: String, destination: WorkspaceDestination, tint: Color? = nil
    ) -> some View {
        let count: Int? = {
            guard case .list(let list) = destination else { return nil }
            guard model.countsReadiness == .ready else { return nil }
            return model.sidebarCounts.count(for: list)
        }()
        return Button {
            requestNavigation(.destination(destination))
        } label: {
            HStack(spacing: 10) {
                Image(systemName: symbol)
                    .foregroundStyle(tint ?? .secondary)
                    .font(.system(size: 14, weight: .semibold))
                    .frame(width: 20)
                    .accessibilityHidden(true)
                Text(title)
                    .lineLimit(1)
                    .layoutPriority(1)
                Spacer(minLength: 0)
                if let count {
                    Text("\(count)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 2)
                        .background(.quaternary, in: Capsule())
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
        }
        .accessibilityLabel(count.map { "\(title), \($0) open tasks" } ?? title)
        .buttonStyle(.plain)
        .padding(.vertical, 3)
        .listRowBackground(model.destination == destination ? Color.accentColor.opacity(0.22) : Color.clear)
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
        Task {
            switch kind {
            case .project:
                if let id = await model.createProject(name, editorID: collectionCreateEditorID) {
                    collectionCreateEditorID = UUID().uuidString
                    addingCollection = nil
                    collectionName = ""
                    requestNavigation(.destination(.project(id)))
                }
            case .tag:
                if let id = await model.createTag(name, editorID: collectionCreateEditorID) {
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
        Task {
            let saved: Bool
            switch kind {
            case .project(let id): saved = await model.renameProject(id, to: name, editorID: collectionEditorID)
            case .tag(let id): saved = await model.renameTag(id, to: name, editorID: collectionEditorID)
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

    private func requestNavigation(_ next: PendingEditorNavigation) {
        let hasTaskEdits = selectedTaskID != nil && editorDirty
        let hasCaptureDraft = !model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || !model.waitingForDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if hasTaskEdits || (hasCaptureDraft && changesCaptureContext(next)) {
            pendingEditorNavigation = next
            confirmingDiscard = true
        } else {
            applyNavigation(next)
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

    private func select(_ id: TaskID?) {
        taskSaveEditorID = UUID().uuidString
        selectedTaskID = id
        editDraft = id.flatMap { model.task($0) }.map { TaskEditDraft($0) }
        selectionAnchor = id.map { SelectionAnchor(id: $0, in: visibleTaskIDs) }
        editorDirty = false
        editorCanSave = false
    }

    fileprivate func applyNavigation(_ navigation: PendingEditorNavigation) {
        pendingEditorNavigation = nil
        if case .signOut = navigation {
            // X-04 now; the editor and the drafts stay as they are until the sign-out happens, so a
            // Cancel in X-04 loses nothing (`BrainBuddyModel.didSignOut` clears them after).
            sync.presentSignOut()
            return
        }
        editorDirty = false
        editorCanSave = false
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
            Task {
                if await model.completeTask(id) {
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
                Task {
                    if await model.moveTask(id, to: destination) {
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
            Task {
                if await model.cancelTask(id) {
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
            clarifyingInbox = true
        case .groupByProject(let value):
            select(nil)
            model.groupByProject = value
        case .showCancelled(let value):
            select(nil)
            model.showCancelled = value
        case .priorityFilter(let value):
            select(nil)
            model.priorityFilter = value
            model.reload()
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
        model.priorityFilter = .all
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

    private var taskCanvas: some View {
        let sections = presentedSections(model.sections)
        let orders = Dictionary(sections.map { ($0.id, $0.rows.map(\.id)) }, uniquingKeysWith: { first, _ in first })
        let onScreen = sections.flatMap { $0.rows.map(\.id) }
        return VStack(alignment: .leading, spacing: 0) {
            canvasHeader
            canvasMessages
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 12) {
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
                    .disabled(!model.listPageState.hasPrevious)
                    Text("More results").font(.caption).foregroundStyle(.secondary)
                    Button("Next page") {
                        Task {
                            await model.workspace.nextListPage(model.destination.query, options: model.visibleListOptions)
                            model.refreshQueryPresentation()
                        }
                    }
                    .disabled(!model.listPageState.hasNext)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
            }
        }
        .frame(minWidth: 560, minHeight: 480)
        .onChange(of: orders, initial: true) { _, new in shownOrders = new }
        .onChange(of: onScreen) { _, ids in keepSelection(in: ids) }
        .onChange(of: selectedTaskID.flatMap { model.task($0) }) { _, task in
            guard let task, let draft = editDraft else { return }
            editDraft = draft.rebased(onto: task)
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
        if case .project(let id) = model.destination, let overview = model.projectOverview(id) {
            projectOverviewCard(overview)
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
                taskCard(task, departed: section.departed.contains(task.id), inProjectGroup: isProjectGroup(section.kind))
            }
        }
        if !isDateDestination && !model.destination.isHistory && !model.isArchivedProjectDestination {
            smartAdd
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
        Text(title.uppercased())
            .font(.caption.bold())
            .tracking(1.5)
            .foregroundStyle(.secondary)
            .padding(.top, top)
            .accessibilityAddTraits(.isHeader)
    }

    @ViewBuilder
    private func emptyState(isEmpty: Bool) -> some View {
        if isEmpty {
            if sync.tasksStillArriving, !model.hasAppliedTaskFilter {
                // X-01 "first load, empty list": one static neutral line, no spinner over content.
                Text(SyncCopy.popoverFirstLoadEmpty)
                    .foregroundStyle(.secondary)
            } else if model.isArchivedProjectDestination || isPreLosslessProject {
                if model.hasAppliedTaskFilter {
                    filteredEmptyState
                } else if model.isArchivedProjectDestination {
                    ContentUnavailableView(
                        "No tasks in this project", systemImage: "archivebox",
                        description: Text("Unarchive this project to add tasks to it.")
                    )
                }
            } else if model.hasAppliedTaskFilter, case .project = model.destination {
                filteredEmptyState
            } else if isDateDestination || model.destination.isHistory {
                ContentUnavailableView(model.destination.isHistory ? "No history" : "No tasks", systemImage: "checkmark.circle")
            }
        }
    }

    private var filteredEmptyState: some View {
        ContentUnavailableView(
            "No matching tasks", systemImage: "magnifyingglass",
            description: Text("Clear the search or priority filter to see this project's tasks.")
        )
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
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                    Button("Rename…") {
                        beginRename(
                            .project(refusal.projectID), name: model.project(refusal.projectID)?.name ?? "", fromRefusal: true
                        )
                    }
                }
                .font(.subheadline)
            }
            Text(taskCountCaption)
                .foregroundStyle(.secondary)
                .font(.subheadline)
            if model.isArchivedProjectDestination {
                Text("Unarchive this project to add tasks to it.")
                    .foregroundStyle(.secondary)
                    .font(.subheadline)
            }
            listControls
        }
        .padding(.horizontal, 28)
        .padding(.top, 28)
        .padding(.bottom, 20)
    }

    private var titleRow: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Text(destinationTitle)
                .font(.largeTitle.bold())
                .lineLimit(2)
                .focusable()
                .focused($canvasFocus, equals: .title)
                .accessibilityAddTraits(.isHeader)
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
        }
    }

    private var listControls: some View {
        HStack(spacing: 16) {
            if model.destination == .list(.inbox) {
                Button("Clarify Inbox") { requestNavigation(.clarifyInbox) }
                    .buttonStyle(.borderedProminent)
            }
            if model.destination == .list(.waiting) {
                Button("Review Waiting for") { requestNavigation(.reviewWaiting) }
                    .buttonStyle(.borderedProminent)
            }
            if model.destination == .list(.someday) {
                Button("Review Someday") { requestNavigation(.reviewSomeday) }
                    .buttonStyle(.borderedProminent)
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
        }
    }

    private var taskCountCaption: String {
        if model.destination.isHistory { return Self.plural(model.listResult?.totalCount ?? 0, "task") }
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
                    .font(.caption.bold())
                    .tracking(1.5)
                    .foregroundStyle(.secondary)
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
                    .font(.body.weight(.medium))
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Text(archived ? "No desired outcome." : "Define what will be true when this project is done.")
                    .foregroundStyle(.secondary)
            }
            Divider()
            if let next = overview.nextAction {
                Label("First Next action", systemImage: "arrow.right.circle")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(next.title)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Text(projectNextExplanation(overview))
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            if overview.display.showsPreLosslessLine {
                // FR-027: one neutral line; nothing says tasks were lost.
                Text("Archived before projects kept their tasks, so none are listed here. Those tasks are still in their lists.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 13))
        .overlay {
            RoundedRectangle(cornerRadius: 13)
                .strokeBorder(Color.accentColor.opacity(0.25))
                .allowsHitTesting(false)
        }
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
        Task {
            if await model.saveTask(task.id, changes: TaskChanges(title: .set(title)), editorID: quickRenameEditorID) {
                quickRenameEditorID = UUID().uuidString
                renamingTask = nil
                quickRenameError = nil
            } else {
                quickRenameError = model.error ?? "The task title could not be saved. Try again."
            }
        }
    }

    private func taskCard(_ task: TaskRecord, departed: Bool = false, inProjectGroup: Bool = false) -> some View {
        let selected = selectedTaskID == task.id
        return VStack(spacing: 0) {
            taskRowLine(task, selected: selected, showsProject: !inProjectGroup)
            if task.state == .waiting, let waitingFor = task.waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines),
                !waitingFor.isEmpty
            {
                HStack(spacing: 4) {
                    Text("Waiting for \(waitingFor)").lineLimit(1)
                    if let since = task.waitingSince {
                        Text("· since")
                        Text(since, style: .date)
                    }
                    Spacer(minLength: 0)
                }
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.leading, 45)
                .padding(.trailing, 13)
                .padding(.bottom, 8)
            }
            if selected {
                if task.state.isTerminal {
                    terminalDetail(task)
                        .padding(.horizontal, 18)
                        .padding(.bottom, 16)
                } else if editDraft != nil {
                    inlineEditor(task)
                        .padding(.horizontal, 18)
                        .padding(.bottom, 16)
                }
            }
        }
        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 13))
        .overlay {
            RoundedRectangle(cornerRadius: 13)
                .strokeBorder(selected ? Color.accentColor.opacity(0.7) : Color.primary.opacity(0.12))
                .allowsHitTesting(false)
        }
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

    @ViewBuilder
    private func taskRowLine(_ task: TaskRecord, selected: Bool, showsProject: Bool) -> some View {
        HStack(spacing: 12) {
            if task.state.isTerminal {
                Image(systemName: task.state == .completed ? "checkmark.circle.fill" : "xmark.circle")
                    .font(.title3)
                    .foregroundStyle(.secondary)
                Button {
                    requestNavigation(.task(selected ? nil : task.id))
                } label: {
                    Text(task.title)
                        .font(.body.weight(.semibold))
                        .lineLimit(1)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("View \(task.title)")
                .accessibilityValue(selected ? "Expanded" : "Collapsed")
            } else {
                Button {
                    requestNavigation(.complete(task.id))
                } label: {
                    Image(systemName: "circle").font(.title3)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Complete \(task.title)")
                if selected, editDraft != nil {
                    TextField("Task title", text: draftBinding(\.title, default: ""))
                        .font(.body.weight(.semibold))
                        .textFieldStyle(.plain)
                } else {
                    Button {
                        requestNavigation(.task(selected ? nil : task.id))
                    } label: {
                        Text(task.title)
                            .font(.body.weight(.semibold))
                            .lineLimit(1)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Edit \(task.title)")
                    .accessibilityValue(selected ? "Expanded" : "Collapsed")
                    .contextMenu {
                        Button("Rename title…") { beginQuickRename(task) }
                            .disabled(selectedTaskID != nil)
                    }
                }
            }
            Spacer(minLength: 8)
            if showsProject, let projectID = task.projectID, model.destination != .project(projectID) {
                Text(model.projectLabel(projectID))
                    .font(.caption)
                    .lineLimit(1)
                    .foregroundStyle(.secondary)
            }
            if let id = task.tagIDs.first, let tag = model.tag(id) {
                Text("#\(tag.name)")
                    .font(.caption)
                    .lineLimit(1)
                    .foregroundStyle(tagTint(id))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(tagTint(id).opacity(0.15), in: Capsule())
            }
            if task.tagIDs.count > 1 {
                Text("+\(task.tagIDs.count - 1)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let due = task.dueDate {
                Text(due.isoString).font(.caption).foregroundStyle(.secondary)
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
        .padding(.horizontal, 13)
        .frame(minHeight: 42)
    }

    /// A binding into the open editor's `TaskEditDraft`.
    private func draftBinding<Value>(_ keyPath: WritableKeyPath<TaskEditDraft, Value>, default fallback: Value) -> Binding<Value> {
        Binding(
            get: { editDraft?[keyPath: keyPath] ?? fallback },
            set: { value in editDraft?[keyPath: keyPath] = value }
        )
    }

    private func inlineEditor(_ task: TaskRecord) -> some View {
        TaskInlineEditor(
            task: task,
            draft: Binding(get: { editDraft ?? TaskEditDraft(task) }, set: { editDraft = $0 }),
            projects: model.projects, labelForProject: { model.projectLabel($0) }, tags: model.tags,
            saveRequest: editorSaveRequest
        ) { changes, list in
            Task {
            if await model.saveTask(task.id, changes: changes, moveTo: list, editorID: taskSaveEditorID) {
                taskSaveEditorID = UUID().uuidString
                editorDirty = false
                editorCanSave = false
                if let pending = pendingEditorNavigation {
                    pendingEditorNavigation = nil
                    requestNavigation(pending)
                } else {
                    select(nil)
                }
            } else {
                pendingEditorNavigation = nil
            }
            }
        } onCancel: {
            select(nil)
        } onCreateProject: { name, editorID in
            await model.createProject(name, editorID: editorID)
        } onEditorStateChange: { dirty, canSave in
            editorDirty = dirty
            editorCanSave = canSave
        } onCancelTask: {
            requestNavigation(.cancel(task.id))
        } extras: { onExtrasDirtyChange in
            TaskDetailExtras(task: task, model: model, onDirtyChange: onExtrasDirtyChange)
        }
    }

    private func terminalDetail(_ detail: TaskRecord) -> some View {
        let statusDate = detail.state == .completed ? detail.completedAt : detail.cancelledAt
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Text(detail.state == .completed ? "Completed" : "Cancelled")
                    .fontWeight(.semibold)
                if let statusDate {
                    Text("·")
                    Text(statusDate, style: .date)
                }
                Spacer()
                Button("Close details") { select(nil) }
                    .buttonStyle(.plain)
            }
            .foregroundStyle(.secondary)
            Text(detail.lastOpenList.map { "Previously in \($0.title)" } ?? "Previous list unknown")
                .font(.caption)
                .foregroundStyle(.secondary)
            if let description = detail.details, !description.isEmpty {
                Text(description)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            if let projectID = detail.projectID {
                Text("Project · \(model.projectLabel(projectID))")
                    .font(.caption)
            }
            if !detail.tagIDs.isEmpty {
                let names = detail.tagIDs.map { id in model.tag(id).map { "#\($0.name)" } ?? "#" }
                Text("Tags · \(names.joined(separator: "  "))")
                    .font(.caption)
            }
            if let due = detail.dueDate {
                Text("Due · \(due.isoString)").font(.caption)
            }
            if detail.priority != .none {
                Text("Priority · \(detail.priority.rawValue.capitalized)").font(.caption)
            }
            if !detail.subtasks.isEmpty {
                DisclosureGroup("Subtasks · \(detail.subtasks.count)") {
                    VStack(alignment: .leading, spacing: 5) {
                        ForEach(detail.subtasks.sorted { $0.orderKey < $1.orderKey }) { subtask in
                            Label(subtask.title, systemImage: subtask.state == .completed ? "checkmark.circle.fill" : "circle")
                                .font(.subheadline)
                        }
                    }
                }
            }
            if !detail.comments.isEmpty {
                DisclosureGroup("Comments · \(detail.comments.count)") {
                    VStack(alignment: .leading, spacing: 6) {
                        ForEach(detail.comments) { comment in
                            Text(comment.body)
                                .font(.subheadline)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: Smart Add

    private var capturePreviewStatus: String {
        if case .failed = model.capturePreviewReadiness { return "Preview couldn’t load" }
        return "Preparing preview…"
    }

    private var smartAdd: some View {
        let preview = model.capturePreview
        let hasDraft = !model.draft.isEmpty
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 12) {
                Image(systemName: "plus.circle")
                    .font(.title3)
                    .foregroundStyle(.secondary)
                TextField("Add a task", text: $model.draft)
                    .textFieldStyle(.plain)
                    .focused($addFocused)
                    .onSubmit { requestNavigation(.createTask) }
            }
            if model.selectedList == .waiting {
                TextField("Waiting for person, event, or condition", text: $model.waitingForDraft)
                    .onSubmit { requestNavigation(.createTask) }
            }
            if hasDraft || model.selectedList == .waiting {
                HStack {
                    if model.capturePreviewReadiness == .ready, !preview.tokens.isEmpty, !preview.title.isEmpty {
                        Text("“\(preview.title)”")
                            .font(.caption.weight(.semibold))
                            .lineLimit(1)
                    }
                    if model.capturePreviewReadiness == .ready {
                        Text("Will save in \(model.selectedList.title)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    } else {
                        Text(capturePreviewStatus)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if case .failed = model.capturePreviewReadiness {
                        Button("Retry preview") { Task { await model.prepareCapturePreview(model.captureDraft) } }
                    }
                    Button("Add task") { requestNavigation(.createTask) }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.capturePreviewReadiness != .ready || addDisabled(preview))
                }
                if model.capturePreviewReadiness == .ready {
                    Text(previewClassification(preview))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if model.capturePreviewReadiness == .ready, hasDraft, let problem = preview.problemMessage, preview.problem != .emptyTitle {
                    Text(problem)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if model.hasAppliedTaskFilter || !model.searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    || model.priorityFilter != .all
                {
                    Text("Current search or priority filter may hide the new task from this list.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            if let notice = model.captureNotice {
                Text(notice)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if model.hasAppliedTaskFilter {
                    Button("Clear search and priority filter") { requestNavigation(.clearTaskFilters) }
                        .font(.caption)
                }
            }
        }
        .textFieldStyle(.roundedBorder)
        .padding(13)
        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 13))
        .overlay {
            RoundedRectangle(cornerRadius: 13)
                .strokeBorder(Color.primary.opacity(0.12))
                .allowsHitTesting(false)
        }
    }

    private func previewClassification(_ preview: CapturePreview) -> String {
        let project = preview.project.map { $0.isNew ? "\($0.name) (new project)" : $0.name } ?? "No project"
        let tags = preview.tags.map { $0.isNew ? "#\($0.name) (new tag)" : "#\($0.name)" }
        return ([project] + (tags.isEmpty ? ["No tags"] : tags)).joined(separator: " · ")
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
            }
            .sheet(item: $renamingTask) { task in
                quickRenameSheet(task)
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
            }
            .confirmationDialog("Discard unsaved changes?", isPresented: $confirmingDiscard) {
                if selectedTaskID != nil && editorDirty {
                    Button("Save task") { editorSaveRequest += 1 }
                        .disabled(!editorCanSave)
                }
                Button("Discard changes", role: .destructive) {
                    if let pending = pendingEditorNavigation {
                        // Sign-out removes the drafts only once it happens (X-04 can still be cancelled).
                        if changesCaptureContext(pending), !Self.isSignOut(pending) {
                            model.draft = ""
                            model.waitingForDraft = ""
                        }
                        applyNavigation(pending)
                    }
                }
                Button("Keep editing", role: .cancel) { pendingEditorNavigation = nil }
            } message: {
                Text(
                    selectedTaskID == nil
                        ? "The new task draft has not been saved."
                        : "Unsaved task fields and unfinished drafts will be discarded. Subtasks and comments already saved will stay saved."
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
            }
            .sheet(item: $reopeningTask) { task in
                reopenSheet(task)
            }
            .sheet(item: $movingTask) { task in
                moveToWaitingSheet(task)
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
        VStack(alignment: .leading, spacing: 16) {
            Text("Add task to").font(.title2.bold())
            Picker("GTD list", selection: $captureListChoice) {
                ForEach(TaskList.allCases) { list in
                    Text(list.title).tag(list)
                }
            }
            .pickerStyle(.radioGroup)
            HStack {
                Spacer()
                Button("Cancel") { choosingCaptureList = false }
                    .keyboardShortcut(.cancelAction)
                Button("Continue") {
                    model.choose(.list(captureListChoice))
                    focusCaptureAfterChoice = true
                    choosingCaptureList = false
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .frame(width: 360)
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
                    Task { if await model.reopenTask(task.id, to: reopenDestination, waitingFor: reopenWaitingFor, editorID: reopenEditorID) { reopeningTask = nil; reopenEditorID = UUID().uuidString } }
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
                    Task { if await model.moveTask(task.id, to: .waiting, waitingFor: moveWaitingFor, editorID: moveWaitingEditorID) { movingTask = nil; moveWaitingEditorID = UUID().uuidString } }
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
            }
            .sheet(item: $editingCollection) { kind in
                renameSheet(kind)
            }
            .sheet(item: $editingOutcomeProject) { project in
                outcomeSheet(project)
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
                    Task { if await model.saveProjectOutcome(project.id, to: outcomeDraft, editorID: projectOutcomeEditorID) { editingOutcomeProject = nil; projectOutcomeEditorID = UUID().uuidString } }
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
            }
            .sheet(isPresented: $reviewingSomeday) {
                SomedayReviewView(model: model)
            }
            .sheet(isPresented: $reviewingProjects) {
                ProjectReviewView(model: model) { id in
                    reviewingProjects = false
                    requestNavigation(.destination(.project(id)))
                }
            }
            .sheet(isPresented: $clarifyingInbox) {
                InboxClarifyView(model: model)
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

// MARK: - The inline editor

/// The task editor: it edits a `TaskEditDraft`, so saving sends only the fields the person
/// touched (FR-009), and a change arriving meanwhile is rebased in by the window.
private struct TaskInlineEditor<Extras: View>: View {
    let task: TaskRecord
    @Binding var draft: TaskEditDraft
    let projects: [ProjectRecord]
    let labelForProject: (ProjectID) -> String
    let tags: [TagRecord]
    let saveRequest: Int
    let onSave: (TaskChanges, TaskList?) -> Void
    let onCancel: () -> Void
    let onCreateProject: (String, String) async -> ProjectID?
    let onEditorStateChange: (Bool, Bool) -> Void
    let onCancelTask: () -> Void
    let extras: (@escaping (Bool) -> Void) -> Extras

    @State private var extrasDirty = false
    @State private var list: TaskList
    @State private var showingProjectCreator = false
    @State private var newProjectName = ""
    @State private var newProjectEditorID = UUID().uuidString
    @State private var isCreatingProject = false
    @State private var showProperties: Bool

    init(
        task: TaskRecord, draft: Binding<TaskEditDraft>, projects: [ProjectRecord],
        labelForProject: @escaping (ProjectID) -> String, tags: [TagRecord], saveRequest: Int,
        onSave: @escaping (TaskChanges, TaskList?) -> Void,
        onCancel: @escaping () -> Void,
        onCreateProject: @escaping (String, String) async -> ProjectID?,
        onEditorStateChange: @escaping (Bool, Bool) -> Void,
        onCancelTask: @escaping () -> Void,
        @ViewBuilder extras: @escaping (@escaping (Bool) -> Void) -> Extras
    ) {
        self.task = task
        _draft = draft
        self.projects = projects
        self.labelForProject = labelForProject
        self.tags = tags
        self.saveRequest = saveRequest
        self.onSave = onSave
        self.onCancel = onCancel
        self.onCreateProject = onCreateProject
        self.onEditorStateChange = onEditorStateChange
        self.onCancelTask = onCancelTask
        self.extras = extras
        _list = State(initialValue: task.state.openList ?? .next)
        _showProperties = State(initialValue: task.dueDate != nil || task.priority != .none || !task.tagIDs.isEmpty)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Button("Save task", action: saveChanges)
                    .buttonStyle(.borderedProminent)
                    .keyboardShortcut("s", modifiers: [.command])
                    .disabled(saveDisabled)
                Button(isDirty ? "Discard task edits" : "Close", action: onCancel)
                    .keyboardShortcut(.cancelAction)
                Spacer()
                Menu("More") {
                    Button("Cancel task", role: .destructive, action: onCancelTask)
                }
            }
            Text("Notes and context")
                .font(.caption)
                .foregroundStyle(.secondary)
            TextEditor(text: details)
                .font(.body)
                .scrollContentBackground(.hidden)
                .frame(height: 120)
                .padding(5)
                .background(.quaternary.opacity(0.45), in: RoundedRectangle(cornerRadius: 8))
                .accessibilityLabel("Notes and context")
            HStack(alignment: .top, spacing: 16) {
                Picker("GTD list", selection: $list) {
                    ForEach(TaskList.allCases) { value in
                        Text(value.title).tag(value)
                    }
                }
                .pickerStyle(.menu)
                .frame(maxWidth: .infinity, alignment: .leading)
                VStack(alignment: .leading, spacing: 4) {
                    projectPicker
                    Button("New project…") {
                        newProjectEditorID = UUID().uuidString
                        showingProjectCreator = true
                    }
                        .font(.caption)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            if list == .waiting {
                TextField("Waiting for person, event, or condition", text: waitingFor)
                    .accessibilityLabel("Waiting for person, event, or condition")
            }
            DisclosureGroup(isExpanded: $showProperties) {
                properties.padding(.top, 8)
            } label: {
                HStack {
                    Text("Date, priority, and tags")
                    Spacer()
                    Text(propertySummary)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            extras { extrasDirty = $0 }
            if extrasDirty {
                Text("Finish the pending subtask or comment edit before saving the task.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .textFieldStyle(.roundedBorder)
        .padding(.top, 12)
        // presentation-region: project creator sheet
        .sheet(isPresented: $showingProjectCreator, onDismiss: {
            newProjectEditorID = UUID().uuidString
            isCreatingProject = false
        }) {
            projectCreator.interactiveDismissDisabled(isCreatingProject)
        }
        // presentation-region-end
        .onAppear { onEditorStateChange(isDirty, !saveDisabled) }
        .onChange(of: isDirty) { _, _ in onEditorStateChange(isDirty, !saveDisabled) }
        .onChange(of: saveDisabled) { _, _ in onEditorStateChange(isDirty, !saveDisabled) }
        .onChange(of: saveRequest) { _, _ in saveChanges() }
    }

    /// "No project", the active projects, and the task's own archived project as
    /// "Old flat · archived" (X-06).
    private var projectPicker: some View {
        Picker("Project", selection: $draft.projectID) {
            Text("No project").tag(ProjectID?.none)
            if let current = draft.projectID, !projects.contains(where: { $0.id == current }) {
                Text(labelForProject(current)).tag(ProjectID?.some(current))
            }
            ForEach(projects) { project in
                Text(project.name).tag(ProjectID?.some(project.id))
            }
        }
        .pickerStyle(.menu)
    }

    private var properties: some View {
        VStack(alignment: .leading, spacing: 10) {
            Toggle(
                "Due date",
                isOn: Binding(
                    get: { draft.dueDate != nil },
                    set: { draft.dueDate = $0 ? CalendarDay(date: Date()) : nil }
                )
            )
            if let due = draft.dueDate {
                DatePicker(
                    "Choose date",
                    selection: Binding(get: { due.startDate() }, set: { draft.dueDate = CalendarDay(date: $0) }),
                    displayedComponents: .date
                )
                .datePickerStyle(.compact)
            }
            Picker("Priority", selection: $draft.priority) {
                ForEach(TaskPriority.allCases, id: \.self) { value in
                    Text(value.rawValue.capitalized).tag(value)
                }
            }
            if !tags.isEmpty {
                VStack(alignment: .leading, spacing: 5) {
                    Text("Tags").font(.caption).foregroundStyle(.secondary)
                    ChipFlowLayout(spacing: 6) {
                        ForEach(tags.filter { draft.tagIDs.contains($0.id) }) { tag in
                            Button {
                                draft.tagIDs.removeAll { $0 == tag.id }
                            } label: {
                                Label("#\(tag.name)", systemImage: "xmark")
                                    .font(.caption)
                                    .foregroundStyle(tagTint(tag.id))
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 4)
                                    .background(tagTint(tag.id).opacity(0.16), in: Capsule())
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("Remove \(tag.name) tag")
                        }
                        Menu {
                            ForEach(tags.filter { !draft.tagIDs.contains($0.id) }) { tag in
                                Button("#\(tag.name)") { draft.tagIDs.append(tag.id) }
                            }
                        } label: {
                            Label("Add tag", systemImage: "plus")
                                .font(.caption)
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(.quaternary, in: Capsule())
                        }
                        .menuStyle(.borderlessButton)
                    }
                }
            }
        }
    }

    private var projectCreator: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("New project").font(.title2.bold())
            TextField("Project name", text: $newProjectName)
                .disabled(isCreatingProject)
            HStack {
                Spacer()
                Button("Cancel") {
                    showingProjectCreator = false
                    newProjectEditorID = UUID().uuidString
                }
                    .keyboardShortcut(.cancelAction)
                    .disabled(isCreatingProject)
                Button("Add project") {
                    guard !isCreatingProject else { return }
                    let authored = newProjectName
                    let editorID = newProjectEditorID
                    isCreatingProject = true
                    Task {
                        let projectID = await onCreateProject(authored, editorID)
                        guard newProjectEditorID == editorID, isCreatingProject else { return }
                        isCreatingProject = false
                        guard showingProjectCreator, newProjectName == authored,
                              let projectID else { return }
                        draft.projectID = projectID
                        newProjectName = ""
                        showingProjectCreator = false
                        newProjectEditorID = UUID().uuidString
                    }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(isCreatingProject || newProjectName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(22)
        .frame(width: 340)
    }

    private var details: Binding<String> {
        Binding(get: { draft.details ?? "" }, set: { draft.details = $0.isEmpty ? nil : $0 })
    }

    private var waitingFor: Binding<String> {
        Binding(get: { draft.waitingFor ?? "" }, set: { draft.waitingFor = $0.isEmpty ? nil : $0 })
    }

    /// The draft as it is saved: the title trimmed, so spaces alone are not a change.
    private var normalized: TaskEditDraft {
        var normalized = draft
        normalized.title = draft.title.trimmingCharacters(in: .whitespacesAndNewlines)
        return normalized
    }

    private var moveTo: TaskList? { list.taskState == task.state ? nil : list }

    private func saveChanges() {
        guard taskFieldsDirty, !saveDisabled else { return }
        onSave(normalized.changes(), moveTo)
    }

    private var taskFieldsDirty: Bool { normalized.changes().hasChanges || moveTo != nil }

    private var isDirty: Bool { taskFieldsDirty || extrasDirty }

    private var saveDisabled: Bool {
        let title = normalized.title
        let waiting = (draft.waitingFor ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return !taskFieldsDirty || extrasDirty || title.isEmpty || !EditorLimits.fits(title, EditorLimits.title)
            || !EditorLimits.fits(draft.details ?? "", EditorLimits.details)
            || (list == .waiting && (waiting.isEmpty || !EditorLimits.fits(waiting, EditorLimits.waitingFor)))
    }

    private var propertySummary: String {
        var parts: [String] = []
        if draft.dueDate != nil { parts.append("Due") }
        if draft.priority != .none { parts.append(draft.priority.rawValue.capitalized) }
        if !draft.tagIDs.isEmpty { parts.append("\(draft.tagIDs.count) tags") }
        return parts.isEmpty ? "Optional" : parts.joined(separator: " · ")
    }
}

private struct ChipFlowLayout: Layout {
    let spacing: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        arrange(subviews, width: proposal.width ?? 500).size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let arranged = arrange(subviews, width: bounds.width)
        for (index, subview) in subviews.enumerated() {
            subview.place(
                at: CGPoint(x: bounds.minX + arranged.positions[index].x, y: bounds.minY + arranged.positions[index].y),
                proposal: .unspecified
            )
        }
    }

    private func arrange(_ subviews: Subviews, width: CGFloat) -> (positions: [CGPoint], size: CGSize) {
        var positions: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            positions.append(CGPoint(x: x, y: y))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        return (positions, CGSize(width: width, height: y + rowHeight))
    }
}

/// Subtasks and comments: each saves at once through the kit, as before.
private struct TaskDetailExtras: View {
    let task: TaskRecord
    let model: BrainBuddyModel
    let onDirtyChange: (Bool) -> Void
    @State private var newSubtask = ""
    @State private var newComment = ""
    @State private var newSubtaskEditorID = UUID().uuidString
    @State private var newCommentEditorID = UUID().uuidString
    @State private var modifiedIDs: Set<String> = []
    @State private var subtaskTitles: [SubtaskID: String] = [:]
    @State private var commentBodies: [CommentID: String] = [:]
    @State private var editingCommentIDs: Set<CommentID> = []

    private var completedSubtasks: Int { task.subtasks.filter { $0.state == .completed }.count }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            DisclosureGroup("Subtasks · \(completedSubtasks) / \(task.subtasks.count)") {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(task.subtasks.sorted { $0.orderKey < $1.orderKey }) { subtask in
                        SubtaskLine(
                            taskID: task.id, subtask: subtask, model: model, title: subtaskTitle(for: subtask),
                            onSaved: {
                                subtaskTitles.removeValue(forKey: subtask.id)
                                setModified("subtask-\(subtask.id.rawValue)", dirty: false)
                            }
                        )
                    }
                    HStack {
                        TextField("New subtask", text: $newSubtask)
                            .onSubmit { addSubtask() }
                        Button("Add subtask") { addSubtask() }
                            .disabled(
                                newSubtask.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                    || !EditorLimits.fits(newSubtask, EditorLimits.title)
                            )
                    }
                }
                .padding(.top, 6)
            }
            DisclosureGroup("Comments · \(task.comments.count)") {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(task.comments) { comment in
                        CommentLine(
                            taskID: task.id, comment: comment, model: model, canEdit: model.isOwnComment(comment),
                            editing: commentEditing(for: comment), draftBody: commentBody(for: comment),
                            onFinished: {
                                commentBodies.removeValue(forKey: comment.id)
                                setModified("comment-\(comment.id.rawValue)", dirty: false)
                            }
                        )
                    }
                    TextField("Write a comment", text: $newComment, axis: .vertical)
                        .lineLimit(2...4)
                    Button("Add comment") {
                        let authored = newComment
                        let editorID = newCommentEditorID
                        Task { if await model.addComment(to: task.id, body: authored, editorID: editorID) {
                            newComment = ""
                            newCommentEditorID = UUID().uuidString
                        } }
                    }
                    .disabled(
                        newComment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || !EditorLimits.fits(newComment, EditorLimits.comment)
                    )
                }
                .padding(.top, 6)
            }
            Text("Subtasks and comments save immediately. Discard keeps those saved changes.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .font(.subheadline)
        .onChange(of: newSubtask) { _, _ in reportDirty() }
        .onChange(of: newComment) { _, _ in reportDirty() }
    }

    private func setModified(_ id: String, dirty: Bool) {
        if dirty { modifiedIDs.insert(id) } else { modifiedIDs.remove(id) }
        reportDirty()
    }

    private func subtaskTitle(for subtask: SubtaskRecord) -> Binding<String> {
        Binding(
            get: { subtaskTitles[subtask.id] ?? subtask.title },
            set: { value in
                subtaskTitles[subtask.id] = value
                setModified("subtask-\(subtask.id.rawValue)", dirty: value != subtask.title)
            }
        )
    }

    private func commentEditing(for comment: CommentRecord) -> Binding<Bool> {
        Binding(
            get: { editingCommentIDs.contains(comment.id) },
            set: { editing in
                if editing { editingCommentIDs.insert(comment.id) } else { editingCommentIDs.remove(comment.id) }
                setModified(
                    "comment-\(comment.id.rawValue)", dirty: editing && (commentBodies[comment.id] ?? comment.body) != comment.body
                )
            }
        )
    }

    private func commentBody(for comment: CommentRecord) -> Binding<String> {
        Binding(
            get: { commentBodies[comment.id] ?? comment.body },
            set: { value in
                commentBodies[comment.id] = value
                setModified(
                    "comment-\(comment.id.rawValue)", dirty: editingCommentIDs.contains(comment.id) && value != comment.body
                )
            }
        )
    }

    private func reportDirty() {
        onDirtyChange(
            !newSubtask.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || !newComment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !modifiedIDs.isEmpty
        )
    }

    private func addSubtask() {
        let authored = newSubtask
        let editorID = newSubtaskEditorID
        Task { if await model.addSubtask(to: task.id, title: authored, editorID: editorID) {
            newSubtask = ""
            newSubtaskEditorID = UUID().uuidString
        } }
    }
}

private struct SubtaskLine: View {
    let taskID: TaskID
    let subtask: SubtaskRecord
    let model: BrainBuddyModel
    @Binding var title: String
    let onSaved: () -> Void
    @State private var editorID = UUID().uuidString

    var body: some View {
        HStack {
            Button {
                Task {
                    if await model.toggleSubtask(subtask, in: taskID, editorID: editorID) { editorID = UUID().uuidString }
                }
            } label: {
                Image(systemName: subtask.state == .completed ? "checkmark.circle.fill" : "circle")
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(subtask.state == .completed ? "Reopen" : "Complete") \(subtask.title)")
            TextField("Subtask title", text: $title)
                .onSubmit { saveTitle() }
            if title != subtask.title {
                Button("Save") { saveTitle() }
                    .disabled(
                        title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || !EditorLimits.fits(title, EditorLimits.title)
                    )
            }
        }
    }

    private func saveTitle() {
        guard title != subtask.title else { return }
        let authored = title
        Task { if await model.renameSubtask(subtask.id, in: taskID, title: authored, editorID: editorID) {
            editorID = UUID().uuidString
            onSaved()
        } }
    }
}

private struct CommentLine: View {
    let taskID: TaskID
    let comment: CommentRecord
    let model: BrainBuddyModel
    let canEdit: Bool
    @Binding var editing: Bool
    @Binding var draftBody: String
    let onFinished: () -> Void
    @State private var editorID = UUID().uuidString

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            if editing {
                TextField("Comment", text: $draftBody, axis: .vertical)
                    .lineLimit(2...4)
                HStack {
                    Button("Save") {
                        let authored = draftBody
                        Task { if await model.editComment(comment.id, in: taskID, body: authored, editorID: editorID) {
                            editing = false
                            editorID = UUID().uuidString
                            onFinished()
                        } }
                    }
                    .disabled(
                        draftBody.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            || !EditorLimits.fits(draftBody, EditorLimits.comment)
                    )
                    Button("Cancel") {
                        editing = false
                        editorID = UUID().uuidString
                        onFinished()
                    }
                }
            } else {
                Text(comment.body)
                    .frame(maxWidth: .infinity, alignment: .leading)
                if canEdit {
                    Button("Edit comment") { editing = true }
                        .font(.caption)
                }
            }
        }
        .padding(8)
        .background(.quinary, in: RoundedRectangle(cornerRadius: 8))
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
        .interactiveDismissDisabled(step != .decision)
        // presentation-region: project creator sheet
        .sheet(isPresented: $showingProjectCreator) { projectCreator }
        // presentation-region-end
        // presentation-region: clarify confirmations
        .confirmationDialog("Cancel this Inbox item?", isPresented: $confirmingCancel) {
            Button("Cancel task", role: .destructive) {
                guard index < items.count else { return }
                Task { if await model.cancelTask(items[index].id) { advance() } }
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
            if item.priority != .none {
                Text("Priority · \(item.priority.rawValue.capitalized)")
                    .font(.caption).foregroundStyle(.secondary)
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
                    Task { if let id = await model.createProject(authored, editorID: newProjectEditorID) {
                        newProjectEditorID = UUID().uuidString
                        stagedProjectID = id
                        newProjectName = ""
                        showingProjectCreator = false
                    } }
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
                Task { if await model.saveTask(item.id, changes: changes, moveTo: .next, editorID: editorID) { advance() } }
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
                Task { if await model.saveTask(item.id, changes: changes, moveTo: .someday, editorID: editorID) { advance() } }
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
                Text("Existing notes, tags, date, and priority stay on the resulting Next action.")
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
        }
    }

    private func submit(_ item: TaskRecord) {
        guard isValidAnswer else { return }
        switch step {
        case .decision:
            break
        case .nextTitle:
            let title = proposedTitle.trimmingCharacters(in: .whitespacesAndNewlines)
            let changes = withStagedProject(title == item.title ? TaskChanges() : TaskChanges(title: .set(title)))
            Task { if await model.saveTask(item.id, changes: changes, moveTo: .next, editorID: editorID) { advance() } }
        case .waitingReason:
            step = .waitingTitle
        case .waitingTitle:
            let title = proposedTitle.trimmingCharacters(in: .whitespacesAndNewlines)
            let reason = waitingReason.trimmingCharacters(in: .whitespacesAndNewlines)
            let changes = withStagedProject(
                TaskChanges(title: title == item.title ? .unchanged : .set(title), waitingFor: .set(reason))
            )
            Task { if await model.saveTask(item.id, changes: changes, moveTo: .waiting, editorID: editorID) { advance() } }
        case .projectName:
            step = .projectOutcome
        case .projectOutcome:
            step = .projectAction
        case .projectAction:
            let outcome = desiredOutcome.trimmingCharacters(in: .whitespacesAndNewlines)
            let projectName = projectName.trimmingCharacters(in: .whitespacesAndNewlines)
            let firstAction = firstAction.trimmingCharacters(in: .whitespacesAndNewlines)
            Task { if await model.clarifyInboxAsProject(item.id, projectName: projectName,
                outcome: outcome.isEmpty ? nil : outcome, firstAction: firstAction,
                projectID: clarifyProjectID, editorID: editorID) { advance() } }
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

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Review Waiting for").font(.title2.bold())
                    Text(loaded ? (items.isEmpty ? "No items due" : "\(min(index + 1, items.count)) of \(items.count)") : "One item at a time")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Close review") { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }
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
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(24)
        .frame(width: 640, height: 480)
        .onAppear(perform: load)
        // presentation-region: cancel task confirmations
        .confirmationDialog("Cancel this task?", isPresented: $confirmingCancel) {
            Button("Cancel task", role: .destructive) {
                guard index < items.count else { return }
                Task { if await model.cancelTask(items[index].id) { advance() } }
            }
            Button("Keep task", role: .cancel) {}
        } message: {
            Text("The task will move to history. No message will be sent.")
        }
        // presentation-region-end
    }

    private func card(_ item: TaskRecord) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(item.title).font(.title3.weight(.semibold))
                .frame(maxWidth: .infinity, alignment: .leading)
            if let details = item.details, !details.isEmpty {
                Text(details)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .lineLimit(4)
            }
            Label("Waiting for \(item.waitingFor ?? "an unspecified response")", systemImage: "hourglass")
                .font(.subheadline.weight(.medium))
            if let date = item.waitingSince {
                Text("Since \(date.formatted(date: .abbreviated, time: .omitted))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            if let projectID = item.projectID {
                Text("Project · \(model.projectLabel(projectID))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
    }

    private func decisionForm(_ item: TaskRecord, decision: WaitingReviewDecision) -> some View {
        let archived = model.isArchived(item.projectID)
        return VStack(alignment: .leading, spacing: 10) {
            Text(decision == .followUp ? "What will you do to follow up?" : "What is the next action now?")
                .font(.headline)
            TextField("Concrete next action", text: $actionTitle)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel("Concrete next action")
                .onSubmit { submit(item, decision: decision) }
            Text(
                decision == .followUp
                    ? (archived
                        ? "Unarchive this project before creating a follow-up in it."
                        : "Creates a separate Next action in the same project. This item stays in Waiting and returns to review after seven days or a change.")
                    : "Moves this item to Next actions and clears its active waiting details."
            )
            .font(.caption)
            .foregroundStyle(.secondary)
            HStack {
                Button("Back") { self.decision = nil }
                Spacer()
                Button(decision == .followUp ? "Create follow-up" : "Move to Next actions") {
                    submit(item, decision: decision)
                }
                .buttonStyle(.borderedProminent)
                .disabled(!validAnswer(actionTitle, limit: EditorLimits.title) || (decision == .followUp && archived))
            }
        }
    }

    @ViewBuilder
    private func choices(_ item: TaskRecord) -> some View {
        let archived = model.isArchived(item.projectID)
        Text("What should happen next?")
            .font(.headline)
        HStack(spacing: 10) {
            Button("Keep waiting") {
                Task { if await model.keepWaiting(item) { advance() } }
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
        if archived {
            Text("Unarchive the project to add a follow-up there.")
                .font(.caption)
                .foregroundStyle(.secondary)
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
        guard validAnswer(actionTitle, limit: EditorLimits.title) else { return }
        let title = actionTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        switch decision {
        case .followUp:
            Task { if await model.createFollowUp(for: item.id, title: title, taskID: followUpTaskID, editorID: editorID, shownTask: item) { advance() } }
            return
        case .returnToNext:
            let changes = title == item.title ? TaskChanges() : TaskChanges(title: .set(title))
            Task { if await model.saveTask(item.id, changes: changes, moveTo: .next, editorID: editorID) { advance() } }
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

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                VStack(alignment: .leading, spacing: 3) {
                    Text("Review Someday").font(.title2.bold())
                    Text(loaded ? (items.isEmpty ? "No items due" : "\(min(index + 1, items.count)) of \(items.count)") : "One item at a time")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("Close review") { dismiss() }
                    .keyboardShortcut(.cancelAction)
            }
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
                    Text(error).font(.caption).foregroundStyle(.red)
                }
            }
        }
        .padding(24)
        .frame(width: 640, height: 440)
        .onAppear(perform: load)
        // presentation-region: cancel task confirmations
        .confirmationDialog("Cancel this task?", isPresented: $confirmingCancel) {
            Button("Cancel task", role: .destructive) {
                guard index < items.count else { return }
                Task { if await model.cancelTask(items[index].id) { advance() } }
            }
            Button("Keep task", role: .cancel) {}
        } message: {
            Text("The task will move to history. No message will be sent.")
        }
        // presentation-region-end
    }

    private func card(_ item: TaskRecord) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(item.title).font(.title3.weight(.semibold))
                .frame(maxWidth: .infinity, alignment: .leading)
            if let details = item.details, !details.isEmpty {
                Text(details).foregroundStyle(.secondary)
            }
            if let projectID = item.projectID {
                Text("Project · \(model.projectLabel(projectID))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
    }

    private func nextForm(_ item: TaskRecord) -> some View {
        let archived = model.isArchived(item.projectID)
        return VStack(alignment: .leading, spacing: 10) {
            Text("What is the concrete next action?").font(.headline)
            TextField("Concrete next action", text: $actionTitle)
                .textFieldStyle(.roundedBorder)
                .accessibilityLabel("Concrete next action")
                .onSubmit { activate(item) }
            Text(
                archived
                    ? "Unarchive this project before moving its task to Next actions."
                    : "The title and GTD list change together. Project, tags, notes, and due date remain attached."
            )
            .font(.caption)
            .foregroundStyle(.secondary)
            HStack {
                Button("Back") { enteringNext = false }
                Spacer()
                Button("Move to Next actions") { activate(item) }
                    .buttonStyle(.borderedProminent)
                    .disabled(!validAnswer(actionTitle, limit: EditorLimits.title) || archived)
            }
        }
    }

    @ViewBuilder
    private func choices(_ item: TaskRecord) -> some View {
        let archived = model.isArchived(item.projectID)
        Text("Is this relevant now?").font(.headline)
        HStack(spacing: 10) {
            Button("Keep in Someday") {
                Task { if await model.keepSomeday(item) { advance() } }
            }
            .help("Review again after seven days or when this task changes")
            Button("Make it a Next action…") {
                actionTitle = item.title
                enteringNext = true
            }
            .disabled(archived)
            Button("No longer relevant…", role: .destructive) { confirmingCancel = true }
        }
        if archived {
            Text("Unarchive the project to activate this task.")
                .font(.caption)
                .foregroundStyle(.secondary)
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
        guard validAnswer(actionTitle, limit: EditorLimits.title), !model.isArchived(task.projectID) else { return }
        let title = actionTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        Task { if await model.activateSomeday(task.id, title: title, editorID: editorID) { advance() } }
    }

    private func advance() {
        editorID = UUID().uuidString
        index += 1
        enteringNext = false
        actionTitle = ""
        model.error = nil
    }
}

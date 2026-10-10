import BrainBuddyMacCore
import SwiftUI

/// Quick Open (⌘O) over the workspace on this Mac: lists, history, projects (archived ones say
/// so), tags and matching tasks, found at once without the network (FR-010).
@MainActor
struct QuickOpenView: View {
    let model: BrainBuddyModel
    let onOpen: (QuickOpenTarget) -> Void
    let onClose: () -> Void

    @State private var query = ""
    @State private var results: [QuickOpenResult] = []
    @State private var selectedIndex = 0
    @FocusState private var queryFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(.secondary)
                TextField("Find a task, project, tag, or list", text: $query)
                    .textFieldStyle(.plain)
                    .focused($queryFocused)
                    .onSubmit { openSelected() }
                    .onKeyPress(.downArrow) {
                        guard !results.isEmpty else { return .ignored }
                        selectedIndex = min(selectedIndex + 1, results.count - 1)
                        return .handled
                    }
                    .onKeyPress(.upArrow) {
                        guard !results.isEmpty else { return .ignored }
                        selectedIndex = max(selectedIndex - 1, 0)
                        return .handled
                    }
            }
            .padding(12)
            .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 10))

            if model.quickOpenReadiness(query) != .ready {
                if case .failed = model.quickOpenReadiness(query) {
                    ContentUnavailableView {
                        Label("Quick Open couldn’t load", systemImage: "exclamationmark.triangle")
                    } actions: {
                        Button("Retry") {
                            Task {
                                await model.prepareQuickOpen(query)
                                results = model.quickOpenResults(query)
                            }
                        }
                    }
                } else {
                    ProgressView("Searching…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            } else if results.isEmpty {
                ContentUnavailableView("No matches", systemImage: "magnifyingglass")
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 4) {
                            ForEach(Array(results.enumerated()), id: \.element.id) { index, result in
                                Button { onOpen(result.target) } label: {
                                    HStack(spacing: 12) {
                                        Image(systemName: result.symbol)
                                            .frame(width: 22)
                                            .foregroundStyle(.secondary)
                                        VStack(alignment: .leading, spacing: 2) {
                                            Text(result.title)
                                                .font(.body.weight(.medium))
                                            Text(result.subtitle)
                                                .font(.caption)
                                                .foregroundStyle(.secondary)
                                        }
                                        Spacer()
                                    }
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 8)
                                    .background(
                                        index == selectedIndex ? Color.accentColor.opacity(0.18) : Color.clear,
                                        in: RoundedRectangle(cornerRadius: 8)
                                    )
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel("\(result.title), \(result.subtitle)")
                                .id(result.id)
                            }
                        }
                    }
                    .onChange(of: selectedIndex) { _, index in
                        if results.indices.contains(index) {
                            proxy.scrollTo(results[index].id, anchor: .center)
                        }
                    }
                }
            }

            HStack {
                Text("↑↓ choose · Return open · Esc close")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Spacer()
                Button("Close", action: onClose)
                    .keyboardShortcut(.cancelAction)
            }
        }
        .padding(18)
        .frame(width: 620, height: 520)
        .task { queryFocused = true }
        .onChange(of: query, initial: true) { _, query in
            results = model.quickOpenResults(query)
            selectedIndex = 0
            Task {
                await model.prepareQuickOpen(query)
                results = model.quickOpenResults(query)
            }
        }
    }

    private func openSelected() {
        guard results.indices.contains(selectedIndex) else { return }
        onOpen(results[selectedIndex].target)
    }
}

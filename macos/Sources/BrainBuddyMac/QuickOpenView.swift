import SwiftUI

enum QuickOpenTarget {
    case list(TaskList)
    case history(HistoryState)
    case project(String)
    case tag(String)
    case task(String)
}

struct QuickOpenResult: Identifiable {
    let id: String
    let title: String
    let subtitle: String
    let symbol: String
    let target: QuickOpenTarget
}

@MainActor
struct QuickOpenView: View {
    @ObservedObject var model: BrainBuddyModel
    let onOpen: (QuickOpenTarget) -> Void
    let onClose: () -> Void

    @State private var query = ""
    @State private var results: [QuickOpenResult] = []
    @State private var selectedIndex = 0
    @State private var searching = false
    @State private var searchError: String?
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
                if searching { ProgressView().controlSize(.small) }
            }
            .padding(12)
            .background(.quaternary.opacity(0.6), in: RoundedRectangle(cornerRadius: 10))

            if let searchError {
                HStack {
                    Text(searchError).foregroundStyle(.red)
                    Button("Retry") { Task { await search() } }
                }
            } else if results.isEmpty && !searching {
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
        .task(id: query) {
            if !query.isEmpty {
                do { try await Task.sleep(nanoseconds: 120_000_000) }
                catch { return }
            }
            await search()
        }
    }

    private func openSelected() {
        guard results.indices.contains(selectedIndex) else { return }
        onOpen(results[selectedIndex].target)
    }

    private func search() async {
        searching = true
        searchError = nil
        do {
            let found = try await model.quickOpenResults(query)
            guard !Task.isCancelled else { return }
            results = found
            selectedIndex = 0
        } catch is CancellationError {
            return
        } catch {
            guard !Task.isCancelled else { return }
            searchError = error.localizedDescription
        }
        searching = false
    }
}

import BrainBuddyDesign
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
            QuickOpenSearchField {
                TextField("Find a task, project, tag, or list", text: $query)
                    .textFieldStyle(.plain)
                    .font(MacSheetFont.body)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
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

            if model.quickOpenReadiness(query) != .ready {
                if case .failed = model.quickOpenReadiness(query) {
                    MacSheetEmptyState(title: "Quick Open couldn’t load", systemImage: "exclamationmark.triangle") {
                        Button("Retry") {
                            Task {
                                await model.prepareQuickOpen(query)
                                results = model.quickOpenResults(query)
                            }
                        }
                    }
                    .frame(maxHeight: .infinity)
                } else {
                    ProgressView("Searching…")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            } else if results.isEmpty {
                MacSheetEmptyState(title: "No matches", systemImage: "magnifyingglass")
                    .frame(maxHeight: .infinity)
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 2) {
                            ForEach(Array(results.enumerated()), id: \.element.id) { index, result in
                                Button { onOpen(result.target) } label: {
                                    QuickOpenResultRow(
                                        symbol: result.symbol, title: result.title, subtitle: result.subtitle,
                                        selected: index == selectedIndex)
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

            QuickOpenFooter(onClose: onClose)
        }
        .padding(18)
        .frame(width: 620, height: 520)
        .macSheetSurface()
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

/// Quick Open's field: the magnifier and the query (`field`) on `field-bg`, radius 12.
struct QuickOpenSearchField<Field: View>: View {
    let field: Field

    init(@ViewBuilder field: () -> Field) {
        self.field = field()
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 14))
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                .accessibilityHidden(true)
            field
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 11)
        .padding(.horizontal, 14)
        .background(CarryOnColorStyle.coFieldBg, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

/// One result: its symbol, the title (14) and what it is (12, secondary), on the row's selection
/// fill when it is the chosen one, as the list's rows.
struct QuickOpenResultRow: View {
    let symbol: String
    let title: String
    let subtitle: String
    let selected: Bool

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 14))
                .frame(width: 22)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(selected ? MacSheetFont.heading : MacSheetFont.body)
                    .foregroundStyle(CarryOnColorStyle.coTextPrimary)
                    .lineLimit(1)
                Text(subtitle)
                    .font(MacSheetFont.meta)
                    .foregroundStyle(CarryOnColorStyle.coTextSecondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .macRowSurface(selected: selected)
        .contentShape(Rectangle())
    }
}

/// The keys line (12, secondary) and "Close" (Esc).
struct QuickOpenFooter: View {
    let onClose: () -> Void

    var body: some View {
        HStack {
            Text("↑↓ choose · Return open · Esc close")
                .font(MacSheetFont.meta)
                .foregroundStyle(CarryOnColorStyle.coTextSecondary)
            Spacer()
            Button("Close", action: onClose)
                .buttonStyle(.macQuietPill)
                .keyboardShortcut(.cancelAction)
        }
    }
}

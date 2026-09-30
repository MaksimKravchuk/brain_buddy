import BrainBuddyCore
import BrainBuddyWorkspace
import Foundation
import SwiftUI

/// Creates a project, or renames and recolours an existing one. Validation
/// runs in the workspace (offline); its message is shown under the name.
struct ProjectEditorSheet: View {
    enum Mode: Identifiable, Hashable {
        case create
        case edit(ProjectRecord)

        var id: String {
            switch self {
            case .create: return "create"
            case .edit(let project): return "edit-\(project.id.rawValue)"
            }
        }
    }

    @Environment(Workspace.self) private var workspace
    @Environment(\.dismiss) private var dismiss

    private let mode: Mode
    @State private var name: String
    @State private var color: String?
    @State private var hasPreparedColor: Bool
    @State private var message: String?
    @FocusState private var isNameFocused: Bool

    init(mode: Mode) {
        self.mode = mode
        switch mode {
        case .create:
            _name = State(initialValue: "")
            _color = State(initialValue: nil)
            _hasPreparedColor = State(initialValue: false)
        case .edit(let project):
            _name = State(initialValue: project.name)
            _color = State(initialValue: project.color)
            _hasPreparedColor = State(initialValue: false)
        }
    }

    var body: some View {
        NavigationStack {
            Form {
                nameSection
                colorSection
            }
            .navigationTitle(isCreating ? "New project" : "Edit project")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isCreating ? "Add" : "Save") { save() }
                        .disabled(trimmedName.isEmpty)
                }
            }
            .onChange(of: name) { message = nil }
            .onAppear { prepare() }
        }
        .presentationDetents([.medium, .large])
    }

    private var isCreating: Bool {
        if case .create = mode { return true }
        return false
    }

    private var trimmedName: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    private var nameSection: some View {
        Section {
            TextField("Project name", text: $name)
                .submitLabel(.done)
                .focused($isNameFocused)
                .onSubmit { save() }
        } footer: {
            if let message {
                EditorValidationMessage(text: message)
            }
        }
    }

    private var colorSection: some View {
        Section {
            LazyVGrid(
                columns: [GridItem(.adaptive(minimum: BBMetrics.hitTarget), spacing: BBSpacing.s2)],
                spacing: BBSpacing.s2
            ) {
                ColorSwatchButton(hex: nil, name: "No colour", isSelected: color == nil) {
                    color = nil
                }
                if let custom = customColor {
                    ColorSwatchButton(hex: custom, name: "Current colour", isSelected: ProjectColorNames.same(color, custom)) {
                        color = custom
                    }
                }
                ForEach(BBColor.projectColorPalette, id: \.self) { hex in
                    ColorSwatchButton(
                        hex: hex,
                        name: ProjectColorNames.name(for: hex),
                        isSelected: ProjectColorNames.same(color, hex)
                    ) {
                        color = hex
                    }
                }
            }
            .padding(.vertical, BBSpacing.s1)
        } header: {
            Text("Colour")
        } footer: {
            Text(selectedColorName)
        }
    }

    /// The project's own colour when it was set elsewhere (for example on the
    /// web) and isn't in the palette, so it stays selectable.
    private var customColor: String? {
        guard case .edit(let project) = mode, let original = project.color, !original.isEmpty,
            ProjectColorNames.paletteEntry(matching: original, in: BBColor.projectColorPalette) == nil
        else { return nil }
        return original
    }

    private var selectedColorName: String {
        guard let color else { return "No colour" }
        return ProjectColorNames.name(for: color)
    }

    private func prepare() {
        isNameFocused = true
        guard !hasPreparedColor else { return }
        hasPreparedColor = true
        let palette = BBColor.projectColorPalette
        if isCreating {
            // Rotate through the palette so new projects are told apart at a glance.
            guard !palette.isEmpty else { return }
            color = palette[workspace.projects().count % palette.count]
        } else if let match = ProjectColorNames.paletteEntry(matching: color, in: palette) {
            color = match
        }
    }

    private func save() {
        let newName = trimmedName
        guard !newName.isEmpty else {
            message = GTDValidationError.emptyName.message
            return
        }
        do {
            switch mode {
            case .create:
                try workspace.createProject(name: newName, color: color)
            case .edit(let original):
                guard let current = workspace.project(original.id) else {
                    throw GTDValidationError.projectNotFound
                }
                if newName != current.name {
                    try workspace.renameProject(current.id, to: newName)
                }
                if !ProjectColorNames.same(color, current.color) {
                    try workspace.setProjectColor(current.id, color: color)
                }
            }
            dismiss()
        } catch let error as GTDValidationError {
            message = error.message
        } catch {
            message = error.localizedDescription
        }
    }
}

/// An inline validation message: an icon plus words, never colour alone.
struct EditorValidationMessage: View {
    let text: String

    var body: some View {
        Label {
            Text(text)
                .foregroundStyle(BBColor.textPrimary)
        } icon: {
            Image(systemName: "exclamationmark.circle.fill")
                .foregroundStyle(BBColor.danger)
        }
        .font(BBFont.meta)
    }
}

/// A project's colour as a small dot; a hollow ring when it has none.
struct ProjectColorIndicator: View {
    let hex: String?
    var diameter: CGFloat = 10

    var body: some View {
        Group {
            if let fill = resolvedColor {
                Circle()
                    .fill(fill)
                    .overlay { Circle().strokeBorder(BBColor.hairlineStrong, lineWidth: 0.5) }
            } else {
                Circle()
                    .strokeBorder(BBColor.textTertiary, lineWidth: 1.5)
            }
        }
        .frame(width: diameter, height: diameter)
        .accessibilityHidden(true)
    }

    private var resolvedColor: Color? {
        guard let hex, !hex.isEmpty else { return nil }
        // Typed as optional so this reads the same whether `Color(hex:)` is failable or not.
        let color: Color? = Color(hex: hex)
        return color
    }
}

/// A 44 pt swatch. Selection is a ring (shape) and the `isSelected` trait,
/// so it never depends on telling colours apart.
private struct ColorSwatchButton: View {
    let hex: String?
    let name: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                ProjectColorIndicator(hex: hex, diameter: 28)
                if isSelected {
                    Circle()
                        .strokeBorder(BBColor.textPrimary, lineWidth: 2)
                        .frame(width: 40, height: 40)
                }
            }
            .frame(width: BBMetrics.hitTarget, height: BBMetrics.hitTarget)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(name)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

// MARK: - Pure helpers (no SwiftUI)

/// Human names for `#RRGGBB` project colours, for VoiceOver and menus. Palette
/// colours use their spoken name (`BBColor.projectColorOptions`); any other
/// colour is named from the colour itself: hue buckets calibrated on the
/// Tailwind 500 scale, plus light/dark modifiers.
enum ProjectColorNames {
    private static let hueNames: [(upperBound: Double, name: String)] = [
        (15, "Red"), (33, "Orange"), (42, "Amber"), (65, "Yellow"), (95, "Lime"),
        (150, "Green"), (170, "Emerald"), (185, "Teal"), (195, "Cyan"), (210, "Sky blue"),
        (230, "Blue"), (250, "Indigo"), (265, "Violet"), (285, "Purple"), (315, "Fuchsia"),
        (340, "Pink"), (360.01, "Rose"),
    ]

    static func name(for hex: String) -> String {
        if let paletteName = BBColor.projectColorName(for: hex) { return paletteName }
        guard let rgb = components(of: hex) else { return hex }
        let (red, green, blue) = rgb
        let maxValue = max(red, green, blue)
        let minValue = min(red, green, blue)
        let delta = maxValue - minValue
        let lightness = (maxValue + minValue) / 2
        let saturation = delta == 0 ? 0 : delta / (1 - abs(2 * lightness - 1))

        let base: String
        if saturation < 0.25 {
            base = "Grey"
        } else {
            let degrees = hue(red, green, blue, delta: delta, max: maxValue)
            base = hueNames.first { degrees < $0.upperBound }?.name ?? "Red"
        }
        if lightness >= 0.72 { return "Light \(base.lowercased())" }
        if lightness <= 0.36 { return "Dark \(base.lowercased())" }
        return base
    }

    /// The palette entry equal to `color` ignoring case, if any.
    static func paletteEntry(matching color: String?, in palette: [String]) -> String? {
        guard let color else { return nil }
        return palette.first { same($0, color) }
    }

    static func same(_ lhs: String?, _ rhs: String?) -> Bool {
        lhs?.lowercased() == rhs?.lowercased()
    }

    static func components(of hex: String) -> (Double, Double, Double)? {
        var digits = hex.trimmingCharacters(in: .whitespaces)
        if digits.hasPrefix("#") { digits.removeFirst() }
        guard digits.count == 6, let value = UInt32(digits, radix: 16) else { return nil }
        return (
            Double((value >> 16) & 0xFF) / 255,
            Double((value >> 8) & 0xFF) / 255,
            Double(value & 0xFF) / 255
        )
    }

    private static func hue(_ red: Double, _ green: Double, _ blue: Double, delta: Double, max maxValue: Double) -> Double {
        guard delta > 0 else { return 0 }
        var degrees: Double
        if maxValue == red {
            degrees = ((green - blue) / delta).truncatingRemainder(dividingBy: 6)
        } else if maxValue == green {
            degrees = (blue - red) / delta + 2
        } else {
            degrees = (red - green) / delta + 4
        }
        degrees *= 60
        return degrees < 0 ? degrees + 360 : degrees
    }
}

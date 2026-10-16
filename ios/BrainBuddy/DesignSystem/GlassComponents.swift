import BrainBuddyCore
import BrainBuddyDesign
import BrainBuddyWorkspace
import SwiftUI

// Liquid Glass is for chrome only: the tab bar, navigation and toolbars,
// sheets, the capture accessory and floating clusters. Rows, cards and lists
// stay flat on the brand surfaces (docs/native-ios-app.md, "Liquid Glass and
// the design system").

/// A 44 pt circular glass button for floating controls.
struct GlassIconButton: View {
    let systemImage: String
    let label: String
    var tint: Color? = nil
    let action: () -> Void

    init(systemImage: String, label: String, tint: Color? = nil, action: @escaping () -> Void) {
        self.systemImage = systemImage
        self.label = label
        self.tint = tint
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(BBFont.bodyMedium)
                .foregroundStyle(symbolStyle)
                .frame(width: BBMetrics.hitTarget, height: BBMetrics.hitTarget)
                .contentShape(.circle)
        }
        .buttonStyle(.plain)
        .glassEffect(glass, in: .circle)
        .accessibilityLabel(label)
        .help(label)
    }

    private var glass: Glass {
        if let tint {
            return Glass.regular.tint(tint).interactive()
        }
        return Glass.regular.interactive()
    }

    private var symbolStyle: AnyShapeStyle {
        tint == nil ? AnyShapeStyle(HierarchicalShapeStyle.primary) : AnyShapeStyle(BBColor.onBrand)
    }
}

extension View {
    /// Groups floating glass controls so they blend and morph together as one
    /// cluster (`GlassEffectContainer`).
    func bbFloatingCluster(spacing: CGFloat = BBSpacing.s3) -> some View {
        GlassEffectContainer(spacing: spacing) {
            self
        }
    }
}

/// The floating glass bar at the bottom of a sheet (boards 13 to 20): one
/// capsule of chrome holding the sheet's actions, at most one of them the
/// tinted `.carryOnGlassPrimary`, the others `.carryOnQuiet`. It is as tall as the
/// board's bottom bar, the buttons inset by what is left of it. Put it in the
/// sheet's bottom safe-area inset so content scrolls under it.
struct BBGlassActionBar<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    /// The bar's height less the button's, halved: the board's 6 pt.
    private static var inset: CGFloat {
        CGFloat((CarryOnLayout.BottomBar.height - CarryOnLayout.Button.height) / 2)
    }

    var body: some View {
        HStack(spacing: Self.inset) {
            content
        }
        .padding(Self.inset)
        .glassEffect(.regular, in: .capsule)
        .padding(.horizontal, CGFloat(CarryOnSpace.xs))
        .padding(.bottom, CGFloat(CarryOnSpace.xs))
    }
}

/// The capture bar: always one tap from capturing. In the tab view's bottom
/// accessory the system draws the glass capsule and this is its content; at
/// the bottom of the iPad sidebar (`drawsGlass`) it draws its own.
///
/// It files where the screen on top files (`AppRouter.captureContextForSelectedTab`):
/// a project, a tag or a list, otherwise Next actions on the Next tab and
/// Inbox everywhere else — and says so in its prompt.
struct CaptureAccessory: View {
    private let drawsGlass: Bool

    @Environment(AppRouter.self) private var router
    @Environment(Workspace.self) private var workspace

    init(drawsGlass: Bool = false) {
        self.drawsGlass = drawsGlass
    }

    var body: some View {
        let context = router.captureContextForSelectedTab
        let prompt = Self.prompt(for: context, workspace: workspace)
        Button {
            router.presentCapture(context)
        } label: {
            HStack(spacing: BBSpacing.s2) {
                Image(systemName: BBSymbol.capture)
                    .font(BBFont.bodyMedium)
                    .foregroundStyle(BBColor.brandText)
                ViewThatFits(in: .horizontal) {
                    Text(prompt + "…")
                    Text("Add")
                }
                .font(BBFont.body)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, BBSpacing.s4)
            .frame(maxWidth: .infinity, minHeight: BBMetrics.hitTarget)
            .contentShape(.rect)
        }
        .buttonStyle(.plain)
        .modifier(SidebarCaptureGlass(isEnabled: drawsGlass))
        // The label starts with the visible words, so Voice Control's
        // "Tap Add to inbox" (or "Tap Add" when only "Add" fits) works.
        .accessibilityLabel(prompt)
        .accessibilityInputLabels([Text(prompt), Text("Add"), Text("Capture"), Text("Capture a task")])
        .accessibilityHint("Opens capture.")
    }

    /// The visible prompt without its ellipsis, for example "Add to inbox",
    /// "Add a next action" or "Add to Errands".
    static func prompt(for context: CaptureContext, workspace: Workspace) -> String {
        if let projectID = context.projectID, let project = workspace.project(projectID) {
            return "Add to \(project.name)"
        }
        if let tagID = context.tagID, let tag = workspace.tag(tagID) {
            return "Add a task tagged \(tag.name)"
        }
        switch context.list {
        case .inbox: return "Add to inbox"
        case .next: return "Add a next action"
        case .waiting: return "Add to \(OpenList.waiting.title)"
        case .someday: return "Add to \(OpenList.someday.title)"
        }
    }
}

/// The capsule the tab view's accessory otherwise provides, for the sidebar.
private struct SidebarCaptureGlass: ViewModifier {
    let isEnabled: Bool

    func body(content: Content) -> some View {
        if isEnabled {
            content
                .glassEffect(.regular.interactive(), in: .capsule)
                .padding(.horizontal, BBSpacing.s3)
                .padding(.vertical, BBSpacing.s2)
        } else {
            content
        }
    }
}

#Preview("Glass controls") {
    ZStack {
        BBColor.surfaceBase.ignoresSafeArea()
        HStack(spacing: BBSpacing.s3) {
            GlassIconButton(systemImage: "arrow.uturn.backward", label: "Undo") {}
            GlassIconButton(systemImage: "checkmark", label: "Done", tint: BBColor.brandFill) {}
        }
        .bbFloatingCluster()
    }
}

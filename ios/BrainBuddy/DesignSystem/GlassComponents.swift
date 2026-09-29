import BrainBuddyCore
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

/// The capture bar in the tab view's bottom accessory: always one tap from
/// capturing. The system draws the accessory's glass capsule; this is its
/// content. Next captures into Next actions, every other tab into Inbox.
struct CaptureAccessory: View {
    @Environment(AppRouter.self) private var router

    var body: some View {
        let context = router.captureContextForSelectedTab
        Button {
            router.presentCapture(context)
        } label: {
            HStack(spacing: BBSpacing.s2) {
                Image(systemName: BBSymbol.capture)
                    .font(BBFont.bodyMedium)
                    .foregroundStyle(BBColor.brand)
                ViewThatFits(in: .horizontal) {
                    Text(Self.prompt(for: context.list))
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
        .accessibilityLabel("Capture a task")
        .accessibilityHint(context.list == .next ? "Adds to Next actions" : "Adds to Inbox")
    }

    static func prompt(for list: OpenList) -> String {
        list == .next ? "Add a next action…" : "Add to inbox…"
    }
}

#Preview("Glass controls") {
    ZStack {
        BBColor.surfaceBase.ignoresSafeArea()
        HStack(spacing: BBSpacing.s3) {
            GlassIconButton(systemImage: "arrow.uturn.backward", label: "Undo") {}
            GlassIconButton(systemImage: "checkmark", label: "Done", tint: BBColor.brand) {}
        }
        .bbFloatingCluster()
    }
}

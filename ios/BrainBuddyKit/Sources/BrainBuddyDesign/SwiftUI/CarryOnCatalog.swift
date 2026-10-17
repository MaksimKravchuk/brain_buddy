#if canImport(SwiftUI)
    import SwiftUI

    /// Every component in every state, laid out like the cells of the design board
    /// "Carry On design system · components": each state on the ground colour with
    /// 16 pt of space around it. The snapshot tests render these sections and the
    /// apps can show them as an in-app gallery.
    public enum CarryOnCatalog {
        public enum Section: String, CaseIterable, Sendable {
            case buttons, nextStepCard, stepRows, chips
        }

        @MainActor @ViewBuilder
        public static func view(_ section: Section) -> some View {
            switch section {
            case .buttons: buttons
            case .nextStepCard: nextStepCards
            case .stepRows: stepRows
            case .chips: chips
            }
        }

        @MainActor private static var buttons: some View {
            CatalogColumn {
                CatalogCell { Button("Done") {}.buttonStyle(.carryOnPrimary) }
                CatalogCell { CarryOnButtonStyle.Preview(kind: .primary, title: "Done", pressed: true) }
                CatalogCell { Button("Done") {}.buttonStyle(.carryOnPrimary).disabled(true) }
                CatalogCell { Button("Not now") {}.buttonStyle(.carryOnSecondary) }
                CatalogCell { CarryOnButtonStyle.Preview(kind: .secondary, title: "Not now", pressed: true) }
                CatalogCell {
                    HStack(spacing: CarryOnSpace.xs) {
                        Button("+") {}.buttonStyle(.carryOnSecondaryIcon)
                        CarryOnButtonStyle.Preview(kind: .secondary, title: "−", pressed: true, iconOnly: true)
                        Button("−") {}.buttonStyle(.carryOnSecondaryIcon).disabled(true)
                    }
                }
                CatalogCell { Button("Write my own") {}.buttonStyle(.carryOnQuiet) }
                CatalogCell {
                    HStack(spacing: CarryOnSpace.sm) {
                        Button("Done") {}.buttonStyle(.carryOnPrimary)
                        Button("Not now") {}.buttonStyle(.carryOnSecondary)
                    }
                }
                CatalogCell { Button("Due Friday 16") {}.buttonStyle(.carryOnStrong) }
                CatalogCell { CarryOnButtonStyle.Preview(kind: .strong, title: "Due Friday 16", pressed: true) }
                CatalogCell { Button("Due Friday 16") {}.buttonStyle(.carryOnStrong).disabled(true) }
                // .carryOnGlassPrimary is left out: ImageRenderer draws Liquid Glass as
                // nothing, so a snapshot of it would approve an empty cell.
            }
        }

        @MainActor private static var nextStepCards: some View {
            CatalogColumn {
                CatalogCell { CarryOnNextStepCard(project: "Garage", step: "Call Sam about the van") }
                CatalogCell { CarryOnNextStepCard(project: "Garage", step: "Call Sam about the van", status: .pressed) }
                CatalogCell { CarryOnNextStepCard(project: "Garage", step: "Call Sam about the van", status: .taken) }
            }
        }

        @MainActor private static var stepRows: some View {
            CatalogColumn {
                CatalogCell { CarryOnStepRow("Buy bin bags", detail: "Garage") }
                CatalogCell { CarryOnStepRow("Call Sam about the van", detail: "Garage", status: .current) }
                CatalogCell { CarryOnStepRow("Clear the shelves", detail: "Garage", status: .done) }
                CatalogCell { CarryOnStepRow("Quote for the van", detail: "Waiting on Sam · 3 days", status: .waiting) }
                CatalogCell { CarryOnStepRow("Buy bin bags", detail: "Garage", isSelected: true) }
            }
        }

        @MainActor private static var chips: some View {
            CatalogColumn {
                CatalogCell {
                    HStack(spacing: CarryOnSpace.xs) {
                        CarryOnChip("Garage", dot: CarryOnProjectColor.lake)
                        CarryOnChip("errands")
                    }
                }
                CatalogCell {
                    HStack(spacing: CarryOnSpace.xs) {
                        CarryOnChip("Tomorrow", tone: .dueSoon)
                        CarryOnChip("Overdue · 2 days", tone: .overdue)
                    }
                }
                CatalogCell {
                    HStack(spacing: 6) {
                        CarryOnChip("Today", size: .quick)
                        CarryOnChip("Tomorrow", size: .quick, isSelected: true)
                        CarryOnChip("Saturday", size: .quick)
                    }
                }
                CatalogCell {
                    HStack(spacing: CarryOnSpace.xs) {
                        CarryOnChip("+ Date", variant: .outlined)
                        CarryOnChip("+ Note", variant: .outlined)
                    }
                }
                CatalogCell {
                    HStack(spacing: 6) {
                        ForEach(CarryOnProjectColor.all, id: \.name) { CarryOnProjectDot($0.color, size: 14) }
                    }
                }
            }
        }
    }

    extension CarryOnButtonStyle {
        /// A button drawn in its pressed state, for the catalog and snapshots.
        struct Preview: View {
            let kind: Kind
            let title: String
            let pressed: Bool
            var iconOnly = false

            var body: some View {
                CarryOnButtonBody(kind: kind, iconOnly: iconOnly, label: Text(title), isPressed: pressed)
            }
        }
    }

    private struct CatalogColumn<Content: View>: View {
        @ViewBuilder let content: Content

        var body: some View {
            VStack(alignment: .leading, spacing: CarryOnSpace.sm) { content }
                .padding(CarryOnSpace.md)
                .background(.coSurfaceCard)
        }
    }

    private struct CatalogCell<Content: View>: View {
        @ViewBuilder let content: Content

        var body: some View {
            content
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(CarryOnSpace.md)
                .background(.coBgGround, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
    }
#endif

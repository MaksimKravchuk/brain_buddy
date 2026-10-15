#if canImport(SwiftUI)
    import SwiftUI

    /// The heart of the app: one step you can start now, on paper, on limestone.
    public struct CarryOnNextStepCard: View {
        public enum Status: Sendable {
            /// At rest.
            case normal
            /// Held down: the selected surface, scaled to 0.98.
            case pressed
            /// The step was taken: struck through and lifted, the frame the
            /// step-taken move passes through before the card leaves.
            case taken
        }

        typealias Metrics = CarryOnLayout.NextStepCard

        let project: String
        let step: String
        let status: Status
        @Environment(\.colorScheme) private var colorScheme

        public init(project: String, step: String, status: Status = .normal) {
            self.project = project
            self.step = step
            self.status = status
        }

        public var body: some View {
            VStack(alignment: .leading, spacing: Metrics.projectGap) {
                Text(project)
                    .carryOnText(CarryOnTypeScale.meta)
                    .foregroundStyle(.coNextStepProject)
                Text(step)
                    .strikethrough(status == .taken, color: CarryOnColorStyle.coStepTextDone.color(in: colorScheme))
                    .carryOnText(CarryOnTypeScale.step)
                    .foregroundStyle(status == .taken ? CarryOnColorStyle.coStepTextDone : .coNextStepText)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, Metrics.paddingY)
            .padding(.horizontal, Metrics.paddingX)
            .background(
                status == .pressed ? CarryOnColorStyle.coSurfaceSelected : .coNextStepBg,
                in: RoundedRectangle(cornerRadius: Metrics.radius, style: .continuous)
            )
            .scaleEffect(status == .pressed ? Metrics.pressedScale : 1)
            .opacity(status == .taken ? 0.7 : 1)
            .offset(y: status == .taken ? -8 : 0)
        }
    }
#endif

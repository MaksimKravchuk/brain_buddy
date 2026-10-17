import BrainBuddyDesign
import SwiftUI

/// The first run's writing field (boards 02 and 03): a surface-card panel with the basalt focus
/// ring while it has the keyboard. The capture grows over several lines; the step is one line
/// whose Return submits.
struct FirstRunField: View {
    private typealias Layout = CarryOnLayout.FirstRun

    let label: String
    @Binding var text: String
    let style: TypeStyle
    var axis: Axis = .horizontal
    var minHeight: Double?
    var focus: FocusState<Bool>.Binding

    var body: some View {
        TextField(label, text: $text, prompt: Text(""), axis: axis)
            .carryOnText(style)
            .foregroundStyle(.coTextPrimary)
            .focused(focus)
            .padding(Layout.fieldPadding)
            .frame(maxWidth: .infinity, minHeight: minHeight.map { CGFloat($0) }, alignment: .topLeading)
            .background(.coSurfaceCard, in: RoundedRectangle(cornerRadius: Layout.fieldRadius))
            .overlay {
                if focus.wrappedValue {
                    let ring = CarryOnLayout.FocusRing.self
                    RoundedRectangle(cornerRadius: Layout.fieldRadius + ring.offset)
                        .strokeBorder(.coFocusRing, lineWidth: ring.width)
                        .padding(-(ring.offset + ring.width))
                        .accessibilityHidden(true)
                }
            }
            .contentShape(.rect)
            .onTapGesture { focus.wrappedValue = true }
    }
}

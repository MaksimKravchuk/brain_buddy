import BrainBuddyDesign
import SwiftUI

/// The six-digit email code as six boxes (boards 27 and 06): surface-card boxes, the next empty
/// one ringed in the focus colour. One hidden field takes the typing, so paste and the
/// keyboard's one-time-code suggestion fill every box at once.
struct CodeBoxesField: View {
    @Binding var code: String
    var length = 6
    var onComplete: () -> Void = {}

    @FocusState private var isFocused: Bool

    var body: some View {
        ZStack {
            TextField("", text: $code)
                .textContentType(.oneTimeCode)
                .keyboardType(.numberPad)
                .focused($isFocused)
                .opacity(0.02)
                .accessibilityLabel("Email code")
                .accessibilityValue(code.isEmpty ? "Empty" : code.map(String.init).joined(separator: " "))
                .onChange(of: code) { _, new in
                    let digits = String(new.filter { $0.isASCII && $0.isNumber }.prefix(length))
                    if digits != new { code = digits }
                    if digits.count == length { onComplete() }
                }
            HStack(spacing: CGFloat(CarryOnLayout.CodeBox.gap)) {
                ForEach(0..<length, id: \.self) { index in
                    box(at: index)
                }
            }
            .accessibilityHidden(true)
            .contentShape(Rectangle())
            .onTapGesture { isFocused = true }
        }
        .onAppear { isFocused = true }
    }

    private func box(at index: Int) -> some View {
        let characters = Array(code)
        let character = index < characters.count ? String(characters[index]) : ""
        let isNext = isFocused && index == min(characters.count, length - 1) && characters.count < length
        let shape = RoundedRectangle(cornerRadius: CGFloat(CarryOnLayout.CodeBox.radius), style: .continuous)
        return Text(character)
            .carryOnFont(CarryOnTypeScale.step)
            .foregroundStyle(.coTextPrimary)
            .frame(maxWidth: .infinity)
            .frame(height: CGFloat(CarryOnLayout.CodeBox.height))
            .background(.coSurfaceCard, in: shape)
            .overlay {
                if isNext { shape.strokeBorder(.coFocusRing, lineWidth: CGFloat(CarryOnLayout.FocusRing.width)) }
            }
    }
}

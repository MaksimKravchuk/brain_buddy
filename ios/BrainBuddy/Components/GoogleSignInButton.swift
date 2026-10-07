import SwiftUI

struct GoogleSignInButton: View {
    let isBusy: Bool
    let action: () -> Void
    @ScaledMetric(relativeTo: .subheadline) private var lineHeight = 20.0

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image("GoogleSignInLogo")
                    .renderingMode(.original)
                    .resizable()
                    .scaledToFit()
                    .frame(width: 20, height: 20)
                    .accessibilityHidden(true)
                Text("Continue with Google")
                    .font(.custom("GoogleSans-Medium", size: 14, relativeTo: .subheadline))
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, minHeight: lineHeight)
                if isBusy {
                    ProgressView().tint(Color(red: 31 / 255, green: 31 / 255, blue: 31 / 255))
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(GoogleButtonStyle())
        .accessibilityLabel("Continue with Google")
        .accessibilityValue(isBusy ? "Please wait…" : "")
    }

    private struct GoogleButtonStyle: ButtonStyle {
        @Environment(\.isEnabled) private var isEnabled

        func makeBody(configuration: Configuration) -> some View {
            configuration.label
                .foregroundStyle(Color(red: 31 / 255, green: 31 / 255, blue: 31 / 255))
                .background(configuration.isPressed ? Color(red: 248 / 255, green: 250 / 255, blue: 1) : .white)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay {
                    RoundedRectangle(cornerRadius: 8)
                        .strokeBorder(Color(red: 116 / 255, green: 119 / 255, blue: 117 / 255), lineWidth: 1)
                }
                .opacity(isEnabled ? 1 : 0.5)
        }
    }
}

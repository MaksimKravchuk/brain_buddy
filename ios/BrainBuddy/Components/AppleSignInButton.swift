import AuthenticationServices
import SwiftUI

/// The system control invokes the existing async server-nonce flow before
/// ModernAuthCoordinator presents Apple's authorization request.
struct AppleSignInButton: UIViewRepresentable {
    let action: () -> Void
    @Environment(\.isEnabled) private var isEnabled

    func makeCoordinator() -> Coordinator { Coordinator(action: action) }

    func makeUIView(context: Context) -> ASAuthorizationAppleIDButton {
        let button = ASAuthorizationAppleIDButton(type: .signIn, style: .black)
        button.cornerRadius = 8
        button.setContentHuggingPriority(.defaultLow, for: .horizontal)
        button.addTarget(context.coordinator, action: #selector(Coordinator.activate), for: .touchUpInside)
        button.isEnabled = isEnabled
        return button
    }

    func updateUIView(_ button: ASAuthorizationAppleIDButton, context: Context) {
        context.coordinator.action = action
        button.isEnabled = isEnabled
    }

    @MainActor final class Coordinator: NSObject {
        var action: () -> Void

        init(action: @escaping () -> Void) { self.action = action }

        @objc func activate() { action() }
    }
}

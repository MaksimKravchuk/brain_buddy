import AuthenticationServices
import BrainBuddyAPI
import CryptoKit
import Foundation
import Network
import Observation
import Security
import UIKit

/// Platform proof collection only. Workspace owns session/owner finalization.
@MainActor
@Observable
final class ModernAuthCoordinator: NSObject, ASWebAuthenticationPresentationContextProviding,
    ASAuthorizationControllerDelegate, ASAuthorizationControllerPresentationContextProviding
{
    private(set) var isOnline = true
    @ObservationIgnored private let monitor = NWPathMonitor()
    @ObservationIgnored private var browser: ASWebAuthenticationSession?
    @ObservationIgnored private var apple: ASAuthorizationController?
    @ObservationIgnored private var continuation: CheckedContinuation<NativeSignInCredential, any Error>?
    @ObservationIgnored private var active: (id: UUID, provider: NativeAuthProvider, start: ProviderStartDTO, verifier: String)?

    override init() {
        super.init()
        monitor.pathUpdateHandler = { [weak self] path in
            let online = path.status == .satisfied
            Task { @MainActor [weak self] in self?.isOnline = online }
        }
        monitor.start(queue: DispatchQueue(label: "brainbuddy.auth.connectivity"))
    }

    struct Proof: Sendable {
        let verifier: String
        let challenge: String
    }

    static func newProof() throws -> Proof {
        var bytes = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else {
            throw Failure(message: "Couldn't start a secure sign-in. Try again.")
        }
        let verifier = base64URL(Data(bytes))
        let challenge = base64URL(Data(SHA256.hash(data: Data(verifier.utf8))))
        return Proof(verifier: verifier, challenge: challenge)
    }
    private static func base64URL(_ data: Data) -> String {
        data.base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }

    func authenticate(provider: NativeAuthProvider, start: ProviderStartDTO, verifier: String) async throws -> NativeSignInCredential {
        cancel()
        guard NativeAuthCallback.isRandomToken(start.state), NativeAuthCallback.isRandomToken(start.nonce),
            NativeAuthCallback.isRandomToken(start.attemptID)
        else { throw Failure(message: "The server returned an unexpected sign-in response.") }
        let id = UUID()
        active = (id, provider, start, verifier)
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                self.continuation = continuation
                switch provider {
                case .google:
                    guard let text = start.authorizationURL, let parts = URLComponents(string: text),
                        parts.scheme == "https", parts.host?.isEmpty == false,
                        parts.user == nil, parts.password == nil, parts.fragment == nil, let url = parts.url
                    else {
                        finish(id: id, result: .failure(Failure(message: "Google sign-in isn't available right now.")))
                        return
                    }
                    let session = ASWebAuthenticationSession(url: url, callbackURLScheme: "brainbuddy") { [weak self] url, error in
                        Task { @MainActor [weak self] in
                            guard let self, self.active?.id == id else { return }
                            if let error {
                                self.finish(id: id, result: .failure(error))
                                return
                            }
                            do {
                                guard let url else { throw NativeAuthCallback.InvalidCallback() }
                                let callback = try NativeAuthCallback.parse(url, attemptID: start.attemptID, state: start.state)
                                self.finish(id: id, result: .success(.browserGrant(attemptID: start.attemptID, state: start.state, handoffCode: callback.handoffCode, verifier: verifier)))
                            } catch {
                                self.finish(id: id, result: .failure(Failure(message: "Couldn't verify the sign-in return. Start a fresh attempt.")))
                            }
                        }
                    }
                    session.presentationContextProvider = self
                    session.prefersEphemeralWebBrowserSession = true
                    browser = session
                    if !session.start() { finish(id: id, result: .failure(Failure(message: "Couldn't open Google sign-in. Try again."))) }
                case .apple:
                    let request = ASAuthorizationAppleIDProvider().createRequest()
                    request.requestedScopes = [.email]
                    request.state = start.state
                    request.nonce = start.nonce
                    let controller = ASAuthorizationController(authorizationRequests: [request])
                    controller.delegate = self
                    controller.presentationContextProvider = self
                    apple = controller
                    controller.performRequests()
                }
            }
        } onCancel: {
            Task { @MainActor [weak self] in self?.cancel() }
        }
    }

    func cancel() {
        let waiting = continuation
        continuation = nil
        active = nil
        browser?.cancel()
        browser = nil
        apple?.cancel()
        apple = nil
        waiting?.resume(throwing: CancellationError())
    }

    func stopMonitoring() { monitor.cancel() }

    private func finish(id: UUID, result: Result<NativeSignInCredential, any Error>) {
        guard active?.id == id else { return }
        let waiting = continuation
        continuation = nil
        active = nil
        browser = nil
        apple = nil
        waiting?.resume(with: result)
    }

    func authorizationController(controller: ASAuthorizationController, didCompleteWithAuthorization authorization: ASAuthorization) {
        guard controller === apple, let active, active.provider == .apple else { return }
        guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
            credential.state == active.start.state,
            let codeData = credential.authorizationCode, let tokenData = credential.identityToken,
            let code = String(data: codeData, encoding: .utf8), !code.isEmpty,
            let token = String(data: tokenData, encoding: .utf8), !token.isEmpty
        else { finish(id: active.id, result: .failure(Failure(message: "Couldn't verify Apple sign-in. Start a fresh attempt."))); return }
        finish(id: active.id, result: .success(.apple(attemptID: active.start.attemptID, state: active.start.state, authorizationCode: code, identityToken: token, verifier: active.verifier)))
    }

    func authorizationController(controller: ASAuthorizationController, didCompleteWithError error: any Error) {
        guard controller === apple, let active else { return }
        finish(id: active.id, result: .failure(error))
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor { anchor }
    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor { anchor }
    private var anchor: UIWindow {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows).first(where: \.isKeyWindow) ?? UIWindow()
    }

    struct Failure: Error, LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }
}

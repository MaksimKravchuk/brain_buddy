import BrainBuddyAPI
import Foundation

/// Verified by a candidate-only authentication exchange, never by a supplied scope.
/// A consumer must recheck `isCurrent` before using this process-local proof.
public struct NativeAcceptedCandidate: Sendable, CustomStringConvertible {
    public let ownerID: String
    public let serverURL: URL
    public let attemptID: UUID
    private let gate: NativeSignInGate

    fileprivate init(ownerID: String, attempt: NativeSignInAttempt, gate: NativeSignInGate) {
        self.ownerID = ownerID
        serverURL = attempt.serverURL
        attemptID = attempt.id
        self.gate = gate
    }

    public var isCurrent: Bool { gate.accepts(attemptID) }
    public var description: String { "Native accepted candidate (redacted)" }
}

public enum NativeCandidateCompletion: Sendable {
    case accepted(NativeAcceptedCandidate)
    case continuation(AuthCompletionDTO)
}

/// Cleanup does not imply that an authentication request still in flight has finished.
public enum NativeCandidateCleanup: Sendable {
    case complete
    case awaitingResponse
    case pending(APIError)
}

/// Produces authenticated owner inputs without linking a store or installing a live token.
/// This owner is process-local; it does not supply task scopes or shared control authority.
public actor NativeCandidateAuthentication {
    private struct Context {
        let attempt: NativeSignInAttempt
        let session: NativeAuthenticationSession
        var submitting = false
        var accepted = false
    }
    private let transport: any HTTPTransport
    private let clientVersion: String
    private let gate = NativeSignInGate()
    private var current: Context?
    private var retired: [UUID: NativeAuthenticationSession] = [:]
    private var cleaning: Set<UUID> = []
    private var inFlight: Set<UUID> = []

    public init(transport: any HTTPTransport = URLSessionTransport(), clientVersion: String = BrainBuddyAPI.bundleVersion) {
        self.transport = transport
        self.clientVersion = clientVersion
    }

    public func begin(serverURL: URL, expectedAccountID: String? = nil) async throws(SignInFailure) -> NativeSignInAttempt {
        guard !Task.isCancelled, let url = BrainBuddyAPI.serverURL(from: serverURL.absoluteString),
            expectedAccountID == nil || expectedAccountID?.isEmpty == false
        else { throw SignInFailure(message: "Use an https server address and a valid account owner.") }
        let previous = current
        let attempt = NativeSignInAttempt(id: UUID(), serverURL: url, expectedAccountID: expectedAccountID)
        // Revoke old proof before any cleanup await, including in-flight responses.
        gate.set(attempt.id)
        current = Context(attempt: attempt, session: NativeAuthenticationSession(serverURL: url, transport: transport, clientVersion: clientVersion))
        if let previous, !previous.submitting { _ = await retire(previous) }
        guard gate.accepts(attempt.id), !Task.isCancelled else {
            if current?.attempt == attempt { _ = await cancel(attempt) }
            throw Self.stale()
        }
        return attempt
    }

    public func complete(_ attempt: NativeSignInAttempt, credential: NativeSignInCredential) async throws(SignInFailure) -> NativeCandidateCompletion {
        guard let context = current, context.attempt == attempt, !context.submitting,
            !context.accepted, gate.accepts(attempt.id), !Task.isCancelled
        else { throw Self.stale() }
        current?.submitting = true
        inFlight.insert(attempt.id)
        defer { inFlight.remove(attempt.id) }
        let completion: AuthCompletionDTO
        do { completion = try await context.session.complete(credential) }
        catch {
            invalidate(attempt)
            _ = await retire(context)
            throw SignInFailure(message: error.message, referenceID: error.referenceID)
        }
        guard gate.accepts(attempt.id), !Task.isCancelled else {
            invalidate(attempt)
            _ = await retire(context)
            throw Self.stale()
        }
        guard case .signedIn(let me, _) = completion else {
            switch completion {
            case .verifyMailbox, .resetReady, .existingAccountRequired:
                current?.submitting = false
                return .continuation(completion)
            default:
                invalidate(attempt)
                _ = await retire(context)
                throw SignInFailure(message: "The server returned an unexpected sign-in response.")
            }
        }
        guard !me.id.isEmpty, !me.email.isEmpty,
            attempt.expectedAccountID == nil || attempt.expectedAccountID == me.id,
            context.session.candidateToken != nil
        else {
            invalidate(attempt)
            _ = await retire(context)
            throw SignInFailure(message: "The sign-in owner does not match this attempt. Your local tasks are kept.")
        }
        current?.submitting = false
        current?.accepted = true
        return .accepted(NativeAcceptedCandidate(ownerID: me.id, attempt: attempt, gate: gate))
    }

    public func cancel(_ attempt: NativeSignInAttempt) async -> NativeCandidateCleanup {
        guard let context = current, context.attempt == attempt else {
            if inFlight.contains(attempt.id) { return .awaitingResponse }
            if retired[attempt.id] != nil { return await clean(attempt.id) }
            return .complete
        }
        invalidate(attempt)
        // The completion owns cleanup of any cookie arriving after cancellation.
        if context.submitting { return .awaitingResponse }
        return await retire(context)
    }

    /// Failed revocations remain private and can be retried while this owner lives.
    public func retryCleanup() async -> NativeCandidateCleanup {
        var result: NativeCandidateCleanup = inFlight.contains { $0 != current?.attempt.id } ? .awaitingResponse : .complete
        for id in Array(retired.keys) {
            switch await clean(id) {
            case .complete: break
            case .awaitingResponse: if case .complete = result { result = .awaitingResponse }
            case .pending(let error): result = .pending(error)
            }
        }
        return result
    }

    public var pendingCleanupCount: Int { retired.count }

    private func invalidate(_ attempt: NativeSignInAttempt) {
        guard current?.attempt == attempt else { return }
        gate.set(nil)
        current = nil
    }

    private func retire(_ context: Context) async -> NativeCandidateCleanup {
        guard context.session.candidateToken != nil else { return .complete }
        retired[context.attempt.id] = context.session
        return await clean(context.attempt.id)
    }

    private func clean(_ id: UUID) async -> NativeCandidateCleanup {
        guard let session = retired[id], let token = session.candidateToken else {
            retired[id] = nil
            return .complete
        }
        guard cleaning.insert(id).inserted else { return .awaitingResponse }
        defer { cleaning.remove(id) }
        // Logout removes its jar even on failure. Keep the original private jar
        // until acknowledgement, so an offline candidate can be retried.
        let jar = InMemorySessionTokenStore(tokens: [session.serverURL: token])
        let client = BrainBuddyAPIClient(baseURL: session.serverURL, transport: transport, tokenStore: jar, clientVersion: clientVersion)
        do { try await client.logout() }
        catch { return .pending(error) }
        session.forgetCandidate()
        retired[id] = nil
        return .complete
    }

    private static func stale() -> SignInFailure {
        SignInFailure(message: "This sign-in attempt is no longer current.")
    }
}

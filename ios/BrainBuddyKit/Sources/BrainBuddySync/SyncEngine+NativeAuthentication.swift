import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization

final class NativeSignInGate: Sendable {
    private let current = Mutex<UUID?>(nil)
    func set(_ id: UUID?) { current.withLock { $0 = id } }
    func accepts(_ id: UUID) -> Bool { current.withLock { $0 == id } }
}

struct NativeSignInContext: Sendable {
    let attempt: NativeSignInAttempt
    let session: NativeAuthenticationSession
    let originalAccount: LinkedAccount?
    var submitting = false
}

extension SyncEngine {
    public func beginSignIn(serverURL: URL) async throws(SignInFailure) -> NativeSignInAttempt {
        await waitForNativeCommit()
        guard let url = BrainBuddyAPI.serverURL(from: serverURL.absoluteString), signInsInProgress == 0 else {
            throw SignInFailure(message: "Wait for the current sign-in, then use an https server address.")
        }
        let previous = nativeSignIn
        invalidateNativeSignIn()
        let id = UUID()
        nativeSignInGate.set(id)
        let stored: LinkedAccount?
        do { stored = try await store.load()?.account } catch {
            if nativeSignInGate.accepts(id) { nativeSignInGate.set(nil) }
            throw SignInFailure(message: "Brain Buddy couldn't read the account on this device.")
        }
        guard nativeSignInGate.accepts(id), !Task.isCancelled else { throw Self.staleNativeAttempt() }
        if let owner = stored ?? account, owner.serverURL != url {
            nativeSignInGate.set(nil)
            throw SignInFailure(message: "Use the server linked to this iPhone. Your local tasks are kept.")
        }
        let attempt = NativeSignInAttempt(id: id, serverURL: url, expectedAccountID: (stored ?? account)?.id)
        nativeSignIn = NativeSignInContext(attempt: attempt, session: NativeAuthenticationSession(serverURL: url, transport: transport, clientVersion: configuration.clientVersion), originalAccount: stored ?? account)
        if let previous { await abandonNativeCandidate(previous) }
        guard nativeSignInGate.accepts(id) else { throw Self.staleNativeAttempt() }
        return attempt
    }

    public func cancelSignIn(_ attempt: NativeSignInAttempt) async {
        guard let context = nativeSignIn, context.attempt == attempt else { return }
        invalidateNativeSignIn()
        await abandonNativeCandidate(context)
    }

    public func completeSignIn(_ attempt: NativeSignInAttempt, credential: NativeSignInCredential) async throws(SignInFailure) -> NativeSignInOutcome {
        guard let context = nativeSignIn, context.attempt == attempt,
            !context.submitting, nativeSignInGate.accepts(attempt.id), !Task.isCancelled
        else { throw Self.staleNativeAttempt() }
        nativeSignIn?.submitting = true
        let completion: AuthCompletionDTO
        do {
            completion = try await context.session.complete(credential)
        } catch {
            if nativeSignInGate.accepts(attempt.id) {
                if context.session.candidateToken == nil, !error.isUncertainOutcome {
                    nativeSignIn?.submitting = false
                } else { invalidateNativeSignIn() }
            }
            await abandonNativeCandidate(context)
            if error.isUncertainOutcome {
                throw SignInFailure(message: "We couldn't confirm whether this finished. Your local tasks are kept. Start a fresh sign-in.", referenceID: error.referenceID)
            }
            throw Self.signInFailure(error)
        }
        guard nativeSignInGate.accepts(attempt.id), !Task.isCancelled else {
            await abandonNativeCandidate(context)
            throw Self.staleNativeAttempt()
        }
        guard case .signedIn(let me, let deletionCancelled) = completion else {
            nativeSignIn?.submitting = false
            switch completion {
            case .verifyMailbox, .resetReady, .existingAccountRequired:
                return .continuation(completion)
            default:
                invalidateNativeSignIn()
                await abandonNativeCandidate(context)
                throw SignInFailure(message: "The server returned an unexpected sign-in response.")
            }
        }
        guard !me.id.isEmpty, !me.email.isEmpty,
            attempt.expectedAccountID == nil || attempt.expectedAccountID == me.id,
            let token = context.session.candidateToken
        else {
            invalidateNativeSignIn()
            await abandonNativeCandidate(context)
            throw SignInFailure(message: "Sign out first to use another account. Your waiting changes are kept.")
        }
        let linked = LinkedAccount(id: me.id, email: me.email, displayName: me.displayName, serverURL: attempt.serverURL, linkedAt: now())
        signInsInProgress += 1
        await stopWork()
        guard nativeSignInGate.accepts(attempt.id), !Task.isCancelled else {
            signInsInProgress -= 1
            if account != nil { kick() }
            await abandonNativeCandidate(context)
            throw Self.staleNativeAttempt()
        }
        // Begin/sign-out wait for persistence. Cancel still invalidates the
        // gate promptly; a cancelled write restores the original binding
        // before any live token installation. No provider I/O holds the lock.
        nativeCommitInProgress = true
        let previousAccount = context.originalAccount
        let previousToken = storedToken(for: attempt.serverURL)
        let gate = nativeSignInGate
        let document: StoreDocument
        do {
            document = try await store.update { doc in
                guard gate.accepts(attempt.id),
                    doc.account?.id == attempt.expectedAccountID,
                    doc.account == nil || doc.account?.isSameAccount(as: linked) == true
                else { throw AccountSwitchRefused() }
                doc.account = linked
            }
            guard gate.accepts(attempt.id), !Task.isCancelled else {
                _ = try await store.update { doc in
                    guard doc.account?.isSameAccount(as: linked) == true else { throw SyncAborted() }
                    doc.account = previousAccount
                }
                throw SyncAborted()
            }
            // Persist the binding first. Failed Keychain installation restores
            // only the binding, preserving work appended by another process.
            do {
                try tokenStore.setToken(token, for: attempt.serverURL)
            } catch {
                _ = try await store.update { doc in
                    guard doc.account?.isSameAccount(as: linked) == true else { throw SyncAborted() }
                    doc.account = previousAccount
                }
                if let previousToken { try? tokenStore.setToken(previousToken, for: attempt.serverURL) }
                else { try? tokenStore.removeToken(for: attempt.serverURL) }
                throw error
            }
        } catch {
            let cancelled = !gate.accepts(attempt.id) || Task.isCancelled
            finishNativeCommit()
            signInsInProgress -= 1
            if nativeSignInGate.accepts(attempt.id) { invalidateNativeSignIn() }
            if account != nil { kick() }
            await abandonNativeCandidate(context)
            if error is AccountSwitchRefused {
                if cancelled { throw Self.staleNativeAttempt() }
                throw SignInFailure(message: "Sign out first to use another account. Your waiting changes are kept.")
            }
            if error is SyncAborted { throw Self.staleNativeAttempt() }
            throw SignInFailure(message: "Brain Buddy couldn't save your sign-in on this device.")
        }
        epoch += 1
        account = linked
        needsSignIn = false
        firstCycle = true
        pullFirst = true
        pullRequested = true
        consecutiveFailures = 0
        consecutiveServerFailures = 0
        rejectionStreak = nil
        lastSyncedAt = document.lastSyncedAt
        invalidateNativeSignIn()
        context.session.forgetCandidate()
        signInsInProgress -= 1
        finishNativeCommit()
        let committedEpoch = epoch
        await emit(.documentChanged(document))
        guard epoch == committedEpoch, account == linked else { throw Self.staleNativeAttempt() }
        if let previousToken, previousToken != token { await endSession(token: previousToken, on: attempt.serverURL) }
        guard epoch == committedEpoch, account == linked else { throw Self.staleNativeAttempt() }
        retryPendingLogouts()
        await syncNow()
        guard epoch == committedEpoch, account == linked else { throw Self.staleNativeAttempt() }
        return .signedIn(SignInResult(account: linked, deletionCancelled: deletionCancelled))
    }

    func invalidateNativeSignIn() {
        nativeSignInGate.set(nil)
        nativeSignIn = nil
    }
    func waitForNativeCommit() async {
        while nativeCommitInProgress { await withCheckedContinuation { nativeCommitWaiters.append($0) } }
    }
    func finishNativeCommit() {
        nativeCommitInProgress = false
        let waiters = nativeCommitWaiters
        nativeCommitWaiters = []
        waiters.forEach { $0.resume() }
    }
    private func abandonNativeCandidate(_ context: NativeSignInContext) async {
        guard let token = context.session.candidateToken else { return }
        context.session.forgetCandidate()
        // A newer accepted session is never undone, even if a server reused a cookie.
        guard storedToken(for: context.attempt.serverURL) != token else { return }
        await endSession(token: token, on: context.attempt.serverURL)
    }
    private static func staleNativeAttempt() -> SignInFailure {
        SignInFailure(message: "This sign-in was cancelled or replaced. Your local tasks are kept.")
    }
}

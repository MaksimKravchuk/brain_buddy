import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

/// Pushes the outbox and pulls the account's data. See `docs/native-ios-app.md`
/// › Sync for the protocol. CONTRACT: the initializer below is what
/// `Workspace.live` calls; implementations keep it.
///
/// - **Push** is sequential, in outbox order, one request per operation,
///   with the operation's `Idempotency-Key`. Every document change is a
///   read-modify-write through the shared store (the workspace appends to
///   the outbox concurrently), followed by `.documentChanged`.
/// - **A cycle** pushes until the outbox is empty or blocked, pulls (after
///   changes, on the first cycle, when asked, when the last pull is older
///   than a minute, or when the server keeps failing the front operation),
///   pushes again if the replay left work, and hydrates the children of
///   changed open tasks. Cycles are single-flight, and so are the task
///   detail reads `refreshTask` asks for: they run in the same slot, so a
///   detail read never overlaps a push.
/// - **Failures**: network errors, 5xx, 429 and refused redirects keep the
///   operation and its key and retry with backoff; an operation the server
///   keeps failing (5xx) is set aside after `rejectionLimit` failures in a
///   row (or `rejectionAge`); 409 stale revision re-reads the record and
///   replays; 401 stops until the user signs in again; a task create or edit
///   rejected for a project or tag gone stale elsewhere is resent without
///   it; other rejections move the operation to `issues`.
public actor SyncEngine: SyncService {
    let store: any DocumentStore
    let tokenStore: any SessionTokenStore
    let transport: any HTTPTransport
    let now: @Sendable () -> Date
    let configuration: SyncConfiguration
    /// Sent as `X-Client`; also tells the account-switch refusal which device to name.
    let identity: ClientIdentity

    var eventHandler: (@Sendable (SyncEvent) async -> Void)?
    var account: LinkedAccount?
    private var cachedClient: (url: URL, client: BrainBuddyAPIClient)?
    /// The status last reported.
    public private(set) var status: SyncStatus = .localOnly
    var networkAvailable = true
    /// Set by a 401; nothing runs until `signIn` or `start`.
    var needsSignIn = false
    /// Bumped by `start`, `signIn` and `signOut`; work from an older epoch stops.
    var epoch = 0
    var lastSyncedAt: Date?
    /// `SyncMetadata.failingSince` as last written, so the retry can land on the 60 s mark.
    var failingSince: Date?
    /// When the cycle whose outcome is being reported began (`lastFailedAttemptAt`).
    var cycleStartedAt = Date()

    // Scheduling.
    var runningCycle: Task<SyncStatus, Never>?
    private var runningCycleID = 0
    /// A trigger arrived while a cycle ran (after its pull decision).
    var rerunRequested = false
    /// The next cycle pulls whatever happened.
    var pullRequested = false
    /// The running cycle already decided whether to pull.
    var pastPullDecision = false
    /// The first cycle after `start` / `signIn` always pulls.
    var firstCycle = true
    /// `signIn`: pull before pushing, so local creates merge by name.
    var pullFirst = false
    private var debounceWork: SyncScheduledWork?
    private var retryWork: SyncScheduledWork?
    var consecutiveFailures = 0
    var consecutiveServerFailures = 0
    /// `syncNow()` calls that joined a running cycle (observed by tests).
    var joinedCycles = 0
    /// Tasks whose details were asked for (`refreshTask`), oldest first. The
    /// single-flight cycle reads them, so a read never overlaps a push whose
    /// acknowledgement it could overwrite with older children.
    var requestedRefreshes: [TaskID] = []
    /// The server's failures in a row of the operation at the front of the outbox.
    var rejectionStreak: RejectionStreak?

    // Sessions.
    /// Sign-ins in progress. Nothing runs meanwhile (a request of the linked
    /// account would carry the session being created), and stale sessions
    /// are not discarded.
    var signInsInProgress = 0
    /// Password sign-ins take turns (spec 021, X-03): one logs in and links, or cleans up after a
    /// Cancel or a refusal, before the next logs in. The login writes the shared token store and
    /// the cleanup puts back the token read before it, so a cancelled login's late reply must never
    /// overlap a newer one's: it would replace, then remove, the newer session.
    var signInTurnTaken = false
    var signInTurnWaiters: [CheckedContinuation<Void, Never>] = []
    /// Sign-ins waiting for their turn.
    var signInsWaiting: Int { signInTurnWaiters.count }
    var nativeSignIn: NativeSignInContext?
    let nativeSignInGate = NativeSignInGate()
    var nativeCommitInProgress = false
    var nativeCommitWaiters: [CheckedContinuation<Void, Never>] = []
    /// A sign-out is between recording its pending logout and finishing: nothing runs, and the
    /// logout waits in the token store until the removal has succeeded.
    var signingOut = false
    /// Sending logouts that waited for the network.
    var logoutWork: Task<Void, Never>?
    /// False once the token store had no pending logouts (saves Keychain reads).
    var mayHavePendingLogouts = true

    /// - Parameters:
    ///   - store: the same document store the workspace writes to.
    ///   - tokenStore: where the session cookie value lives (Keychain in the app).
    ///   - transport: HTTP; tests pass a fake server.
    ///   - now: the clock, injectable for tests.
    ///   - identity: the client the server logs. Its name goes out as `X-Client`; the version sent
    ///     is `SyncConfiguration.clientVersion`, which defaults to the app's own.
    public init(
        store: any DocumentStore, tokenStore: any SessionTokenStore,
        transport: any HTTPTransport = URLSessionTransport(), now: @escaping @Sendable () -> Date = { Date() },
        identity: ClientIdentity = .iOS
    ) {
        self.init(
            store: store, tokenStore: tokenStore, transport: transport, now: now, configuration: SyncConfiguration(),
            identity: identity)
    }

    /// The same, with explicit timers and tunables (tests pass a `ManualSyncScheduler`).
    public init(
        store: any DocumentStore, tokenStore: any SessionTokenStore, transport: any HTTPTransport,
        now: @escaping @Sendable () -> Date, configuration: SyncConfiguration, identity: ClientIdentity = .iOS
    ) {
        self.store = store
        self.tokenStore = tokenStore
        self.transport = transport
        self.now = now
        self.configuration = configuration
        self.identity = identity
    }

    // MARK: - SyncService

    public func setEventHandler(_ handler: @escaping @Sendable (SyncEvent) async -> Void) async {
        eventHandler = handler
    }

    public func start(account: LinkedAccount) async {
        await waitForNativeCommit()
        invalidateNativeSignIn()
        await stopWork()
        epoch += 1
        self.account = account
        needsSignIn = false
        firstCycle = true
        pullRequested = true
        consecutiveFailures = 0
        consecutiveServerFailures = 0
        let stored = try? await store.load()
        lastSyncedAt = stored?.lastSyncedAt
        failingSince = stored?.sync.failingSince
        await setStatus(networkAvailable ? .idle(lastSyncedAt: lastSyncedAt) : .offline(lastSyncedAt: lastSyncedAt))
        await request(.launch)
    }

    public func signIn(serverURL: URL, email: String, password: String) async throws(SignInFailure) -> LinkedAccount {
        try await signInWithResult(serverURL: serverURL, email: email, password: password).account
    }

    public func signInWithResult(
        serverURL: URL, email: String, password: String
    ) async throws(SignInFailure) -> SignInResult {
        try await signInWithResult(serverURL: serverURL, email: email, password: password, cancellation: SignInCancellation())
    }

    public func signInWithResult(
        serverURL: URL, email: String, password: String, cancellation: SignInCancellation
    ) async throws(SignInFailure) -> SignInResult {
        let result: SignInResult
        do throws(SignInFailure) {
            result = try await linkAccount(serverURL: serverURL, email: email, password: password, cancellation: cancellation)
        } catch {
            // Nothing was linked: the account that was (if any) carries on.
            if account != nil {
                pullRequested = true
                kick()
            }
            throw error
        }
        retryPendingLogouts()
        await syncNow()
        return result
    }

    /// Logs in and links the account in the document. Nothing of the linked
    /// account runs meanwhile, and a refused link leaves it as it was.
    private func linkAccount(
        serverURL: URL, email: String, password: String, cancellation: SignInCancellation
    ) async throws(SignInFailure) -> SignInResult {
        await takeSignInTurn()
        defer { passSignInTurn() }
        await waitForNativeCommit()
        invalidateNativeSignIn()
        guard let url = BrainBuddyAPI.serverURL(from: serverURL.absoluteString) else {
            throw SignInFailure(message: "Use an https server address.")
        }
        signInsInProgress += 1
        defer { signInsInProgress -= 1 }
        // Once the login stores the new session, a request of the linked
        // account would carry it: stop that work first.
        await stopWork()
        epoch += 1
        let client = client(for: url)
        let previousToken = storedToken(for: url)
        let me: MeDTO
        do {
            me = try await client.login(email: email, password: password)
        } catch {
            throw Self.signInFailure(error)
        }
        // The one point where Cancel and the link are decided (the Mac's X-03 Cancel): with no
        // suspension between here and the link's write, a Cancel that came first ends the session
        // the server just opened and links nothing (spec 021, FR-001, FR-005); otherwise the link
        // wins, and a Cancel from now on is refused (`SignInCancellation.cancel()` returns false):
        // the sign-in and its first sync finish as a normal one, never reported as cancelled. The
        // logout runs in a task of its own, which a task cancellation does not reach (a request of
        // the cancelled task would never leave); offline it waits as a pending logout.
        if Task.isCancelled || !cancellation.commit() {
            await Task { await self.abandonSession(on: url, restoring: previousToken) }.value
            throw SignInFailure(message: Self.signInCancelledMessage)
        }
        let linked = LinkedAccount(
            id: me.id, email: me.email, displayName: me.displayName, serverURL: url, linkedAt: now()
        )
        let replaced = ReplacedAccount()
        let document: StoreDocument
        do {
            document = try await store.update { doc in
                if let previous = doc.account, !previous.isSameAccount(as: linked) {
                    // Another account's queued changes and issues must never
                    // reach this one: they stay until that account signs out.
                    guard doc.outbox.isEmpty, doc.issues.isEmpty else { throw AccountSwitchRefused() }
                    // Nor may its server data mix with this one's.
                    doc.base = .empty
                    doc.sync = SyncMetadata()
                    replaced.set(previous)
                }
                doc.account = linked
            }
        } catch {
            await abandonSession(on: url, restoring: previousToken)
            if error is AccountSwitchRefused {
                throw SignInFailure(message: SyncCopy.accountSwitchRefused(device: device).sentence)
            }
            throw SignInFailure(message: "Brain Buddy couldn't save your sign-in on this device.")
        }
        account = linked
        needsSignIn = false
        firstCycle = true
        pullFirst = true
        pullRequested = true
        consecutiveFailures = 0
        consecutiveServerFailures = 0
        rejectionStreak = nil
        lastSyncedAt = document.lastSyncedAt
        failingSince = document.sync.failingSince
        await emit(.documentChanged(document))
        if let previous = replaced.value {
            await retireSessions(of: previous, replacedOn: url, previousToken: previousToken)
        }
        if !networkAvailable { await setStatus(.offline(lastSyncedAt: lastSyncedAt)) }
        return SignInResult(account: linked, deletionCancelled: me.deletionCancelled)
    }

    /// Waits until no other password sign-in logs in, links or cleans up (`signInTurnTaken`).
    private func takeSignInTurn() async {
        guard signInTurnTaken else {
            signInTurnTaken = true
            return
        }
        // Handed over by `passSignInTurn()`, still taken.
        await withCheckedContinuation { signInTurnWaiters.append($0) }
    }

    private func passSignInTurn() {
        if signInTurnWaiters.isEmpty {
            signInTurnTaken = false
        } else {
            signInTurnWaiters.removeFirst().resume()
        }
    }

    public func request(_ trigger: SyncTrigger) async {
        if trigger != .localChange { retryPendingLogouts() }
        guard account != nil else {
            await setStatus(.localOnly)
            return
        }
        switch trigger {
        case .localChange:
            debounceWork?.cancel()
            debounceWork = configuration.scheduler.schedule(after: configuration.localChangeDelay) { [weak self] in
                await self?.debounceFired()
            }
        case .launch, .foreground, .networkRestored, .manual, .backgroundRefresh:
            pullRequested = true
            kick()
        case .periodic:
            // Never shortens a backoff, and never asks for a pull: the cycle pulls when the last one is
            // old enough. A tick with nothing to do causes no cycle, no status and no document write.
            guard canRun, retryWork == nil else { return }
            let document = try? await loadDocument()
            let pullIsDue = document?.sync.lastPullAt.map { now().timeIntervalSince($0) >= configuration.pullInterval } ?? true
            let changesWait = !(document?.outbox.isEmpty ?? true) && debounceWork == nil
            if pullIsDue || changesWait { kick() }
        }
    }

    @discardableResult
    public func syncNow() async -> SyncStatus {
        guard account != nil else {
            await setStatus(.localOnly)
            return status
        }
        if let debounce = debounceWork {
            debounce.cancel()
            debounceWork = nil
        }
        pullRequested = true
        guard canRun else { return status }
        if let running = runningCycle {
            // The running cycle pulls unless it already decided not to.
            if pastPullDecision { rerunRequested = true }
            joinedCycles += 1
            return await running.value
        }
        return await startCycles(full: true).value
    }

    /// Reads the task's detail inside the single-flight cycle: after the
    /// running one (which reads it before it ends), or alone.
    public func refreshTask(_ id: TaskID) async {
        guard account != nil, canRun else { return }
        if !requestedRefreshes.contains(id) { requestedRefreshes.append(id) }
        if let running = runningCycle {
            _ = await running.value
        } else {
            _ = await startCycles(full: false).value
        }
    }

    public func setNetworkAvailable(_ available: Bool) async {
        guard available != networkAvailable else { return }
        networkAvailable = available
        if available {
            consecutiveFailures = 0
            retryPendingLogouts()
            await request(.networkRestored)
        } else {
            retryWork?.cancel()
            retryWork = nil
            if account != nil, !needsSignIn { await setStatus(.offline(lastSyncedAt: lastSyncedAt)) }
        }
    }

    // MARK: - Beyond the contract

    /// Waits until no cycle runs and no logout is on its way (tests; also a
    /// clean point before the app is suspended).
    public func waitUntilIdle() async {
        while true {
            if let running = runningCycle {
                _ = await running.value
            } else if let logouts = logoutWork {
                await logouts.value
            } else {
                return
            }
        }
    }

    /// The device the copy that names one (the account-switch refusal) is about.
    var device: DeviceKind { identity.name == ClientIdentity.macOS(version: "").name ? .mac : .iPhone }

    // MARK: - Scheduling

    var canRun: Bool { account != nil && networkAvailable && !needsSignIn && signInsInProgress == 0 && !signingOut }

    func kick() {
        guard canRun else { return }
        if runningCycle != nil {
            rerunRequested = true
            return
        }
        startCycles(full: true)
    }

    private func debounceFired() {
        debounceWork = nil
        kick()
    }

    private func retryFired() {
        retryWork = nil
        kick()
    }

    /// Starts the single-flight task: a full cycle, or (`full: false`) only
    /// the requested task reads, which leave a scheduled retry in place.
    @discardableResult
    private func startCycles(full: Bool) -> Task<SyncStatus, Never> {
        if full {
            retryWork?.cancel()
            retryWork = nil
        }
        runningCycleID += 1
        let id = runningCycleID
        let cycleEpoch = epoch
        // Whoever joins a task that makes no pull decision asks for a cycle.
        pastPullDecision = !full
        let task = Task { await self.runCycles(id: id, epoch: cycleEpoch, full: full) }
        runningCycle = task
        return task
    }

    /// Runs cycles until none was requested meanwhile, reading requested task
    /// details after each, then reports and schedules a retry after a failure.
    private func runCycles(id: Int, epoch cycleEpoch: Int, full: Bool) async -> SyncStatus {
        var outcome: CycleOutcome?
        var runsCycle = full
        while cycleEpoch == epoch {
            if runsCycle {
                rerunRequested = false
                pastPullDecision = false
                let result = await runCycle(epoch: cycleEpoch)
                outcome = result
                if cycleEpoch == epoch { await report(result) }
                guard cycleEpoch == epoch else { break }
            }
            if !requestedRefreshes.isEmpty {
                if canRun {
                    await hydrateRequestedTasks(epoch: cycleEpoch)
                } else {
                    requestedRefreshes.removeAll()
                }
                guard cycleEpoch == epoch else { break }
            }
            runsCycle = rerunRequested && canRun && (outcome?.allowsRerun ?? true)
            // No suspension from this check until the slot is free, so a
            // request made meanwhile is never left behind.
            if !runsCycle, requestedRefreshes.isEmpty { break }
        }
        if runningCycleID == id { runningCycle = nil }
        if cycleEpoch == epoch, outcome?.shouldRetry == true, canRun { scheduleRetry() }
        return status
    }

    private func scheduleRetry() {
        retryWork?.cancel()
        var delay = configuration.retryDelay(afterFailures: max(1, consecutiveFailures))
        // One attempt starts exactly when the failures have lasted `failureSurfacesAfter`: the line
        // says "Couldn't sync" only if that one fails too, and a server back by then shows nothing.
        if let failingSince {
            let untilMark = failingSince.addingTimeInterval(SyncTiming.failureSurfacesAfter).timeIntervalSince(now())
            if untilMark > 0, untilMark < delay { delay = untilMark }
        }
        retryWork = configuration.scheduler.schedule(after: .seconds(delay)) { [weak self] in
            await self?.retryFired()
        }
    }

    /// Cancels timers and stops the running cycle before the account changes.
    func stopWork() async {
        debounceWork?.cancel()
        debounceWork = nil
        retryWork?.cancel()
        retryWork = nil
        if let running = runningCycle {
            epoch += 1
            running.cancel()
            _ = await running.value
        }
        runningCycle = nil
        rerunRequested = false
        pastPullDecision = false
        requestedRefreshes.removeAll()
        rejectionStreak = nil
    }

    // MARK: - Status

    private func report(_ outcome: CycleOutcome) async {
        switch outcome {
        case .synced:
            consecutiveFailures = 0
            consecutiveServerFailures = 0
            await clearFailingClock()
            await setStatus(.idle(lastSyncedAt: lastSyncedAt))
        case .offline(let requestID):
            consecutiveFailures += 1
            pullRequested = true  // the pull this cycle did not finish is still wanted
            // A request that got no answer while the path monitor reports a network is the server's
            // failure; with the network gone it is only "offline", which keeps a running clock.
            if networkAvailable, let requestID { await recordFailingClock(referenceID: requestID) }
            await setStatus(.offline(lastSyncedAt: lastSyncedAt))
        case .serverFailure(let message, let referenceID):
            consecutiveFailures += 1
            consecutiveServerFailures += 1
            pullRequested = true
            // A failure that never reached the server (the store, the Keychain) has no request id, and
            // is not what the 60 s clock is about.
            if let referenceID { await recordFailingClock(referenceID: referenceID) }
            if consecutiveServerFailures >= configuration.failingThreshold {
                await setStatus(.failing(message: message, referenceID: referenceID, lastSyncedAt: lastSyncedAt))
                await recordFailure(message)
            } else {
                await setStatus(.idle(lastSyncedAt: lastSyncedAt))
            }
        case .unauthorized:
            needsSignIn = true
            await setStatus(.needsSignIn)
        case .aborted:
            break
        }
        if !networkAvailable, account != nil, !needsSignIn { await setStatus(.offline(lastSyncedAt: lastSyncedAt)) }
    }

    func setStatus(_ new: SyncStatus) async {
        guard new != status else { return }
        status = new
        await emit(.status(new))
    }

    func emit(_ event: SyncEvent) async {
        await eventHandler?(event)
    }

    /// A server-blocked cycle: starts the failing run if there is none, and notes this attempt.
    private func recordFailingClock(referenceID: String) async {
        guard let account else { return }
        let accountID = account.id
        let started = cycleStartedAt
        guard let document = try? await store.update({ doc in
            guard doc.account?.id == accountID else { throw SyncAborted() }
            doc.sync.failingSince = doc.sync.failingSince ?? started
            doc.sync.lastFailedAttemptAt = started
            doc.sync.lastFailureReferenceID = referenceID
        }) else { return }
        failingSince = document.sync.failingSince
        await emit(.documentChanged(document))
    }

    /// A completed cycle ends the run.
    private func clearFailingClock() async {
        guard failingSince != nil, let account else { return }
        failingSince = nil
        let accountID = account.id
        guard let document = try? await store.update({ doc in
            guard doc.account?.id == accountID else { throw SyncAborted() }
            doc.sync.failingSince = nil
            doc.sync.lastFailedAttemptAt = nil
            doc.sync.lastFailureReferenceID = nil
        }) else { return }
        await emit(.documentChanged(document))
    }

    /// Keeps the last failure in the document's sync metadata.
    private func recordFailure(_ message: String) async {
        guard let account else { return }
        let accountID = account.id
        guard let document = try? await store.update({ doc in
            guard doc.account?.id == accountID, doc.sync.lastFailure != message else { throw SyncAborted() }
            doc.sync.lastFailure = message
        }) else { return }
        await emit(.documentChanged(document))
    }

    // MARK: - Clients

    func client(for url: URL) -> BrainBuddyAPIClient {
        if let cachedClient, cachedClient.url == url { return cachedClient.client }
        let client = BrainBuddyAPIClient(
            baseURL: url, transport: transport, tokenStore: tokenStore, clientVersion: configuration.clientVersion,
            identity: identity
        )
        cachedClient = (url, client)
        return client
    }

    static func signInFailure(_ error: APIError) -> SignInFailure {
        switch error.kind {
        case .unauthorized:
            SignInFailure(message: "Check your email and password.", referenceID: error.referenceID)
        case .rateLimited:
            SignInFailure(message: "Too many attempts. Try again in a few minutes.", referenceID: error.referenceID)
        case .network:
            // The id the request carried: online, a request with no answer is "Brain Buddy didn't
            // answer" on the Mac, quoted with that id (spec 021, FR-015); offline the app shows none.
            SignInFailure(message: networkFailureMessage, referenceID: error.referenceID)
        case .cancelled:
            SignInFailure(message: networkFailureMessage)
        default:
            SignInFailure(message: error.message, referenceID: error.referenceID)
        }
    }

    /// A sign-in whose request got no answer (or never left).
    public static let networkFailureMessage = "Can't reach the server. Check your connection."
    /// A sign-in the person cancelled: its late reply was undone.
    public static let signInCancelledMessage = "The sign-in was cancelled."
}

/// How one cycle ended.
enum CycleOutcome: Sendable {
    case synced
    /// No answer. `requestID` is the id the failed request carried; nil when it was only cancelled.
    case offline(requestID: String?)
    case serverFailure(message: String, referenceID: String?)
    case unauthorized
    case aborted

    var allowsRerun: Bool {
        switch self {
        case .synced: true
        case .offline, .serverFailure, .unauthorized, .aborted: false
        }
    }

    var shouldRetry: Bool {
        switch self {
        case .offline, .serverFailure: true
        case .synced, .unauthorized, .aborted: false
        }
    }
}

/// What one cycle works with; `epoch` stops it when the account changes.
struct CycleContext: Sendable {
    let account: LinkedAccount
    let client: BrainBuddyAPIClient
    let epoch: Int
}

/// The server failing the operation at the front of the outbox, in a row.
struct RejectionStreak: Sendable {
    var operationID: UUID
    var count: Int
    /// The first failure of the streak, or the operation's first attempt
    /// with its current key when that is earlier (it survives a relaunch).
    var since: Date
}

/// The work belongs to an account that is no longer linked (or was cancelled).
struct SyncAborted: Error {}

/// Signing in to another account while the linked one still has queued
/// changes or sync issues on the device.
struct AccountSwitchRefused: Error {}

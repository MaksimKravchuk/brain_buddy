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
///   changes, on the first cycle, when asked, or when the last pull is older
///   than a minute), pushes again if the replay left work, and hydrates the
///   children of changed open tasks. Cycles are single-flight.
/// - **Failures**: network errors, 5xx and 429 keep the operation and its key
///   and retry with backoff; 409 stale revision re-reads the record and
///   replays; 401 stops until the user signs in again; other rejections move
///   the operation to `issues`.
public actor SyncEngine: SyncService {
    let store: any DocumentStore
    let tokenStore: any SessionTokenStore
    let transport: any HTTPTransport
    let now: @Sendable () -> Date
    let configuration: SyncConfiguration

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

    /// - Parameters:
    ///   - store: the same document store the workspace writes to.
    ///   - tokenStore: where the session cookie value lives (Keychain in the app).
    ///   - transport: HTTP; tests pass a fake server.
    ///   - now: the clock, injectable for tests.
    public init(
        store: any DocumentStore, tokenStore: any SessionTokenStore,
        transport: any HTTPTransport = URLSessionTransport(), now: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.init(store: store, tokenStore: tokenStore, transport: transport, now: now, configuration: SyncConfiguration())
    }

    /// The same, with explicit timers and tunables (tests pass a `ManualSyncScheduler`).
    public init(
        store: any DocumentStore, tokenStore: any SessionTokenStore, transport: any HTTPTransport,
        now: @escaping @Sendable () -> Date, configuration: SyncConfiguration
    ) {
        self.store = store
        self.tokenStore = tokenStore
        self.transport = transport
        self.now = now
        self.configuration = configuration
    }

    // MARK: - SyncService

    public func setEventHandler(_ handler: @escaping @Sendable (SyncEvent) async -> Void) async {
        eventHandler = handler
    }

    public func start(account: LinkedAccount) async {
        await stopWork()
        epoch += 1
        self.account = account
        needsSignIn = false
        firstCycle = true
        pullRequested = true
        consecutiveFailures = 0
        consecutiveServerFailures = 0
        lastSyncedAt = (try? await store.load())?.lastSyncedAt
        await setStatus(networkAvailable ? .idle(lastSyncedAt: lastSyncedAt) : .offline(lastSyncedAt: lastSyncedAt))
        await request(.launch)
    }

    public func signIn(serverURL: URL, email: String, password: String) async throws(SignInFailure) -> LinkedAccount {
        guard let url = BrainBuddyAPI.serverURL(from: serverURL.absoluteString) else {
            throw SignInFailure(message: "Use an https server address.")
        }
        let client = client(for: url)
        let me: MeDTO
        do {
            me = try await client.login(email: email, password: password)
        } catch {
            throw Self.signInFailure(error)
        }
        let linked = LinkedAccount(
            id: me.id, email: me.email, displayName: me.displayName, serverURL: url, linkedAt: now()
        )
        await stopWork()
        epoch += 1
        account = linked
        needsSignIn = false
        firstCycle = true
        pullFirst = true
        pullRequested = true
        consecutiveFailures = 0
        consecutiveServerFailures = 0
        let date = now()
        do {
            let document = try await store.update { doc in
                if let previous = doc.account, previous.id != linked.id {
                    // Another account's server data must not mix with this one's.
                    doc.base = .empty
                    doc.sync = SyncMetadata()
                    doc.replayOutbox(now: date)
                }
                doc.account = linked
            }
            lastSyncedAt = document.lastSyncedAt
            await emit(.documentChanged(document))
        } catch {
            account = nil
            try? client.discardStoredSession()
            await setStatus(.localOnly)
            throw SignInFailure(message: "Brain Buddy couldn't save your sign-in on this device.")
        }
        if !networkAvailable { await setStatus(.offline(lastSyncedAt: lastSyncedAt)) }
        await syncNow()
        return linked
    }

    public func signOut() async {
        let signedOut = account
        await stopWork()
        epoch += 1
        account = nil
        needsSignIn = false
        pullFirst = false
        if let signedOut {
            try? await client(for: signedOut.serverURL).logout()
        }
        await setStatus(.localOnly)
    }

    public func request(_ trigger: SyncTrigger) async {
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
        return await startCycles().value
    }

    public func refreshTask(_ id: TaskID) async {
        guard let account, canRun else { return }
        let context = CycleContext(account: account, client: client(for: account.serverURL), epoch: epoch)
        do {
            guard let serverID = try await loadDocument().base.tasks[id]?.serverID else { return }
            try await hydrate([serverID], context)
        } catch let error as APIError {
            if case .unauthorized = error.kind, context.epoch == epoch {
                needsSignIn = true
                await setStatus(.needsSignIn)
            }
        } catch {
            // Offline, aborted or unreadable: the detail shows what the device has.
        }
    }

    public func setNetworkAvailable(_ available: Bool) async {
        guard available != networkAvailable else { return }
        networkAvailable = available
        if available {
            consecutiveFailures = 0
            await request(.networkRestored)
        } else {
            retryWork?.cancel()
            retryWork = nil
            if account != nil, !needsSignIn { await setStatus(.offline(lastSyncedAt: lastSyncedAt)) }
        }
    }

    // MARK: - Beyond the contract

    /// Waits until no cycle is running (tests; also a clean point before
    /// the app is suspended).
    public func waitUntilIdle() async {
        while let running = runningCycle { _ = await running.value }
    }

    // MARK: - Scheduling

    var canRun: Bool { account != nil && networkAvailable && !needsSignIn }

    func kick() {
        guard canRun else { return }
        if runningCycle != nil {
            rerunRequested = true
            return
        }
        startCycles()
    }

    private func debounceFired() {
        debounceWork = nil
        kick()
    }

    private func retryFired() {
        retryWork = nil
        kick()
    }

    @discardableResult
    private func startCycles() -> Task<SyncStatus, Never> {
        retryWork?.cancel()
        retryWork = nil
        runningCycleID += 1
        let id = runningCycleID
        let cycleEpoch = epoch
        let task = Task { await self.runCycles(id: id, epoch: cycleEpoch) }
        runningCycle = task
        return task
    }

    /// Runs cycles until none was requested meanwhile, then reports and
    /// schedules a retry after a failure.
    private func runCycles(id: Int, epoch cycleEpoch: Int) async -> SyncStatus {
        var outcome = CycleOutcome.aborted
        repeat {
            rerunRequested = false
            pastPullDecision = false
            outcome = await runCycle(epoch: cycleEpoch)
            if cycleEpoch == epoch { await report(outcome) }
        } while rerunRequested && cycleEpoch == epoch && canRun && outcome.allowsRerun
        if runningCycleID == id { runningCycle = nil }
        if cycleEpoch == epoch, outcome.shouldRetry, canRun { scheduleRetry() }
        return status
    }

    private func scheduleRetry() {
        retryWork?.cancel()
        let delay = configuration.retryDelay(afterFailures: max(1, consecutiveFailures))
        retryWork = configuration.scheduler.schedule(after: .seconds(delay)) { [weak self] in
            await self?.retryFired()
        }
    }

    /// Cancels timers and stops the running cycle before the account changes.
    private func stopWork() async {
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
    }

    // MARK: - Status

    private func report(_ outcome: CycleOutcome) async {
        switch outcome {
        case .synced:
            consecutiveFailures = 0
            consecutiveServerFailures = 0
            await setStatus(.idle(lastSyncedAt: lastSyncedAt))
        case .offline:
            consecutiveFailures += 1
            await setStatus(.offline(lastSyncedAt: lastSyncedAt))
        case .serverFailure(let message, let referenceID):
            consecutiveFailures += 1
            consecutiveServerFailures += 1
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
            baseURL: url, transport: transport, tokenStore: tokenStore, clientVersion: configuration.clientVersion
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
        case .network, .cancelled:
            SignInFailure(message: "Can't reach the server. Check your connection.")
        default:
            SignInFailure(message: error.message, referenceID: error.referenceID)
        }
    }
}

/// How one cycle ended.
enum CycleOutcome: Sendable {
    case synced
    case offline
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

/// The work belongs to an account that is no longer linked (or was cancelled).
struct SyncAborted: Error {}

import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyPersistence
import BrainBuddySync
import BrainBuddyWorkspace
import Foundation
import Testing

@testable import BrainBuddyMacCore

/// The Mac's sync flows against a stub server (contracts/mac-app-host.md §5, §7, §8): what an
/// account-less or signed-out Mac sends (nothing but a pending logout), sign-in (X-03) and its
/// errors, the account-switch refusal, sign-out (X-04) with its count and backup rules, the token
/// store's calls (off the main thread, none in a dry run until a sign-in), and the client identity.
/// The XCTest ledger's sign-in rows (`APIClientTests`) end here.
@Suite("Mac sync flows")
@MainActor
struct MacSyncFlowTests {
    /// One Mac: its folder, the stub server, a spy token store, manual timers, and the host, the
    /// sync controller and the trigger source the app builds.
    @MainActor
    final class Rig {
        let folder: TemporaryFolder
        let clock: TestClock
        let server: StubServer
        let tokens: SpyTokenStore
        let ticks: ManualSyncScheduler
        let timers: ManualSyncScheduler
        let details = ManualSyncScheduler()
        let log: CapturingMacLog
        let monitor = FakePathMonitor()
        let activity = FakeActivity()
        let host: WorkspaceHost
        let controller: MacSyncController
        let triggers: SyncTriggerSource
        let model: BrainBuddyModel

        init(
            folder: TemporaryFolder = TemporaryFolder(), server: StubServer = StubServer(), tokens: SpyTokenStore = SpyTokenStore(),
            dryRun: Bool = false
        ) async {
            self.folder = folder
            self.server = server
            self.tokens = tokens
            clock = TestClock()
            log = CapturingMacLog()
            ticks = ManualSyncScheduler()
            timers = ManualSyncScheduler()
            host = WorkspaceHost(
                configuration: MacHostConfiguration(directory: folder.url, isDryRun: dryRun), tokenStore: tokens,
                transport: server, now: clock.provider, makeID: SequentialIDs(namespace: 9).provider, tickScheduler: ticks,
                syncScheduler: timers, log: log
            )
            await host.workspace.load()
            (controller, triggers, model) = Self.wire(host, clock: clock, log: log, monitor: monitor, activity: activity, details: details)
        }

        /// The same wiring around a host a launch made.
        init(
            launched host: WorkspaceHost, folder: TemporaryFolder, server: StubServer, tokens: SpyTokenStore, log: CapturingMacLog,
            ticks: ManualSyncScheduler, timers: ManualSyncScheduler, clock: TestClock = TestClock()
        ) {
            self.folder = folder
            self.server = server
            self.tokens = tokens
            self.host = host
            self.log = log
            self.ticks = ticks
            self.timers = timers
            self.clock = clock
            (controller, triggers, model) = Self.wire(host, clock: clock, log: log, monitor: monitor, activity: activity, details: details)
        }

        private static func wire(
            _ host: WorkspaceHost, clock: TestClock, log: CapturingMacLog, monitor: FakePathMonitor, activity: FakeActivity,
            details: ManualSyncScheduler
        ) -> (MacSyncController, SyncTriggerSource, BrainBuddyModel) {
            let controller = MacSyncController(host: host, now: clock.provider, log: log, defaultServer: { StubServer.server })
            let triggers = SyncTriggerSource(target: host, pathMonitor: monitor, activity: activity, detailScheduler: details, log: log)
            controller.triggers = triggers
            let model = BrainBuddyModel(workspace: host.workspace, localStateStore: host.localState, now: clock.provider)
            controller.signOut.didSignOut = { model.didSignOut() }
            return (controller, triggers, model)
        }

        var workspace: Workspace { host.workspace }

        /// Waits until the network reports, the engine and the store are quiet.
        func settle() async {
            await workspace.waitForNetworkUpdates()
            await host.engine.waitUntilIdle()
            await workspace.flush()
            await host.engine.waitUntilIdle()
            controller.observeSnapshot()
        }

        /// Every trigger of mac-app-host §5 once: launch, activation, the window shown, four 15 s
        /// ticks, the network gone and back, and a local change with its debounce.
        func fireEveryTrigger(capturing title: String = "Call the landlord") async throws {
            await triggers.start()
            await triggers.handle(.didBecomeActive)
            await triggers.handle(.windowBecameVisible)
            for _ in 0..<4 { await ticks.runNext() }
            triggers.pathChanged(satisfied: false)
            await settle()
            triggers.pathChanged(satisfied: true)
            await settle()
            try workspace.capture(CaptureDraft(text: title, list: .inbox))
            await workspace.flush()
            await timers.runAll()
            await settle()
        }

        /// X-03 to the end: the flow, after its one request.
        @discardableResult
        func signIn(_ account: StubServer.Account = StubServer.ada, from entry: SignInEntry = .statusLineAction) async -> SignInFlow? {
            controller.beginSignIn(from: entry)
            guard let flow = controller.signIn else { return nil }
            if !flow.isLocked { flow.email = account.email }
            flow.password = account.password
            flow.submit()
            await flow.waitForAttempt()
            await settle()
            // Signed in: the sheet closes, as the app's sheet does.
            if flow.phase == .finished { controller.closeSignIn() }
            return flow
        }

        /// A change that waits: captured, written, its debounce not run.
        func captureWaiting(_ title: String) async throws {
            try workspace.capture(CaptureDraft(text: title, list: .inbox))
            await workspace.flush()
        }

        /// The session ends on the server; the next sync finds out.
        func endSession() async {
            server.endSessions()
            await workspace.syncNow()
            await settle()
        }
    }

    // MARK: Nothing is sent before sign-in (FR-029)

    @Test("021-FR-029 account-less: launch, foreground, 15 s ticks, network-restored and local-change triggers send no request")
    func accountLessSendsNothing() async throws {
        let rig = await Rig()
        try await rig.fireEveryTrigger()
        #expect(rig.server.requests.isEmpty, "\(rig.server.routes)")
        #expect(rig.workspace.pendingChangeCount == 1, "the change stays on this Mac")
        #expect(!rig.activity.held, "no App Nap activity account-less")
    }

    @Test("021-FR-029 021-FR-005 after a sign-out the only request is the queued logout")
    func afterSignOutOnlyTheLogout() async throws {
        let rig = await Rig()
        await rig.triggers.start()
        let flow = await rig.signIn()
        #expect(flow?.phase == .finished)
        #expect(rig.activity.held, "the App Nap activity while signed in")
        rig.triggers.pathChanged(satisfied: false)
        await rig.settle()

        rig.controller.presentSignOut()
        #expect(await rig.controller.confirmSignOut() == .signedOut)
        #expect(rig.workspace.account == nil)
        #expect(!rig.activity.held, "ended at sign-out")
        #expect(rig.server.liveSessions == 1, "offline: the logout waits")
        rig.server.clearLog()

        try await rig.fireEveryTrigger()
        #expect(rig.server.routes == ["POST /auth/logout"])
        #expect(rig.server.liveSessions == 0)
        #expect(rig.tokens.storedPending.isEmpty && rig.tokens.storedTokens.isEmpty)
    }

    @Test("021-FR-029 021-FR-005 an upgraded account-less Mac with a pre-021 cookie sends one bodiless logout, to that cookie's host only")
    func upgradedMacSendsOneLogout() async throws {
        let folder = TemporaryFolder()
        let server = StubServer()
        let tokens = SpyTokenStore()
        let log = CapturingMacLog()
        let ticks = ManualSyncScheduler()
        let timers = ManualSyncScheduler()
        let launch = MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: MacHostConfiguration(directory: folder.url, isDryRun: false), tokenStore: tokens, transport: server,
                cookieJar: FakeCookieJar([FakeCookieJar.session("legacy-session", domain: "api.example.com")]),
                responseCache: FakeResponseCache(), now: TestClock().provider, makeID: SequentialIDs().provider, log: log,
                tickScheduler: ticks, syncScheduler: timers
            )
        )
        await launch.run { _ in }
        let host = try #require(launch.host)
        let rig = Rig(launched: host, folder: folder, server: server, tokens: tokens, log: log, ticks: ticks, timers: timers)
        await rig.settle()
        await rig.triggers.start()
        await rig.triggers.handle(.didBecomeActive)
        for _ in 0..<4 { await ticks.runNext() }
        rig.triggers.pathChanged(satisfied: false)
        rig.triggers.pathChanged(satisfied: true)
        await rig.settle()

        let requests = server.requests
        #expect(requests.count == 1, "\(server.routes)")
        let logout = try #require(requests.first)
        #expect(logout.method == .post)
        #expect(logout.url.absoluteString == "https://api.example.com/auth/logout")
        #expect(logout.body == nil, "bodiless: no task data")
        #expect(logout.header("Cookie") == "brainbuddy_session=legacy-session")
        #expect(tokens.storedPending.isEmpty, "delivered, so no longer pending")
    }

    @Test("021-FR-030 the sync category's log lines hold no title, email or host")
    func syncLogsHoldNoContent() async throws {
        let sentinel = "Sentinel-7f3c title"
        let rig = await Rig()
        try await rig.fireEveryTrigger(capturing: sentinel)
        rig.controller.beginSignIn(from: .menu)
        rig.controller.signIn?.email = StubServer.ada.email
        rig.controller.signIn?.password = "wrong password"
        rig.controller.signIn?.submit()
        await rig.controller.signIn?.waitForAttempt()
        rig.controller.closeSignIn()
        await rig.signIn()
        try await rig.captureWaiting("\(sentinel) two")
        rig.controller.presentSignOut()
        _ = await rig.controller.confirmSignOut()

        let lines = rig.log.messages(.sync)
        #expect(!lines.isEmpty)
        for line in lines {
            for secret in ["Sentinel", "alex@example.com", "example.com", "api.example", "wrong password", StubServer.ada.password] {
                #expect(!line.contains(secret), "“\(line)” holds \(secret)")
            }
        }
    }

    // MARK: Sign-in (X-03)

    @Test("021-FR-001 021-FR-003 sign-in sends one request, with the sheet read-only meanwhile; the first sign-in names the local tasks")
    func signInIsSingleFlight() async throws {
        let rig = await Rig()
        try await rig.captureWaiting("Order soil")
        rig.server.holdNextLogin()
        rig.controller.beginSignIn(from: .statusLineAction)
        let flow = try #require(rig.controller.signIn)
        #expect(flow.showsLocalTasksNotice, "the outbox holds account-less data")
        #expect(flow.title == "Sign in to Brain Buddy" && !flow.canSubmit, "disabled until filled")
        flow.email = StubServer.ada.email
        flow.password = StubServer.ada.password
        flow.submit()
        flow.submit()
        await rig.server.loginGate.waitForArrival()
        #expect(flow.phase == .signingIn && flow.submitTitle == "Signing in…")
        #expect(flow.credentialsReadOnly && flow.accountFieldsReadOnly && !flow.canSubmit)
        flow.submit()
        await rig.server.loginGate.open()
        await flow.waitForAttempt()
        await rig.settle()

        #expect(flow.phase == .finished)
        #expect(flow.requestsStarted == 1)
        #expect(rig.server.routes.filter { $0 == "POST /auth/login" }.count == 1)
        #expect(rig.workspace.account?.email == StubServer.ada.email)
        rig.controller.closeSignIn()
        #expect(rig.controller.router.surface == nil)
        #expect(rig.controller.router.focus?.target == .statusWords, "the trailing action vanished: focus to the words")
    }

    @Test("021-FR-001 Sign in… again while X-03 is signing in keeps that flow and its request; no second login starts")
    func secondSignInWhileSigningInKeepsTheFirst() async throws {
        let rig = await Rig()
        rig.server.holdNextLogin()
        rig.controller.beginSignIn(from: .statusLineAction)
        let flow = try #require(rig.controller.signIn)
        flow.email = StubServer.ada.email
        flow.password = StubServer.ada.password
        flow.submit()
        await rig.server.loginGate.waitForArrival()
        let presented = rig.controller.router.presented.count
        #expect(rig.controller.isSignInOpen, "the app menu's Sign in… is disabled")

        // The app menu's "Sign in…" (or any other entry) while the first sheet waits for its login.
        rig.controller.beginSignIn(from: .menu)
        #expect(rig.controller.signIn === flow, "the open flow stays")
        #expect(rig.controller.router.presented.count == presented, "no second sheet")
        #expect(flow.phase == .signingIn && flow.email == StubServer.ada.email)

        await rig.server.loginGate.open()
        await flow.waitForAttempt()
        await rig.settle()
        #expect(flow.phase == .finished && flow.requestsStarted == 1)
        #expect(rig.server.routes.filter { $0 == "POST /auth/login" }.count == 1)
        #expect(rig.workspace.account?.email == StubServer.ada.email)
        rig.controller.closeSignIn()
        #expect(!rig.controller.isSignInOpen)
    }

    @Test("021-FR-018 Sign out… while Sign in again is signing in does nothing; the sign-in links and stays linked")
    func signOutWhileSigningInDoesNothing() async throws {
        let rig = await Rig()
        await rig.signIn()
        await rig.endSession()
        rig.server.holdNextLogin()
        rig.controller.beginSignIn(from: .menu)
        let flow = try #require(rig.controller.signIn)
        flow.password = StubServer.ada.password
        flow.submit()
        await rig.server.loginGate.waitForArrival()
        #expect(rig.controller.accountMenu.signOut, "linked, so the item is there")
        #expect(rig.controller.isSignInOpen, "and disabled")

        // The app menu's (or X-02's) "Sign out…" while X-03 waits for its login.
        let requests = rig.controller.signOutRequests
        rig.controller.requestSignOut()
        rig.controller.presentSignOut()
        #expect(rig.controller.signOutRequests == requests, "no unsaved-edit guard, no X-04")
        #expect(rig.controller.signOut.prompt == nil)
        #expect(rig.controller.router.signInRequest != nil, "X-03 stays")

        await rig.server.loginGate.open()
        await flow.waitForAttempt()
        await rig.settle()
        #expect(flow.phase == .finished)
        #expect(rig.workspace.account?.email == StubServer.ada.email)
        let stored = try await FileDocumentStore(fileURL: rig.folder.store).load()
        #expect(stored?.account == rig.workspace.account, "linked in the store as in the window")
    }

    @Test("021-FR-001 Sign in… while a confirmed sign-out commits does nothing; the sign-out finishes")
    func signInWhileSigningOutDoesNothing() async throws {
        let rig = await Rig()
        await rig.signIn()
        rig.server.holdNextLogout()
        rig.controller.presentSignOut()
        let controller = rig.controller
        let confirming = Task { await controller.confirmSignOut() }
        await rig.server.logoutGate.waitForArrival()
        #expect(rig.controller.isSigningOut, "the app menu's Sign in… is disabled")

        rig.controller.beginSignIn(from: .menu)
        #expect(rig.controller.signIn == nil, "no X-03")
        #expect(rig.controller.router.signInRequest == nil)

        await rig.server.logoutGate.open()
        #expect(await confirming.value == .signedOut)
        await rig.settle()
        #expect(rig.workspace.account == nil)
        #expect(rig.server.routes.filter { $0 == "POST /auth/login" }.count == 1, "only the first sign-in's")
        #expect(!rig.controller.isSigningOut)
    }

    @Test("021-FR-001 021-FR-005 Cancel while signing in keeps the typed values; the reply after it has its session ended and links nothing")
    func cancelWhileSigningIn() async throws {
        let rig = await Rig()
        rig.server.holdNextLogin()
        rig.controller.beginSignIn(from: .menu)
        let flow = try #require(rig.controller.signIn)
        flow.email = StubServer.ada.email
        flow.password = StubServer.ada.password
        flow.submit()
        await rig.server.loginGate.waitForArrival()

        #expect(flow.canCancel, "before the link, Cancel applies")
        #expect(flow.cancel() == false, "the sheet stays open")
        #expect(flow.phase == .editing && flow.email == StubServer.ada.email && flow.password == StubServer.ada.password)
        #expect(flow.preferredFocus == .signInPassword)
        await rig.server.loginGate.open()
        await flow.waitForAttempt()
        await rig.settle()

        #expect(rig.workspace.account == nil, "nothing is linked")
        #expect(rig.server.liveSessions == 0, "the late session is ended at once")
        #expect(rig.server.routes == ["POST /auth/login", "POST /auth/logout"])
        #expect(flow.phase == .editing && flow.message == nil, "nothing changed in the sheet")
        #expect(rig.tokens.storedTokens.isEmpty)
    }

    @Test("021-FR-001 021-FR-005 once the account is linked, Cancel never says cancelled: the first sync runs and the sheet closes signed in")
    func cancelAfterTheLinkDoesNotClaimCancelled() async throws {
        let rig = await Rig()
        try await rig.captureWaiting("Order soil")
        rig.server.holdNextSync()
        rig.controller.beginSignIn(from: .statusLineAction)
        let flow = try #require(rig.controller.signIn)
        flow.email = StubServer.ada.email
        flow.password = StubServer.ada.password
        flow.submit()
        // The link is saved and the first sync's first request is on its way.
        await rig.server.syncGate.waitForArrival()
        #expect(!flow.canCancel, "Cancel and Esc no longer apply")
        #expect(flow.submitTitle == "Signing in…" && flow.credentialsReadOnly)

        #expect(flow.cancel() == false, "the sheet stays open")
        #expect(flow.phase == .finishing, "the sheet doesn't go back to the form as if nothing happened")
        #expect(!rig.log.messages(.sync).contains("sign-in cancelled"))
        await rig.server.syncGate.open()
        await flow.waitForAttempt()
        await rig.settle()

        #expect(flow.phase == .finished, "signed in: the sheet closes on what is true")
        #expect(rig.workspace.account?.email == StubServer.ada.email)
        #expect(rig.server.routes.contains("POST /tasks"), "the first sync ran as a normal signed-in sync")
        rig.controller.closeSignIn()
        #expect(rig.controller.router.focus?.target == .statusWords, "closed as signed in, not as cancelled")
    }

    @Test("021-FR-001 021-FR-015 sign-in errors in this Mac's words, with the reference id where there is one")
    func signInErrors() async throws {
        let rig = await Rig()
        rig.controller.beginSignIn(from: .menu)
        let flow = try #require(rig.controller.signIn)
        flow.email = StubServer.ada.email
        flow.password = "not the password"
        flow.submit()
        await flow.waitForAttempt()
        #expect(flow.message?.kind == .wrongPassword && flow.message?.title == "Check your email and password.")
        #expect(flow.message?.referenceID == rig.server.requests.last?.header("X-Correlation-ID"))
        #expect(flow.preferredFocus == .signInPassword)

        // Online, but no answer: the id the request carried.
        rig.server.setOffline(true)
        flow.password = StubServer.ada.password
        flow.submit()
        await flow.waitForAttempt()
        #expect(flow.message?.kind == .noAnswer && flow.message?.title == "Brain Buddy didn't answer. Try again.")
        #expect(flow.message?.referenceID != nil)
        #expect(flow.message?.referenceID == rig.server.requests.last?.header("X-Correlation-ID"))

        // Offline: the reason and the reassurance, no reference id.
        rig.triggers.pathChanged(satisfied: false)
        await rig.settle()
        flow.submit()
        await flow.waitForAttempt()
        #expect(flow.message?.kind == .offline && flow.message?.referenceID == nil)
        #expect(flow.message?.detail == SignInCopy.offlineReassurance)

        flow.serverAddress = "http://example.com/api"
        flow.submit()
        #expect(flow.message?.title == "Use an https server address. http works only for localhost.")
        #expect(rig.workspace.account == nil)

        let unsaved = SignInFlow.message(
            for: WorkspaceError.signInFailed(message: APIError.tokenNotSavedMessage, referenceID: "4e5d9a20"), isOnline: true)
        #expect(unsaved == .init(kind: .couldNotSave, title: "Brain Buddy couldn't save your sign-in on this Mac. Try again.", referenceID: "4e5d9a20"))
        #expect(
            SignInFlow.message(for: WorkspaceError.signInFailed(message: SyncEngine.signInCancelledMessage, referenceID: nil), isOnline: true)
                == nil, "a cancelled sign-in shows nothing")
    }

    @Test("021-FR-017 a sign-in that cancelled the account's deletion says so in the sheet before it closes")
    func deletionCancelledNote() async throws {
        let rig = await Rig()
        rig.server.scheduleDeletion(StubServer.ada.email)
        let flow = try #require(await rig.signIn())
        #expect(flow.phase == .deletionCancelledNote)
        #expect(flow.preferredFocus == .signInNote)
        #expect(rig.workspace.account != nil, "sync has already started behind it")
        #expect(flow.cancel() == true, "OK, Return or Esc closes the sheet")
        #expect(flow.phase == .finished)
        #expect(!rig.workspace.signInCancelledAccountDeletion)
    }

    @Test("021-FR-001 a session that ended keeps the outbox; Sign in again to the same account sends it")
    func sessionEndedThenSignInAgainSends() async throws {
        let rig = await Rig()
        await rig.signIn()
        try await rig.captureWaiting("Book the plumber")
        await rig.endSession()
        #expect(rig.workspace.syncSnapshot.sessionEnded)
        #expect(rig.workspace.pendingChangeCount == 1, "the change is kept")
        #expect(rig.controller.line.description.text == "Sign in again to sync")
        #expect(rig.controller.accountMenu == AccountMenuItems(signIn: false, signInAgain: true, signOut: true))
        #expect(!rig.controller.syncNowEnabled)
        rig.server.clearLog()

        let flow = try #require(await rig.signIn(from: .popover))
        #expect(flow.isLocked && flow.email == StubServer.ada.email, "locked to the account")
        #expect(flow.phase == .finished)
        let sent = rig.server.requests.filter { $0.method == .post && StubServer.route($0.url) == "/tasks" }
        #expect(sent.count >= 1)
        #expect(sent.allSatisfy { String(decoding: $0.body ?? Data(), as: UTF8.self).contains("Book the plumber") })
    }

    @Test("021-FR-004 Sign in again that resolves to another account while changes wait is refused, and nothing is sent (US4-5)")
    func accountSwitchRefused() async throws {
        let rig = await Rig()
        await rig.signIn()
        try await rig.captureWaiting("Ada's private task")
        await rig.endSession()
        rig.server.reassign(StubServer.ada.email, to: "user_ada_recreated")
        rig.server.clearLog()

        let flow = try #require(await rig.signIn(from: .menu))
        #expect(flow.message?.kind == .accountSwitchRefused)
        #expect(flow.message?.title == "Sign out first to use another account.")
        #expect(flow.message?.detail == "Changes from the other account are still waiting on this Mac.")
        #expect(rig.server.routes == ["POST /auth/login", "POST /auth/logout"], "nothing but the refused session's end")
        #expect(rig.server.liveSessions == 0)
        #expect(rig.workspace.account?.id == StubServer.ada.id && rig.workspace.pendingChangeCount == 1)
    }

    @Test("021-FR-004 the same owner id on another server is refused while changes wait, and nothing is sent")
    func sameOwnerOnAnotherServerRefused() async throws {
        let rig = await Rig()
        await rig.signIn()
        try await rig.captureWaiting("Ada's private task")
        await rig.endSession()
        rig.server.clearLog()

        let workspace = rig.workspace
        let flow = SignInFlow(
            mode: .signIn, hasLocalTasks: false, defaultServer: StubServer.otherServer, isOnline: { true },
            signIn: { url, email, password, cancellation in
                try await workspace.signIn(serverURL: url, email: email, password: password, cancellation: cancellation)
            }
        )
        flow.email = StubServer.ada.email
        flow.password = StubServer.ada.password
        flow.submit()
        await flow.waitForAttempt()
        await rig.settle()

        #expect(flow.message?.kind == .accountSwitchRefused)
        #expect(rig.server.requests.allSatisfy { $0.url.host == "other.example.org" })
        #expect(rig.server.routes == ["POST /auth/login", "POST /auth/logout"])
        #expect(rig.workspace.account?.serverURL == StubServer.server && rig.workspace.pendingChangeCount == 1)
    }

    // MARK: Sign-out (X-04)

    @Test("021-FR-018 X-04 shown with 3 unsent changes and a quick capture before confirm signs nothing out and shows 4")
    func changesArrivedWhileOpen() async throws {
        let rig = await Rig()
        await rig.signIn()
        rig.triggers.pathChanged(satisfied: false)
        await rig.settle()
        for title in ["Call the landlord", "Order soil", "Book the plumber"] { try await rig.captureWaiting(title) }

        rig.controller.presentSignOut()
        let first = try #require(rig.controller.signOut.prompt)
        #expect(first.unsent == 3 && first.confirmTitle == "Sign out and remove")
        #expect(first.text.title == "3 changes haven't synced yet.")
        #expect(first.text.detail?.contains("You're offline, so they can't be sent now.") == true)
        #expect(rig.controller.router.isConfirmingSignOut)

        try rig.model.quickCaptureInbox("Water the tomatoes")
        #expect(await rig.controller.confirmSignOut() == .changed)
        let second = try #require(rig.controller.signOut.prompt)
        #expect(second.unsent == 4 && second.text.title == "4 changes haven't synced yet.")
        #expect(rig.controller.router.isConfirmingSignOut, "X-04 again, with the new count")
        #expect(rig.controller.signOut.presentations == 2)
        #expect(rig.workspace.account != nil && rig.workspace.pendingChangeCount == 4, "nothing was signed out")

        #expect(await rig.controller.confirmSignOut() == .signedOut)
        #expect(rig.workspace.account == nil && rig.workspace.pendingChangeCount == 0)
    }

    @Test("021-FR-018 a Quick Capture while a confirmed sign-out commits is refused with words and never silently removed")
    func quickCaptureWhileSigningOutIsNeverLost() async throws {
        let rig = await Rig()
        await rig.signIn()
        rig.server.holdNextLogout()
        rig.controller.presentSignOut()
        #expect(rig.controller.signOut.prompt?.unsent == 0)
        let controller = rig.controller
        let confirming = Task { await controller.confirmSignOut() }
        // The data is removed; the logout is on its way.
        await rig.server.logoutGate.waitForArrival()

        var refusal: String?
        do {
            try rig.model.quickCaptureInbox("Water the tomatoes")
        } catch {
            refusal = error.message
        }
        await rig.server.logoutGate.open()
        #expect(await confirming.value == .signedOut)
        await rig.settle()

        #expect(
            refusal != nil || rig.workspace.state.tasks.values.contains { $0.title == "Water the tomatoes" },
            "refused, so the panel keeps the text, or kept")
        #expect(refusal == "Brain Buddy is signing out. This wasn't saved; try again in a moment.")
        #expect(rig.workspace.account == nil)
        try rig.model.quickCaptureInbox("Water the tomatoes")
        #expect(rig.workspace.pendingChangeCount == 1, "saved again once signed out, on this Mac")
    }

    @Test("021-FR-018 a plain Sign out the kit refuses, because another process queued a change, shows X-04 again")
    func plainSignOutRefusedByTheKit() async throws {
        let rig = await Rig()
        await rig.signIn()
        rig.controller.presentSignOut()
        let shown = try #require(rig.controller.signOut.prompt)
        #expect(shown.unsent == 0 && shown.confirmTitle == "Sign out")
        #expect(shown.text.title == "Sign out?")

        // A widget or another process queued a change this window has not picked up.
        let other = FileDocumentStore(fileURL: rig.folder.store)
        let date = rig.clock.now
        _ = try await other.update { doc in
            let command = GTDCommand.createTask(.init(taskID: "queued-elsewhere", title: "Queued elsewhere", list: .inbox))
            doc.outbox.append(PendingOperation(command: command, issuedAt: date))
        }
        #expect(await rig.controller.confirmSignOut() == .changed)
        #expect(rig.workspace.account != nil, "nothing was signed out")
        #expect(rig.controller.signOut.prompt?.unsent == 1)
        #expect(rig.controller.router.isConfirmingSignOut)
    }

    @Test("021-FR-018 with an unsaved task edit or a capture draft, Sign out… first shows the window's discard confirmation")
    func unsavedEditGuardComesFirst() async {
        #expect(SignOutGuard.needsDiscardConfirmation(taskEditUnsaved: true, captureDraft: "", waitingForDraft: ""))
        #expect(SignOutGuard.needsDiscardConfirmation(taskEditUnsaved: false, captureDraft: "Call the landlord", waitingForDraft: ""))
        #expect(SignOutGuard.needsDiscardConfirmation(taskEditUnsaved: false, captureDraft: " ", waitingForDraft: "Sam"))
        #expect(!SignOutGuard.needsDiscardConfirmation(taskEditUnsaved: false, captureDraft: "  \n", waitingForDraft: ""))

        let rig = await Rig()
        await rig.signIn()
        rig.model.draft = "Call the landlord"
        rig.controller.requestSignOut()
        #expect(rig.controller.signOutRequests == 1, "the window runs its guard")
        #expect(rig.controller.router.surface == nil, "X-04 is not shown before the guard")
        #expect(rig.controller.signOut.prompt == nil)
        #expect(rig.model.draft == "Call the landlord", "nothing typed is lost by asking")
    }

    @Test("021-FR-005 021-FR-018 a removal that fails says “Couldn't sign out”, removes nothing, and the person is still signed in")
    func failedRemovalKeepsTheSession() async throws {
        let server = StubServer()
        let tokens = SpyTokenStore()
        let store = UnremovableStore()
        let clock = TestClock()
        let engine = SyncEngine(
            store: store, tokenStore: tokens, transport: server, now: clock.provider,
            configuration: SyncConfiguration(scheduler: ManualSyncScheduler(), pullInterval: SyncTiming.pullAge, clientVersion: "test"),
            identity: .macOS(version: "test")
        )
        let workspace = Workspace(store: store, sync: engine, now: clock.provider, tickScheduler: ManualSyncScheduler())
        await workspace.load()
        try await workspace.signIn(serverURL: StubServer.server, email: StubServer.ada.email, password: StubServer.ada.password)
        await engine.waitUntilIdle()
        try workspace.capture(CaptureDraft(text: "Kept on failure", list: .inbox))
        await workspace.flush()
        let flow = SignOutFlow(workspace: workspace, importer: nil, now: clock.provider, log: CapturingMacLog())
        var signedOut = false
        flow.didSignOut = { signedOut = true }
        server.clearLog()

        flow.open()
        let outcome = await flow.confirm()
        await engine.waitUntilIdle()

        #expect(outcome == .failed)
        #expect(flow.failure == SignOutFailure())
        #expect(flow.failure?.detail == "Brain Buddy couldn't remove your tasks from this Mac, so you're still signed in. Nothing was removed.")
        #expect(!signedOut)
        #expect(workspace.account != nil && workspace.pendingChangeCount == 1, "nothing was removed")
        #expect(tokens.storedTokens.count == 1, "the token stays")
        #expect(tokens.storedPending.isEmpty, "the pending logout recorded first was withdrawn")
        #expect(!server.routes.contains("POST /auth/logout"), "the server session was not ended")
        #expect(server.liveSessions == 1)
    }

    /// A store whose removal fails (a disk that refuses it).
    struct UnremovableStore: DocumentStore {
        let inner = InMemoryDocumentStore()

        func load() async throws(DocumentStoreError) -> StoreDocument? { try await inner.load() }
        func update(_ transform: @Sendable (inout StoreDocument) throws -> Void) async throws -> StoreDocument {
            try await inner.update(transform)
        }
        func generation() async throws(DocumentStoreError) -> Int? { try await inner.generation() }
        func destroy() async throws(DocumentStoreError) { throw .io("removal refused") }
        func destroy(after check: @Sendable (StoreDocument?) throws -> Void) async throws {
            try check(try await inner.load())
            throw DocumentStoreError.io("removal refused")
        }
        func storedAccount() async -> LinkedAccount? { await inner.storedAccount() }
    }

    @Test("021-FR-005 021-FR-021 after a sign-out: Inbox, the account-less line, the sign-out recorded and the backup rule applied")
    func afterSignOut() async throws {
        let folder = TemporaryFolder()
        try Fixture.install("legacy-populated", in: folder)
        let server = StubServer()
        let tokens = SpyTokenStore()
        let clock = TestClock()
        let ticks = ManualSyncScheduler()
        let timers = ManualSyncScheduler()
        let log = CapturingMacLog()
        let launch = MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: MacHostConfiguration(directory: folder.url, isDryRun: false), tokenStore: tokens, transport: server,
                cookieJar: FakeCookieJar(), responseCache: FakeResponseCache(), now: clock.provider, makeID: SequentialIDs().provider,
                log: log, tickScheduler: ticks, syncScheduler: timers
            )
        )
        await launch.run { _ in }
        let rig = Rig(
            launched: try #require(launch.host), folder: folder, server: server, tokens: tokens, log: log, ticks: ticks, timers: timers,
            clock: clock
        )
        let record = try #require(MacLocalStateStore(directory: folder.url).load()?.legacyImport)
        let backup = try #require(record.backupFileName)

        // During the first upload (the server refuses the creates here) the backup is kept, dated.
        await rig.signIn()
        rig.model.choose(.list(.next))
        rig.controller.presentSignOut()
        let prompt = try #require(rig.controller.signOut.prompt)
        #expect(prompt.unsent > 0)
        #expect(prompt.backup == .kept(until: clock.now.addingTimeInterval(LegacyImportCoordinator.backupRetention)))
        #expect(prompt.text.detail?.hasSuffix("A copy of your tasks from before the update stays on this Mac until 5 Nov.") == true)
        #expect(await rig.controller.confirmSignOut() == .signedOut)
        #expect(rig.model.destination == .list(.inbox), "selection resets to Inbox")
        #expect(rig.controller.line.description.text == "On this Mac · Sign in to sync")
        #expect(MacLocalStateStore(directory: folder.url).load()?.legacyImport?.signedOutSinceImport == true)
        #expect(MacFiles.exists(folder.file(backup)), "kept: its 30 days have not passed")

        // 31 days later a sign-out with nothing of the first upload left removes it, and says so.
        clock.advance(31 * TestClock.day)
        await rig.signIn()
        rig.controller.presentSignOut()
        let later = try #require(rig.controller.signOut.prompt)
        #expect(later.backup == .removed)
        #expect(later.text.detail?.hasSuffix(SyncCopy.signOutBackupRemoved) == true, "never silent")
        #expect(await rig.controller.confirmSignOut() == .signedOut)
        #expect(!MacFiles.exists(folder.file(backup)))
        #expect(MacLocalStateStore(directory: folder.url).load()?.legacyImport?.backupDeletedAt != nil)
    }

    // MARK: The token store and the client

    @Test("021-FR-005 the host's Keychain service, and every token-store call off the main thread; only the sign-in writes interactively")
    func tokenStoreCallsOffTheMainThread() async throws {
        #expect(MacHostConfiguration.keychainService == "app.brainbuddy.mac.session")
        let rig = await Rig()
        try await rig.fireEveryTrigger()
        await rig.signIn()
        await rig.controller.syncNow()
        for _ in 0..<4 { await rig.ticks.runNext() }
        await rig.settle()
        rig.controller.presentSignOut()
        _ = await rig.controller.confirmSignOut()
        await rig.settle()

        let calls = rig.tokens.calls
        #expect(!calls.isEmpty)
        #expect(calls.allSatisfy { !$0.onMainThread }, "\(calls.filter(\.onMainThread))")
        #expect(calls.filter { $0.name == "setTokenInteractive" }.count == 1, "only the person's sign-in may prompt")
    }

    @Test("021-FR-005 021-FR-029 a dry run makes no token-store call and sends nothing until a sign-in, which is the first call")
    func dryRunTouchesNothingUntilSignIn() async throws {
        let pending = PendingLogout(serverURL: StubServer.server, token: "real-pending", signedOutAt: TestClock.importTime)
        let tokens = SpyTokenStore(token: "real-session", for: StubServer.server, pending: [pending])
        let folder = TemporaryFolder()
        let server = StubServer()
        let log = CapturingMacLog()
        let ticks = ManualSyncScheduler()
        let timers = ManualSyncScheduler()
        let launch = MacLaunch(
            environment: MacLaunchEnvironment(
                configuration: MacHostConfiguration(directory: folder.url, isDryRun: true), tokenStore: tokens, transport: server,
                cookieJar: FakeCookieJar([FakeCookieJar.session("legacy-session", domain: "api.example.com")]),
                responseCache: FakeResponseCache(), now: TestClock().provider, makeID: SequentialIDs().provider, log: log,
                tickScheduler: ticks, syncScheduler: timers
            )
        )
        await launch.run { _ in }
        let rig = Rig(launched: try #require(launch.host), folder: folder, server: server, tokens: tokens, log: log, ticks: ticks, timers: timers)
        await rig.triggers.start()
        await rig.triggers.handle(.didBecomeActive)
        await rig.triggers.handle(.windowBecameVisible)
        for _ in 0..<4 { await ticks.runNext() }
        rig.triggers.pathChanged(satisfied: false)
        rig.triggers.pathChanged(satisfied: true)
        await rig.settle()

        #expect(tokens.calls.isEmpty, "no token-store call in a dry run")
        #expect(server.requests.isEmpty, "nothing sent")
        #expect(tokens.storedPending == [pending] && tokens.storedTokens.count == 1, "the real items stay")

        await rig.signIn()
        #expect(tokens.calls.first?.name == "setTokenInteractive", "the person's sign-in is the first call")
    }

    @Test("021-FR-031 every request carries X-Client: brainbuddy-macos/<version>")
    func requestsCarryTheMacIdentity() async throws {
        let rig = await Rig()
        await rig.signIn()
        try await rig.captureWaiting("Order soil")
        await rig.controller.syncNow()
        await rig.settle()
        let expected = "brainbuddy-macos/\(WorkspaceHost.clientIdentity.version)"
        #expect(WorkspaceHost.clientIdentity.name == "brainbuddy-macos")
        #expect(!rig.server.requests.isEmpty)
        #expect(rig.server.requests.allSatisfy { $0.header("X-Client") == expected })
    }
}

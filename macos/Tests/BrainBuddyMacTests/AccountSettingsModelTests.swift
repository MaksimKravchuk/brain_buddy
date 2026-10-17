import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Synchronization
import Testing

@testable import BrainBuddyMacCore

/// Holds a request until the test lets it go, so a "late" answer is deterministic (no sleeps).
actor AccountReadGate {
    private var isOpen = false
    private var arrived = false
    private var held: [CheckedContinuation<Void, Never>] = []
    private var watchers: [CheckedContinuation<Void, Never>] = []

    func pass() async {
        arrived = true
        for watcher in watchers { watcher.resume() }
        watchers = []
        if isOpen { return }
        await withCheckedContinuation { held.append($0) }
    }

    func waitForArrival() async {
        if arrived { return }
        await withCheckedContinuation { watchers.append($0) }
    }

    func release() {
        isOpen = true
        for waiter in held { waiter.resume() }
        held = []
    }
}

/// A scripted `AccountSettingsRemote` that counts its calls.
final class FakeAccountRemote: AccountSettingsRemote {
    private struct State {
        var summary: Result<AccountSummaryDTO, APIError>
        var methods: Result<AccountAuthMethodsDTO, APIError>
        var summaryCalls = 0
        var methodsCalls = 0
    }

    private let state: Mutex<State>
    private let gate: AccountReadGate?

    init(
        summary: Result<AccountSummaryDTO, APIError> = .success(AccountFixtures.summary()),
        methods: Result<AccountAuthMethodsDTO, APIError> = .success(AccountFixtures.methods()),
        gate: AccountReadGate? = nil
    ) {
        state = Mutex(State(summary: summary, methods: methods))
        self.gate = gate
    }

    var summaryCalls: Int { state.withLock { $0.summaryCalls } }
    var methodsCalls: Int { state.withLock { $0.methodsCalls } }

    func accountSummary() async throws(APIError) -> AccountSummaryDTO {
        let result = state.withLock { state in
            state.summaryCalls += 1
            return state.summary
        }
        await gate?.pass()
        return try result.get()
    }

    func accountAuthMethods() async throws(APIError) -> AccountAuthMethodsDTO {
        let result = state.withLock { state in
            state.methodsCalls += 1
            return state.methods
        }
        return try result.get()
    }
}

enum AccountFixtures {
    static let server = URL(string: "https://api.example.com/api")!

    static func account(id: String = "user_max") -> LinkedAccount {
        LinkedAccount(id: id, email: "max@example.com", displayName: "Max", serverURL: server, linkedAt: Date(timeIntervalSince1970: 0))
    }

    static func summary(id: String = "user_max", name: String? = "Max", steps: Int = 214) -> AccountSummaryDTO {
        AccountSummaryDTO(id: id, email: "max@example.com", displayName: name, completedTaskCount: steps)
    }

    /// `providers` are `"apple:active:true"`-style triples.
    static func methods(
        id: String = "user_max", verified: Bool = true, password: Bool = true,
        providers: [String] = ["apple:active:true"]
    ) -> AccountAuthMethodsDTO {
        let list = providers.map { entry -> String in
            let parts = entry.split(separator: ":").map(String.init)
            return #"{"method":"\#(parts[0])","state":"\#(parts[1])","usable":\#(parts[2]),"connected_at":null}"#
        }.joined(separator: ",")
        let json = """
            {"account_id":"\(id)","email":"max@example.com","email_verified":\(verified),\
            "email_delivery":"available","has_password":\(password),"methods":[\(list)]}
            """
        return try! BrainBuddyAPI.makeDecoder().decode(AccountAuthMethodsDTO.self, from: Data(json.utf8))
    }

    static func failure(_ kind: APIError.Kind, reference: String? = nil) -> APIError {
        APIError(kind: kind, message: "server words", referenceID: reference)
    }
}

@MainActor
@Suite("028 Account settings model")
struct AccountSettingsModelTests {
    private func makeModel(
        _ remote: FakeAccountRemote, account: LinkedAccount? = AccountFixtures.account(), log: CapturingMacLog = CapturingMacLog()
    ) -> AccountSettingsModel {
        AccountSettingsModel(account: account, remote: { _ in remote }, log: log)
    }

    private func loadedRows(_ model: AccountSettingsModel) -> AccountRows? {
        if case .loaded(let rows) = model.phase { return rows }
        return nil
    }

    @Test("028_FR_005 a late response for the previous account is discarded")
    func lateResponseForPreviousAccountIsDiscarded() async {
        let gate = AccountReadGate()
        let model = makeModel(FakeAccountRemote(gate: gate))
        let pending = Task { await model.reload() }
        await gate.waitForArrival()
        model.update(account: AccountFixtures.account(id: "user_other"), sessionEnded: false)
        await gate.release()
        await pending.value
        #expect(model.phase == .loading, "the new account starts over; nothing of the old one shows")
        #expect(model.account?.id == "user_other")
    }

    @Test("028_FR_005 a summary whose id differs from the signed-in account is discarded")
    func summaryForAnotherAccountIsDiscarded() async {
        let remote = FakeAccountRemote(summary: .success(AccountFixtures.summary(id: "user_other", name: "Eve")))
        let model = makeModel(remote)
        await model.reload()
        #expect(loadedRows(model) == nil)
        guard case .failed(_, let reference, let rateLimited) = model.phase else {
            Issue.record("expected the failed phase, got \(model.phase)")
            return
        }
        #expect(reference == nil && !rateLimited)
    }

    @Test("028_FR_005 a method list for another account is not used")
    func methodsForAnotherAccountAreNotUsed() async {
        let model = makeModel(FakeAccountRemote(methods: .success(AccountFixtures.methods(id: "user_other"))))
        await model.reload()
        #expect(loadedRows(model)?.methodsUnavailable == true)
        #expect(loadedRows(model)?.password == "Unavailable")
    }

    @Test("028_FR_016 the open Account tab reloads when the session is valid again after Sign in again")
    func reloadsWhenSessionRenews() async {
        let ended = FakeAccountRemote(summary: .failure(AccountFixtures.failure(.unauthorized)))
        let renewed = FakeAccountRemote()
        var calls = 0
        let model = AccountSettingsModel(
            account: AccountFixtures.account(),
            remote: { _ in
                calls += 1
                return calls == 1 ? ended : renewed
            }, log: CapturingMacLog())
        await model.reload()
        #expect(model.phase == .sessionEnded)
        await model.sessionMayHaveRenewed()
        #expect(loadedRows(model) != nil, "the stale session notice gives way to the rows without leaving the tab")
        #expect(renewed.summaryCalls == 1)
    }

    @Test("028_FR_016 sessionMayHaveRenewed leaves loaded rows and a still-ended session alone")
    func renewalIgnoredWhenNotEnded() async {
        let remote = FakeAccountRemote()
        let model = makeModel(remote)
        await model.reload()
        await model.sessionMayHaveRenewed()
        #expect(remote.summaryCalls == 1, "loaded rows are not re-read")
        model.update(account: AccountFixtures.account(), sessionEnded: true)
        await model.sessionMayHaveRenewed()
        #expect(model.phase == .sessionEnded && remote.summaryCalls == 1)
    }

    @Test("028_FR_005 clear() on sign-out drops the rows and ignores a request still in flight")
    func signOutClearsAndDropsLateResponse() async {
        let gate = AccountReadGate()
        let model = makeModel(FakeAccountRemote(gate: gate))
        let pending = Task { await model.reload() }
        await gate.waitForArrival()
        model.update(account: nil, sessionEnded: false)
        #expect(model.phase == .notSignedIn)
        await gate.release()
        await pending.value
        #expect(model.phase == .notSignedIn)
    }

    @Test("028_FR_005 an account change after a load clears the old rows")
    func accountChangeClearsLoadedRows() async {
        let model = makeModel(FakeAccountRemote())
        await model.reload()
        #expect(loadedRows(model) != nil)
        model.update(account: AccountFixtures.account(id: "user_other"), sessionEnded: false)
        #expect(model.phase == .loading)
        model.clear()
        #expect(model.phase == .loading)
    }

    @Test("028_FR_004 028_FR_006 028_FR_007 028_FR_008 028_FR_009 028_FR_010 loaded rows match the M25 sample")
    func loadedRowsForTheSampleAccount() async {
        let remote = FakeAccountRemote()
        let model = makeModel(remote)
        #expect(model.phase == .loading)
        await model.reload()
        #expect(remote.summaryCalls == 1 && remote.methodsCalls == 1, "both reads run on each load")
        #expect(
            loadedRows(model)
                == AccountRows(
                    name: "Max", steps: "214", email: "max@example.com · Verified", apple: "Connected",
                    google: "Not connected", password: "Set · also used for Mac sign-in", methodsUnavailable: false))
    }

    @Test("028_FR_006 028_FR_008 028_FR_009 028_FR_010 unnamed, unverified, disabled provider, no password")
    func edgeRows() async {
        let methods = AccountFixtures.methods(
            verified: false, password: false, providers: ["apple:disabled:false", "google:active:false"])
        let model = makeModel(FakeAccountRemote(summary: .success(AccountFixtures.summary(name: nil, steps: 0)), methods: .success(methods)))
        await model.reload()
        let rows = loadedRows(model)
        #expect(rows?.name == "Not set")
        #expect(rows?.steps == "0")
        #expect(rows?.email == "max@example.com · Unverified")
        #expect(rows?.apple == "Connected · unavailable")
        #expect(rows?.google == "Connected · unavailable")
        #expect(rows?.password == "Not set")
    }

    @Test("028_FR_008 028_FR_009 028_FR_010 028_FR_017 a failed or missing method list reads Unavailable, never a guess")
    func methodsReadFailure() async {
        for kind in [APIError.Kind.server, .notFound(resource: nil, id: nil), .network("down")] {
            let model = makeModel(FakeAccountRemote(methods: .failure(AccountFixtures.failure(kind))))
            await model.reload()
            let rows = loadedRows(model)
            #expect(rows?.name == "Max" && rows?.steps == "214", "\(kind)")
            #expect(rows?.email == "max@example.com · Unavailable", "\(kind)")
            #expect(rows?.apple == "Unavailable" && rows?.google == "Unavailable" && rows?.password == "Unavailable")
            #expect(rows?.methodsUnavailable == true)
        }
    }

    @Test("028_FR_015 not signed in makes no request")
    func notSignedIn() async {
        let remote = FakeAccountRemote()
        let model = makeModel(remote, account: nil)
        await model.reload()
        #expect(model.phase == .notSignedIn)
        #expect(remote.summaryCalls == 0 && remote.methodsCalls == 0)
    }

    @Test("028_FR_016 offline shows the connection state")
    func offline() async {
        let model = makeModel(FakeAccountRemote(summary: .failure(AccountFixtures.failure(.network("offline")))))
        await model.reload()
        #expect(model.phase == .offline)
    }

    @Test("028_FR_016 028_SC_005 a 401 shows session ended and leaves the account link untouched")
    func unauthorized() async {
        let account = AccountFixtures.account()
        let model = makeModel(FakeAccountRemote(summary: .failure(AccountFixtures.failure(.unauthorized))), account: account)
        await model.reload()
        #expect(model.phase == .sessionEnded)
        #expect(model.account == account, "the model never unlinks or edits local work")
    }

    @Test("028_FR_016 a 401 on the method list alone also reads session ended")
    func unauthorizedOnMethods() async {
        let model = makeModel(FakeAccountRemote(methods: .failure(AccountFixtures.failure(.unauthorized))))
        await model.reload()
        #expect(model.phase == .sessionEnded)
    }

    @Test("028_FR_016 the sync line reporting a ended session shows it without a request")
    func sessionEndedFromSyncLine() async {
        let remote = FakeAccountRemote()
        let model = makeModel(remote)
        await model.reload()
        model.update(account: AccountFixtures.account(), sessionEnded: true)
        #expect(model.phase == .sessionEnded)
        await model.reload()
        #expect(model.phase == .sessionEnded)
        #expect(remote.summaryCalls == 1)
    }

    @Test("028_FR_017 rate limited is not retried and says to wait; the reference shows")
    func rateLimited() async {
        let remote = FakeAccountRemote(summary: .failure(AccountFixtures.failure(.rateLimited, reference: "ref-429")))
        let model = makeModel(remote)
        await model.reload()
        #expect(
            model.phase
                == .failed(message: "Your account details couldn't be loaded.", reference: "ref-429", rateLimited: true))
        #expect(remote.summaryCalls == 1, "no automatic retry")
    }

    @Test("028_FR_017 a server error carries its reference")
    func serverError() async {
        let model = makeModel(FakeAccountRemote(summary: .failure(AccountFixtures.failure(.server, reference: "ref-500"))))
        await model.reload()
        #expect(
            model.phase
                == .failed(message: "Your account details couldn't be loaded.", reference: "ref-500", rateLimited: false))
    }

    @Test("028_FR_018 028_SC_006 logs hold stage, outcome, duration and reference, never name, email or path")
    func logsCarryNoPersonalData() async {
        let log = CapturingMacLog()
        await makeModel(FakeAccountRemote(), log: log).reload()
        await makeModel(FakeAccountRemote(summary: .failure(AccountFixtures.failure(.server, reference: "ref-500"))), log: log).reload()
        let lines = log.messages(.sync)
        #expect(lines.count == 2)
        for line in lines {
            #expect(line.hasPrefix("account-settings stage=reload outcome="))
            for secret in ["Max", "max@example.com", "example.com", "/", "user_max"] {
                #expect(!line.contains(secret), "\(line) leaked \(secret)")
            }
        }
        #expect(lines[1].contains("ref=ref-500"))
    }
}

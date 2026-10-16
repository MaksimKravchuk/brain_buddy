import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Observation

/// The two reads the Account tab makes (spec 028 plan "Mac core"). `BrainBuddyAPIClient` is the
/// production implementation; tests supply fakes.
package protocol AccountSettingsRemote: Sendable {
    func accountSummary() async throws(APIError) -> AccountSummaryDTO
    func accountAuthMethods() async throws(APIError) -> AccountAuthMethodsDTO
}

extension BrainBuddyAPIClient: AccountSettingsRemote {}

/// The display strings of design S-02.02 / S-02.03, each already final ("Unavailable" included).
package struct AccountRows: Equatable, Sendable {
    package var name: String
    package var steps: String
    package var email: String
    package var apple: String
    package var google: String
    package var password: String
    /// S-02.03: the methods read failed, so the "couldn't be loaded" line and Try again show.
    package var methodsUnavailable: Bool

    package init(
        name: String, steps: String, email: String, apple: String, google: String, password: String,
        methodsUnavailable: Bool
    ) {
        self.name = name
        self.steps = steps
        self.email = email
        self.apple = apple
        self.google = google
        self.password = password
        self.methodsUnavailable = methodsUnavailable
    }
}

package enum AccountSettingsPhase: Equatable, Sendable {
    case notSignedIn, loading, loaded(AccountRows), offline, sessionEnded
    case failed(message: String, reference: String?, rateLimited: Bool)
}

/// The Account tab's state machine (028-FR-003 – 028-FR-010, 028-FR-015 – 028-FR-018). Memory only:
/// nothing here touches the disk, and a result is applied only while it still belongs to the
/// account and the request that started it (the owner guard, 028-FR-005).
@MainActor
@Observable
package final class AccountSettingsModel {
    package private(set) var phase: AccountSettingsPhase
    package private(set) var account: LinkedAccount?
    package private(set) var sessionEnded: Bool
    @ObservationIgnored private var generation = 0
    @ObservationIgnored private let makeRemote: @MainActor (LinkedAccount) -> any AccountSettingsRemote
    @ObservationIgnored private let log: any MacLogSink

    package init(
        account: LinkedAccount?, sessionEnded: Bool = false,
        remote: @escaping @MainActor (LinkedAccount) -> any AccountSettingsRemote = AccountSettingsModel.liveRemote,
        log: any MacLogSink = SystemMacLog()
    ) {
        self.account = account
        self.sessionEnded = sessionEnded
        makeRemote = remote
        self.log = log
        phase = Self.initialPhase(account: account, sessionEnded: sessionEnded)
    }

    /// The account's own server and the stored session, built like the review-suggestion remote.
    package static func liveRemote(for account: LinkedAccount) -> any AccountSettingsRemote {
        BrainBuddyAPIClient(
            baseURL: account.serverURL, tokenStore: WorkspaceHost.systemTokenStore(), identity: WorkspaceHost.clientIdentity)
    }

    /// The workspace's account or the sync line changed (S-02.14, S-02.15). A different account
    /// drops everything and starts over; the session ending drops the rows.
    package func update(account new: LinkedAccount?, sessionEnded ended: Bool) {
        let changed = new?.id != account?.id
        account = new
        sessionEnded = ended
        if changed {
            clear()
        } else if ended, phase != .sessionEnded {
            clear()
        }
    }

    /// Forgets what was read and ignores any request still in flight.
    package func clear() {
        generation += 1
        phase = Self.initialPhase(account: account, sessionEnded: sessionEnded)
    }

    /// Reads the account and its methods together. The latest call wins; a late answer is dropped.
    package func reload() async {
        guard let account else { return clear() }
        if sessionEnded { return clear() }
        generation += 1
        let ticket = generation
        let started = ContinuousClock.now
        if case .loaded = phase {} else { phase = .loading }
        let remote = makeRemote(account)
        async let summary = Self.readSummary(remote)
        async let methods = Self.readMethods(remote)
        let (summaryResult, methodsResult) = await (summary, methods)
        guard ticket == generation, self.account?.id == account.id else {
            record("discarded", started)
            return
        }
        let (next, outcome, reference) = Self.resolve(summaryResult, methodsResult, owner: account.id)
        phase = next
        record(outcome, started, reference: reference)
    }

    private static func initialPhase(account: LinkedAccount?, sessionEnded: Bool) -> AccountSettingsPhase {
        account == nil ? .notSignedIn : (sessionEnded ? .sessionEnded : .loading)
    }

    private nonisolated static func readSummary(
        _ remote: any AccountSettingsRemote
    ) async -> Result<AccountSummaryDTO, APIError> {
        do throws(APIError) { return .success(try await remote.accountSummary()) } catch { return .failure(error) }
    }

    private nonisolated static func readMethods(
        _ remote: any AccountSettingsRemote
    ) async -> Result<AccountAuthMethodsDTO, APIError> {
        do throws(APIError) { return .success(try await remote.accountAuthMethods()) } catch { return .failure(error) }
    }

    private static func resolve(
        _ summary: Result<AccountSummaryDTO, APIError>, _ methods: Result<AccountAuthMethodsDTO, APIError>,
        owner: String
    ) -> (AccountSettingsPhase, String, String?) {
        var failure: APIError?
        if case .failure(let error) = summary { failure = error }
        if failure == nil, case .failure(let error) = methods, error.kind == .unauthorized { failure = error }
        if let failure { return outcome(for: failure) }
        guard case .success(let dto) = summary, dto.id == owner else {
            let failed = AccountSettingsPhase.failed(message: AccountSettingsCopy.loadFailed, reference: nil, rateLimited: false)
            return (failed, "mismatch", nil)
        }
        var usable: AccountAuthMethodsDTO?
        if case .success(let list) = methods, list.accountID == owner { usable = list }
        return (.loaded(rows(dto, usable)), usable == nil ? "loadedWithoutMethods" : "loaded", nil)
    }

    private static func outcome(for error: APIError) -> (AccountSettingsPhase, String, String?) {
        switch error.kind {
        case .network: (.offline, "offline", error.referenceID)
        case .unauthorized: (.sessionEnded, "sessionEnded", error.referenceID)
        case .rateLimited:
            (.failed(message: AccountSettingsCopy.loadFailed, reference: error.referenceID, rateLimited: true),
                "rateLimited", error.referenceID)
        default:
            (.failed(message: AccountSettingsCopy.loadFailed, reference: error.referenceID, rateLimited: false),
                "failed", error.referenceID)
        }
    }

    /// S-02.02 / S-02.03. With no method list, nothing about verification or sign-in is guessed.
    package static func rows(_ summary: AccountSummaryDTO, _ methods: AccountAuthMethodsDTO?) -> AccountRows {
        let unavailable = AccountSettingsCopy.unavailable
        let name = summary.displayName.flatMap { $0.isEmpty ? nil : $0 } ?? AccountSettingsCopy.nameEmpty
        return AccountRows(
            name: name, steps: String(summary.completedTaskCount),
            email: AccountSettingsCopy.email(summary.email, verified: methods?.emailVerified),
            apple: methods.map { provider(.apple, in: $0) } ?? unavailable,
            google: methods.map { provider(.google, in: $0) } ?? unavailable,
            password: methods.map { $0.hasPassword ? AccountSettingsCopy.passwordSet : AccountSettingsCopy.passwordNotSet }
                ?? unavailable,
            methodsUnavailable: methods == nil)
    }

    private static func provider(_ kind: AccountAuthMethodsDTO.Method.Kind, in methods: AccountAuthMethodsDTO) -> String {
        guard let method = methods.methods.first(where: { $0.method == kind }) else { return AccountSettingsCopy.notConnected }
        return method.state == .active && method.usable ? AccountSettingsCopy.connected : AccountSettingsCopy.connectedUnavailable
    }

    /// Stage, outcome, duration and reference only (028-FR-018): never a name, email or path.
    private func record(_ outcome: String, _ started: ContinuousClock.Instant, reference: String? = nil) {
        let parts = started.duration(to: .now).components
        let millis = parts.seconds * 1000 + parts.attoseconds / 1_000_000_000_000_000
        log.log(.sync, "account-settings stage=reload outcome=\(outcome) ms=\(millis)" + (reference.map { " ref=\($0)" } ?? ""))
    }
}

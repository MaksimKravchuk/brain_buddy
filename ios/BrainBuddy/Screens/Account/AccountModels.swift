import BrainBuddyAPI
import BrainBuddyCore
import BrainBuddyWorkspace
import Observation
import SwiftUI

/// One `AccountSecurityModel` per linked account, shared by the Account screen and the screens
/// pushed from it (spec 033). It sits above the navigation stacks, because a pushed screen does
/// not inherit what the screen that pushed it put in the environment.
@MainActor
@Observable
final class AccountModels {
    @ObservationIgnored private var cached: (key: String, model: AccountSecurityModel)?

    /// The model for `account`; a different account or server gets a fresh one.
    func model(for account: LinkedAccount) -> AccountSecurityModel {
        let key = "\(account.id)@\(account.serverURL.absoluteString)"
        if let cached, cached.key == key { return cached.model }
        let model = AccountSecurityModel(
            accountID: account.id,
            remote: BrainBuddyAPIClient(baseURL: account.serverURL, tokenStore: KeychainSessionTokenStore()),
            clientProof: {
                let proof = try ModernAuthCoordinator.newProof()
                return AccountClientProof(verifier: proof.verifier, challenge: proof.challenge)
            })
        cached = (key, model)
        return model
    }
}

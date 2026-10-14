import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// Q06 on the kit side: the first sign-in of an account-less install merges its local work into an
/// account that already holds data, exactly once. (The legacy `store.json` import of the fixture files is
/// the Mac package's `MacRehearsalTests`, which owns those fixtures.)
@Suite("Pilot rehearsal: first-sign-in merge (026 Q06)", .rehearsal, .serialized)
@MainActor
struct RehearsalImportTests {
    @Test("Q06 first sign-in merges account-less work into an account with data, once, and a relaunch adds nothing")
    func q06FirstSignInMerge() async {
        await RehearsalRig.scenario("Q06-merge", "first-sign-in merge into a populated account") { r, rig in
            let existing = RehearsalRig.title("Q06", "already in the account")
            let plain = RehearsalRig.title("Q06", "local plain")
            let edited = RehearsalRig.title("Q06", "local edited")
            let moved = RehearsalRig.title("Q06", "local moved")
            let mac = try await rig.device("mac")
            try await mac.signIn("A")
            try await mac.capture(existing)
            r.expect(await mac.settle(), "the account's own device did not settle")

            // An install that has only ever worked locally.
            let phone = try await rig.device("phone")
            try await phone.capture(plain)
            let draft = try await phone.capture(RehearsalRig.title("Q06", "local to edit"))
            try await phone.retitle(draft, edited)
            let toMove = try await phone.capture(moved)
            try await phone.move(toMove, to: .someday)
            r.expect(phone.workspace.hasLocalWorkToMerge, "local work is not reported as something a sign-in would merge")
            let before = await phone.allTitles()
            r.observe("localBeforeMerge", before.count)

            r.stage("sign in")
            try await phone.signIn("A")
            r.expect(await phone.settle(timeout: 90), "the merged install did not settle")
            let wanted = [plain, edited, moved, existing]
            var server = try phone.serverTitles()
            r.observe("serverCounts", wanted.map { "\(server.occurrences(of: $0))" }.joined(separator: "/"))
            r.expect(wanted.allSatisfy { server.occurrences(of: $0) == 1 }, "the account does not hold each title exactly once after the merge")
            r.expect(server.occurrences(of: RehearsalRig.title("Q06", "local to edit")) == 0, "the superseded local title was merged")
            let union = await phone.eventually { Set(await phone.allTitles()).isSuperset(of: wanted) }
            let phoneTitles = await phone.allTitles()
            r.expect(union && wanted.allSatisfy { phoneTitles.occurrences(of: $0) == 1 }, "the install does not show the union once")
            let onMac = await mac.eventually(timeout: 30) { Set(await mac.allTitles()).isSuperset(of: wanted) }
            r.expect(onMac, "the account's other device did not receive the merged work")
            r.observe("states", try rig.session.states(token: phone.token()).filter { $0.key.hasPrefix("Q06") }.map { "\($0.value)" }.sorted().joined(separator: ","))

            // A relaunch must not merge again.
            r.stage("relaunch")
            try await phone.relaunch()
            r.expect(await phone.settle(timeout: 60), "the relaunched install did not settle")
            server = try phone.serverTitles()
            r.expect(wanted.allSatisfy { server.occurrences(of: $0) == 1 }, "a relaunch duplicated merged work")
            r.observe("serverCountsAfterRelaunch", wanted.map { "\(server.occurrences(of: $0))" }.joined(separator: "/"))
            r.correlation(try rig.session.email(token: phone.token()).correlationID)
        }
    }
}

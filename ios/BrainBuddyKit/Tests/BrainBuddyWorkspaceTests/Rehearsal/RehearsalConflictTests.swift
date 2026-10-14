import BrainBuddyCore
import BrainBuddySync
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// Q02 (concurrent edits), Q05 (account switch) and Q12 (the states a person sees) of the pilot
/// rehearsal, two installs against the real backend.
@Suite("Pilot rehearsal: conflicts, isolation and recovery states (026 Q02, Q05, Q12)", .rehearsal, .serialized)
@MainActor
struct RehearsalConflictTests {
    /// Both devices edit `base` from the same revision while offline; `first` delivers, then `second`.
    /// Returns the issue the second device holds.
    private func concurrentEdit(
        _ r: RehearsalRecorder, _ rig: RehearsalRig, label: String, first: RehearsalDevice, second: RehearsalDevice
    ) async throws -> RustWorkspaceIssue? {
        let base = RehearsalRig.title(label, "base")
        let firstEdit = RehearsalRig.title(label, "edit by \(first.name)")
        let secondEdit = RehearsalRig.title(label, "edit by \(second.name)")
        let unrelated = RehearsalRig.title(label, "unrelated on \(second.name)")
        try await first.capture(base)
        r.expect(await RehearsalDevice.settle(first, second), "\(label): not settled before the edits")
        let seen = await second.eventually { await second.taskID(titled: base) != nil }
        r.expect(seen, "\(label): the base task never reached the second device")
        guard let firstID = await first.taskID(titled: base), let secondID = await second.taskID(titled: base) else { return nil }

        await first.setOffline(true)
        await second.setOffline(true)
        try await first.retitle(firstID, firstEdit)
        try await second.retitle(secondID, secondEdit)
        try await second.capture(unrelated)

        r.stage("\(label): \(first.name) delivers")
        await first.setOffline(false)
        r.expect(await first.settle(), "\(label): the first device did not deliver")
        r.stage("\(label): \(second.name) delivers")
        await second.setOffline(false)
        let conflicted = await second.eventually(timeout: 30) { !second.workspace.runtimeIssues.isEmpty }
        r.expect(conflicted, "\(label): no conflict issue appeared on \(second.name)")
        guard let issue = second.workspace.runtimeIssues.first else { return nil }

        let version = try await second.workspace.accountVersion(ofIssue: issue.id)
        r.observe("\(label).issueReason", issue.reason)
        r.observe("\(label).issueCount", second.workspace.runtimeIssues.count)
        r.expect(issue.localText.values.contains(secondEdit), "\(label): the local text of the losing edit is not available")
        r.expect(version?.fields["title"] == firstEdit, "\(label): the account version is not the winning edit")
        r.observe("\(label).bothVersionsAvailable", issue.localText.values.contains(secondEdit) && version?.fields["title"] == firstEdit)
        let server = try first.serverTitles()
        r.expect(server.contains(unrelated) && server.occurrences(of: firstEdit) == 1, "\(label): an unrelated task or the winning edit is missing on the server")
        r.observe("\(label).unrelatedSynced", server.contains(unrelated))
        return issue
    }

    @Test("Q02 concurrent edits: a conflict issue keeps both texts, a stale resolution conflicts again, both delivery orders")
    func q02ConcurrentEdits() async {
        await RehearsalRig.scenario("Q02", "concurrent edits, conflict issue, stale resolve") { r, rig in
            let phone = try await rig.device("phone")
            let mac = try await rig.device("mac")
            try await phone.signIn("A")
            try await mac.signIn("A")

            // Order 1: the phone delivers first; the Mac's edit conflicts.
            guard let issue = try await concurrentEdit(r, rig, label: "Q02a", first: phone, second: mac) else {
                r.fail("Q02a produced no issue")
                return
            }
            let shown = try await mac.workspace.accountVersion(ofIssue: issue.id)
            let phoneEdits = RehearsalRig.title("Q02a", "second edit by phone")
            r.stage("stale resolve")
            guard let phoneID = await phone.taskID(titled: RehearsalRig.title("Q02a", "edit by phone")) else {
                r.fail("the phone lost the task")
                return
            }
            try await phone.retitle(phoneID, phoneEdits)
            r.expect(await phone.settle(), "the phone did not deliver its second edit")
            let moved = await mac.eventually(timeout: 30) {
                (try? await mac.workspace.accountVersion(ofIssue: issue.id))??.fields["title"] == phoneEdits
            }
            r.expect(moved, "the Mac never saw the account version move")
            let stale = await mac.workspace.submit(
                RuntimeIssueResolution(issueID: issue.id, outcome: .keepMine, shownRevision: shown?.revision))
            if case .changedAgain(let current) = stale {
                r.observe("staleResolve", "changedAgain, current=\(current?.fields["title"] == phoneEdits)")
            } else {
                r.observe("staleResolve", String(describing: stale))
                r.fail("a resolution against a stale revision was not refused with changedAgain")
            }
            r.expect(!mac.workspace.runtimeIssues.isEmpty, "the issue vanished after a refused stale resolution")

            // Reload the account version and resolve for real: the Mac's text wins and syncs once.
            let current = try await mac.workspace.accountVersion(ofIssue: issue.id)
            let outcome = await mac.workspace.submit(
                RuntimeIssueResolution(issueID: issue.id, outcome: .keepMine, shownRevision: current?.revision))
            r.observe("freshResolve", String(describing: outcome))
            r.expect(outcome == .resolved, "the fresh resolution was not accepted")
            r.expect(await mac.settle(), "the Mac did not deliver the resolved edit")
            let mine = RehearsalRig.title("Q02a", "edit by mac")
            let converged = await phone.eventually(timeout: 30) { await phone.allTitles().contains(mine) }
            r.expect(converged && mac.workspace.runtimeIssues.isEmpty, "the devices did not converge on the resolved text")
            r.expect(try phone.serverTitles().occurrences(of: mine) == 1, "the resolved text is not on the server exactly once")

            // Order 2: the Mac delivers first; the phone's edit conflicts.
            r.stage("order 2")
            let other = try await concurrentEdit(r, rig, label: "Q02b", first: mac, second: phone)
            r.expect(other != nil, "the opposite delivery order produced no conflict issue")
            r.correlation(try rig.session.email(token: mac.token()).correlationID)
        }
        RehearsalReport.notAutomated(
            "Q02-tag-and-descendants", "delete/edit of a Tag; blocked descendants (preserve, reapprove, discard); interrupted choices",
            reason: "Needs descendant/Tag fixtures and the sheet's discard confirmation; the shipped Swift and Rust unit suites cover the decisions, the rehearsal drives only the single-task conflict.")
    }

    @Test("Q05 isolation: switching A to B moves no cache, queue or receipt; A's late work stays A's")
    func q05AccountSwitch() async {
        await RehearsalRig.scenario("Q05", "A to B switch isolation") { r, rig in
            let phone = try await rig.device("phone")
            try await phone.signIn("A")
            let mine = RehearsalRig.title("Q05", "A's synced task")
            let pendingA = RehearsalRig.title("Q05", "A's waiting task")
            let inflight = RehearsalRig.title("Q05", "A's task in flight")
            try await phone.capture(mine)
            r.expect(await phone.settle(), "A did not settle")

            // A has unsent work and one request held on the wire when the person switches.
            await phone.setOffline(true)
            try await phone.capture(pendingA)
            phone.plan.offline = false
            phone.plan.add(path: "/api/sync/v1/commands", .delay(3), times: 1)
            try await phone.capture(inflight)
            r.stage("sign out A")
            try await phone.workspace.signOut(discardUnsyncedChanges: true)
            r.expect(phone.workspace.account == nil, "A is still signed in")
            let afterOut = await phone.allTitles()
            r.observe("localAfterSignOut", afterOut.count)
            r.expect(afterOut.isEmpty, "A's records remain on the device after sign-out")

            r.stage("sign in B")
            try await phone.signIn("B")
            let bTitle = RehearsalRig.title("Q05", "B's task")
            try await phone.capture(bTitle)
            r.expect(await phone.settle(), "B did not settle")
            try? await Task.sleep(for: .seconds(4))  // A's held request would land here
            let tokenB = try phone.token()
            let onB = try rig.session.titles(token: tokenB)
            let onA = try rig.session.titles(token: try rig.session.login("A"))
            r.observe("bServer", "B=\(onB.filter { $0.hasPrefix("Q05") }.count) leakedA=\(onB.filter { $0 == mine || $0 == pendingA || $0 == inflight }.count)")
            r.observe("aServer", "mine=\(onA.occurrences(of: mine)) pending=\(onA.occurrences(of: pendingA)) inflight=\(onA.occurrences(of: inflight)) leakedB=\(onA.occurrences(of: bTitle))")
            r.expect(onB.filter { $0 == mine || $0 == pendingA || $0 == inflight }.isEmpty, "A's work reached B's account")
            r.expect(onA.occurrences(of: bTitle) == 0, "B's work reached A's account")
            let shownB = await phone.allTitles()
            r.expect(shownB == [bTitle], "B's device shows something other than B's task")
            r.expect(onA.occurrences(of: pendingA) == 0, "A's discarded unsent work reached the server")

            // Re-authenticate A: B's work does not follow, A's server data returns.
            r.stage("sign B out, A in again")
            try await phone.workspace.signOut(discardUnsyncedChanges: false)
            try await phone.signIn("A")
            let backToA = await phone.eventually(timeout: 30) { await phone.allTitles().contains(mine) }
            let shownA = await phone.allTitles()
            r.expect(backToA && !shownA.contains(bTitle), "A's device did not return to A's data without B's")
            r.observe("reauthShows", "mine=\(shownA.contains(mine)) B=\(shownA.contains(bTitle))")
            r.correlation(try rig.session.email(token: phone.token()).correlationID)
        }
        RehearsalReport.notAutomated(
            "Q05-ids", "identical 404 for unknown vs foreign scope/device/snapshot/transfer IDs, including SSE registration",
            reason: "Server-side oracle assertions (backend and bb-client suites); the Swift driver only exercises the client-visible isolation.")
    }

    @Test("Q12 recovery states: waiting, persistent failure, conflict and rebuild are what the Workspace reports")
    func q12ModelStates() async {
        await RehearsalRig.scenario("Q12", "waiting, failure, conflict and rebuild states on the Workspace model") { r, rig in
            let phone = try await rig.device("phone")
            let mac = try await rig.device("mac")
            try await phone.signIn("A")
            try await mac.signIn("A")
            r.expect(await RehearsalDevice.settle(phone, mac), "not settled after sign-in")
            @MainActor func line(_ device: RehearsalDevice) -> String {
                SyncStatusDescriber.describe(device.workspace.syncSnapshot, now: Date(), device: .iPhone, calendar: Calendar(identifier: .gregorian)).text
            }

            // Waiting: offline edits are saved and counted, in words.
            await phone.setOffline(true)
            try await phone.capture(RehearsalRig.title("Q12", "waits"))
            await phone.workspace.refreshRustStatus()
            let waiting = line(phone)
            r.observe("waitingLine", waiting)
            r.expect(phone.workspace.pendingChangeCount == 1, "one waiting change is not counted")
            r.observe("waitingStatus", String(describing: phone.workspace.syncStatus).prefix(60))
            r.expect(waiting.lowercased().contains("offline") && waiting.lowercased().contains("waiting"), "the status line does not say offline and what waits")

            // Rebuild fails while the snapshot route is cut, keeps the waiting change, then resumes.
            await phone.setOffline(false)
            r.expect(await phone.settle(), "the waiting change did not deliver")
            phone.plan.add(path: "/api/sync/v1/snapshots", .dropRequest, times: 10_000)
            try await phone.capture(RehearsalRig.title("Q12", "kept through rebuild"))
            let failedRebuild = await phone.workspace.rebuildSyncedCopy()
            r.observe("rebuildInterrupted", "\(failedRebuild) recovery=\(phone.workspace.syncRecovery.rebuild)")
            if case .failed = failedRebuild {} else { r.fail("an interrupted rebuild did not report failure: \(failedRebuild)") }
            if case .failed = phone.workspace.syncRecovery.rebuild {} else { r.fail("the recovery state does not show the failed rebuild") }
            phone.plan.clearRules()
            let resumed = await phone.workspace.rebuildSyncedCopy()
            r.observe("rebuildResumed", "\(resumed) recovery=\(phone.workspace.syncRecovery.rebuild)")
            r.expect(resumed == .rebuilt && phone.workspace.syncRecovery.rebuild == .idle, "the rebuild did not resume to completion")
            await phone.workspace.refreshRustStatus()
            let keptTitle = RehearsalRig.title("Q12", "kept through rebuild")
            let keptOnServer = try phone.serverTitles().contains(keptTitle)
            r.expect(phone.workspace.pendingChangeCount >= 1 || keptOnServer, "the change waiting during the rebuild was lost")

            // Persistent failure: the server keeps answering 503 (a refusal such as 422 is a verdict instead: the
            // command becomes an issue); the model says syncing stopped with a reference, keeps the change, and
            // recovers when sends are accepted again.
            phone.plan.add(path: "/api/sync/v1/commands", .respond(status: 503, code: "SERVICE_UNAVAILABLE"), times: 10_000)
            try await phone.capture(RehearsalRig.title("Q12", "failing"))
            let failing = await phone.eventually(timeout: 30) {
                if case .failing = phone.workspace.syncStatus { return true }
                return false
            }
            await phone.workspace.refreshRustStatus()
            r.observe("failureLine", line(phone))
            r.observe("failureStatus", String(describing: phone.workspace.syncStatus).prefix(120))
            r.expect(failing, "persistent delivery failure never reached the failing status")
            // The snapshot carries the failure run; the line words it only once an attempt at least
            // `SyncTiming.failureSurfacesAfter` after the first failure has failed too (until then it still reads
            // the last success). Age this real snapshot past that bound instead of waiting a minute.
            let snapshot = phone.workspace.syncSnapshot
            r.expect(snapshot.failingSince != nil, "the snapshot does not carry the persistent failure")
            if let since = snapshot.failingSince {
                var aged = snapshot
                aged.lastFailedAttemptAt = since.addingTimeInterval(SyncTiming.failureSurfacesAfter + 1)
                let agedLine = SyncStatusDescriber.describe(
                    aged, now: since.addingTimeInterval(SyncTiming.failureSurfacesAfter + 2), device: .iPhone,
                    calendar: Calendar(identifier: .gregorian)
                ).text
                r.observe("failureLineAfter60s", agedLine)
                r.expect(agedLine.hasPrefix("Couldn't sync"), "a failure older than 60 s is not worded (reads: \(agedLine))")
            }
            r.expect(phone.workspace.pendingChangeCount >= 1, "the failing change is not counted as waiting")
            phone.plan.clearRules()
            r.expect(await phone.settle(timeout: 90), "the device did not recover when the network did")

            // Conflict: two-version issue on the Mac.
            let issue = try await concurrentEdit(r, rig, label: "Q12c", first: phone, second: mac)
            await mac.workspace.refreshRustStatus()
            r.observe("conflictLine", line(mac))
            r.observe("conflictIssueCount", mac.workspace.syncSnapshot.issueCount)
            r.expect(issue != nil && mac.workspace.syncSnapshot.issueCount >= 1, "the conflict is not in the sync snapshot")
            r.correlation(try rig.session.email(token: mac.token()).correlationID)
        }
        RehearsalReport.notAutomated(
            "Q12-people", "keyboard/VoiceOver reach, representative-user comprehension, timing comparison against M-/D- states",
            reason: "Human judgement on a reference device (SC-008); this driver asserts model state only.")
    }
}

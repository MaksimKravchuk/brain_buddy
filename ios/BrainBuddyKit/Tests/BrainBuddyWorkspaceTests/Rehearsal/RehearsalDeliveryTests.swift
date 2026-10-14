import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyWorkspace

/// Q01 (offline capture) and Q03 (delivery faults) of the pilot rehearsal, two installs signed into
/// account A against the real backend.
@Suite("Pilot rehearsal: offline capture and delivery faults (026 Q01, Q03)", .rehearsal, .serialized)
@MainActor
struct RehearsalDeliveryTests {
    @Test("Q01 offline capture survives a runtime close/reopen and converges exactly once")
    func q01OfflineCapture() async {
        await RehearsalRig.scenario("Q01", "offline capture, kill/reopen, converge once") { r, rig in
            let milk = RehearsalRig.title("Q01", "buy milk")
            let oat = RehearsalRig.title("Q01", "buy oat milk")
            let plumber = RehearsalRig.title("Q01", "call plumber")
            let phone = try await rig.device("phone")
            let mac = try await rig.device("mac")

            // Account-less work issues no account request.
            let loner = try await rig.device("loner")
            try await loner.capture(RehearsalRig.title("Q01", "account-less"))
            try? await Task.sleep(for: .milliseconds(500))
            r.expect(loner.plan.events.isEmpty, "an account-less device sent a request")
            r.observe("accountlessRequests", loner.plan.events.count)

            try await phone.signIn("A")
            try await mac.signIn("A")
            r.expect(await RehearsalDevice.settle(phone, mac), "the devices did not settle after sign-in")

            // The phone is disconnected: create, edit, move.
            await phone.setOffline(true)
            let reachedBefore = phone.plan.reachedServer
            r.stage("capture"); let milkID = try await phone.capture(milk)
            let plumberID = try await phone.capture(plumber)
            r.stage("move"); try await phone.move(plumberID, to: .someday)
            r.stage("retitle"); try await phone.retitle(milkID, oat)
            await phone.workspace.refreshRustStatus()
            r.observe("pendingWhileOffline", phone.pending)
            r.expect(phone.pending > 0, "no change is waiting after offline edits")
            r.expect(phone.plan.reachedServer == reachedBefore, "a request reached the server while offline")

            r.stage("relaunch")
            try await phone.relaunch()
            await phone.setOffline(true)
            await phone.workspace.refreshRustStatus()
            let shown = await phone.titles()
            r.observe("pendingAfterReopen", phone.pending)
            r.expect(shown[.inbox]?.contains(oat) == true && shown[.inbox]?.contains(milk) == false,
                     "the edited title did not survive the reopen")
            r.expect(shown[.someday]?.contains(plumber) == true, "the moved task did not survive the reopen")
            r.expect(phone.pending > 0, "the waiting changes did not survive the reopen")
            r.expect(try !phone.serverTitles().contains(oat), "offline work reached the server")

            r.stage("reconnect")
            // Reconnect: it converges once, on the server and on the Mac.
            await phone.setOffline(false)
            let phoneSettled = await phone.settle()
            r.observe("serverStates", try rig.session.states(token: phone.token()).filter { $0.key.hasPrefix("Q01 ") }.map { "\($0.key.split(separator: " ", maxSplits: 2).last ?? "")=\($0.value)" }.sorted())
            r.expect(phoneSettled, "the phone did not settle after reconnecting")
            let server = try phone.serverTitles()
            r.observe("serverCounts", "oat=\(server.occurrences(of: oat)) plumber=\(server.occurrences(of: plumber)) stale=\(server.occurrences(of: milk))")
            r.expect(server.occurrences(of: oat) == 1 && server.occurrences(of: plumber) == 1, "the server does not hold each task exactly once")
            r.expect(server.occurrences(of: milk) == 0, "the superseded title reached the server")
            let onMac = await mac.eventually { let shown = await mac.allTitles(); return shown.contains(plumber) && shown.contains(oat) }
            let macTitles = await mac.allTitles()
            r.observe("macCounts", "oat=\(macTitles.occurrences(of: oat)) plumber=\(macTitles.occurrences(of: plumber))")
            r.expect(onMac && macTitles.occurrences(of: oat) == 1 && macTitles.occurrences(of: plumber) == 1, "the Mac does not show each task exactly once")
            let me = try rig.session.email(token: phone.token())
            r.correlation(me.correlationID)
        }
    }

    /// Finding (rehearsal 2026-10-14): with the weekly review hidden, the Rust runtime sends a command
    /// into Next without `new_formulation_id` (the Swift side stamps it only while the review is exposed,
    /// `Workspace.perform`), and the sync-v1 server rejects that as `INVALID_REQUEST`
    /// (`device_executor_children.py`: "state == next and not new_formulation_id"). The rejection is
    /// terminal, no issue is raised, and the sync loop retries it without backoff. Known issue: this test
    /// starts failing the day the defect is fixed, which is the signal to remove `withKnownIssue`.
    @Test("Q01b a capture or move into Next reaches the server (known defect: INVALID_REQUEST)")
    func q01bNextReachesTheServer() async {
        await RehearsalRig.scenario("Q01b", "capture into Next reaches the server",
            note: "KNOWN DEFECT: task.smart_add into Next carries new_formulation_id=null while the review is hidden; sync-v1 answers 422 INVALID_REQUEST, the queue wedges (status failing, no issue)") { r, rig in
            let phone = try await rig.device("phone")
            try await phone.signIn("A")
            let next = RehearsalRig.title("Q01b", "into Next")
            _ = try await phone.workspace.capture(CaptureDraft(text: next, list: .next), editorID: "scene:phone:next")
            let settled = await phone.settle(timeout: 10)
            let states = try rig.session.states(token: phone.token())
            r.observe("serverState", states[next] ?? "absent")
            r.observe("settled", settled)
            withKnownIssue("Next without new_formulation_id is rejected by the server") {
                r.expect(settled && states[next] == "next", "a task captured into Next did not reach the server")
            }
        }
    }

    @Test("Q03 delivery faults: a dropped request, a lost response after commit, a delay and a crash never duplicate")
    func q03DeliveryFaults() async {
        await RehearsalRig.scenario("Q03", "client-side delivery faults, no duplicate effect") { r, rig in
            let phone = try await rig.device("phone")
            let mac = try await rig.device("mac")
            try await phone.signIn("A")
            try await mac.signIn("A")
            r.expect(await RehearsalDevice.settle(phone, mac), "the devices did not settle after sign-in")
            let commands = "/api/sync/v1/commands"

            // 1. The request is dropped before the server sees it.
            let dropped = RehearsalRig.title("Q03", "request dropped")
            phone.plan.add(path: commands, .dropRequest, times: 2)
            try await phone.capture(dropped)
            r.expect(await phone.settle(timeout: 90), "no recovery after a dropped request")
            r.observe("requestDropped", "events=\(phone.plan.count(path: commands, outcomePrefix: "request-dropped")) server=\(try phone.serverTitles().occurrences(of: dropped))")
            r.expect(try phone.serverTitles().occurrences(of: dropped) == 1, "dropped request: not exactly one effect")

            // 2. The server commits and the answer is lost; the retry must not duplicate.
            let lost = RehearsalRig.title("Q03", "response lost")
            phone.plan.add(path: commands, .dropResponse, times: 1)
            try await phone.capture(lost)
            r.expect(await phone.settle(timeout: 90), "no recovery after a lost response")
            let lostCount = try phone.serverTitles().occurrences(of: lost)
            r.observe("responseLost", "dropped=\(phone.plan.count(path: commands, outcomePrefix: "response-dropped")) sentAfter=\(phone.plan.count(path: commands, outcomePrefix: "sent:")) server=\(lostCount)")
            r.expect(phone.plan.count(path: commands, outcomePrefix: "response-dropped") == 1, "the lost-response fault did not fire")
            r.expect(lostCount == 1, "lost response: not exactly one effect")

            // 3. A slow request.
            let slow = RehearsalRig.title("Q03", "delayed")
            phone.plan.add(path: commands, .delay(1.5), times: 1)
            try await phone.capture(slow)
            r.expect(await phone.settle(timeout: 90), "no recovery after a delayed request")
            r.expect(try phone.serverTitles().occurrences(of: slow) == 1, "delayed request: not exactly one effect")

            // 4. Crash between the server's commit and the local settle: kill the app while the answer is lost.
            let crash = RehearsalRig.title("Q03", "crash after commit")
            phone.plan.add(path: commands, .dropResponse, times: 1)
            try await phone.capture(crash)
            let fired = await phone.eventually(timeout: 20) { phone.plan.count(path: commands, outcomePrefix: "response-dropped") >= 2 }
            try await phone.relaunch()
            r.expect(await phone.settle(timeout: 90), "no recovery after a crash after commit")
            let crashCount = try phone.serverTitles().occurrences(of: crash)
            r.observe("crashAfterCommit", "faultFired=\(fired) server=\(crashCount) pending=\(phone.pending)")
            r.expect(crashCount == 1, "crash after commit: not exactly one effect")

            // The Mac sees each of them once.
            let all = [dropped, lost, slow, crash]
            let converged = await mac.eventually(timeout: 60) { let titles = await mac.allTitles(); return all.allSatisfy { titles.contains($0) } }
            let macTitles = await mac.allTitles()
            r.observe("macCounts", all.map { "\(macTitles.occurrences(of: $0))" }.joined(separator: "/"))
            r.expect(converged && all.allSatisfy { macTitles.occurrences(of: $0) == 1 }, "the Mac does not show each task exactly once")
            r.correlation(try rig.session.email(token: mac.token()).correlationID)
        }
    }
}

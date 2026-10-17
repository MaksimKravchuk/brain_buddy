import BrainBuddyAgents
import BrainBuddyAPI
import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyMacCore

@MainActor
@Suite("030 Agent connection editor")
struct AgentConnectionEditorTests {
    private struct Rig {
        let remote: FakeAgentRemote
        let model: AgentSettingsModel
        let availability: AgentAvailability
        let availabilityRemote: FakeAvailabilityRemote
        let log: CapturingMacLog
    }

    private let hermes = AgentFixtures.connection()

    private func rig(password: Bool = true, rereadRevision: Int = 3) async -> Rig {
        let log = CapturingMacLog()
        let remote = FakeAgentRemote(
            list: .success([AgentFixtures.connection(), AgentFixtures.connection(id: "agent_2", name: "Claude")]),
            reread: .success(AgentFixtures.connection(revision: rereadRevision)))
        let availabilityRemote = FakeAvailabilityRemote(password: password)
        let availability = AgentAvailability(account: AccountFixtures.account(), remote: { _ in availabilityRemote })
        await availability.refresh()
        let model = AgentSettingsModel(account: AccountFixtures.account(), availability: availability, remote: { _ in remote }, log: log)
        await model.reload()
        return Rig(remote: remote, model: model, availability: availability, availabilityRemote: availabilityRemote, log: log)
    }

    private func fillAdd(_ editor: AgentConnectionEditor) {
        editor.name = "Research"
        editor.address = "https://research.example.org"
        editor.scheme = .apiKey
        editor.secret = "s3cret-token"
        editor.password = "hunter2"
    }

    @Test("030_FR_031 Add and test creates, tests, then selects the new agent")
    func addCreatesTestsAndSelects() async {
        let rig = await rig()
        let created = AgentFixtures.connection(id: "agent_new", name: "Research", status: "untested", ready: false, revision: 1)
        rig.remote.queue(.success(created))
        rig.remote.queue(.success(AgentFixtures.connection(id: "agent_new", name: "Research", revision: 2)))
        let editor = AgentConnectionEditor(mode: .add, model: rig.model, log: rig.log)
        let blank = editor.canSubmit
        fillAdd(editor)
        let ready = editor.canSubmit
        await editor.submit()
        let calls = rig.remote.calls.filter { $0.op != "list" }
        #expect(!blank, "Add and test is disabled until every field is filled")
        #expect(ready)
        #expect(calls.map(\.op) == ["create", "test"])
        #expect(calls[0].name == "Research" && calls[0].scheme == "api_key" && calls[0].credential == "s3cret-token")
        #expect(calls[0].password == "hunter2")
        #expect(calls[0].key != nil && calls[1].key != nil && calls[0].key != calls[1].key, "each request has its own key")
        #expect(calls[1].id == "agent_new" && calls[1].password == nil)
        #expect(rig.model.selectedID == "agent_new")
        #expect(rig.model.rows.last?.status == "Tested ready")
        #expect(editor.phase == .done)
    }

    @Test("030_FR_031 an agent whose test fails is still added and selected")
    func addWithFailedTest() async {
        let rig = await rig()
        rig.remote.queue(.success(AgentFixtures.connection(id: "agent_new", name: "Research", status: "untested", ready: false)))
        rig.remote.queue(.failure(AgentFixtures.offline))
        let editor = AgentConnectionEditor(mode: .add, model: rig.model, log: rig.log)
        fillAdd(editor)
        await editor.submit()
        #expect(rig.model.selectedID == "agent_new")
        #expect(rig.model.rows.last?.status == "Not tested")
        #expect(editor.phase == .done)
        #expect(editor.secret.isEmpty && editor.password.isEmpty)
    }

    @Test("030_FR_032 a name-only Edit sends no password, address or type")
    func nameOnlyEditSendsNoPassword() async {
        let rig = await rig()
        rig.remote.queue(.success(AgentFixtures.connection(name: "Hermes 2", revision: 4)))
        let editor = AgentConnectionEditor(mode: .edit(hermes), model: rig.model, log: rig.log)
        let untouched = editor.canSubmit
        editor.name = "Hermes 2"
        let needsPassword = editor.needsPassword
        let ready = editor.canSubmit
        await editor.submit()
        let call = rig.remote.calls.first { $0.op == "update" }
        #expect(!untouched, "nothing changed")
        #expect(!needsPassword && ready)
        #expect(call?.name == "Hermes 2")
        #expect(call?.password == nil && call?.address == nil && call?.scheme == nil)
        #expect(call?.revision == 3)
        #expect(rig.model.rows.first?.name == "Hermes 2")
    }

    @Test("030_FR_032 changing the address or type needs the password and sends it")
    func destinationEditNeedsPassword() async {
        let rig = await rig()
        rig.remote.queue(.success(AgentFixtures.connection(address: "https://new.example.org", revision: 4)))
        let editor = AgentConnectionEditor(mode: .edit(hermes), model: rig.model, log: rig.log)
        editor.address = "https://new.example.org"
        let moved = editor.destinationChanged
        let withoutPassword = editor.canSubmit
        editor.password = "hunter2"
        let withPassword = editor.canSubmit
        await editor.submit()
        let call = rig.remote.calls.first { $0.op == "update" }
        #expect(moved && !withoutPassword && withPassword)
        #expect(call?.address == "https://new.example.org" && call?.name == nil)
        #expect(call?.password == "hunter2")
        let type = AgentConnectionEditor(mode: .edit(hermes), model: rig.model, log: rig.log)
        type.scheme = .apiKey
        #expect(type.destinationChanged && type.needsPassword)
    }

    @Test("030_FR_032 Replace credential sends the new secret, the password and the revision")
    func replaceCredential() async {
        let rig = await rig()
        rig.remote.queue(.success(AgentFixtures.connection(revision: 4)))
        let editor = AgentConnectionEditor(mode: .replaceCredential(hermes), model: rig.model, log: rig.log)
        editor.secret = "new-secret"
        editor.password = "hunter2"
        await editor.submit()
        let call = rig.remote.calls.first { $0.op == "replace" }
        #expect(call?.credential == "new-secret" && call?.password == "hunter2" && call?.revision == 3)
        #expect(call?.key != nil)
        #expect(editor.phase == .done)
        #expect(editor.secret.isEmpty && editor.password.isEmpty)
    }

    @Test("030_FR_033 Delete sends the password and the revision, then drops the agent")
    func deleteDisconnects() async {
        let rig = await rig()
        rig.remote.queue(.success(AgentFixtures.connection(status: "disconnected", ready: false, revision: 4)))
        let editor = AgentConnectionEditor(mode: .delete(hermes), model: rig.model, log: rig.log)
        let empty = editor.canSubmit
        editor.password = "hunter2"
        await editor.submit()
        let call = rig.remote.calls.first { $0.op == "disconnect" }
        #expect(!empty)
        #expect(call?.id == "agent_1" && call?.password == "hunter2" && call?.revision == 3)
        #expect(rig.model.rows.map(\.name) == ["Claude"])
        #expect(rig.model.selectedID == "agent_2")
    }

    @Test("030_FR_034 a wrong password keeps the sheet, keeps the other fields and clears the secrets")
    func wrongPasswordKeepsFields() async {
        let rig = await rig()
        rig.remote.queue(.failure(AgentFixtures.wrongPassword))
        rig.remote.queue(.success(AgentFixtures.connection(id: "agent_new", name: "Research")))
        rig.remote.queue(.success(AgentFixtures.connection(id: "agent_new", name: "Research")))
        let editor = AgentConnectionEditor(mode: .add, model: rig.model, log: rig.log)
        fillAdd(editor)
        await editor.submit()
        let failed = editor.phase
        #expect(failed == .failed(AgentNotice(message: AgentsCopy.wrongPassword, reference: "ref_403", failure: .wrongPassword)))
        #expect(editor.name == "Research" && editor.address == "https://research.example.org" && editor.scheme == .apiKey)
        #expect(editor.password.isEmpty && editor.secret.isEmpty)
        fillAdd(editor)
        await editor.submit()
        let creates = rig.remote.calls.filter { $0.op == "create" }
        #expect(creates.count == 2)
        #expect(creates[0].key != creates[1].key, "a refused request is not repeated under its key")
    }

    @Test("030_FR_034 Try again after a network failure reuses the action's Idempotency-Key")
    func retryReusesKey() async {
        let rig = await rig()
        rig.remote.queue(.failure(AgentFixtures.offline))
        rig.remote.queue(.success(AgentFixtures.connection(revision: 4)))
        let editor = AgentConnectionEditor(mode: .replaceCredential(hermes), model: rig.model, log: rig.log)
        editor.secret = "new-secret"
        editor.password = "hunter2"
        await editor.submit()
        let first = editor.phase
        editor.secret = "new-secret"
        editor.password = "hunter2"
        await editor.submit()
        let replaces = rig.remote.calls.filter { $0.op == "replace" }
        guard case .failed(let notice) = first else {
            Issue.record("expected a failure")
            return
        }
        #expect(notice.canRetry && notice.failure == .offline)
        #expect(replaces.count == 2)
        #expect(replaces[0].key == replaces[1].key)
        #expect(editor.phase == .done)
    }

    @Test("030_FR_034 a stale revision re-reads the agent and says so; the next request carries the new revision")
    func staleRevisionRereads() async {
        let rig = await rig(rereadRevision: 8)
        rig.remote.queue(.failure(AgentFixtures.stale))
        rig.remote.queue(.success(AgentFixtures.connection(status: "disconnected", ready: false, revision: 9)))
        let editor = AgentConnectionEditor(mode: .delete(hermes), model: rig.model, log: rig.log)
        editor.password = "hunter2"
        await editor.submit()
        guard case .failed(let notice) = editor.phase else {
            Issue.record("expected a failure")
            return
        }
        #expect(notice.message == AgentsCopy.staleRevision)
        #expect(rig.remote.calls.contains { $0.op == "read" && $0.id == "agent_1" })
        #expect(editor.current?.revision == 8)
        editor.password = "hunter2"
        await editor.submit()
        let revisions = rig.remote.calls.filter { $0.op == "disconnect" }.map(\.revision)
        #expect(revisions == [3, 8])
    }

    @Test("030_FR_034 a 429 is shown in words and never retried")
    func rateLimitIsNotRetried() async {
        let rig = await rig()
        rig.remote.queue(.failure(AgentFixtures.rateLimited))
        let editor = AgentConnectionEditor(mode: .delete(hermes), model: rig.model, log: rig.log)
        editor.password = "hunter2"
        await editor.submit()
        #expect(rig.remote.calls.filter { $0.op == "disconnect" }.count == 1)
        guard case .failed(let notice) = editor.phase else {
            Issue.record("expected a failure")
            return
        }
        #expect(notice.message == AgentsCopy.rateLimited && !notice.canRetry)
        #expect(editor.password.isEmpty)
    }

    @Test("030_FR_034 the relay's flag-off 404 hides the surface and reads availability again")
    func relayUnavailable() async {
        let rig = await rig()
        rig.availabilityRemote.setFlag(false)
        rig.remote.queue(.failure(AgentFixtures.relayOff))
        let before = rig.availabilityRemote.meCalls
        let editor = AgentConnectionEditor(mode: .delete(hermes), model: rig.model, log: rig.log)
        editor.password = "hunter2"
        await editor.submit()
        #expect(!rig.availability.relayEnabled)
        #expect(rig.availabilityRemote.meCalls == before + 1)
    }

    @Test("030_FR_035 secrets are empty after success, failure and dismiss")
    func secretsAreEmptiedEverywhere() async {
        let rig = await rig()
        rig.remote.queue(.success(AgentFixtures.connection(revision: 4)))
        rig.remote.queue(.failure(AgentFixtures.wrongPassword))
        let ok = AgentConnectionEditor(mode: .replaceCredential(hermes), model: rig.model, log: rig.log)
        ok.secret = "a"
        ok.password = "b"
        await ok.submit()
        let bad = AgentConnectionEditor(mode: .replaceCredential(hermes), model: rig.model, log: rig.log)
        bad.secret = "a"
        bad.password = "b"
        await bad.submit()
        let typed = AgentConnectionEditor(mode: .delete(hermes), model: rig.model, log: rig.log)
        typed.password = "b"
        typed.dismiss()
        #expect(ok.secret.isEmpty && ok.password.isEmpty)
        #expect(bad.secret.isEmpty && bad.password.isEmpty)
        #expect(typed.password.isEmpty && typed.phase == .idle)
        #expect("\(typed)" == "AgentConnectionEditor (redacted)")
    }

    @Test("030_FR_036 without a password only a name-only Edit is possible")
    func passwordlessEditor() async {
        let rig = await rig(password: false)
        let delete = AgentConnectionEditor(mode: .delete(hermes), model: rig.model, log: rig.log)
        delete.password = "x"
        let rename = AgentConnectionEditor(mode: .edit(hermes), model: rig.model, log: rig.log)
        rename.name = "Renamed"
        let move = AgentConnectionEditor(mode: .edit(hermes), model: rig.model, log: rig.log)
        move.address = "https://elsewhere.example.org"
        move.password = "x"
        #expect(!delete.canSubmit)
        #expect(rename.canSubmit)
        #expect(!move.canSubmit)
    }

    @Test("030_FR_038 a rejected address shows the server's message and a 401 ends the session")
    func rejectedAndUnauthorized() async {
        let rig = await rig()
        rig.remote.queue(.failure(APIError(kind: .rejected, message: "Address must use HTTPS.", referenceID: "ref_422", statusCode: 422)))
        rig.remote.queue(.failure(APIError(kind: .unauthorized, message: "Sign in", statusCode: 401)))
        let first = AgentConnectionEditor(mode: .add, model: rig.model, log: rig.log)
        fillAdd(first)
        await first.submit()
        let second = AgentConnectionEditor(mode: .delete(hermes), model: rig.model, log: rig.log)
        second.password = "x"
        await second.submit()
        #expect(first.phase == .failed(AgentNotice(message: "Address must use HTTPS.", reference: "ref_422")))
        #expect(rig.model.phase == .sessionEnded)
    }

    @Test("030_FR_035 logs hold stage and outcome only, never a name, address, secret or password")
    func logsHoldNoSecrets() async {
        let rig = await rig()
        rig.remote.queue(.success(AgentFixtures.connection(id: "agent_new", name: "Research")))
        rig.remote.queue(.success(AgentFixtures.connection(id: "agent_new", name: "Research")))
        let editor = AgentConnectionEditor(mode: .add, model: rig.model, log: rig.log)
        fillAdd(editor)
        await editor.submit()
        let text = rig.log.messages().joined(separator: "\n")
        #expect(text.contains("agent-editor stage=add outcome=done"))
        for secret in ["s3cret-token", "hunter2", "Research", "research.example.org"] {
            #expect(!text.contains(secret))
        }
    }
}

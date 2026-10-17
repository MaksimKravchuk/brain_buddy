#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyAgents
    import BrainBuddyAPI
    import Foundation
    import Testing

    @testable import BrainBuddyMac
    @testable import BrainBuddyMacCore

    /// The Add, Replace credential, Edit and Delete sheets (design G-07, G-08, spec 030): what each says,
    /// when its button is on, which button Return presses and that closing empties the secure fields.
    @Suite("030 Agent sheets")
    @MainActor
    struct AgentSheetsTests {
        private let hermes = AgentFixtures.connection()

        private func controller(password: Bool = true, remote: FakeAgentRemote? = nil) async -> AgentsTabController {
            let availability = AgentAvailability(
                account: AccountFixtures.account(),
                remote: { _ in FakeAvailabilityRemote(password: password) }, now: { Date(timeIntervalSince1970: 1_000_000) })
            await availability.refresh()
            let remote = remote ?? FakeAgentRemote(list: .success([AgentFixtures.connection()]))
            let model = AgentSettingsModel(account: AccountFixtures.account(), availability: availability, remote: { _ in remote })
            await model.reload()
            return AgentsTabController(model: model, availability: availability)
        }

        @Test("030_FR_031 Add and test is off until every field is filled")
        func addNeedsEveryField() async {
            let editor = AgentConnectionEditor(mode: .add, model: await controller().model)
            var steps = [editor.canSubmit]
            editor.name = "Research"
            steps.append(editor.canSubmit)
            editor.address = "https://research.example.org"
            steps.append(editor.canSubmit)
            editor.secret = "s3cret"
            steps.append(editor.canSubmit)
            editor.password = "hunter2"
            steps.append(editor.canSubmit)
            #expect(steps == [false, false, false, false, true])
            #expect(AgentSheetPlan.submitTitle(.add, phase: .idle) == "Add and test")
            #expect(AgentSheetPlan.submitTitle(.add, phase: .adding) == "Adding…")
            #expect(AgentSheetPlan.submitTitle(.add, phase: .testing) == "Testing…")
        }

        @Test("030_FR_031 M30 opens proof without a request and submits only after password entry")
        func addConfirmsBeforeSending() async {
            let remote = FakeAgentRemote()
            let editor = AgentConnectionEditor(mode: .add, model: await controller(remote: remote).model)
            editor.name = "Hermes"
            editor.address = "https://hermes.example.org"
            editor.secret = "synthetic-credential"
            #expect(editor.canConfirmAdd && !editor.canSubmit)
            let flow = AgentEditorSheetFlow()
            await flow.performPrimary(editor: editor)
            #expect(flow.confirmingAdd)
            await flow.performPrimary(editor: editor)
            #expect(remote.calls.filter { $0.op == "create" }.isEmpty)
            editor.password = "synthetic-password"
            remote.queue(.success(hermes))
            remote.queue(.success(hermes))
            await flow.performPrimary(editor: editor)
            #expect(remote.calls.filter { $0.op == "create" }.count == 1)
            #expect(editor.phase == .done)
            #expect(editor.secret.isEmpty && editor.password.isEmpty)
        }

        @Test("030_FR_034 M30 rejection clears proof and returns to the credential form")
        func addFailureReturnsToForm() async {
            let remote = FakeAgentRemote()
            remote.queue(.failure(AgentFixtures.wrongPassword))
            let editor = AgentConnectionEditor(mode: .add, model: await controller(remote: remote).model)
            editor.name = "Hermes"
            editor.address = "https://hermes.example.org"
            editor.scheme = .apiKey
            editor.secret = "synthetic-credential"
            let flow = AgentEditorSheetFlow()
            await flow.performPrimary(editor: editor)
            editor.password = "synthetic-password"
            await flow.performPrimary(editor: editor)
            #expect(!flow.confirmingAdd)
            #expect(editor.secret.isEmpty && editor.password.isEmpty)
            #expect(editor.name == "Hermes" && editor.address == "https://hermes.example.org" && editor.scheme == .apiKey)
            #expect(!editor.canConfirmAdd && !editor.canSubmit)
            if case .failed(let notice) = editor.phase { #expect(notice.failure == .wrongPassword) }
            else { Issue.record("Wrong password must stay a visible failure") }
            await flow.performPrimary(editor: editor)
            #expect(!flow.confirmingAdd)
            #expect(remote.calls.filter { $0.op == "create" }.count == 1)
            editor.secret = "synthetic-credential"
            #expect(editor.canConfirmAdd && !editor.canSubmit)
            await flow.performPrimary(editor: editor)
            #expect(flow.confirmingAdd && editor.password.isEmpty)
            await flow.performPrimary(editor: editor)
            #expect(flow.confirmingAdd, "Return with empty proof must not collapse the retry stage")
            #expect(remote.calls.filter { $0.op == "create" }.count == 1)
        }

        @Test("030_FR_025 030_FR_036 M30 cannot request proof while offline or passwordless")
        func addConfirmationNeedsAvailability() async {
            for controller in [await controller(password: false), await controller(remote: FakeAgentRemote(list: .failure(AgentFixtures.offline)))] {
                let editor = AgentConnectionEditor(mode: .add, model: controller.model)
                editor.name = "Hermes"
                editor.address = "https://hermes.example.org"
                editor.secret = "synthetic-credential"
                editor.password = "synthetic-password"
                #expect(!editor.canConfirmAdd && !editor.canSubmit)
                let flow = AgentEditorSheetFlow()
                await flow.performPrimary(editor: editor)
                #expect(!flow.confirmingAdd)
            }
        }

        @Test("030_FR_032 Edit shows the password only after the address or type changes")
        func editShowsPasswordOnDestinationChange() async {
            let editor = AgentConnectionEditor(mode: .edit(hermes), model: await controller().model)
            let initial = editor.needsPassword
            editor.name = "Hermes 2"
            let renamed = editor.needsPassword
            editor.address = "https://elsewhere.example.org"
            let moved = editor.needsPassword
            editor.address = hermes.agentAddress
            editor.scheme = .apiKey
            let retyped = editor.needsPassword
            #expect(!initial && !renamed && moved && retyped)
            #expect(AgentSheetPlan.showsDetails(.edit(hermes)) && !AgentSheetPlan.showsSecret(.edit(hermes)))
            #expect(AgentSheetPlan.title(.edit(hermes)) == "Hermes")
        }

        @Test("030_FR_032 Replace credential asks for the secret and the password")
        func replaceAsksForBoth() async {
            let editor = AgentConnectionEditor(mode: .replaceCredential(hermes), model: await controller().model)
            editor.secret = "new"
            let withoutPassword = editor.canSubmit
            editor.password = "hunter2"
            #expect(!withoutPassword && editor.canSubmit)
            #expect(AgentSheetPlan.showsSecret(.replaceCredential(hermes)) && !AgentSheetPlan.showsDetails(.replaceCredential(hermes)))
            #expect(AgentSheetPlan.title(.replaceCredential(hermes)) == "Replace credential for Hermes")
            #expect(AgentSheetPlan.submitTitle(.replaceCredential(hermes), phase: .idle) == "Replace")
        }

        @Test("030_FR_033 Delete is never the default button and needs the password")
        func deleteIsNeverTheDefault() async {
            let mode = AgentEditorMode.delete(hermes)
            let editor = AgentConnectionEditor(mode: mode, model: await controller().model)
            let empty = editor.canSubmit
            editor.password = "hunter2"
            #expect(!empty && editor.canSubmit)
            #expect(AgentSheetPlan.returnPressesCancel(mode))
            for other in [AgentEditorMode.add, .replaceCredential(hermes), .edit(hermes)] {
                #expect(!AgentSheetPlan.returnPressesCancel(other))
            }
            #expect(AgentSheetPlan.title(mode) == "Delete Hermes?")
            #expect(AgentsCopy.deleteNote == "Its credential is destroyed. Runs already sent keep their history.")
        }

        @Test("030_FR_035 closing a sheet empties its secure fields")
        func closingEmptiesSecrets() async {
            let controller = await controller()
            controller.open(.replaceCredential(hermes))
            controller.editor?.secret = "new-secret"
            controller.editor?.password = "hunter2"
            let editor = controller.editor
            controller.closeEditor()
            #expect(controller.editor == nil)
            #expect(editor?.secret.isEmpty == true && editor?.password.isEmpty == true)
        }

        @Test("030_FR_036 without a password on the account Add and Replace cannot be opened")
        func passwordlessCannotOpenCredentialSheets() async {
            let controller = await controller(password: false)
            controller.open(.add)
            #expect(controller.editor == nil)
        }
    }
#endif

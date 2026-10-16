#if canImport(SwiftUI) && os(macOS)
    import BrainBuddyAgents
    import BrainBuddyAPI
    import BrainBuddyMacCore
    import Foundation
    import Testing

    @testable import BrainBuddyMac

    @MainActor
    @Suite("030 Hand-off sheet")
    struct HandoffSheetTests {
        private func source() -> String {
            let url = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
                .deletingLastPathComponent().appendingPathComponent("Sources/BrainBuddyMac/Agents/HandoffSheet.swift")
            return try! String(contentsOf: url, encoding: .utf8)
        }

        private func makeFlow(_ manifest: AgentManifestDTO) -> (HandoffFlow, FakeHandoffRemote) {
            let remote = FakeHandoffRemote()
            remote.script(connections: [HandoffFixture.connection(id: "conn_a", name: "Hermes")], manifests: [manifest])
            let availability = AgentAvailability(account: AccountFixtures.account(), remote: { _ in FakeAvailabilityRemote() })
            return (HandoffFlow(taskServerID: "task_1", projectName: "Admin", remote: remote, availability: availability), remote)
        }

        @Test("030_FR_013 Hand off… is hidden with the relay off, disabled with its reason without a server id")
        func controlStates() {
            #expect(HandOffControl(relayEnabled: false, serverID: "task_1") == .hidden)
            #expect(HandOffControl(relayEnabled: false, serverID: nil) == .hidden)
            #expect(HandOffControl(relayEnabled: true, serverID: nil) == .disabled(reason: "This step hasn't reached your account yet."))
            #expect(HandOffControl(relayEnabled: true, serverID: "task_1") == .enabled)
        }

        @Test("030_SC_001 030_FR_013 a selected step reaches Send in three interactions with no password field")
        func threeInteractions() async {
            // 1. Hand off…  2. the first ready agent is already chosen  3. Send.
            let (flow, remote) = makeFlow(HandoffFixture.manifest())
            await flow.start()
            #expect(flow.selectedID == "conn_a")
            #expect(!flow.needsPassword && !flow.needsAcknowledgement)
            #expect(flow.canSend)
            await flow.send()
            #expect(remote.sends.count == 1)
            #expect(remote.sends.first?.password == nil)
            #expect(flow.phase == .sent(runID: "run_1"))
        }

        @Test("030_FR_016 the password and acknowledgement appear only when the preview requires them")
        func fieldsOnlyWhenRequired() async {
            let (plain, _) = makeFlow(HandoffFixture.manifest())
            await plain.start()
            #expect(!plain.needsPassword && !plain.needsAcknowledgement)
            let (strict, _) = makeFlow(HandoffFixture.manifest(password: true, acknowledge: true))
            await strict.start()
            #expect(strict.needsPassword && strict.needsAcknowledgement)
            #expect(!strict.canSend)
        }

        @Test("030_FR_040 Return sends, Esc cancels, and the password only goes in a SecureField")
        func keysAndSecureField() {
            let text = source()
            #expect(text.contains(".keyboardShortcut(.defaultAction)"))
            #expect(text.contains(".keyboardShortcut(.cancelAction)"))
            #expect(text.contains("SecureField(AgentsCopy.currentPassword"))
            #expect(!text.contains("TextField(AgentsCopy.currentPassword"))
            #expect(!text.contains("log("))
        }

        @Test("030_FR_013 030_FR_040 the flag turning off closes the sheet")
        func flagOffCloses() {
            #expect(HandOffControl.sheetStaysOpen(relayEnabled: true))
            #expect(!HandOffControl.sheetStaysOpen(relayEnabled: false))
            #expect(source().contains("if !HandOffControl.sheetStaysOpen(relayEnabled: on) { onClose() }"))
        }
    }
#endif

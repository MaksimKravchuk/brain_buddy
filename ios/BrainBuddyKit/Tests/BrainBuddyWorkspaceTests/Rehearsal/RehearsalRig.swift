import Foundation

/// A scenario's server and the devices it launched, shut down together even when it throws.
@MainActor
final class RehearsalRig {
    let session: RehearsalSession
    private var devices: [RehearsalDevice] = []

    init() throws { session = try RehearsalSession.start() }

    var recorder: RehearsalRecorder?

    func device(_ name: String, root: URL? = nil, legacyDocument: Data? = nil, offline: Bool = false) async throws -> RehearsalDevice {
        let device = try await RehearsalDevice.launch(session, name: name, root: root, legacyDocument: legacyDocument, offline: offline)
        device.recorder = recorder
        devices.append(device)
        return device
    }

    func shutdown() async {
        for device in devices { await device.close() }
        devices = []
        session.stop()
    }

    /// Runs a scenario against a fresh rig and records its result.
    static func scenario(
        _ id: String, _ title: String, note: String = "",
        _ body: @MainActor (RehearsalRecorder, RehearsalRig) async throws -> Void
    ) async {
        await RehearsalReport.run(id, title, note: note) { recorder in
            let rig = try RehearsalRig()
            rig.recorder = recorder
            do { try await body(recorder, rig) } catch {
                await rig.shutdown()
                throw error
            }
            await rig.shutdown()
        }
    }

    /// A title unique to this run.
    static func title(_ scenario: String, _ what: String) -> String { "\(scenario) \(RehearsalTarget.runTag) \(what)" }
}

extension Array where Element: Equatable {
    func occurrences(of element: Element) -> Int { filter { $0 == element }.count }
}

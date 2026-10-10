import BrainBuddyCore
import BrainBuddyPersistence
import Foundation

/// An immutable prepared gesture survives unknown completion and process
/// death. This is a runtime draft, not another outbox or domain authority.
struct RustWorkspaceGesture: Codable, Sendable {
    let authoredIntent: Data
    let commands: [RustWorkspaceCommand]
    let context: RustWorkspaceContext
}

struct RustWorkspaceSavedGesture: Sendable {
    let commands: [RustWorkspaceCommand]
    let receipts: [RustWorkspaceSaved]
}

enum RustWorkspaceGestureCompletion: Sendable {
    case saved(RustWorkspaceSavedGesture)
    case refused(RustRefusal, failedCommandID: String?, commands: [RustWorkspaceCommand])
}

@MainActor
final class RustWorkspaceGestureSaver {
    private let runtime: RustWorkspaceRuntime
    private var saving: Set<String> = []
    private(set) var maintenanceError: String?

    init(runtime: RustWorkspaceRuntime) { self.runtime = runtime }

    func save(editorID: String, authoredIntent: Data,
              prepare: () async throws -> RustWorkspaceGesture) async throws -> RustWorkspaceGestureCompletion {
        guard !editorID.isEmpty, editorID.utf8.count <= 200 else { throw RustBridgeError(code: "INVALID_DRAFT_ID") }
        guard saving.insert(editorID).inserted else { throw RustBridgeError(code: "BUSY") }
        defer { saving.remove(editorID) }
        let draftID = "runtime:prepared:" + editorID
        if let draft = try await runtime.loadDraft(draftID) {
            let original = try StoreDocumentCoding.makeDecoder().decode(RustWorkspaceGesture.self, from: draft.fields)
            let known: RustWorkspaceExecution
            let tokenlessInteractive = original.commands.contains {
                $0.commandType == "review.decide" && ($0.admissionTokens.isEmpty || $0.admissionTokens == Data("[]".utf8))
            }
            if tokenlessInteractive {
                guard let receipts = try await runtime.lookupKnownBatch(original.commands, context: original.context) else {
                    throw RustBridgeError(code: "SHOWN_FRAME_RELOAD_REQUIRED")
                }
                known = .saved(receipts)
            } else {
                known = try await runtime.execute(original.commands, context: original.context)
            }
            switch known {
            case .saved(let receipts):
                // Cleanup cannot turn a committed save into a failure. A later
                // attempt can recover the original receipt again if it remains.
                await clearKnownDraft(draftID)
                if original.authoredIntent == authoredIntent {
                    return .saved(RustWorkspaceSavedGesture(commands: original.commands, receipts: receipts))
                }
            case .refused(let refusal, let failedCommandID):
                if original.authoredIntent == authoredIntent {
                    await clearKnownDraft(draftID)
                    return .refused(refusal, failedCommandID: failedCommandID, commands: original.commands)
                }
            }
        }
        let prepared = try await prepare()
        guard prepared.authoredIntent == authoredIntent else { throw RustBridgeError(code: "DRAFT_INTENT_MISMATCH") }
        let fields = try StoreDocumentCoding.makeEncoder().encode(prepared)
        try await runtime.saveDraft(RustWorkspaceDraft(draftID: draftID, editorKind: "runtime_gesture",
            recordType: nil, recordKey: nil, baseRevision: nil, fields: fields,
            updatedAt: ISO8601DateFormatter().string(from: prepared.context.now)))
        let result = try await runtime.execute(prepared.commands, context: prepared.context)
        // Only known completion permits deletion; a thrown unknown-completion
        // error leaves the exact payload, context and IDs for the next attempt.
        await clearKnownDraft(draftID)
        switch result {
        case .saved(let receipts): return .saved(RustWorkspaceSavedGesture(commands: prepared.commands, receipts: receipts))
        case .refused(let refusal, let failedCommandID): return .refused(refusal, failedCommandID: failedCommandID, commands: prepared.commands)
        }
    }

    private func clearKnownDraft(_ draftID: String) async {
        do {
            try await runtime.deleteDraft(draftID)
            maintenanceError = nil
        } catch {
            maintenanceError = (error as? RustBridgeError)?.code ?? "DRAFT_CLEANUP_FAILED"
        }
    }
}

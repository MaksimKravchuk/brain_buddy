import Foundation

/// Only the original fields a TaskStamp compares. No child completeness or
/// current task state can be inferred from this migration witness.
struct RustLegacyTaskStampWitness: Decodable {
    let id: TaskID
    let serverRevision: Int?
    let updatedAt: Date
}

extension TaskStamp {
    func matchesLegacyWitness(_ original: RustLegacyTaskStampWitness?) -> Bool {
        guard let original else { return false }
        return (updatedAt == nil || original.updatedAt == updatedAt) && original.serverRevision == serverRevision
    }
}

extension ReviewReceipt {
    func taskIsUnchanged(_ original: RustLegacyTaskStampWitness) -> Bool {
        (taskRevision == nil || taskRevision == original.serverRevision)
            && (taskUpdatedAt == nil || taskUpdatedAt == original.updatedAt)
    }
}

struct RustLegacySessionWitness: Decodable {
    let id: ReviewSessionID
    let lastActivityAt: Date
}

struct RustLegacySessionScalar: Decodable {
    let id: ReviewSessionID
    let status: ReviewSessionStatus
}

/// A decision's original scalar snapshot, intentionally independent of
/// TaskRecord. Children stay in their separate canonical records; tags arrive
/// through the declared tag component. Neither omission means an empty set.
struct RustLegacyTaskBeforeScalar: Decodable {
    let id: TaskID
    let serverRevision: Int?
    let title: String
    let details: String?
    let state: TaskState
    let projectID: ProjectID?
    let dueDate: CalendarDay?
    let priority: TaskPriority
    let waitingFor: String?
    let waitingSince: Date?
    let completedAt: Date?
    let cancelledAt: Date?
    let orderKey: Int
    let createdAt: Date
    let updatedAt: Date
    let formulation: FormulationClock?
    let consecutiveStalledFormulations: Int?
    let parked: ParkMarker?

    var stampWitness: RustLegacyTaskStampWitness {
        RustLegacyTaskStampWitness(id: id, serverRevision: serverRevision, updatedAt: updatedAt)
    }

    func wire(revision: String, ids: inout RustIDTable) -> WireObject {
        ["id": ids.task(id), "title": title, "details": wireNull(details), "state": state.rawValue,
         "project_id": ids.optional(projectID?.rawValue, prefix: "project"),
         "due_date": wireNull(dueDate?.isoString), "priority": priority.rawValue,
         "waiting_for": wireNull(waitingFor), "waiting_since": wireInstant(waitingSince),
         "order_key": String(max(orderKey, 0)), "source_capture_ids": [String](),
         "created_at": RustInstant.format(createdAt), "updated_at": RustInstant.format(updatedAt),
         "completed_at": wireInstant(completedAt), "cancelled_at": wireInstant(cancelledAt), "revision": revision,
         "consecutive_stalled_formulations": max(consecutiveStalledFormulations ?? 0, 0),
         "formulation": wireNull(formulation.map { RustReadSet.clock($0, &ids) }),
         "parked": wireNull(parked.map { ["at": RustInstant.format($0.at),
                                        "formulation_id": ids.formulation($0.formulationID)] as WireObject })]
    }
}

struct RustLegacyDecisionSource: Decodable {
    let id: DecisionID
    let taskID: TaskID
    let sessionID: ReviewSessionID?
    let decidedAt: Date
    let formulationID: FormulationID?
    let taskAfter: TaskStamp
    let undo: Undo?

    struct Undo: Decodable {
        let taskBefore: RustLegacyTaskBeforeScalar
        let createdTaskID: TaskID?
        let createdTaskAfter: TaskStamp?
        let receiptWritten: ReceiptKind?
        let receiptReplaced: ReviewReceipt?
        let sessionBefore: DecisionUndo.SessionBefore?
    }
}

struct RustLegacyParkSource: Decodable {
    let id: TaskID
    let serverRevision: Int?
    let updatedAt: Date
    let parked: ParkMarker?

    var stamp: TaskStamp { TaskStamp(updatedAt: updatedAt, serverRevision: serverRevision) }
}

enum RustLegacyPrivateSourceDecoding {
    static func decode<T: Decodable>(_ type: T.Type, _ value: Any) throws -> T {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let text = try decoder.singleValueContainer().decode(String.self)
            guard let date = RustInstant.parse(text) else { throw RustDomainError.malformedResult }
            return date
        }
        return try decoder.decode(type, from: RustJSON.data(value))
    }
}

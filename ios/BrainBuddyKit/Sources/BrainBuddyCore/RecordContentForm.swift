import Foundation

/// The canonical bytes of a task's user-visible content, for the Mac's review marks (data-model E7.2):
/// title, notes, state, waiting-for, due date, priority, its project's and tags' normalized names, and
/// its subtasks' titles and states, in a fixed order with every field length-prefixed so no two different
/// field sets give the same bytes. Never an id, a record key, `updatedAt` or any server time, so the bytes
/// survive an upload, a pull that changes nothing visible, re-keying and sign-out then sign-in. There is no
/// hashing here: the Mac target keys an HMAC over these bytes.
public enum RecordContentForm {
    public static func bytes(of task: TaskRecord, in state: GTDState) -> [UInt8] {
        var out: [UInt8] = []
        field(task.title, into: &out)
        field(task.details, into: &out)
        field(task.state.rawValue, into: &out)
        field(task.waitingFor, into: &out)
        field(task.dueDate?.isoString, into: &out)
        field(task.priority.rawValue, into: &out)
        field(task.projectID.flatMap { state.projects[$0] }.map { NameNormalizer.project($0.name) }, into: &out)
        let tags = task.tagIDs.compactMap { state.tags[$0] }.map { NameNormalizer.tag($0.name) }.sorted()
        count(tags.count, into: &out)
        for tag in tags { field(tag, into: &out) }
        let subtasks = task.subtasks.sorted { ($0.orderKey, $0.id) < ($1.orderKey, $1.id) }
        count(subtasks.count, into: &out)
        for subtask in subtasks {
            field(subtask.title, into: &out)
            field(subtask.state.rawValue, into: &out)
        }
        return out
    }

    /// A project's content: the sorted, length-prefixed bytes of the tasks in it, in any state.
    public static func bytes(ofTasksIn project: ProjectID, in state: GTDState) -> [UInt8] {
        let tasks = state.tasks.values.filter { $0.projectID == project }.map { bytes(of: $0, in: state) }
        var out: [UInt8] = []
        for task in tasks.sorted(by: { $0.lexicographicallyPrecedes($1) }) {
            count(task.count, into: &out)
            out += task
        }
        return out
    }

    /// Present marker, then the UTF-8 length and bytes; absent is a single zero byte.
    private static func field(_ value: String?, into out: inout [UInt8]) {
        guard let value else {
            out.append(0)
            return
        }
        out.append(1)
        let utf8 = Array(value.utf8)
        count(utf8.count, into: &out)
        out += utf8
    }

    private static func count(_ value: Int, into out: inout [UInt8]) {
        for shift in stride(from: 24, through: 0, by: -8) { out.append(UInt8((value >> shift) & 0xFF)) }
    }
}

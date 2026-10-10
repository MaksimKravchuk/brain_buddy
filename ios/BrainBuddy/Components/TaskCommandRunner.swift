import BrainBuddyCore
import BrainBuddyWorkspace
import SwiftUI
import UIKit

/// Runs workspace commands from the UI: validation failures become a calm
/// toast (never an alert), and the common transitions get the brand
/// animation, a haptic and an Undo toast.
///
/// Workspace commands throw `GTDValidationError` (typed throws). `run` takes a
/// plain `throws` closure on purpose: Swift 6.2 does not infer a closure's
/// typed `throws(E)` from context, so an unannotated `{ try workspace.x() }`
/// would not convert to `() throws(GTDValidationError) -> Void`. Both an
/// unannotated closure and one written `{ () throws(GTDValidationError) in … }`
/// are accepted.
@MainActor
enum TaskCommandRunner {
    static func run(_ toasts: ToastCenter, _ body: () async throws -> Void) async -> Bool {
        do { try await body(); return true }
        catch { report(error, toasts: toasts); return false }
    }

    static func attempt<Value>(_ toasts: ToastCenter, _ body: () async throws -> Value) async -> Value? {
        do { return try await body() }
        catch { report(error, toasts: toasts); return nil }
    }
    /// Runs `body`; on failure shows the error's message as a toast.
    /// Returns true when `body` succeeded.
    @discardableResult
    static func run(_ toasts: ToastCenter, _ body: () throws -> Void) -> Bool {
        do {
            try body()
            return true
        } catch {
            report(error, toasts: toasts)
            return false
        }
    }

    /// Like `run`, for commands that return a value (a new id, for example).
    static func attempt<Value>(_ toasts: ToastCenter, _ body: () throws -> Value) -> Value? {
        do {
            return try body()
        } catch {
            report(error, toasts: toasts)
            return nil
        }
    }

    /// The message shown for an error thrown by a workspace command.
    static func message(for error: any Error) -> String {
        if let validation = error as? GTDValidationError { return validation.message }
        if let workspaceError = error as? WorkspaceError { return workspaceError.message }
        return "Something went wrong. Try again."
    }

    // MARK: Transitions

    /// Completes an open task with the brand animation (none with Reduce
    /// Motion), a success haptic and a "Completed" toast whose Undo reopens
    /// it into the list it came from (Waiting for keeps its note).
    @discardableResult
    static func complete(_ task: TaskRecord, workspace: Workspace, toasts: ToastCenter, editorID: String = UUID().uuidString) async -> Bool {
        guard let origin = task.openList else { return false }
        let waitingFor = task.waitingFor
        let undoEditorID = UUID().uuidString
        let completed = await run(toasts) { try await workspace.completeTask(task.id, editorID: editorID) }
        guard completed else { return false }
        Haptics.success()
        toasts.show("Completed", actionTitle: "Undo") {
            Task { _ = await run(toasts) { try await workspace.reopenTask(task.id, to: origin, waitingFor: origin == .waiting ? waitingFor : nil, editorID: undoEditorID) } }
        }
        return true
    }

    /// Cancels an open task ("won't do"), with an Undo that reopens it into
    /// the list it came from.
    @discardableResult
    static func cancel(_ task: TaskRecord, workspace: Workspace, toasts: ToastCenter, editorID: String = UUID().uuidString) async -> Bool {
        guard let origin = task.openList else { return false }
        let waitingFor = task.waitingFor
        let undoEditorID = UUID().uuidString
        let cancelled = await run(toasts) { try await workspace.cancelTask(task.id, editorID: editorID) }
        guard cancelled else { return false }
        Haptics.light()
        toasts.show("Cancelled", actionTitle: "Undo") {
            Task { _ = await run(toasts) { try await workspace.reopenTask(task.id, to: origin, waitingFor: origin == .waiting ? waitingFor : nil, editorID: undoEditorID) } }
        }
        return true
    }

    /// Moves an open task to another open list, with an Undo that moves it
    /// back. Moving to Waiting for needs `waitingFor`.
    @discardableResult
    static func move(
        _ task: TaskRecord, to list: OpenList, waitingFor: String? = nil, workspace: Workspace, toasts: ToastCenter,
        editorID: String = UUID().uuidString
    ) async -> Bool {
        guard let origin = task.openList else { return false }
        let originalWaitingFor = task.waitingFor
        let undoEditorID = UUID().uuidString
        let moved = await run(toasts) { try await workspace.moveTask(task.id, to: list, waitingFor: list == .waiting ? waitingFor : nil, editorID: editorID) }
        guard moved else { return false }
        Haptics.light()
        toasts.show("Moved to \(list.title)", actionTitle: "Undo") {
            Task { _ = await run(toasts) { try await workspace.moveTask(task.id, to: origin, waitingFor: origin == .waiting ? originalWaitingFor : nil, editorID: undoEditorID) } }
        }
        return true
    }

    /// Reopens a completed or cancelled task into the list it was in before
    /// (Next actions when that is unknown, as `ReopenSheet` preselects; Inbox
    /// when it was Waiting for and the note is gone), and says where it went.
    @discardableResult
    static func reopen(_ task: TaskRecord, workspace: Workspace, toasts: ToastCenter, editorID: String = UUID().uuidString) async -> Bool {
        let preferred = task.lastOpenList ?? .next
        let note = task.waitingFor?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let list: OpenList = preferred == .waiting && note.isEmpty ? .inbox : preferred
        let reopened = await reopen(task.id, into: list, waitingFor: note, workspace: workspace, toasts: toasts, editorID: editorID)
        if reopened { toasts.show("Reopened in \(list.title)") }
        return reopened
    }

    /// Reopens a terminal task into `list`; `waitingFor` is used only for
    /// Waiting for.
    @discardableResult
    static func reopen(
        _ taskID: TaskID, into list: OpenList, waitingFor: String?, workspace: Workspace, toasts: ToastCenter,
        editorID: String = UUID().uuidString
    ) async -> Bool {
        await run(toasts) { try await workspace.reopenTask(taskID, to: list, waitingFor: list == .waiting ? waitingFor : nil, editorID: editorID) }
    }

    // MARK: Private

    private static func report(_ error: any Error, toasts: ToastCenter) {
        Haptics.warning()
        toasts.showError(message(for: error))
    }
}

/// Haptics for command outcomes.
@MainActor
private enum Haptics {
    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    static func warning() {
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }

    static func light() {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
    }
}

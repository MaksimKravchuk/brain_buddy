import BrainBuddyRustBindings
import Foundation

// The Swift face of the shared Rust core's bridge (spec 026, contracts/runtime-ffi.md).
// The UniFFI-generated `BrainBuddyRustBindings` module is imported here and nowhere else,
// so no generated type is part of the kit's API. Everything that crosses is an owned
// value (`Data`, `String`, integers); there are no pointers, and no error carries
// payload text. This mirrors the Python bridge (`rust/bindings/python`).

/// A typed, content-free failure of the Rust bridge: a stable `code`, whether retrying
/// can help, and the static name of the rule or field it concerns.
///
/// `CANCELLED` is raised on this side too, when the calling task was cancelled.
public struct RustBridgeError: Error, Equatable, Sendable, CustomStringConvertible {
    public let code: String
    public let retryable: Bool
    public let field: String?

    public init(code: String, retryable: Bool = false, field: String? = nil) {
        self.code = code
        self.retryable = retryable
        self.field = field
    }

    /// The calling task was cancelled before or while the call ran; nothing was kept.
    public static let cancelled = RustBridgeError(code: "CANCELLED")

    public var description: String {
        if let field { return "\(code) (\(field))" }
        return code
    }

    /// Maps whatever the generated bindings threw. A panic that escaped the Rust guard,
    /// or any unexpected binding error, is reported as `INTERNAL_ERROR` without its
    /// message, which could embed input text.
    fileprivate init(thrown error: any Error) {
        if let bridge = error as? BridgeError, case let .Failed(code, retryable, field) = bridge {
            self.init(code: code, retryable: retryable, field: field)
        } else if let existing = error as? RustBridgeError {
            self = existing
        } else {
            self.init(code: "INTERNAL_ERROR")
        }
    }
}

/// A command envelope decoded and validated by the Rust codec (sync-v1 section 3).
public struct RustDecodedCommand: Equatable, Sendable {
    public let protocolVersion: UInt32
    public let commandID: String
    public let scopeID: String
    public let deviceID: String
    /// A decimal string: counters can exceed what JSON numbers (and `Double`) hold exactly.
    public let localSequence: String
    public let commandType: String
    public let commandVersion: UInt32
    public let entityID: String
    /// True when this build can execute the command. Otherwise `unsupportedReason`
    /// says why, and the command is kept in its stable recovery form (`UPGRADE_REQUIRED`).
    public let executable: Bool
    public let unsupportedReason: String?
    /// The stable envelope as wire bytes; omitted optional fields stay omitted.
    public let wire: Data

    fileprivate init(_ command: BridgeCommand) {
        protocolVersion = command.protocolVersion
        commandID = command.commandId
        scopeID = command.scopeId
        deviceID = command.deviceId
        localSequence = command.localSequence
        commandType = command.commandType
        commandVersion = command.commandVersion
        entityID = command.entityId
        executable = command.executable
        unsupportedReason = command.unsupportedReason
        wire = command.wire
    }
}

/// One bridge runtime handle. It is safe to share between tasks and threads; `close()`
/// is final and idempotent, and later calls fail with `WORKSPACE_CLOSED`.
public final class RustBridgeRuntime: Sendable {
    // The generated class is `Sendable`: the Rust object behind it is `Send + Sync`
    // (an atomic lifecycle state), which UniFFI requires of every exported object.
    private let runtime: BridgeRuntime

    /// The sync protocol version this build speaks.
    public static var supportedProtocolVersion: UInt32 { bridgeProtocolVersion() }

    /// Opens a runtime. An unsupported `protocolVersion` fails with `UPGRADE_REQUIRED`.
    public init(protocolVersion: UInt32 = RustBridgeRuntime.supportedProtocolVersion) throws {
        do {
            runtime = try BridgeRuntime(protocolVersion: protocolVersion)
        } catch {
            throw RustBridgeError(thrown: error)
        }
    }

    public var isOpen: Bool { runtime.isOpen() }

    /// Closes the runtime. Calls still running report `CANCELLED`.
    public func close() { runtime.close() }

    /// Decodes and validates one command envelope off the caller's actor.
    ///
    /// A cancelled caller gets `CANCELLED` and nothing is kept. The call is pure, so a
    /// cancellation that lands while it runs discards the result rather than interrupting
    /// the Rust code.
    public func decodeCommand(_ data: Data) async throws -> RustDecodedCommand {
        if Task.isCancelled { throw RustBridgeError.cancelled }
        let runtime = self.runtime
        let outcome = await Task.detached(priority: .userInitiated) {
            () -> Result<BridgeCommand, RustBridgeError> in
            do {
                return .success(try runtime.decodeCommand(data: data))
            } catch {
                return .failure(RustBridgeError(thrown: error))
            }
        }.value
        if Task.isCancelled { throw RustBridgeError.cancelled }
        return RustDecodedCommand(try outcome.get())
    }
}

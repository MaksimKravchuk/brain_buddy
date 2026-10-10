import Foundation
import Testing

@testable import BrainBuddyCore

// The Swift end of the Rust bridge (spec 026, T005): the compiled `bb-swift` library is
// linked for real, on Linux and on Apple platforms. The codec itself is covered by
// the Rust crates; these tests are about the boundary: owned values, typed errors that
// carry no payload text, cancellation, the bounded runtime lifecycle and sharing one
// handle across tasks. Panic containment is a Rust-side test (`cargo test -p bb-swift
// bridge`): nothing in the Swift API can make the Rust code panic.

private let commandJSON = """
    {
      "protocol_version": 1,
      "command_id": "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11",
      "scope_id": "scope-1",
      "device_id": "device-1",
      "device_epoch": "epoch-1",
      "local_sequence": "9007199254740993",
      "type": "task.create",
      "command_version": 1,
      "entity_id": "task-1",
      "preconditions": [],
      "depends_on": [],
      "issued_at": "2026-10-09T12:00:00Z",
      "payload": {"title": "Buy milk"}
    }
    """

private let commandData = Data(commandJSON.utf8)

/// The bridge error a call throws, or nil when it did not throw one.
private func bridgeFailure(of body: () async throws -> Void) async -> RustBridgeError? {
    do {
        try await body()
        return nil
    } catch {
        return error as? RustBridgeError
    }
}

@Suite("Rust bridge (026-FR-002, 026-FR-025, 026-FR-026)")
struct RustBridgeTests {
    @Test("026-FR-002: a command decodes into owned values and keeps its 64-bit counter exact")
    func decodesACommand() async throws {
        let runtime = try RustBridgeRuntime()
        let command = try await runtime.decodeCommand(commandData)

        #expect(command.executable)
        #expect(command.unsupportedReason == nil)
        #expect(command.protocolVersion == RustBridgeRuntime.supportedProtocolVersion)
        #expect(command.commandID == "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11")
        #expect(command.commandType == "task.create")
        #expect(command.localSequence == "9007199254740993")

        let wire = try #require(
            try JSONSerialization.jsonObject(with: command.wire) as? [String: Any]
        )
        #expect(wire["local_sequence"] as? String == "9007199254740993")
        #expect(wire["supersedes_command_id"] == nil)
    }

    @Test("026-FR-002: an unsupported command is a value, not an error")
    func unsupportedCommandIsAValue() async throws {
        let runtime = try RustBridgeRuntime()
        let future = commandJSON.replacingOccurrences(of: "task.create", with: "task.from_the_future")
        let command = try await runtime.decodeCommand(Data(future.utf8))

        #expect(!command.executable)
        #expect(command.unsupportedReason == "command_type")
    }

    @Test("026-FR-025: a bad request fails with a typed error that carries no payload text")
    func errorsCarryNoPayloadText() async throws {
        let runtime = try RustBridgeRuntime()
        let truncated = Data("{\"title\": \"Buy milk\"".utf8)

        let failure = try #require(await bridgeFailure { _ = try await runtime.decodeCommand(truncated) })
        #expect(failure.code == "INVALID_REQUEST")
        #expect(!failure.retryable)
        #expect(!failure.description.contains("Buy milk"))
        #expect(!String(reflecting: failure).contains("Buy milk"))

        let notUTF8 = Data([0xFF, 0xFE])
        let second = try #require(await bridgeFailure { _ = try await runtime.decodeCommand(notUTF8) })
        #expect(second.code == "INVALID_REQUEST")
        // A failed call leaves the runtime usable.
        #expect(runtime.isOpen)
        let command = try await runtime.decodeCommand(commandData)
        #expect(command.executable)
    }

    @Test("026-FR-002: an unsupported protocol version is refused as UPGRADE_REQUIRED")
    func refusesUnsupportedProtocolVersion() throws {
        do {
            _ = try RustBridgeRuntime(protocolVersion: RustBridgeRuntime.supportedProtocolVersion + 1)
            Issue.record("a newer protocol version must not open a runtime")
        } catch let error as RustBridgeError {
            #expect(error == RustBridgeError(code: "UPGRADE_REQUIRED", field: "protocol_version"))
        }
    }

    @Test("026-FR-025: close is final and idempotent across repeated open and close cycles")
    func repeatedOpenAndClose() async throws {
        for _ in 0..<50 {
            let runtime = try RustBridgeRuntime()
            #expect(runtime.isOpen)
            runtime.close()
            runtime.close()
            #expect(!runtime.isOpen)

            let failure = await bridgeFailure { _ = try await runtime.decodeCommand(commandData) }
            #expect(failure?.code == "WORKSPACE_CLOSED")
        }
    }

    @Test("026-FR-026: a cancelled task gets CANCELLED and the runtime stays usable")
    func cancellation() async throws {
        let runtime = try RustBridgeRuntime()
        let (gate, release) = AsyncStream<Void>.makeStream()
        let task = Task { () -> RustBridgeError? in
            // Cancelling a task ends its iteration, so the call below always starts cancelled.
            for await _ in gate { break }
            return await bridgeFailure { _ = try await runtime.decodeCommand(commandData) }
        }
        task.cancel()
        release.yield()
        release.finish()

        let failure = await task.value
        #expect(failure == RustBridgeError.cancelled)
        #expect(runtime.isOpen)
        let command = try await runtime.decodeCommand(commandData)
        #expect(command.executable)
    }

    @Test("026-FR-025: one handle is shared by many concurrent tasks")
    func concurrentCalls() async throws {
        let runtime = try RustBridgeRuntime()
        let commands = try await withThrowingTaskGroup(of: RustDecodedCommand.self) { group in
            for _ in 0..<64 {
                group.addTask { try await runtime.decodeCommand(commandData) }
            }
            var decoded: [RustDecodedCommand] = []
            for try await command in group { decoded.append(command) }
            return decoded
        }

        #expect(commands.count == 64)
        #expect(commands.allSatisfy { $0.executable && $0.localSequence == "9007199254740993" })
    }

    @Test("026-FR-025: closing while calls run ends each call in a result or a typed error")
    func closeWhileCallsRun() async throws {
        let runtime = try RustBridgeRuntime()
        let outcomes = await withTaskGroup(of: String.self) { group in
            for _ in 0..<64 {
                group.addTask {
                    do {
                        _ = try await runtime.decodeCommand(commandData)
                        return "ok"
                    } catch let error as RustBridgeError {
                        return error.code
                    } catch {
                        return "unexpected"
                    }
                }
            }
            group.addTask {
                runtime.close()
                return "closed"
            }
            var seen = Set<String>()
            for await outcome in group { seen.insert(outcome) }
            return seen
        }

        #expect(outcomes.isSubset(of: ["ok", "closed", "CANCELLED", "WORKSPACE_CLOSED"]))
        #expect(!runtime.isOpen)
    }
}

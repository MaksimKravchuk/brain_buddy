import Foundation

#if canImport(os)
    import os
#endif

/// Where the agent models' diagnostic lines go (030-FR-039). Callers pass only stage, outcome,
/// counts, durations and server references, never a title, name, address, question or secret, so
/// every line is logged as public. The Mac passes its own sink; the iPhone uses the default.
public protocol AgentLogSink: Sendable {
    func log(_ message: String)
}

/// The default sink: `os.Logger`, category `agents`, under the app's bundle identifier.
public struct SystemAgentLog: AgentLogSink {
    public init() {}

    public func log(_ message: String) {
        #if canImport(os)
            Logger(subsystem: Bundle.main.bundleIdentifier ?? "com.brainbuddy", category: "agents")
                .info("\(message, privacy: .public)")
        #endif
    }
}

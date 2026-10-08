import Foundation
import Synchronization

#if canImport(os)
    import os
#endif

/// Where the Mac's diagnostic lines go: `os.Logger` with subsystem `com.brainbuddy.mac` in the
/// app, a capturing sink in tests (plan "Observability"; research R21). Callers pass only counts,
/// durations, enum names and error classes, never a title, a path, a file name or a digest
/// (FR-030), so every line is logged as public.
package protocol MacLogSink: Sendable {
    func log(_ category: MacLogCategory, _ message: String)
}

package enum MacLogCategory: String, Sendable, CaseIterable {
    case `import`, sync, instance
}

/// The production sink.
package struct SystemMacLog: MacLogSink {
    package static let subsystem = "com.brainbuddy.mac"

    package init() {}

    package func log(_ category: MacLogCategory, _ message: String) {
        #if canImport(os)
            Logger(subsystem: Self.subsystem, category: category.rawValue).info("\(message, privacy: .public)")
        #endif
    }
}

/// Keeps every line, for the privacy tests.
package final class CapturingMacLog: MacLogSink {
    private let lines = Mutex<[(category: MacLogCategory, message: String)]>([])

    package init() {}

    package func log(_ category: MacLogCategory, _ message: String) {
        lines.withLock { $0.append((category, message)) }
    }

    package func messages(_ category: MacLogCategory? = nil) -> [String] {
        lines.withLock { all in all.filter { category == nil || $0.category == category }.map(\.message) }
    }
}

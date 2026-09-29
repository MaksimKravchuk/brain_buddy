import Foundation

#if os(iOS) || os(tvOS) || os(watchOS) || os(visionOS)
    /// Asks the system not to suspend this process until `end()`, so a write
    /// never stops halfway while it holds the shared store's file lock (which
    /// would block the app, its widgets and App Intents). Unlike a background
    /// task, `performExpiringActivity` also works in app extensions.
    ///
    /// The system runs the activity block on a background queue with
    /// `expired == false` and ends the activity when the block returns, so the
    /// block waits for `end()`. If the process is about to be suspended anyway,
    /// the block is called again with `expired == true`, which releases the
    /// first call at once.
    final class ExpiringActivity: Sendable {
        private let finished: DispatchSemaphore

        init(reason: String) {
            let finished = DispatchSemaphore(value: 0)
            self.finished = finished
            ProcessInfo.processInfo.performExpiringActivity(withReason: reason) { expired in
                if expired {
                    finished.signal()
                } else {
                    finished.wait()
                }
            }
        }

        /// Ends the activity. Extra signals are harmless: a semaphore may be
        /// released with a higher count than it started with.
        func end() {
            finished.signal()
        }
    }
#else
    /// macOS and Linux never suspend a process mid-write, and
    /// `performExpiringActivity` is unavailable on macOS.
    struct ExpiringActivity {
        init(reason: String) {}
        func end() {}
    }
#endif

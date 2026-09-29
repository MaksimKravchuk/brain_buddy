import Foundation

#if os(iOS) || os(tvOS) || os(watchOS) || os(visionOS)
    /// Asks the system not to suspend this process until `end()`, so a write
    /// never stops halfway while it holds the shared store's file lock (which
    /// would block the app, its widgets and App Intents, and gets a process
    /// that is suspended holding a lock in the App Group container killed with
    /// 0xdead10cc). Unlike a background task, `performExpiringActivity` also
    /// works in app extensions. `FileDocumentStore` takes one around every
    /// locked stretch, so every writer is covered.
    ///
    /// The system runs the activity block on a background queue with
    /// `expired == false` and ends the activity when the block returns, so the
    /// block waits for `end()`. If the process is about to be suspended anyway,
    /// the block is called again with `expired == true`, which releases the
    /// first call at once.
    ///
    /// `performExpiringActivity` is unavailable on macOS, where processes are
    /// not suspended this way; see the no-op below.
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
    /// No process suspension to prevent on macOS and Linux.
    struct ExpiringActivity {
        init(reason: String) {}
        func end() {}
    }
#endif

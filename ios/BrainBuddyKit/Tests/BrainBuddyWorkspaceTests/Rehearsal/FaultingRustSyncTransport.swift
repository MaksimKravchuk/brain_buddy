import BrainBuddyCore
import Foundation
import Synchronization

/// What a rehearsal device's network does, decided up front so a run is repeatable: while `offline`
/// nothing leaves the device; a rule applies to the next `times` requests whose path contains `path`,
/// in the order they are added. Rules are consumed by request count, never by wall-clock time.
final class FaultPlan: Sendable {
    enum Action: Sendable, Equatable {
        /// The request never reaches the server (the caller sees a timeout).
        case dropRequest
        /// The server gets the request and commits it; the answer is lost (the caller sees a timeout).
        case dropResponse
        /// The request is held this long, then sent.
        case delay(TimeInterval)
        /// The server's answer is replaced by this status with an error envelope carrying `code`; the
        /// request never reaches the server.
        case respond(status: Int, code: String)
    }

    struct Event: Sendable, Equatable {
        let method: String
        let path: String
        /// `offline`, `request-dropped`, `response-dropped:<status>`, `delayed:<seconds>`, `sent:<status>`,
        /// `budget`, `refused`, `cancelled`.
        let outcome: String
        /// The error envelope's code and correlation id of an answer of 400 or more (no user content).
        var code: String? = nil
        var correlationID: String? = nil
    }

    private struct Rule {
        let path: String
        let action: Action
        var remaining: Int
    }

    private struct State {
        var offline = false
        var rules: [Rule] = []
        var events: [Event] = []
    }

    private let state = Mutex(State())

    var offline: Bool {
        get { state.withLock { $0.offline } }
        set { state.withLock { $0.offline = newValue } }
    }

    func add(path: String, _ action: Action, times: Int = 1) {
        state.withLock { $0.rules.append(Rule(path: path, action: action, remaining: times)) }
    }

    func clearRules() { state.withLock { $0.rules = [] } }

    var events: [Event] { state.withLock { $0.events } }

    func count(path: String, outcomePrefix: String) -> Int {
        events.filter { $0.path.contains(path) && $0.outcome.hasPrefix(outcomePrefix) }.count
    }

    /// Requests that reached the server (the answer may have been dropped afterwards).
    var reachedServer: Int { events.filter { $0.outcome.hasPrefix("sent:") || $0.outcome.hasPrefix("response-dropped") }.count }

    fileprivate func record(_ request: RustSyncRequest, _ outcome: String, answer: Data? = nil) {
        var event = Event(method: request.method == .get ? "GET" : "POST", path: request.path, outcome: outcome)
        if let answer, let object = try? JSONSerialization.jsonObject(with: answer) as? [String: Any] {
            event.code = (object["error"] as? [String: Any])?["code"] as? String
            event.correlationID = object["correlation_id"] as? String
        }
        state.withLock { $0.events.append(event) }
    }

    fileprivate func nextAction(for request: RustSyncRequest) -> (offline: Bool, action: Action?) {
        state.withLock { state in
            if state.offline { return (true, nil) }
            guard let index = state.rules.firstIndex(where: { $0.remaining > 0 && request.path.contains($0.path) })
            else { return (false, nil) }
            state.rules[index].remaining -= 1
            return (false, state.rules[index].action)
        }
    }
}

/// `RustSyncTransport` that sits between the core and `URLSessionRustSyncTransport` and applies a
/// `FaultPlan`. It also counts every request that goes out against the run's budget and refuses the
/// routes a prod run must not touch.
final class FaultingRustSyncTransport: RustSyncTransport {
    private let inner: any RustSyncTransport
    private let plan: FaultPlan
    private let budget: RehearsalBudget

    init(wrapping inner: any RustSyncTransport, plan: FaultPlan, budget: RehearsalBudget = .shared) {
        self.inner = inner
        self.plan = plan
        self.budget = budget
    }

    func send(_ request: RustSyncRequest, cancel: RustSyncCancellation) throws(RustSyncTransportFailure) -> RustSyncResponse {
        if cancel.isCancelled { throw .cancelled }
        if (try? RehearsalRoutes.check(request.path)) == nil {
            plan.record(request, "refused")
            throw .connection
        }
        let decision = plan.nextAction(for: request)
        if decision.offline {
            plan.record(request, "offline")
            throw .connection
        }
        if decision.action == .dropRequest {
            plan.record(request, "request-dropped")
            throw .timeout
        }
        if case .respond(let status, let code)? = decision.action {
            let envelope = #"{"error":{"code":"\#(code)","retryable":false,"message":"rehearsal fault","details":{}},"correlation_id":"rehearsal-fault"}"#
            plan.record(request, "synthetic:\(status)")
            return RustSyncResponse(status: status, body: Data(envelope.utf8))
        }
        if case .delay(let seconds)? = decision.action {
            let deadline = Date().addingTimeInterval(seconds)
            while Date() < deadline {
                if cancel.isCancelled {
                    plan.record(request, "cancelled")
                    throw .cancelled
                }
                Thread.sleep(forTimeInterval: 0.025)
            }
            plan.record(request, "delayed:\(seconds)")
        }
        guard budget.spend() else {
            plan.record(request, "budget")
            throw .connection
        }
        let response = try inner.send(request, cancel: cancel)
        if decision.action == .dropResponse {
            plan.record(request, "response-dropped:\(response.status)")
            throw .timeout
        }
        plan.record(request, "sent:\(response.status)", answer: response.status >= 400 ? response.body : nil)
        return response
    }
}

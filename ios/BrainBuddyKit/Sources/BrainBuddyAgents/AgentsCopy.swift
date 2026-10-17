/// Every string of design.md § Copy for the agent surfaces (030-FR-041) plus the web's connection
/// status words (030-FR-030), ported from `frontend/src/features/agents/agentCopy.ts`.
public enum AgentsCopy {
    public static let sidebar = "Agents", allRuns = "All runs", addNewAgent = "Add new agent"
    public static let allRunsSubtitle = "Every step you handed off, by what it needs from you."
    public static let allRunsEmpty = "Nothing handed off yet. Choose Hand off… on a step's card."
    public static let runsLoading = "Loading runs…", runsFailed = "Runs couldn't be loaded."
    public static let groups = ["Needs you", "Running", "Queued", "To review", "Lost contact"]
    public static let waitingAgents = "Agents", waitingPeople = "People"
    public static let queued = "Waiting for a free connection slot; nothing has been sent yet"
    public static let handOff = "Hand off…", handToAgent = "Hand to an agent", handOffAgain = "Hand off again"
    public static let handOffIntro = "It works on its own and comes back with a result. The step stays yours."
    public static let whatItWillGet = "What it will get", cancel = "Cancel", sending = "Sending…"
    public static let currentPassword = "Current password"
    public static let acknowledge = "I understand that a duplicate task is possible with this agent"
    public static let noReadyAgent = "No agent is ready to receive a hand-off.", openSettings = "Open Settings…"
    public static let stepNotSynced = "This step hasn't reached your account yet."
    public static let handOffOffline = "Handing off needs a connection."
    public static let handOffUnavailable = "Handing off isn't available right now."
    public static let guaranteed = "Guaranteed single start", bestEffort = "Best-effort single start"
    public static let yourAnswer = "Your answer", reply = "Reply", stopRun = "Stop run", checkAgain = "Check again"
    public static let replySent = "Reply sent. Waiting for the agent."
    public static let succession = "The agent continued this run in a new task", earlierRuns = "Earlier runs"
    public static let reportedComplete = "Agent reported complete", result = "Result", then = "Then"
    public static let resultTooLarge = "The result is too large to show here."
    public static let finishingIsYours = "The agent finishing does not finish your step. You decide."
    public static let makeNextStep = "Make the next step", markDone = "Mark step done"
    public static let stoppedReporting = "Stopped reporting", lostContact = "Lost contact"
    public static let expired = "Content expired under retention policy"
    public static let needsConnection = "Needs a connection."
    public static let testAgain = "Test again", testing = "Testing…", replaceCredentialAction = "Replace credential…"
    public static let edit = "Edit…", noAgents = "No agents yet.", addAgentEllipsis = "Add new agent…"
    public static let agentsFailed = "Agents couldn't be loaded.", readyForHandoff = "Ready to receive a hand-off."
    public static let addAgentHelper = "Its agent card is read from there when you test."
    public static let secretHelper = "Stored sealed. It is never shown again."
    public static let addAndTest = "Add and test", adding = "Adding…", replace = "Replace", save = "Save"
    public static let confirmDestination = "Confirm your password to change this agent's destination."
    public static let deleteNote = "Its credential is destroyed. Runs already sent keep their history."
    public static let noPassword = "Set a password to connect an agent.", openAccount = "Open account on the web…"
    public static let wrongPassword = "That password isn't right."
    public static let rateLimited = "Too many attempts. Try again in a few minutes."
    public static let staleRevision = "This agent changed elsewhere. Check and try again.", tryAgain = "Try again"

    public static func runCount(_ n: Int) -> String { n == 1 ? "1 run" : "\(n) runs" }
    public static func waitingHeader(people: Int, agents: Int) -> String {
        "\(people) \(people == 1 ? "person" : "people"), \(agents) \(agents == 1 ? "agent" : "agents")"
    }
    public static func note(_ details: String) -> String { "Note: \(details)" }
    public static func project(_ name: String) -> String { "Project: \(name)" }
    public static func send(to agent: String) -> String { "Send to \(agent)" }
    public static func asks(_ agent: String) -> String { "\(agent) asks" }
    public static func lastContact(_ time: String) -> String { "Last contact \(time)" }
    public static func stoppedAgo(_ time: String) -> String { "last contact \(time) ago" }
    public static func lastUpdated(_ time: String) -> String { "Last updated \(time). This may be out of date." }
    public static func replaceCredential(for name: String) -> String { "Replace credential for \(name)" }
    public static func delete(_ name: String) -> String { "Delete \(name)?" }
    public static func reference(_ id: String) -> String { "Reference: \(id)" }
    public static func cardVersion(_ version: String, protocol protocolVersion: String) -> String {
        "\(version) · protocol \(protocolVersion)"
    }
    public static func updates(streaming: Bool, push: Bool) -> String {
        "\(streaming ? "Streaming" : "No streaming") · \(push ? "push" : "no push")"
    }
    public static func credential(bearer: Bool, header: String?) -> String {
        bearer ? "Bearer token · stored sealed" : "API key\(header.map { " in \($0)" } ?? "") · stored sealed"
    }

    /// What the web reads off a connection to pick its status words.
    public struct Connection: Equatable, Sendable {
        public var status: String
        public var stale = false, agentChanged = false
        public var errorCode: String?, disconnectReason: String?, foundVersion: String?, scheme: String?
        public var staleAfterSeconds = 0

        public init(status: String, stale: Bool = false, agentChanged: Bool = false, errorCode: String? = nil,
                     disconnectReason: String? = nil, foundVersion: String? = nil, scheme: String? = nil,
                     staleAfterSeconds: Int = 0) {
            (self.status, self.stale, self.agentChanged, self.errorCode) = (status, stale, agentChanged, errorCode)
            (self.disconnectReason, self.foundVersion, self.scheme) = (disconnectReason, foundVersion, scheme)
            self.staleAfterSeconds = staleAfterSeconds
        }
    }

    /// `connectionStatusLabel` of the web, word for word.
    public static func statusLabel(_ c: Connection) -> String {
        if c.agentChanged { return "Agent changed" }
        if c.errorCode == "a2a_rate_limited" { return "Rate limited" }
        switch c.status {
        case "disconnected": return c.disconnectReason == "superseded_wire_contract" ? "Superseded wire contract" : "Disconnected"
        case "invalid_credentials": return "Invalid credentials"
        case "unreachable": return "Unreachable"
        case "unsupported": return "Unsupported"
        case "untested": return "Not tested"
        default: return c.stale ? "Stale" : "Tested ready"
        }
    }

    /// `connectionStatusDetail` of the web, sentence for sentence.
    public static func statusDetail(_ c: Connection) -> String {
        if c.agentChanged {
            return "This agent's card now advertises a different interface address or different authentication requirements than the one you tested. BrainBuddy will not send task content to a destination you have not tested. Test the connection again — you will be asked for your password, because a new destination is a new content-bearing send."
        }
        if c.errorCode == "a2a_rate_limited" {
            return "The agent is rate limiting. It answered the test by refusing it, so BrainBuddy learned nothing about the connection and nothing was sent."
        }
        switch c.status {
        case "disconnected":
            return c.disconnectReason == "superseded_wire_contract"
                ? "Superseded wire contract. This connection was made under BrainBuddy's previous agent wire, which no longer exists. Add the agent again by its address to use it."
                : "The stored credential and the agent-card summary BrainBuddy discovered were destroyed. New hand-offs and replies through this agent are blocked."
        case "invalid_credentials": return "The agent answered and rejected the credential. Rotate it below, then test again."
        case "unreachable": return "BrainBuddy could not reach this address before the test timeout. Nothing was sent."
        case "unsupported": return unsupported(c)
        case "untested": return "BrainBuddy has not contacted this agent yet. Test it before handing over a task."
        default:
            return c.stale
                ? "The last contact is older than the \(duration(c.staleAfterSeconds)) staleness threshold. Test it again before a hand-off."
                : "The last test reached this agent and it authenticated."
        }
    }

    private static func unsupported(_ c: Connection) -> String {
        switch c.errorCode {
        case "a2a_not_an_agent": return "There is no agent card at its well-known location. Check the address you entered, then test again."
        case "a2a_protocol_version_unsupported":
            return c.foundVersion.map { "The card declares A2A \($0). BrainBuddy speaks protocol version 1.0.x only." }
                ?? "The card declares a protocol version outside 1.0.x. BrainBuddy speaks protocol version 1.0.x only."
        case "a2a_auth_scheme_unsupported":
            return c.scheme.map { "This card requires \($0). BrainBuddy supports a bearer token or an API key named by the card, and nothing else." }
                ?? "This card requires an authentication scheme BrainBuddy does not support. BrainBuddy supports a bearer token or an API key named by the card."
        default: return "No JSON-RPC interface BrainBuddy can use over HTTPS."
        }
    }

    private static func duration(_ seconds: Int) -> String {
        func unit(_ n: Int, _ word: String) -> String { "\(n) \(word)\(n == 1 ? "" : "s")" }
        if seconds < 60 { return unit(seconds, "second") }
        return seconds < 3600 ? unit((seconds + 30) / 60, "minute") : unit((seconds + 1800) / 3600, "hour")
    }
}

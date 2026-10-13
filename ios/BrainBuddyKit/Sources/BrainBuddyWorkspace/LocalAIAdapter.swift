import BrainBuddyAPI
import BrainBuddyCore
import Foundation
#if canImport(NaturalLanguage)
import NaturalLanguage
#endif

// The Apple side of the shared AI capability policy (spec 026, T049; FR-018, FR-019). The decision
// itself, which executor may see the input and why none may, is `bb_domain::ai_policy::route`,
// reached through `RustBridgeRuntime.aiRoute`; nothing here decides policy. This file only
// states the facts the policy needs, forwards them, and runs the executor the policy chose.
// It adds no model engine: a platform supplies `LocalAIExecutor`s (the app targets, PR-59/60).

public enum AIPrivacyMode: String, Sendable, Equatable {
    /// Remote inference is prohibited, also as a fallback after a local error.
    case onDeviceOnly = "on_device_only"
    case remoteAllowed = "remote_allowed"
}

public enum LocalAISource: String, Sendable, Hashable {
    case appleOnDevice = "apple_on_device"
    case downloadedOnDevice = "downloaded_on_device"
}

public enum LocalAIRuntime: String, Sendable, Equatable {
    case ready
    case deviceNotEligible = "device_not_eligible"
    case systemFeatureOff = "system_feature_off"
    case modelNotReady = "model_not_ready"
    case notDownloaded = "not_downloaded"
    case disabled
}

public enum LocalAIUnavailableReason: String, Sendable, Equatable {
    case deviceNotEligible = "device_not_eligible"
    case systemFeatureOff = "system_feature_off"
    case modelNotReady = "model_not_ready"
    case notDownloaded = "not_downloaded"
    case disabled
    case unsupportedLanguage = "unsupported_language"
    case insufficientMemory = "insufficient_memory"
    case failedThisRequest = "failed_this_request"
}

/// What one local executor can run now, as its adapter reports it.
public struct LocalAIFacts: Sendable, Equatable {
    public var source: LocalAISource
    public var runtime: LocalAIRuntime
    /// BCP-47 tags; only the primary subtag is compared.
    public var supportedLanguages: [String]
    public var freeMemoryMB: UInt64
    public var requiredMemoryMB: UInt64

    public init(source: LocalAISource, runtime: LocalAIRuntime, supportedLanguages: [String],
                freeMemoryMB: UInt64, requiredMemoryMB: UInt64) {
        self.source = source
        self.runtime = runtime
        self.supportedLanguages = supportedLanguages
        self.freeMemoryMB = freeMemoryMB
        self.requiredMemoryMB = requiredMemoryMB
    }
}

/// The limits the adapter keeps whichever executor runs.
public struct AITerms: Sendable, Equatable {
    public var timeoutMS: UInt32
    public var maxInputTokens: UInt32
    public var maxOutputTokens: UInt32

    public init(timeoutMS: UInt32, maxInputTokens: UInt32, maxOutputTokens: UInt32) {
        self.timeoutMS = timeoutMS
        self.maxInputTokens = maxInputTokens
        self.maxOutputTokens = maxOutputTokens
    }

    public static let navigator = AITerms(timeoutMS: 20_000, maxInputTokens: 4_000, maxOutputTokens: 400)
}

public enum SuggestionKind: String, Sendable, Equatable {
    case firstStep = "first_step"
    case reformulate
    case projectNextAction = "project_next_action"
}

/// FR-019: the only data any model receives (no identifiers, dates or language).
public struct SuggestionInput: Sendable, Equatable {
    public var kind: SuggestionKind
    public var taskTitle: String?
    public var taskNotes: String?
    public var stallReason: String?
    public var projectName: String?
    /// At most 20 other open task titles of the project: the only titles a model receives.
    public var openTaskTitles: [String]
    /// Every other open task title of the project the client holds; only rule 5 compares against it.
    public var allOpenTaskTitles: [String]

    public init(kind: SuggestionKind, taskTitle: String?, taskNotes: String? = nil, stallReason: String? = nil,
                projectName: String? = nil, openTaskTitles: [String] = [], allOpenTaskTitles: [String]? = nil) {
        self.kind = kind
        self.taskTitle = taskTitle
        self.taskNotes = taskNotes
        self.stallReason = stallReason
        self.projectName = projectName
        self.openTaskTitles = Array(openTaskTitles.prefix(20))
        self.allOpenTaskTitles = allOpenTaskTitles ?? openTaskTitles
    }

    /// A rough size for the policy's input guard (about four characters a token).
    public var estimatedTokens: UInt32 {
        let characters = [taskTitle, taskNotes, stallReason, projectName].compactMap { $0 }.reduce(0) { $0 + $1.count }
            + openTaskTitles.reduce(0) { $0 + $1.count }
        return UInt32(min(characters / 4 + 1, Int(UInt32.max)))
    }
}

/// A model's raw answer, before the shared validation.
public struct ModelAnswer: Sendable, Equatable {
    public var proposals: [String]
    public var clarifyingQuestion: String?
    public init(proposals: [String], clarifyingQuestion: String? = nil) {
        self.proposals = proposals
        self.clarifyingQuestion = clarifyingQuestion
    }
}

/// One on-device executor. The platform implements it (Foundation Models on Apple platforms);
/// the package tests use fakes and never a real model.
public protocol LocalAIExecutor: Sendable {
    var source: LocalAISource { get }
    func facts() async -> LocalAIFacts
    func suggest(_ input: SuggestionInput, terms: AITerms) async throws -> ModelAnswer
}

/// The existing navigator endpoints (spec 020 `/review/navigator…`).
public protocol NavigatorRemote: Sendable {
    func status() async throws -> NavigatorStatusDTO
    func suggest(_ body: NavigatorSuggestionBody) async throws -> NavigatorSuggestionResponseDTO
}

extension BrainBuddyAPIClient: NavigatorRemote {
    public func status() async throws -> NavigatorStatusDTO { try await navigatorStatus() }
    public func suggest(_ body: NavigatorSuggestionBody) async throws -> NavigatorSuggestionResponseDTO {
        try await navigatorSuggestions(body)
    }
}

/// The shared policy as the bridge exposes it.
public protocol AIPolicyEngine: Sendable {
    func aiRoute(_ request: Data) async throws -> Data
    func aiValidateAnswer(_ answer: Data) async throws -> Data
    func aiReduceNotes(_ notes: Data) async throws -> Data
}

extension RustBridgeRuntime: AIPolicyEngine {}

public enum AIConsentState: String, Sendable, Equatable {
    case current, missing, revoked
    case textOutdated = "text_outdated"
}

/// One owner's stored consent for one provider (the local review state's ledger).
public struct OwnerConsentFact: Sendable, Equatable {
    public var owner: String
    public var provider: String
    public var grantedAt: Date
    public var revokedAt: Date?
    public var consentTextVersion: Int

    public init(owner: String, provider: String, grantedAt: Date, revokedAt: Date? = nil, consentTextVersion: Int) {
        self.owner = owner
        self.provider = provider
        self.grantedAt = grantedAt
        self.revokedAt = revokedAt
        self.consentTextVersion = consentTextVersion
    }
}

public struct RemoteFacts: Sendable, Equatable {
    /// The configured provider category; nil when remote AI is switched off.
    public var provider: String?
    public var credentialsConfigured: Bool
    public var consentTextVersion: Int
    /// The consent the request itself will echo (`external_processing_allowed`, provider).
    public var echoedConsent: (allowed: Bool, provider: String)?
    public var consents: [OwnerConsentFact]

    public init(provider: String?, credentialsConfigured: Bool, consentTextVersion: Int,
                echoedConsent: (allowed: Bool, provider: String)?, consents: [OwnerConsentFact]) {
        self.provider = provider
        self.credentialsConfigured = credentialsConfigured
        self.consentTextVersion = consentTextVersion
        self.echoedConsent = echoedConsent
        self.consents = consents
    }

    public static func == (lhs: RemoteFacts, rhs: RemoteFacts) -> Bool {
        lhs.provider == rhs.provider && lhs.credentialsConfigured == rhs.credentialsConfigured
            && lhs.consentTextVersion == rhs.consentTextVersion && lhs.consents == rhs.consents
            && lhs.echoedConsent?.allowed == rhs.echoedConsent?.allowed
            && lhs.echoedConsent?.provider == rhs.echoedConsent?.provider
    }
}

public struct LocalAIUnavailability: Sendable, Equatable {
    public var source: LocalAISource
    public var reason: LocalAIUnavailableReason
}

public enum AIDenial: Sendable, Equatable {
    case cancelled
    /// On-device only (or no remote choice) and no local executor is suitable.
    case localUnavailable([LocalAIUnavailability])
    case remoteDisabled
    case credentialsMissing
    case providerMismatch
    case consentRequired(AIConsentState)
    case inputTooLarge
}

public enum AIRoute: Sendable, Equatable {
    case deterministic
    case local(LocalAISource, AITerms)
    case remote(provider: String, consentTextVersion: Int, terms: AITerms)
    case denied(AIDenial)
}

/// The shared validation of a model answer (navigator contract rules 1-5).
public enum ValidatedAnswer: Sendable, Equatable {
    case proposals([String])
    case question(String)
    /// Rules 1-4 left nothing usable.
    case malformed
    /// Rule 5 left no proposal.
    case noUsefulSuggestion
}

public struct LocalAIAdapter: Sendable {
    public let policy: any AIPolicyEngine
    public let executors: [any LocalAIExecutor]
    public let terms: AITerms
    private let detectLanguage: @Sendable (String) -> String?

    public init(policy: any AIPolicyEngine, executors: [any LocalAIExecutor] = [], terms: AITerms = .navigator,
                detectLanguage: @escaping @Sendable (String) -> String? = LocalAIAdapter.dominantLanguage) {
        self.policy = policy
        self.executors = executors
        self.terms = terms
        self.detectLanguage = detectLanguage
    }

    /// The dominant language of `text`, where the platform can tell; nil makes a local executor
    /// unsupported (the policy never guesses a language).
    public static let dominantLanguage: @Sendable (String) -> String? = { text in
        #if canImport(NaturalLanguage)
        let recognizer = NLLanguageRecognizer()
        recognizer.processString(text)
        return recognizer.dominantLanguage?.rawValue
        #else
        return nil
        #endif
    }

    /// Which executor may see `input`, or why none may. Runs no model and sends nothing.
    public func route(
        input: SuggestionInput, owner: String, privacy: AIPrivacyMode, cancelled: Bool = false,
        failedLocal: [LocalAISource] = [], remote: RemoteFacts?
    ) async throws -> AIRoute {
        var facts: [LocalAIFacts] = []
        for executor in executors { facts.append(await executor.facts()) }
        let text = [input.taskTitle, input.taskNotes].compactMap { $0 }.joined(separator: "\n")
        let request: [String: Any] = [
            "owner": owner,
            "language": detectLanguage(text) as Any? ?? NSNull(),
            "privacy": privacy.rawValue,
            "deterministic_sufficient": false,
            "cancelled": cancelled,
            "local": facts.map { fact -> [String: Any] in
                ["source": fact.source.rawValue, "runtime": fact.runtime.rawValue,
                 "supported_languages": fact.supportedLanguages, "free_memory_mb": fact.freeMemoryMB,
                 "required_memory_mb": fact.requiredMemoryMB]
            },
            "failed_local": failedLocal.map(\.rawValue),
            "remote": remote.map(Self.remoteJSON) as Any? ?? NSNull(),
            "estimated_input_tokens": input.estimatedTokens,
            "terms": Self.termsJSON(terms),
        ]
        let answer = try await policy.aiRoute(JSONSerialization.data(withJSONObject: request, options: [.sortedKeys]))
        return try Self.decodeRoute(answer)
    }

    /// Runs the executor the policy chose. A cancelled caller gets `CancellationError` and nothing
    /// from the executor is used.
    public func runLocal(_ source: LocalAISource, input: SuggestionInput, terms: AITerms) async throws -> ModelAnswer {
        guard let executor = executors.first(where: { $0.source == source }) else {
            throw LocalAIError.executorMissing
        }
        let answer = try await executor.suggest(input, terms: terms)
        try Task.checkCancellation()
        return answer
    }

    /// The input with its notes reduced by the shared rule (at most 6 003 scalars), and whether lines
    /// were dropped. Applied before routing, so the estimate, a local model and the cloud body agree.
    public func reducingNotes(_ input: SuggestionInput) async throws -> (input: SuggestionInput, truncated: Bool) {
        guard let notes = input.taskNotes, !notes.isEmpty else { return (input, false) }
        let data = try await policy.aiReduceNotes(JSONSerialization.data(withJSONObject: ["notes": notes]))
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let reduced = object["notes"] as? String, let truncated = object["truncated"] as? Bool else {
            throw LocalAIError.malformedPolicyAnswer
        }
        var result = input
        result.taskNotes = reduced
        return (result, truncated)
    }

    /// Rules 1-5 of the navigator contract. Rule 5 compares against every open title the client holds
    /// (`allOpenTaskTitles`), not only the bounded list the model saw; `projectOpenTitles` overrides it.
    public func validate(_ answer: ModelAnswer, for input: SuggestionInput, projectOpenTitles: [String]? = nil)
        async throws -> ValidatedAnswer {
        let request: [String: Any] = [
            "kind": input.kind.rawValue,
            "task_title": input.taskTitle as Any? ?? NSNull(),
            "task_notes": input.taskNotes as Any? ?? NSNull(),
            "stall_reason": input.stallReason as Any? ?? NSNull(),
            "project_name": input.projectName as Any? ?? NSNull(),
            "open_task_titles": input.openTaskTitles,
            "project_open_titles": projectOpenTitles ?? input.allOpenTaskTitles,
            "proposals": answer.proposals,
            "clarifying_question": answer.clarifyingQuestion as Any? ?? NSNull(),
        ]
        let data = try await policy.aiValidateAnswer(JSONSerialization.data(withJSONObject: request, options: [.sortedKeys]))
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let outcome = object["outcome"] as? String else { throw LocalAIError.malformedPolicyAnswer }
        switch outcome {
        case "proposals":
            guard let proposals = object["proposals"] as? [String] else { throw LocalAIError.malformedPolicyAnswer }
            return .proposals(proposals)
        case "question":
            guard let question = object["question"] as? String else { throw LocalAIError.malformedPolicyAnswer }
            return .question(question)
        case "malformed": return .malformed
        case "no_useful_suggestion": return .noUsefulSuggestion
        default: throw LocalAIError.malformedPolicyAnswer
        }
    }

    // MARK: JSON

    private static func termsJSON(_ terms: AITerms) -> [String: Any] {
        ["timeout_ms": terms.timeoutMS, "max_input_tokens": terms.maxInputTokens, "max_output_tokens": terms.maxOutputTokens]
    }

    private static func instant(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: date)
    }

    private static func remoteJSON(_ remote: RemoteFacts) -> [String: Any] {
        [
            "provider": remote.provider as Any? ?? NSNull(),
            "credentials_configured": remote.credentialsConfigured,
            "consent_text_version": remote.consentTextVersion,
            "echoed_consent": remote.echoedConsent.map {
                ["external_processing_allowed": $0.allowed, "provider": $0.provider] as [String: Any]
            } as Any? ?? NSNull(),
            "consents": remote.consents.map { entry -> [String: Any] in
                ["owner": entry.owner, "consent": [
                    "provider": entry.provider,
                    "consent": ["granted_at": instant(entry.grantedAt),
                                "revoked_at": entry.revokedAt.map(instant) as Any? ?? NSNull(),
                                "consent_text_version": entry.consentTextVersion] as [String: Any],
                ] as [String: Any]]
            },
        ]
    }

    private static func decodeRoute(_ data: Data) throws -> AIRoute {
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let route = object["route"] as? String else { throw LocalAIError.malformedPolicyAnswer }
        func terms() throws -> AITerms {
            guard let t = object["terms"] as? [String: Any], let timeout = t["timeout_ms"] as? UInt32,
                  let input = t["max_input_tokens"] as? UInt32, let output = t["max_output_tokens"] as? UInt32 else {
                throw LocalAIError.malformedPolicyAnswer
            }
            return AITerms(timeoutMS: timeout, maxInputTokens: input, maxOutputTokens: output)
        }
        switch route {
        case "deterministic": return .deterministic
        case "local":
            guard let name = object["source"] as? String, let source = LocalAISource(rawValue: name) else {
                throw LocalAIError.malformedPolicyAnswer
            }
            return .local(source, try terms())
        case "remote":
            guard let provider = object["provider"] as? String,
                  let version = object["consent_text_version"] as? Int else { throw LocalAIError.malformedPolicyAnswer }
            return .remote(provider: provider, consentTextVersion: version, terms: try terms())
        case "denied":
            guard let denial = object["denial"] as? [String: Any], let kind = denial["kind"] as? String else {
                throw LocalAIError.malformedPolicyAnswer
            }
            return .denied(try decodeDenial(kind: kind, detail: denial["detail"]))
        default: throw LocalAIError.malformedPolicyAnswer
        }
    }

    private static func decodeDenial(kind: String, detail: Any?) throws -> AIDenial {
        switch kind {
        case "cancelled": return .cancelled
        case "remote_disabled": return .remoteDisabled
        case "credentials_missing": return .credentialsMissing
        case "provider_mismatch": return .providerMismatch
        case "input_too_large": return .inputTooLarge
        case "consent_required":
            guard let name = detail as? String, let state = AIConsentState(rawValue: name) else {
                throw LocalAIError.malformedPolicyAnswer
            }
            return .consentRequired(state)
        case "local_unavailable":
            let entries = (detail as? [[String: Any]]) ?? []
            return .localUnavailable(try entries.map { entry in
                guard let source = (entry["source"] as? String).flatMap(LocalAISource.init(rawValue:)),
                      let reason = (entry["reason"] as? String).flatMap(LocalAIUnavailableReason.init(rawValue:)) else {
                    throw LocalAIError.malformedPolicyAnswer
                }
                return LocalAIUnavailability(source: source, reason: reason)
            })
        default: throw LocalAIError.malformedPolicyAnswer
        }
    }
}

/// Content-free adapter failures.
public enum LocalAIError: Error, Equatable, Sendable {
    case executorMissing
    case malformedPolicyAnswer
    /// The executor could not answer this request (an engine error or a timeout).
    case executorFailed
}

import Foundation

public struct SessionUser: Codable, Equatable, Sendable {
    public let id: String
    public let email: String
    public let featureFlags: [String: Bool]

    enum CodingKeys: String, CodingKey {
        case id, email
        case featureFlags = "feature_flags"
    }
}

public struct ResearchSource: Codable, Equatable, Sendable {
    public let title: String
    public let url: URL
    public let observedAt: Date?

    public init(title: String, url: URL, observedAt: Date?) {
        self.title = title
        self.url = url
        self.observedAt = observedAt
    }
}

public struct LocalServiceOption: Codable, Equatable, Identifiable, Sendable {
    public let id: String
    public let name: String
    public let summary: String
    public let uncertainty: String
    public let sources: [ResearchSource]

    public init(id: String, name: String, summary: String, uncertainty: String, sources: [ResearchSource]) {
        self.id = id
        self.name = name
        self.summary = summary
        self.uncertainty = uncertainty
        self.sources = sources
    }
}

public struct LocalServiceResearch: Codable, Equatable, Sendable {
    public let query: String
    public let generatedAt: Date
    public let options: [LocalServiceOption]

    public init(query: String, generatedAt: Date, options: [LocalServiceOption]) throws {
        guard options.count == 3 else { throw ValidationError.requiresExactlyThreeOptions }
        guard options.allSatisfy({ !$0.uncertainty.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }) else {
            throw ValidationError.missingUncertainty
        }
        guard options.allSatisfy({ !$0.sources.isEmpty }) else { throw ValidationError.missingSource }
        self.query = query
        self.generatedAt = generatedAt
        self.options = options
    }

    public enum ValidationError: Error, Equatable {
        case requiresExactlyThreeOptions
        case missingUncertainty
        case missingSource
    }
}

public enum PilotBoundary {
    public static let notice = "Research only. BrainBuddy cannot contact providers, book appointments, make purchases, or complete this task for you. Verify availability, pricing, and fit directly."
}

import Foundation

/// `GET /account` (`AccountResponse`): the fields the Mac Settings window shows (spec 028).
/// Other fields of the response are ignored. Description is redacted: it holds personal data.
public struct AccountSummaryDTO: Decodable, Hashable, Sendable, CustomStringConvertible {
    public let id: String
    public let email: String
    public let displayName: String?
    public let completedTaskCount: Int
    public var description: String { "Account summary (redacted)" }

    public init(id: String, email: String, displayName: String?, completedTaskCount: Int) {
        self.id = id
        self.email = email
        self.displayName = displayName
        self.completedTaskCount = completedTaskCount
    }

    enum CodingKeys: String, CodingKey {
        case id, email
        case displayName = "display_name"
        case completedTaskCount = "completed_task_count"
    }
}

extension BrainBuddyAPIClient {
    /// The signed-in account's own summary.
    public func accountSummary() async throws(APIError) -> AccountSummaryDTO {
        try await get(["account"])
    }
}

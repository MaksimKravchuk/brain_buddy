import Foundation

/// A client-side identifier. It is minted on the device, never changes, and is
/// what the UI, commands and the outbox refer to. The server's own id (for
/// example `task_1a2b3c4d5e6f`) is stored separately as `serverID` because the
/// API mints ids itself and rejects client-supplied ones.
public struct EntityID<Kind>: Hashable, Comparable, Sendable, Codable, CodingKeyRepresentable,
    CustomStringConvertible, ExpressibleByStringLiteral
{
    public let rawValue: String

    public init(_ rawValue: String) { self.rawValue = rawValue }
    public init(stringLiteral value: String) { self.rawValue = value }

    /// A fresh random id (lowercased UUID).
    public static func random() -> EntityID { EntityID(UUID().uuidString.lowercased()) }

    public var description: String { rawValue }
    public static func < (lhs: EntityID, rhs: EntityID) -> Bool { lhs.rawValue < rhs.rawValue }

    public init(from decoder: Decoder) throws {
        rawValue = try decoder.singleValueContainer().decode(String.self)
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(rawValue)
    }

    public var codingKey: CodingKey { AnyCodingKey(rawValue) }
    public init?<T: CodingKey>(codingKey: T) { self.rawValue = codingKey.stringValue }
}

public enum TaskKind {}
public enum SubtaskKind {}
public enum CommentKind {}
public enum ProjectKind {}
public enum TagKind {}

public typealias TaskID = EntityID<TaskKind>
public typealias SubtaskID = EntityID<SubtaskKind>
public typealias CommentID = EntityID<CommentKind>
public typealias ProjectID = EntityID<ProjectKind>
public typealias TagID = EntityID<TagKind>

struct AnyCodingKey: CodingKey {
    let stringValue: String
    let intValue: Int? = nil
    init(_ string: String) { stringValue = string }
    init?(stringValue: String) { self.stringValue = stringValue }
    init?(intValue: Int) { return nil }
}

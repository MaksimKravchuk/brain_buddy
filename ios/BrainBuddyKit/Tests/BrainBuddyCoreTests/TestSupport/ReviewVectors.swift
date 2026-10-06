import BrainBuddyCore
import Foundation
import Testing

/// A JSON value from the shared review vector files (spec 020). The files are
/// byte-identical copies of `backend/tests/fixtures/*.json`, declared as
/// resources of this test target in `Package.swift`.
enum VectorValue: Hashable, Sendable, Decodable, CustomStringConvertible {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([VectorValue])
    case object([String: VectorValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([VectorValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: VectorValue].self))
        }
    }

    subscript(key: String) -> VectorValue? {
        if case .object(let members) = self { return members[key] }
        return nil
    }

    var isNull: Bool { self == .null }
    var string: String? { if case .string(let value) = self { value } else { nil } }
    var int: Int? { if case .number(let value) = self { Int(exactly: value) } else { nil } }
    var double: Double? { if case .number(let value) = self { value } else { nil } }
    var bool: Bool? { if case .bool(let value) = self { value } else { nil } }
    var array: [VectorValue] { if case .array(let items) = self { items } else { [] } }
    var object: [String: VectorValue] { if case .object(let members) = self { members } else { [:] } }
    var keys: Set<String> { Set(object.keys) }

    var description: String {
        switch self {
        case .null: "null"
        case .bool(let value): String(value)
        case .number(let value): String(value)
        case .string(let value): "\"\(value)\""
        case .array(let items): "[" + items.map(\.description).joined(separator: ", ") + "]"
        case .object(let members):
            "{" + members.keys.sorted().map { "\"\($0)\": \(members[$0]!.description)" }.joined(separator: ", ") + "}"
        }
    }
}

/// One named entry of a vector section, so a failing case names its id.
struct Vector: Sendable, CustomTestStringConvertible {
    var id: String
    var value: VectorValue

    subscript(key: String) -> VectorValue? { value[key] }

    var testDescription: String { id }
}

enum ReviewVectors {
    static let formulation = load("review_formulation_vectors")
    static let flow = load("review_flow_vectors")

    static func load(_ name: String) -> VectorValue {
        guard let url = Bundle.module.url(forResource: name, withExtension: "json", subdirectory: "Resources"),
            let data = try? Data(contentsOf: url),
            let value = try? JSONDecoder().decode(VectorValue.self, from: data)
        else { fatalError("Missing or unreadable test resource Resources/\(name).json") }
        return value
    }

    static func section(_ file: VectorValue, _ name: String) -> [Vector] {
        file[name]?.array.map { Vector(id: $0["id"]?.string ?? "?", value: $0) } ?? []
    }

    /// `2026-09-24T09:14:00Z` → `Date` (the vectors only use whole-second UTC instants).
    static func instant(_ value: VectorValue?) -> Date? {
        guard let text = value?.string else { return nil }
        guard let date = try? Date(text, strategy: .iso8601) else {
            Issue.record("Not an ISO-8601 instant: \(text)")
            return nil
        }
        return date
    }

    static func iso(_ date: Date?) -> VectorValue {
        guard let date else { return .null }
        return .string(date.formatted(Date.ISO8601FormatStyle()))
    }

    static func day(_ value: VectorValue?) -> CalendarDay? {
        value?.string.flatMap(CalendarDay.init(isoString:))
    }
}

import BrainBuddyAPI
import BrainBuddyCore
import Foundation

/// A JSON request body checked the way the backend's pydantic request models
/// check it: `extra="forbid"`, lax types (an integral float is an int),
/// lengths in Unicode scalars (Python's `len`), and "set" meaning "the key
/// was present", even with `null`.
struct RequestBody: Sendable {
    let fields: [String: JSONValue]

    init(_ data: Data?, allowing keys: Set<String>) throws(FakeHTTPError) {
        guard let data, !data.isEmpty else { throw .validation(["body"], "Field required", type: "missing") }
        guard let value = try? JSONDecoder().decode(JSONValue.self, from: data), case .object(let fields) = value else {
            throw .validation(["body"], "Input should be a valid dictionary", type: "model_attributes_type")
        }
        if let extra = fields.keys.sorted().first(where: { !keys.contains($0) }) {
            throw .validation(["body", extra], "Extra inputs are not permitted", type: "extra_forbidden")
        }
        self.fields = fields
    }

    init(fields: [String: JSONValue]) { self.fields = fields }

    /// `model_fields_set`: the keys the client sent.
    func has(_ key: String) -> Bool { fields[key] != nil }

    /// The idempotency fingerprint: command plus the canonical body (sorted
    /// keys), so the same fields in another order match and an omitted key
    /// differs from an explicit default, as in `request_fingerprint`.
    func fingerprint(command: String) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        let body = (try? encoder.encode(JSONValue.object(fields))).map { String(decoding: $0, as: UTF8.self) } ?? ""
        return command + "\n" + body
    }

    // MARK: - Typed fields

    /// A string field: nil when absent or `null` (unless `required`).
    func string(_ key: String, required: Bool = false, nullable: Bool = true, min: Int = 0, max: Int? = nil)
        throws(FakeHTTPError) -> String?
    {
        switch fields[key] {
        case nil:
            if required { throw .validation(["body", key], "Field required", type: "missing") }
            return nil
        case .null?:
            if required || !nullable { throw .validation(["body", key], "Input should be a valid string", type: "string_type") }
            return nil
        case .string(let value)?:
            let length = value.unicodeScalars.count
            if length < min {
                throw .validation(["body", key], "String should have at least \(min) character", type: "string_too_short")
            }
            if let max, length > max {
                throw .validation(["body", key], "String should have at most \(max) characters", type: "string_too_long")
            }
            return value
        default:
            throw .validation(["body", key], "Input should be a valid string", type: "string_type")
        }
    }

    func int(_ key: String, minimum: Int) throws(FakeHTTPError) -> Int {
        guard let raw = fields[key] else { throw .validation(["body", key], "Field required", type: "missing") }
        guard case .number(let number) = raw, number.rounded() == number, abs(number) < 1e15 else {
            throw .validation(["body", key], "Input should be a valid integer", type: "int_type")
        }
        let value = Int(number)
        guard value >= minimum else {
            throw .validation(["body", key], "Input should be greater than or equal to \(minimum)", type: "greater_than_equal")
        }
        return value
    }

    /// A `Literal[...]` field.
    func value<T: RawRepresentable>(_ key: String, as type: T.Type, allowed: Set<String>? = nil)
        throws(FakeHTTPError) -> T? where T.RawValue == String
    {
        guard let raw = try string(key) else { return nil }
        guard let value = T(rawValue: raw), allowed?.contains(raw) ?? true else {
            throw .validation(["body", key], "Input should be one of the allowed values", type: "literal_error")
        }
        return value
    }

    func stringList(_ key: String) throws(FakeHTTPError) -> [String]? {
        switch fields[key] {
        case nil, .null?:
            return nil
        case .array(let items)?:
            var values: [String] = []
            for item in items {
                guard case .string(let value) = item else {
                    throw .validation(["body", key], "Input should be a valid string", type: "string_type")
                }
                values.append(value)
            }
            return values
        default:
            throw .validation(["body", key], "Input should be a valid list", type: "list_type")
        }
    }

    func day(_ key: String) throws(FakeHTTPError) -> CalendarDay? {
        guard let raw = try string(key) else { return nil }
        guard let day = CalendarDay(isoString: raw) else {
            throw .validation(["body", key], "Input should be a valid date", type: "date_from_datetime_parsing")
        }
        return day
    }
}

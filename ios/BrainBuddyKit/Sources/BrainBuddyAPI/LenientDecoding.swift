import Foundation

// Response-side tolerance for the weekly review's codes (spec 020): a newer
// server may send a step, entry, origin, counter or receipt kind this build
// does not know. One unknown value must not make a whole response, such as
// `GET /review/state`, unreadable: unknown optional codes read as nil,
// unknown map keys and list entries are dropped, and the caller picks a
// fallback where a field is required. Request bodies stay strict.

/// A list entry that is dropped when it cannot be read.
struct Lossy<Value: Decodable>: Decodable {
    let value: Value?

    init(from decoder: Decoder) throws {
        value = try? Value(from: decoder)
    }
}

extension KeyedDecodingContainer {
    /// A code, or nil when absent, null or unknown to this build.
    func decodeCode<Code: RawRepresentable & Decodable>(_ type: Code.Type, forKey key: Key) throws -> Code?
    where Code.RawValue == String {
        guard let raw = try decodeIfPresent(String.self, forKey: key) else { return nil }
        return Code(rawValue: raw)
    }

    /// A map keyed by codes, without entries whose key or value is unknown.
    func decodeCodeMap<Code: RawRepresentable & Hashable, Value: Decodable>(
        _ key: Key, keyedBy codeType: Code.Type, values valueType: Value.Type
    ) throws -> [Code: Value] where Code.RawValue == String {
        let raw = try decodeIfPresent([String: Lossy<Value>].self, forKey: key) ?? [:]
        var map: [Code: Value] = [:]
        for (name, entry) in raw {
            guard let code = Code(rawValue: name), let value = entry.value else { continue }
            map[code] = value
        }
        return map
    }

    /// A list without the entries this build cannot read.
    func decodeLossyList<Value: Decodable>(_ type: Value.Type, forKey key: Key) throws -> [Value] {
        (try decodeIfPresent([Lossy<Value>].self, forKey: key) ?? []).compactMap(\.value)
    }

    /// A nested object, or nil when it cannot be read.
    func decodeLossy<Value: Decodable>(_ type: Value.Type, forKey key: Key) -> Value? {
        (try? decodeIfPresent(Lossy<Value>.self, forKey: key))??.value
    }
}

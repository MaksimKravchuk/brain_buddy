import BrainBuddyCore
import Foundation

/// The one JSON format for the stored `StoreDocument`, shared by every store
/// and both directions: sorted keys (so the bytes are deterministic) and
/// ISO-8601 UTC timestamps with microseconds (`2026-09-29T08:15:30.123456Z`).
///
/// A `Date` is rounded to the nearest microsecond when it is first written;
/// from then on it round-trips exactly. `FileDocumentStore.update` returns
/// the document as decoded from the bytes it wrote, so what a caller holds is
/// what the next `load` returns.
public enum StoreDocumentCoding {
    /// Shared instances. They are configured here once and never mutated, and
    /// `JSONEncoder` / `JSONDecoder` are safe to use from several threads.
    static let encoder = makeEncoder()
    static let decoder = makeDecoder()

    /// A new encoder with the store's settings, for callers that need the
    /// same format elsewhere (for example an export).
    public static func makeEncoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        encoder.dateEncodingStrategy = .custom { date, encoder in
            guard let text = ISO8601Timestamp.string(from: date) else {
                throw EncodingError.invalidValue(
                    date,
                    EncodingError.Context(
                        codingPath: encoder.codingPath,
                        debugDescription: "Dates must fall between the years 0 and 9999."
                    )
                )
            }
            var container = encoder.singleValueContainer()
            try container.encode(text)
        }
        return encoder
    }

    /// A new decoder that reads what `makeEncoder()` writes. It also accepts
    /// fewer or more fractional digits and a numeric UTC offset.
    public static func makeDecoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let text = try container.decode(String.self)
            guard let date = ISO8601Timestamp.date(from: text) else {
                throw DecodingError.dataCorruptedError(
                    in: container, debugDescription: "Expected an ISO-8601 timestamp, got \"\(text)\"."
                )
            }
            return date
        }
        return decoder
    }

    public static func encode(_ document: StoreDocument) throws(DocumentStoreError) -> Data {
        do {
            return try encoder.encode(document)
        } catch {
            throw .io("the document could not be encoded: \(describe(error))")
        }
    }

    /// Decodes stored bytes: checks the version, migrates an older document
    /// forward, then decodes it. Throws `.unsupportedVersion` for a newer
    /// document and `.unreadable` for anything else that cannot be decoded.
    public static func decode(_ data: Data) throws(DocumentStoreError) -> StoreDocument {
        let version = try storedVersion(of: data)
        let current = try migrate(data, fromVersion: version)
        let document: StoreDocument
        do {
            document = try decoder.decode(StoreDocument.self, from: current)
        } catch {
            throw .unreadable(describe(error))
        }
        guard document.version == StoreDocument.currentVersion else {
            throw .unreadable("migration from version \(version) produced version \(document.version)")
        }
        return document
    }

    /// The generation of a stored document without decoding the rest of it.
    public static func generation(of data: Data) throws(DocumentStoreError) -> Int {
        try checkSupported(storedVersion(of: data))
        do {
            return try decoder.decode(GenerationHeader.self, from: data).generation
        } catch {
            throw .unreadable(describe(error))
        }
    }

    /// The `account` of stored bytes, decoded on its own and whatever the
    /// version, so it is also found in a document that cannot be decoded as a
    /// whole. Nil when there is none or not even it can be read.
    public static func linkedAccount(in data: Data) -> LinkedAccount? {
        (try? decoder.decode(AccountHeader.self, from: data))?.account
    }

    /// Brings a document written by an older app version forward to
    /// `StoreDocument.currentVersion`. Each step rewrites the raw JSON of one
    /// version into the next (and sets its `version`), so no step needs the
    /// old Swift types. Version 1 is the first format, so there are no steps
    /// yet and a version-1 document passes through unchanged.
    public static func migrate(_ data: Data, fromVersion version: Int) throws(DocumentStoreError) -> Data {
        try checkSupported(version)
        var data = data
        var version = version
        while version < StoreDocument.currentVersion {
            data = try migrationStep(from: version, data)
            version += 1
        }
        return data
    }

    /// One format change. Add a case when `StoreDocument.currentVersion`
    /// goes up, for example `case 1: return try rewrite(data) { … }`.
    static func migrationStep(from version: Int, _ data: Data) throws(DocumentStoreError) -> Data {
        switch version {
        default: throw .unreadable("no migration from document version \(version)")
        }
    }

    /// The read-modify-write step both stores share: applies `transform` to
    /// `current` (or a fresh document), stamps the version and the next
    /// generation, and returns the bytes to write together with the document
    /// as a reader will decode it. Nothing is written here; if `transform`
    /// throws, its error propagates unchanged.
    static func prepareWrite(
        from current: StoreDocument?, _ transform: (inout StoreDocument) throws -> Void
    ) throws -> (data: Data, document: StoreDocument) {
        var document = current ?? StoreDocument()
        let generation = document.generation
        try transform(&document)
        // The store owns these two fields, whatever the transform did.
        document.version = StoreDocument.currentVersion
        document.generation = generation + 1
        let data = try encode(document)
        // Never write bytes this app could not read back.
        let written = try decode(data)
        return (data, written)
    }

    private struct VersionHeader: Decodable {
        var version: Int
    }

    private struct GenerationHeader: Decodable {
        var generation: Int
    }

    private struct AccountHeader: Decodable {
        var account: LinkedAccount?
    }

    /// Versions start at 1; anything newer than this build is unsupported.
    private static func checkSupported(_ version: Int) throws(DocumentStoreError) {
        guard version >= 1 else { throw .unreadable("unknown document version \(version)") }
        guard version <= StoreDocument.currentVersion else { throw .unsupportedVersion(version) }
    }

    private static func storedVersion(of data: Data) throws(DocumentStoreError) -> Int {
        do {
            return try decoder.decode(VersionHeader.self, from: data).version
        } catch {
            throw .unreadable(describe(error))
        }
    }

    /// A short, technical description of a coding error.
    static func describe(_ error: any Error) -> String {
        func location(_ path: [any CodingKey]) -> String {
            path.isEmpty ? "" : " at \(path.map(\.stringValue).joined(separator: "."))"
        }
        switch error {
        case DecodingError.dataCorrupted(let context):
            return context.debugDescription + location(context.codingPath)
        case DecodingError.keyNotFound(let key, let context):
            return "missing \"\(key.stringValue)\"" + location(context.codingPath)
        case DecodingError.typeMismatch(_, let context), DecodingError.valueNotFound(_, let context):
            return context.debugDescription + location(context.codingPath)
        case EncodingError.invalidValue(_, let context):
            return context.debugDescription + location(context.codingPath)
        default:
            return String(describing: error)
        }
    }
}

/// ISO-8601 timestamps in UTC with six fractional digits, written by hand
/// rather than with a formatter so the output is identical on every platform
/// and the value round-trips: the date is rounded to the nearest microsecond
/// once, after which encoding and decoding it again is exact. Whole seconds
/// and the fraction are converted separately, so a date's magnitude never
/// costs the fraction precision. Years are proleptic Gregorian, as ISO 8601
/// requires.
enum ISO8601Timestamp {
    private static let microsecondsPerSecond: Int64 = 1_000_000
    private static let secondsPerDay: Int64 = 86_400
    /// Seconds from 1970-01-01 to Foundation's reference date, 2001-01-01.
    private static let referenceDateOffset: Int64 = 978_307_200

    /// `yyyy-MM-ddTHH:mm:ss.SSSSSSZ`, or nil for a date outside years 0–9999.
    /// Year 0 is there for `Date.distantPast`, which is 0000-12-30 in the
    /// proleptic Gregorian calendar (Foundation's 0001-01-01 is Julian).
    static func string(from date: Date) -> String? {
        guard let parts = components(of: date) else { return nil }
        return "\(pad(parts.year, 4))-\(pad(parts.month, 2))-\(pad(parts.day, 2))"
            + "T\(pad(parts.hour, 2)):\(pad(parts.minute, 2)):\(pad(parts.second, 2))"
            + ".\(pad(parts.microsecond, 6))Z"
    }

    /// `yyyyMMddTHHmmssZ`, safe in file names; "unknown-date" when out of range.
    static func compactString(from date: Date) -> String {
        guard let parts = components(of: date) else { return "unknown-date" }
        return "\(pad(parts.year, 4))\(pad(parts.month, 2))\(pad(parts.day, 2))"
            + "T\(pad(parts.hour, 2))\(pad(parts.minute, 2))\(pad(parts.second, 2))Z"
    }

    /// Parses `yyyy-MM-ddTHH:mm:ss[.f…]` followed by `Z` or `±HH:MM`, with 1–9
    /// fractional digits (rounded to microseconds). Anything else is nil.
    static func date(from text: String) -> Date? {
        var scanner = ByteScanner(text)
        guard let year = scanner.number(digits: 4), scanner.skip("-"),
            let month = scanner.number(digits: 2), scanner.skip("-"),
            let day = scanner.number(digits: 2), scanner.skip("T"),
            let hour = scanner.number(digits: 2), scanner.skip(":"),
            let minute = scanner.number(digits: 2), scanner.skip(":"),
            let second = scanner.number(digits: 2)
        else { return nil }
        guard (1...12).contains(month), (1...daysIn(month: month, year: year)).contains(day),
            hour < 24, minute < 60, second < 60
        else { return nil }

        var microsecond: Int64 = 0
        if scanner.skip(".") {
            guard let fraction = scanner.fraction() else { return nil }
            microsecond = fraction
        }

        var offset: Int64 = 0
        if scanner.skip("Z") {
            // UTC
        } else if let sign = scanner.sign() {
            guard let offsetHours = scanner.number(digits: 2), scanner.skip(":"),
                let offsetMinutes = scanner.number(digits: 2), offsetHours < 24, offsetMinutes < 60
            else { return nil }
            offset = sign * (offsetHours * 3_600 + offsetMinutes * 60)
        } else {
            return nil
        }
        guard scanner.isAtEnd else { return nil }

        let days = daysSinceEpoch(year: year, month: month, day: day)
        let seconds = days * secondsPerDay + hour * 3_600 + minute * 60 + second - offset - referenceDateOffset
        return Date(
            timeIntervalSinceReferenceDate: Double(seconds) + Double(microsecond) / Double(microsecondsPerSecond)
        )
    }

    private struct Components {
        var year, month, day, hour, minute, second, microsecond: Int64
    }

    private static func components(of date: Date) -> Components? {
        let interval = date.timeIntervalSinceReferenceDate
        // 4e11 s is about 12 700 years: past 0…9999 either way, well inside Int64.
        guard interval.isFinite, abs(interval) < 4e11 else { return nil }
        let wholeSeconds = interval.rounded(.down)
        var seconds = Int64(wholeSeconds) + referenceDateOffset
        // `interval - wholeSeconds` is exact, so only the rounding below is lossy.
        var microsecond = Int64(((interval - wholeSeconds) * Double(microsecondsPerSecond)).rounded())
        if microsecond == microsecondsPerSecond {
            seconds += 1
            microsecond = 0
        }
        let (days, secondOfDay) = floorDivide(seconds, secondsPerDay)
        let (year, month, day) = civilDate(daysSinceEpoch: days)
        guard (0...9_999).contains(year) else { return nil }
        return Components(
            year: year, month: month, day: day, hour: secondOfDay / 3_600, minute: secondOfDay / 60 % 60,
            second: secondOfDay % 60, microsecond: microsecond
        )
    }

    private static func floorDivide(_ value: Int64, _ divisor: Int64) -> (quotient: Int64, remainder: Int64) {
        let remainder = value % divisor
        return remainder < 0 ? (value / divisor - 1, remainder + divisor) : (value / divisor, remainder)
    }

    private static func pad(_ value: Int64, _ width: Int) -> String {
        let digits = String(value)
        return String(repeating: "0", count: max(0, width - digits.count)) + digits
    }

    private static func daysIn(month: Int64, year: Int64) -> Int64 {
        switch month {
        case 2: (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 ? 29 : 28
        case 4, 6, 9, 11: 30
        default: 31
        }
    }

    // Proleptic Gregorian calendar <-> days since 1970-01-01, after Howard
    // Hinnant's `days_from_civil` / `civil_from_days`.

    private static func daysSinceEpoch(year: Int64, month: Int64, day: Int64) -> Int64 {
        let y = month <= 2 ? year - 1 : year
        let era = (y >= 0 ? y : y - 399) / 400
        let yearOfEra = y - era * 400
        let dayOfYear = (153 * (month > 2 ? month - 3 : month + 9) + 2) / 5 + day - 1
        let dayOfEra = yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear
        return era * 146_097 + dayOfEra - 719_468
    }

    private static func civilDate(daysSinceEpoch days: Int64) -> (year: Int64, month: Int64, day: Int64) {
        let z = days + 719_468
        let era = (z >= 0 ? z : z - 146_096) / 146_097
        let dayOfEra = z - era * 146_097
        let yearOfEra = (dayOfEra - dayOfEra / 1_460 + dayOfEra / 36_524 - dayOfEra / 146_096) / 365
        let dayOfYear = dayOfEra - (365 * yearOfEra + yearOfEra / 4 - yearOfEra / 100)
        let shiftedMonth = (5 * dayOfYear + 2) / 153
        let day = dayOfYear - (153 * shiftedMonth + 2) / 5 + 1
        let month = shiftedMonth < 10 ? shiftedMonth + 3 : shiftedMonth - 9
        return (yearOfEra + era * 400 + (month <= 2 ? 1 : 0), month, day)
    }

    /// A cursor over ASCII bytes.
    private struct ByteScanner {
        private let bytes: [UInt8]
        private var index = 0

        init(_ text: String) { bytes = Array(text.utf8) }

        var isAtEnd: Bool { index == bytes.count }

        mutating func skip(_ character: Unicode.Scalar) -> Bool {
            guard index < bytes.count, bytes[index] == UInt8(ascii: character) else { return false }
            index += 1
            return true
        }

        mutating func sign() -> Int64? {
            if skip("+") { return 1 }
            if skip("-") { return -1 }
            return nil
        }

        /// Exactly `digits` decimal digits.
        mutating func number(digits: Int) -> Int64? {
            guard index + digits <= bytes.count else { return nil }
            var value: Int64 = 0
            for byte in bytes[index..<index + digits] {
                guard let digit = Self.digit(byte) else { return nil }
                value = value * 10 + digit
            }
            index += digits
            return value
        }

        /// 1–9 digits after the decimal point, as microseconds rounded half up
        /// (1 000 000 carries into the next second when added).
        mutating func fraction() -> Int64? {
            var microseconds: Int64 = 0
            var scale: Int64 = 100_000
            var count = 0
            while index < bytes.count, let digit = Self.digit(bytes[index]) {
                if count < 6 {
                    microseconds += digit * scale
                    scale /= 10
                } else if count == 6, digit >= 5 {
                    microseconds += 1
                }
                count += 1
                index += 1
            }
            return (1...9).contains(count) ? microseconds : nil
        }

        private static func digit(_ byte: UInt8) -> Int64? {
            (0x30...0x39).contains(byte) ? Int64(byte - 0x30) : nil
        }
    }
}

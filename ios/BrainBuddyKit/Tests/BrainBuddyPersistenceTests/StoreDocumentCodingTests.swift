import BrainBuddyCore
import Foundation
import Testing

@testable import BrainBuddyPersistence

@Suite struct TimestampTests {
    @Test func writesUTCWithMicroseconds() {
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: 0)) == "2001-01-01T00:00:00.000000Z")
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSince1970: 0)) == "1970-01-01T00:00:00.000000Z")
        #expect(
            ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: -0.25)) == "2000-12-31T23:59:59.750000Z"
        )
        #expect(
            ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: 812_345_678.123456))
                == "2026-09-29T03:34:38.123456Z"
        )
        // Foundation's distantPast is Julian 0001-01-01, proleptic Gregorian 0000-12-30.
        #expect(ISO8601Timestamp.string(from: Date.distantPast) == "0000-12-30T00:00:00.000000Z")
        #expect(ISO8601Timestamp.date(from: "0000-12-30T00:00:00.000000Z") == Date.distantPast)
        #expect(ISO8601Timestamp.string(from: Date.distantFuture) == "4001-01-01T00:00:00.000000Z")
    }

    @Test func roundsToTheNearestMicrosecond() {
        #expect(
            ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: 0.000_000_6)) == "2001-01-01T00:00:00.000001Z"
        )
        #expect(
            ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: 59.999_999_7)) == "2001-01-01T00:01:00.000000Z"
        )
    }

    @Test func refusesDatesOutsideYearsZeroTo9999() {
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: 3e11)) == nil)
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: -7e10)) == nil)
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: .infinity)) == nil)
        #expect(ISO8601Timestamp.string(from: Date(timeIntervalSinceReferenceDate: .nan)) == nil)
    }

    @Test(arguments: [
        ("2001-01-01T00:00:00Z", 0.0),
        ("2001-01-01T00:00:00.000000Z", 0.0),
        ("2001-01-01T02:00:00+02:00", 0.0),
        ("2000-12-31T19:00:00.5-05:00", 0.5),
        ("2001-01-01T00:00:00.123Z", 0.123),
        ("2001-01-01T00:00:00.1234565Z", 0.123457),
        ("2001-01-01T00:00:00.123456789Z", 0.123457),
        ("2001-01-01T00:00:59.9999995Z", 60.0),
        ("2024-02-29T12:00:00Z", 730_900_800.0),
    ])
    func parsesOffsetsAndOtherPrecisions(text: String, expected: TimeInterval) {
        #expect(ISO8601Timestamp.date(from: text) == Date(timeIntervalSinceReferenceDate: expected))
    }

    @Test(arguments: [
        "", "2001-01-01", "2001-01-01T00:00:00", "2001-13-01T00:00:00Z", "2001-02-29T00:00:00Z",
        "2001-04-31T00:00:00Z", "2001-01-01T24:00:00Z", "2001-01-01T00:60:00Z", "2001-01-01T00:00:60Z",
        "2001-01-01T00:00:00.Z", "2001-01-01T00:00:00.1234567890Z", "2001-01-01 00:00:00Z",
        "2001-01-01T00:00:00Zjunk", "-001-01-01T00:00:00Z", "2001-01-01T00:00:00+2:00", "2001-01-01t00:00:00z",
        "+2001-01-01T00:00:00Z", "12001-01-01T00:00:00Z", "２００１-01-01T00:00:00Z",
    ])
    func rejectsMalformedTimestamps(text: String) {
        #expect(ISO8601Timestamp.date(from: text) == nil)
    }

    /// The calendar arithmetic agrees with Foundation's own ISO-8601 format
    /// (Gregorian years only: Foundation switches to Julian before 1582).
    @Test func calendarArithmeticMatchesFoundation() throws {
        var random = SplitMix64(seed: 0x0B5E_55ED)
        let lower: Int64 = -3_155_673_600  // about 1901
        let upper: Int64 = 6_311_433_600  // about 2201
        for _ in 0..<2_000 {
            let seconds = lower + Int64(random.next() % UInt64(upper - lower))
            let date = Date(timeIntervalSinceReferenceDate: TimeInterval(seconds))
            let ours = try #require(ISO8601Timestamp.string(from: date))
            let wholeSeconds = String(ours.prefix(19)) + "Z"
            #expect(wholeSeconds == date.formatted(Date.ISO8601FormatStyle()))
            #expect(try Date(wholeSeconds, strategy: .iso8601) == ISO8601Timestamp.date(from: ours))
        }
    }

    /// Any `Date` comes back within a microsecond, and from then on exactly,
    /// near today (where `Date()` values are) and across years 0–8000.
    @Test(arguments: [(-978_307_200.0, 4_102_444_800.0), (-63_113_904_000.0, 252_423_993_600.0)])
    func roundTripIsExactOnceNormalized(from lower: TimeInterval, span: TimeInterval) throws {
        var random = SplitMix64(seed: 42)
        for _ in 0..<5_000 {
            let interval = lower + span * (Double(random.next() >> 11) / Double(1 << 53))
            let original = Date(timeIntervalSinceReferenceDate: interval)
            let first = try #require(roundTrip(original))
            #expect(abs(first.timeIntervalSince(original)) < 0.000_001)
            #expect(roundTrip(first) == first)
        }
    }
}

@Suite struct StoreDocumentCodingTests {
    @Test func encodingIsDeterministicWithSortedKeys() throws {
        let document = Fixtures.richDocument()
        let first = try StoreDocumentCoding.encode(document)
        let second = try StoreDocumentCoding.encode(document)
        #expect(first == second)
        let text = try #require(String(data: first, encoding: .utf8))
        #expect(text.hasPrefix("{\"account\":"))
        #expect(text.hasSuffix("\"version\":1}"))
        #expect(text.contains("\"issuedAt\":\"2026-09-29T03:34:38.123456Z\""))
        #expect(text.contains("\"dueDate\":\"2026-10-02\""))
    }

    @Test func decodeRoundTripsEveryStoredType() throws {
        let document = Fixtures.richDocument()
        #expect(try StoreDocumentCoding.decode(StoreDocumentCoding.encode(document)) == document)
    }

    @Test func generationIsReadWithoutTheRestOfTheDocument() throws {
        #expect(try StoreDocumentCoding.generation(of: Data(#"{"version":1,"generation":12}"#.utf8)) == 12)
        let missing = #expect(throws: DocumentStoreError.self) {
            try StoreDocumentCoding.generation(of: Data(#"{"version":1}"#.utf8))
        }
        #expect(isUnreadable(missing))
        let unknownVersion = #expect(throws: DocumentStoreError.self) {
            try StoreDocumentCoding.generation(of: Data(#"{"version":0,"generation":2}"#.utf8))
        }
        #expect(isUnreadable(unknownVersion))
    }

    @Test func newerVersionsAreUnsupported() {
        let data = Data(#"{"version":2,"generation":7,"shape":"from the future"}"#.utf8)
        #expect(throws: DocumentStoreError.unsupportedVersion(2)) { try StoreDocumentCoding.decode(data) }
        #expect(throws: DocumentStoreError.unsupportedVersion(2)) { try StoreDocumentCoding.generation(of: data) }
    }

    @Test(arguments: ["", "not json", "[]", #"{"generation":1}"#, #"{"version":"1"}"#, #"{"version":1}"#, #"{"version":0}"#])
    func malformedDocumentsAreUnreadable(text: String) {
        let error = #expect(throws: DocumentStoreError.self) { try StoreDocumentCoding.decode(Data(text.utf8)) }
        #expect(isUnreadable(error))
    }

    @Test func migrationIsIdentityForTheCurrentVersion() throws {
        let data = try StoreDocumentCoding.encode(Fixtures.richDocument())
        #expect(try StoreDocumentCoding.migrate(data, fromVersion: StoreDocument.currentVersion) == data)
        let tooOld = #expect(throws: DocumentStoreError.self) { try StoreDocumentCoding.migrate(data, fromVersion: 0) }
        #expect(isUnreadable(tooOld))
        #expect(throws: DocumentStoreError.unsupportedVersion(StoreDocument.currentVersion + 1)) {
            try StoreDocumentCoding.migrate(data, fromVersion: StoreDocument.currentVersion + 1)
        }
    }

    @Test func datesOutsideFourDigitYearsCannotBeEncoded() {
        var document = StoreDocument()
        document.sync.lastPullAt = Date(timeIntervalSinceReferenceDate: 3e11)
        let error = #expect(throws: DocumentStoreError.self) { try StoreDocumentCoding.encode(document) }
        #expect(isIO(error))
    }

    /// `PendingOperation.everSent` came later: older documents decode with it
    /// false, and it is written only when set, so other documents keep their bytes.
    @Test func everSentIsOptionalOnDiskAndWrittenOnlyWhenSet() throws {
        var document = Fixtures.richDocument()
        let before = try StoreDocumentCoding.encode(document)
        #expect(!String(decoding: before, as: UTF8.self).contains("everSent"))
        let legacy = try StoreDocumentCoding.decode(before)
        #expect(legacy.outbox.map(\.everSent) == [false, false])
        #expect(legacy == document)

        document.outbox[0].everSent = true
        let after = try StoreDocumentCoding.encode(document)
        #expect(String(decoding: after, as: UTF8.self).contains(#""everSent":true"#))
        let decoded = try StoreDocumentCoding.decode(after)
        #expect(decoded.outbox[0].everSent)
        #expect(decoded.outbox[0].hasBeenSent, "with no attempt under its current key")
        #expect(decoded == document)
    }

    @Test func errorMessagesAreSentences() {
        let errors: [DocumentStoreError] = [.unreadable("x"), .unsupportedVersion(2), .io("disk full")]
        for error in errors {
            #expect(error.message.hasSuffix("."))
        }
        #expect(DocumentStoreError.io("disk full").message.contains("disk full"))
    }
}

private func roundTrip(_ date: Date) -> Date? {
    ISO8601Timestamp.string(from: date).flatMap(ISO8601Timestamp.date(from:))
}

/// A tiny deterministic generator so the property tests are reproducible.
struct SplitMix64 {
    private var state: UInt64

    init(seed: UInt64) { state = seed }

    mutating func next() -> UInt64 {
        state &+= 0x9E37_79B9_7F4A_7C15
        var z = state
        z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
        z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
        return z ^ (z >> 31)
    }
}

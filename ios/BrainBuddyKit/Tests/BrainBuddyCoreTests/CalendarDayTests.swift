import Foundation
import Testing

@testable import BrainBuddyCore

@Suite("CalendarDay")
struct CalendarDayTests {
    private func zone(_ identifier: String) -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: identifier)!
        return calendar
    }

    // MARK: Validation and parsing

    @Test(
        "Real dates parse, including leap days",
        arguments: ["2024-02-29", "2000-02-29", "1600-02-29", "2026-09-29", "0001-01-01", "9999-12-31", "2026-04-30"])
    func parsesValidDates(iso: String) throws {
        let day = try #require(CalendarDay(isoString: iso))
        #expect(day.isoString == iso)
        #expect(day.description == iso)
    }

    @Test(
        "Impossible dates and malformed strings are rejected",
        arguments: [
            "2023-02-29", "1900-02-29", "2100-02-29", "2026-04-31", "2026-13-01", "2026-00-10", "2026-01-00",
            "2026-01-32", "0000-01-01", "2026-9-29", "2026-09-9", "26-09-29", "02026-09-29", "2026/09/29",
            "2026-09-29T00:00", " 2026-09-29", "2026-09-29 ", "2026-09-2a", "+026-09-29", "-026-09-29",
            "２０２６-09-29", "٢٠٢٦-٠٩-٢٩", "", "2026-0929-",
        ])
    func rejectsInvalid(iso: String) {
        #expect(CalendarDay(isoString: iso) == nil)
    }

    @Test("Components are validated against the Gregorian calendar")
    func componentValidation() {
        #expect(CalendarDay(year: 2024, month: 2, day: 29) != nil)
        #expect(CalendarDay(year: 2023, month: 2, day: 29) == nil)
        #expect(CalendarDay(year: 0, month: 1, day: 1) == nil)
        #expect(CalendarDay(year: 10_000, month: 1, day: 1) == nil)
        #expect(CalendarDay(year: -1, month: 1, day: 1) == nil)
        #expect(CalendarDay(year: 2026, month: 0, day: 1) == nil)
        #expect(CalendarDay(year: 2026, month: 13, day: 1) == nil)
        #expect(CalendarDay(year: 2026, month: 6, day: 0) == nil)
        #expect(CalendarDay(year: 2026, month: 6, day: 31) == nil)
        #expect(CalendarDay(year: 2026, month: 12, day: 31) != nil)
    }

    @Test("Days per month follow the leap-year rules", arguments: [(1900, 28), (2000, 29), (2023, 28), (2024, 29), (2100, 28), (2400, 29)])
    func february(year: Int, days: Int) {
        #expect(CalendarDay.daysIn(month: 2, year: year) == days)
    }

    @Test("Years below 1000 are zero-padded")
    func padding() {
        #expect(CalendarDay(year: 1, month: 2, day: 3)?.isoString == "0001-02-03")
        #expect(CalendarDay(year: 999, month: 12, day: 31)?.isoString == "0999-12-31")
    }

    // MARK: Ordering and arithmetic

    @Test("Comparison is chronological")
    func ordering() {
        let days = ["2026-10-01", "2025-12-31", "2026-09-30", "2026-01-01", "2026-09-29"].map(isoDay)

        #expect(days.sorted().map(\.isoString) == ["2025-12-31", "2026-01-01", "2026-09-29", "2026-09-30", "2026-10-01"])
        #expect(isoDay("2026-02-01") > isoDay("2026-01-31"))
        #expect(!(isoDay("2026-02-01") < isoDay("2026-02-01")))
    }

    @Test(
        "Adding days crosses months, years and leap days",
        arguments: [
            ("2024-02-28", 1, "2024-02-29"), ("2024-02-28", 2, "2024-03-01"), ("2023-02-28", 1, "2023-03-01"),
            ("2026-12-31", 1, "2027-01-01"), ("2027-01-01", -1, "2026-12-31"), ("2026-03-01", -1, "2026-02-28"),
            ("2024-03-01", -1, "2024-02-29"), ("2026-09-29", 0, "2026-09-29"), ("2026-09-29", 365, "2027-09-29"),
            ("2000-01-01", 146_097, "2400-01-01"), ("2026-01-31", 30, "2026-03-02"), ("1970-01-01", -1, "1969-12-31"),
        ])
    func adding(start: String, days: Int, expected: String) {
        #expect(isoDay(start).adding(days: days).isoString == expected)
        #expect(isoDay(start).days(to: isoDay(expected)) == days)
    }

    @Test("Adding days across 1582 stays proleptic Gregorian (no Julian switch)")
    func noJulianSwitch() {
        #expect(isoDay("1582-10-15").adding(days: -1).isoString == "1582-10-14")
        #expect(isoDay("1500-02-28").adding(days: 1).isoString == "1500-03-01")
        #expect(isoDay("0001-01-01").days(to: isoDay("1970-01-01")) == 719_162)
    }

    @Test("Adding days clamps to the supported range instead of trapping")
    func addingClamps() {
        #expect(isoDay("9999-12-31").adding(days: 1).isoString == "9999-12-31")
        #expect(isoDay("0001-01-01").adding(days: -1).isoString == "0001-01-01")
        #expect(isoDay("2026-09-29").adding(days: .max).isoString == "9999-12-31")
        #expect(isoDay("2026-09-29").adding(days: .min).isoString == "0001-01-01")
    }

    @Test("Every day of a leap year round-trips through day numbers")
    func dayNumbersRoundTrip() {
        var day = isoDay("2023-12-31")
        var count = 0
        while day < isoDay("2025-01-01") {
            let next = day.adding(days: 1)
            #expect(CalendarDay(clampingDayNumber: next.dayNumber) == next)
            #expect(day.days(to: next) == 1)
            day = next
            count += 1
        }
        #expect(count == 367)
        #expect(isoDay("1970-01-01").dayNumber == 0)
    }

    // MARK: Time zones

    @Test("The same instant is a different day in different time zones")
    func timeZones() {
        // 2026-09-29 11:30 UTC
        let instant = Date(timeIntervalSince1970: 1_790_681_400)

        #expect(CalendarDay(date: instant, calendar: zone("UTC")).isoString == "2026-09-29")
        #expect(CalendarDay(date: instant, calendar: zone("Pacific/Kiritimati")).isoString == "2026-09-30")  // +14
        #expect(CalendarDay(date: instant, calendar: zone("Pacific/Pago_Pago")).isoString == "2026-09-29")  // -11
        #expect(CalendarDay(date: instant.addingTimeInterval(-12 * 3600), calendar: zone("Pacific/Pago_Pago")).isoString == "2026-09-28")
    }

    @Test("A non-Gregorian calendar only contributes its time zone")
    func nonGregorianCalendar() {
        var buddhist = Calendar(identifier: .buddhist)
        buddhist.timeZone = TimeZone(identifier: "Asia/Bangkok")!
        let instant = Date(timeIntervalSince1970: 1_790_681_400)

        #expect(CalendarDay(date: instant, calendar: buddhist).isoString == "2026-09-29")
    }

    @Test(
        "The start of a day is local midnight and round-trips",
        arguments: ["UTC", "Europe/Berlin", "America/Los_Angeles", "Asia/Kolkata", "Pacific/Kiritimati", "Pacific/Pago_Pago"])
    func startDate(identifier: String) {
        let calendar = zone(identifier)
        for iso in ["2026-03-29", "2026-09-29", "2026-11-01", "2024-02-29", "1582-10-15", "0001-01-01", "9999-12-31"] {
            let day = isoDay(iso)
            let start = day.startDate(in: calendar)
            #expect(CalendarDay(date: start, calendar: calendar) == day)
            #expect(CalendarDay(date: start.addingTimeInterval(-1), calendar: calendar) == day.adding(days: -1) || iso == "0001-01-01")
        }
    }

    @Test("Where daylight saving skips midnight, the day starts when the clocks change")
    func startDateSkippedMidnight() {
        // São Paulo moved clocks from 00:00 to 01:00 on 2018-11-04 (UTC-3 → UTC-2).
        let calendar = zone("America/Sao_Paulo")
        let start = isoDay("2018-11-04").startDate(in: calendar)

        #expect(start == Date(timeIntervalSince1970: 1_541_300_400))  // 2018-11-04 03:00 UTC = 01:00 local
        #expect(CalendarDay(date: start, calendar: calendar).isoString == "2018-11-04")
        #expect(CalendarDay(date: start.addingTimeInterval(-1), calendar: calendar).isoString == "2018-11-03")
    }

    @Test("Instants outside 0001...9999 clamp instead of producing unencodable days")
    func extremeInstants() {
        let utc = zone("UTC")
        #expect(CalendarDay(date: .distantPast, calendar: utc).isoString == "0001-01-01")
        #expect(CalendarDay(date: Date(timeIntervalSince1970: -1e15), calendar: utc).isoString == "0001-01-01")
        #expect(CalendarDay(date: Date(timeIntervalSince1970: 1e12), calendar: utc).isoString == "9999-12-31")
        #expect(CalendarDay(date: Date(timeIntervalSince1970: .infinity), calendar: utc).isoString == "9999-12-31")
        #expect(CalendarDay(date: Date(timeIntervalSince1970: -.infinity), calendar: utc).isoString == "0001-01-01")
        #expect(CalendarDay(date: Date(timeIntervalSince1970: .nan), calendar: utc).isoString == "0001-01-01")
        #expect(CalendarDay(date: .distantFuture, calendar: utc).isoString == "4001-01-01")
    }

    @Test("Instants before 1582 get proleptic Gregorian fields")
    func prolepticFromDate() {
        let utc = zone("UTC")
        // -14_200_000_000 s is 1520-01-09 in the proleptic Gregorian calendar
        // (Foundation's Gregorian calendar would say 1519-12-30, Julian).
        let day = CalendarDay(date: Date(timeIntervalSince1970: -14_200_000_000), calendar: utc)

        #expect(day.isoString == "1520-01-09")
        #expect(day.startDate(in: utc) == Date(timeIntervalSince1970: TimeInterval(day.dayNumber * 86_400)))
    }

    // MARK: Codable

    private struct Payload: Codable, Equatable {
        var due: CalendarDay?
    }

    @Test("Encodes as a bare YYYY-MM-DD string and decodes it back")
    func codable() throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let payload = Payload(due: isoDay("0987-06-05"))

        let data = try encoder.encode(payload)
        #expect(String(decoding: data, as: UTF8.self) == #"{"due":"0987-06-05"}"#)
        #expect(try JSONDecoder().decode(Payload.self, from: data) == payload)
        #expect(try JSONDecoder().decode(Payload.self, from: Data(#"{"due":null}"#.utf8)) == Payload(due: nil))
        #expect(try JSONDecoder().decode([CalendarDay].self, from: Data(#"["2024-02-29","2026-09-29"]"#.utf8)) == [
            isoDay("2024-02-29"), isoDay("2026-09-29"),
        ])
    }

    @Test("Decoding rejects anything but a valid YYYY-MM-DD string", arguments: [#""2023-02-29""#, #""2026-9-29""#, "20260929", "null", #""""#])
    func decodingRejects(json: String) {
        #expect(throws: DecodingError.self) {
            try JSONDecoder().decode(CalendarDay.self, from: Data(json.utf8))
        }
    }

    @Test("Clamped extremes still encode and decode")
    func clampedValuesRoundTrip() throws {
        let utc = zone("UTC")
        for day in [CalendarDay(date: .distantPast, calendar: utc), CalendarDay(date: Date(timeIntervalSince1970: 1e13), calendar: utc)] {
            let data = try JSONEncoder().encode([day])
            #expect(try JSONDecoder().decode([CalendarDay].self, from: data) == [day])
        }
    }
}

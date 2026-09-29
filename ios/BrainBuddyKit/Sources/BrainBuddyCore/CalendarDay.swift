import Foundation

/// A local calendar date with no time or zone, encoded as `YYYY-MM-DD` exactly
/// like the API's `due_date`. Comparison is chronological.
///
/// Dates are proleptic Gregorian (ISO 8601), computed arithmetically rather
/// than with Foundation's Gregorian calendar, which switches to the Julian
/// calendar before 1582-10-15. Values span 0001-01-01 through 9999-12-31, the
/// range `YYYY-MM-DD` can express; conversions and arithmetic clamp to it, so
/// every value encodes and decodes again.
public struct CalendarDay: Hashable, Comparable, Sendable, Codable, CustomStringConvertible {
    public let year: Int
    public let month: Int
    public let day: Int

    /// Fails unless the components name a real Gregorian date.
    public init?(year: Int, month: Int, day: Int) {
        guard (1...9999).contains(year), (1...12).contains(month),
            (1...CalendarDay.daysIn(month: month, year: year)).contains(day)
        else { return nil }
        self.init(validYear: year, month: month, day: day)
    }

    /// Strict `YYYY-MM-DD` parsing: four-digit year, two-digit month and day.
    public init?(isoString: String) {
        let scalars = Array(isoString.unicodeScalars)
        guard scalars.count == 10, scalars[4] == "-", scalars[7] == "-" else { return nil }
        func number(_ range: Range<Int>) -> Int? {
            var value = 0
            for index in range {
                let code = scalars[index].value
                guard (48...57).contains(code) else { return nil }
                value = value * 10 + Int(code - 48)
            }
            return value
        }
        guard let year = number(0..<4), let month = number(5..<7), let day = number(8..<10) else { return nil }
        self.init(year: year, month: month, day: day)
    }

    /// The day `date` falls on in `calendar`'s time zone (Gregorian fields,
    /// whatever `calendar`'s identifier). Instants outside the supported range
    /// clamp to its first or last day.
    public init(date: Date, calendar: Calendar = .current) {
        let seconds = date.timeIntervalSince1970.rounded(.down)
        // Two days of margin covers every UTC offset. NaN fails the first check.
        let lowest = Double((CalendarDay.earliest.dayNumber - 2) * CalendarDay.secondsPerDay)
        let highest = Double((CalendarDay.latest.dayNumber + 2) * CalendarDay.secondsPerDay)
        guard seconds > lowest else {
            self = .earliest
            return
        }
        guard seconds < highest else {
            self = .latest
            return
        }
        self.init(clampingDayNumber: CalendarDay.localDayNumber(atSecond: Int(seconds), in: calendar.timeZone))
    }

    public var isoString: String {
        func pad(_ value: Int, _ width: Int) -> String {
            let digits = String(value)
            return String(repeating: "0", count: max(0, width - digits.count)) + digits
        }
        return "\(pad(year, 4))-\(pad(month, 2))-\(pad(day, 2))"
    }

    public var description: String { isoString }

    /// The first instant of this day in `calendar`'s time zone: midnight, or
    /// the end of the clock change where a zone skips midnight (for example a
    /// daylight-saving change at 00:00). For a day a zone skipped entirely, it
    /// is the start of the next day.
    public func startDate(in calendar: Calendar = .current) -> Date {
        let zone = calendar.timeZone
        let target = dayNumber
        let midnight = target * CalendarDay.secondsPerDay
        // UTC offsets stay well within ±26 hours, so the local day before
        // `self` is still showing at `low` and `self` (or later) at `high`.
        var low = midnight - 30 * 3600
        var high = midnight + 30 * 3600
        while high - low > 1 {
            let middle = low + (high - low) / 2
            if CalendarDay.localDayNumber(atSecond: middle, in: zone) < target { low = middle } else { high = middle }
        }
        return Date(timeIntervalSince1970: TimeInterval(high))
    }

    /// The day `days` days later (earlier when negative), clamped to
    /// 0001-01-01 through 9999-12-31.
    public func adding(days: Int) -> CalendarDay {
        let (sum, overflow) = dayNumber.addingReportingOverflow(days)
        if overflow { return days > 0 ? .latest : .earliest }
        return CalendarDay(clampingDayNumber: sum)
    }

    /// Whole days from `self` to `other`: positive when `other` is later.
    public func days(to other: CalendarDay) -> Int {
        other.dayNumber - dayNumber
    }

    public static func < (lhs: CalendarDay, rhs: CalendarDay) -> Bool {
        (lhs.year, lhs.month, lhs.day) < (rhs.year, rhs.month, rhs.day)
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        let raw = try container.decode(String.self)
        guard let value = CalendarDay(isoString: raw) else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Expected YYYY-MM-DD, got \(raw)")
        }
        self = value
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(isoString)
    }

    static func daysIn(month: Int, year: Int) -> Int {
        switch month {
        case 2: (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 ? 29 : 28
        case 4, 6, 9, 11: 30
        default: 31
        }
    }

    // MARK: Day numbers

    static let earliest = CalendarDay(validYear: 1, month: 1, day: 1)
    static let latest = CalendarDay(validYear: 9999, month: 12, day: 31)
    static let secondsPerDay = 86_400

    private init(validYear year: Int, month: Int, day: Int) {
        self.year = year
        self.month = month
        self.day = day
    }

    /// Days since 1970-01-01 in the proleptic Gregorian calendar
    /// (Howard Hinnant's `days_from_civil`).
    var dayNumber: Int {
        let shiftedYear = month <= 2 ? year - 1 : year
        let era = (shiftedYear >= 0 ? shiftedYear : shiftedYear - 399) / 400
        let yearOfEra = shiftedYear - era * 400
        let dayOfYear = (153 * ((month + 9) % 12) + 2) / 5 + day - 1
        let dayOfEra = yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear
        return era * 146_097 + dayOfEra - 719_468
    }

    /// The inverse of `dayNumber` (`civil_from_days`), clamped to the supported range.
    init(clampingDayNumber value: Int) {
        let number = min(max(value, CalendarDay.earliest.dayNumber), CalendarDay.latest.dayNumber)
        let shifted = number + 719_468
        let era = (shifted >= 0 ? shifted : shifted - 146_096) / 146_097
        let dayOfEra = shifted - era * 146_097
        let yearOfEra = (dayOfEra - dayOfEra / 1460 + dayOfEra / 36524 - dayOfEra / 146_096) / 365
        let dayOfYear = dayOfEra - (365 * yearOfEra + yearOfEra / 4 - yearOfEra / 100)
        let shiftedMonth = (5 * dayOfYear + 2) / 153
        let day = dayOfYear - (153 * shiftedMonth + 2) / 5 + 1
        let month = shiftedMonth < 10 ? shiftedMonth + 3 : shiftedMonth - 9
        self.init(validYear: yearOfEra + era * 400 + (month <= 2 ? 1 : 0), month: month, day: day)
    }

    /// The local day number showing at Unix second `second` in `zone`.
    private static func localDayNumber(atSecond second: Int, in zone: TimeZone) -> Int {
        let local = second + zone.secondsFromGMT(for: Date(timeIntervalSince1970: TimeInterval(second)))
        return local >= 0 ? local / secondsPerDay : (local - secondsPerDay + 1) / secondsPerDay
    }
}

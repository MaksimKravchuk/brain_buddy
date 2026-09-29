import Foundation

/// The API's datetime format. Pydantic writes timezone-aware UTC datetimes as
/// `2026-09-29T08:15:30Z`, with microseconds only when they are non-zero
/// (`2026-09-29T08:15:30.123456Z`).
///
/// Parsing is exact integer arithmetic (no `DateFormatter`, no locale) and
/// accepts 1–9 fractional digits and a `Z`, `±HH:MM`, `±HHMM` or `±HH` offset;
/// a datetime without an offset is read as UTC.
public enum WireDate {
    public static func parse(_ text: String) -> Date? {
        let s = Array(text.utf8)
        guard s.count >= 19, s[4] == UInt8(ascii: "-"), s[7] == UInt8(ascii: "-"),
            s[10] == UInt8(ascii: "T") || s[10] == UInt8(ascii: "t") || s[10] == UInt8(ascii: " "),
            s[13] == UInt8(ascii: ":"), s[16] == UInt8(ascii: ":"),
            let year = digits(s, 0, 4), let month = digits(s, 5, 2), let day = digits(s, 8, 2),
            let hour = digits(s, 11, 2), let minute = digits(s, 14, 2), let second = digits(s, 17, 2),
            (1...12).contains(month), day >= 1, day <= daysIn(month: month, year: year),
            hour <= 23, minute <= 59, second <= 59
        else { return nil }

        var index = 19
        var nanoseconds = 0
        if index < s.count, s[index] == UInt8(ascii: ".") || s[index] == UInt8(ascii: ",") {
            index += 1
            var count = 0
            while index < s.count, let digit = digit(s[index]) {
                guard count < 9 else { return nil }
                nanoseconds = nanoseconds * 10 + digit
                count += 1
                index += 1
            }
            guard count > 0 else { return nil }
            for _ in count..<9 { nanoseconds *= 10 }
        }

        var offsetSeconds = 0
        if index < s.count {
            switch s[index] {
            case UInt8(ascii: "Z"), UInt8(ascii: "z"):
                index += 1
            case UInt8(ascii: "+"), UInt8(ascii: "-"):
                let sign = s[index] == UInt8(ascii: "-") ? -1 : 1
                index += 1
                guard let hours = digits(s, index, 2), hours <= 23 else { return nil }
                index += 2
                var minutes = 0
                if index < s.count {
                    if s[index] == UInt8(ascii: ":") { index += 1 }
                    guard let value = digits(s, index, 2), value <= 59 else { return nil }
                    minutes = value
                    index += 2
                }
                offsetSeconds = sign * (hours * 3600 + minutes * 60)
            default:
                return nil
            }
        }
        guard index == s.count else { return nil }

        let days = daysFromCivil(year: year, month: month, day: day)
        let wholeSeconds = days * 86_400 + hour * 3600 + minute * 60 + second - offsetSeconds
        return Date(timeIntervalSince1970: Double(wholeSeconds) + Double(nanoseconds) / 1_000_000_000)
    }

    /// `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` in UTC, rounded to the microsecond, with
    /// the fraction only when it is non-zero — the same text the server writes.
    public static func format(_ date: Date) -> String {
        let totalMicroseconds = Int64((date.timeIntervalSince1970 * 1_000_000).rounded())
        var seconds = totalMicroseconds / 1_000_000
        var micros = totalMicroseconds % 1_000_000
        if micros < 0 {
            micros += 1_000_000
            seconds -= 1
        }
        var days = seconds / 86_400
        var secondOfDay = seconds % 86_400
        if secondOfDay < 0 {
            secondOfDay += 86_400
            days -= 1
        }
        let (year, month, day) = civilFromDays(Int(days))
        let hour = Int(secondOfDay / 3600)
        let minute = Int(secondOfDay % 3600 / 60)
        let second = Int(secondOfDay % 60)
        var text = "\(pad(year, 4))-\(pad(month, 2))-\(pad(day, 2))T\(pad(hour, 2)):\(pad(minute, 2)):\(pad(second, 2))"
        if micros != 0 { text += "." + pad(Int(micros), 6) }
        return text + "Z"
    }

    // MARK: - Helpers

    private static func digit(_ byte: UInt8) -> Int? {
        (48...57).contains(byte) ? Int(byte - 48) : nil
    }

    private static func digits(_ s: [UInt8], _ start: Int, _ count: Int) -> Int? {
        guard start + count <= s.count else { return nil }
        var value = 0
        for index in start..<(start + count) {
            guard let digit = digit(s[index]) else { return nil }
            value = value * 10 + digit
        }
        return value
    }

    private static func pad(_ value: Int, _ width: Int) -> String {
        let text = String(value)
        return String(repeating: "0", count: max(0, width - text.count)) + text
    }

    private static func daysIn(month: Int, year: Int) -> Int {
        switch month {
        case 2: (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 ? 29 : 28
        case 4, 6, 9, 11: 30
        default: 31
        }
    }

    /// Days since 1970-01-01 for a proleptic Gregorian date (Howard Hinnant's algorithm).
    private static func daysFromCivil(year: Int, month: Int, day: Int) -> Int {
        let y = month <= 2 ? year - 1 : year
        let era = (y >= 0 ? y : y - 399) / 400
        let yearOfEra = y - era * 400
        let dayOfYear = (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1
        let dayOfEra = yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear
        return era * 146_097 + dayOfEra - 719_468
    }

    private static func civilFromDays(_ days: Int) -> (year: Int, month: Int, day: Int) {
        let z = days + 719_468
        let era = (z >= 0 ? z : z - 146_096) / 146_097
        let dayOfEra = z - era * 146_097
        let yearOfEra = (dayOfEra - dayOfEra / 1460 + dayOfEra / 36_524 - dayOfEra / 146_096) / 365
        let dayOfYear = dayOfEra - (365 * yearOfEra + yearOfEra / 4 - yearOfEra / 100)
        let mp = (5 * dayOfYear + 2) / 153
        let day = dayOfYear - (153 * mp + 2) / 5 + 1
        let month = mp < 10 ? mp + 3 : mp - 9
        let year = yearOfEra + era * 400 + (month <= 2 ? 1 : 0)
        return (year, month, day)
    }
}

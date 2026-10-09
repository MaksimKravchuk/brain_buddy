//! Calendar days and time zones.
//!
//! A [`CalendarDay`] is a local date with no time or zone: what the API calls
//! `due_date` (`YYYY-MM-DD`). An instant is a Unix second. The two only meet
//! through an explicit [`TimeZone`], so "due on the 9th" never silently means a
//! particular instant and a DST change cannot move a day.
//!
//! Dates are proleptic Gregorian, computed arithmetically, and span 0001-01-01
//! through 9999-12-31 like Python's `datetime.date` and the Swift
//! `CalendarDay`. Arithmetic and instant conversions clamp to that range, so
//! every value encodes and decodes again.
//!
//! Wall-clock to instant conversion follows Python's `zoneinfo` with
//! `fold=0` (`datetime(y, m, d, ..., tzinfo=zone).astimezone(UTC)`), the server
//! rule in `formulation.due_start` and `review_rules._slot`: a time inside a
//! DST gap uses the offset in force before the change, and a repeated time
//! resolves to its first occurrence.

use std::fmt;
use std::str::FromStr;

use jiff::Timestamp;
use jiff::civil::DateTime;
use jiff::tz::TimeZone as JiffTimeZone;

const SECONDS_PER_DAY: i64 = 86_400;

/// A string that is not a real `YYYY-MM-DD` Gregorian date within years
/// 0001 to 9999.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvalidCalendarDay;

impl fmt::Display for InvalidCalendarDay {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("expected a real calendar date as YYYY-MM-DD")
    }
}

impl std::error::Error for InvalidCalendarDay {}

/// A time-zone name that is not in the bundled IANA database.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnknownTimeZone(pub String);

impl fmt::Display for UnknownTimeZone {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "unknown time zone {:?}", self.0)
    }
}

impl std::error::Error for UnknownTimeZone {}

/// An IANA time zone from the bundled tz database (never the host's).
#[derive(Debug, Clone, PartialEq)]
pub struct TimeZone(JiffTimeZone);

impl TimeZone {
    /// The UTC zone.
    #[must_use]
    pub fn utc() -> Self {
        Self(JiffTimeZone::UTC)
    }

    /// Looks `name` up exactly as `zoneinfo.ZoneInfo(name)` does: an IANA key
    /// with its exact spelling, so `europe/berlin` is unknown.
    ///
    /// # Errors
    ///
    /// [`UnknownTimeZone`] for any name the database does not contain.
    pub fn named(name: &str) -> Result<Self, UnknownTimeZone> {
        let unknown = || UnknownTimeZone(name.to_owned());
        let zone = JiffTimeZone::get(name).map_err(|_| unknown())?;
        // The bundled lookup ignores case; Python on Linux does not.
        if zone.iana_name() == Some(name) {
            Ok(Self(zone))
        } else {
            Err(unknown())
        }
    }

    /// The UTC offset in seconds in force at Unix second `unix_seconds`.
    #[must_use]
    pub fn offset_seconds_at(&self, unix_seconds: i64) -> i32 {
        self.0
            .to_offset(timestamp_saturating(unix_seconds))
            .seconds()
    }
}

fn timestamp_saturating(unix_seconds: i64) -> Timestamp {
    Timestamp::from_second(unix_seconds).unwrap_or(if unix_seconds < 0 {
        Timestamp::MIN
    } else {
        Timestamp::MAX
    })
}

/// A local calendar date. Ordering is chronological.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct CalendarDay {
    year: u16,
    month: u8,
    day: u8,
}

impl CalendarDay {
    /// 0001-01-01.
    pub const EARLIEST: Self = Self {
        year: 1,
        month: 1,
        day: 1,
    };
    /// 9999-12-31.
    pub const LATEST: Self = Self {
        year: 9999,
        month: 12,
        day: 31,
    };

    /// `None` unless the components name a real Gregorian date in 1..=9999.
    #[must_use]
    pub fn new(year: i32, month: u32, day: u32) -> Option<Self> {
        let year = u16::try_from(year)
            .ok()
            .filter(|y| (1..=9999).contains(y))?;
        let month = u8::try_from(month).ok().filter(|m| (1..=12).contains(m))?;
        let day = u8::try_from(day).ok()?;
        (1..=days_in_month(year, month))
            .contains(&day)
            .then_some(Self { year, month, day })
    }

    /// Strict `YYYY-MM-DD`: four ASCII digits, a hyphen, two digits, a hyphen,
    /// two digits. No sign, spaces, other digit scripts or time part.
    ///
    /// # Errors
    ///
    /// [`InvalidCalendarDay`] for anything else, including impossible dates.
    pub fn parse_iso(value: &str) -> Result<Self, InvalidCalendarDay> {
        let bytes = value.as_bytes();
        if bytes.len() != 10 || bytes[4] != b'-' || bytes[7] != b'-' {
            return Err(InvalidCalendarDay);
        }
        let number = |range: std::ops::Range<usize>| -> Option<u32> {
            bytes[range].iter().try_fold(0_u32, |acc, byte| {
                byte.is_ascii_digit()
                    .then(|| acc * 10 + u32::from(byte - b'0'))
            })
        };
        let (year, month, day) = (number(0..4), number(5..7), number(8..10));
        match (year, month, day) {
            (Some(year), Some(month), Some(day)) => Self::new(
                i32::try_from(year).map_err(|_| InvalidCalendarDay)?,
                month,
                day,
            )
            .ok_or(InvalidCalendarDay),
            _ => Err(InvalidCalendarDay),
        }
    }

    /// The year, 1..=9999.
    #[must_use]
    pub fn year(self) -> u16 {
        self.year
    }

    /// The month, 1..=12.
    #[must_use]
    pub fn month(self) -> u8 {
        self.month
    }

    /// The day of the month, 1..=31.
    #[must_use]
    pub fn day(self) -> u8 {
        self.day
    }

    /// `YYYY-MM-DD`, years below 1000 zero-padded.
    #[must_use]
    pub fn iso_string(self) -> String {
        self.to_string()
    }

    /// Days since 1970-01-01 in the proleptic Gregorian calendar (Howard
    /// Hinnant's `days_from_civil`).
    #[must_use]
    pub fn day_number(self) -> i64 {
        let month = i64::from(self.month);
        let shifted_year = i64::from(self.year) - i64::from(month <= 2);
        let era = shifted_year.div_euclid(400);
        let year_of_era = shifted_year - era * 400;
        let day_of_year = (153 * ((month + 9) % 12) + 2) / 5 + i64::from(self.day) - 1;
        let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
        era * 146_097 + day_of_era - 719_468
    }

    /// The inverse of [`CalendarDay::day_number`] (`civil_from_days`), clamped
    /// to 0001-01-01 through 9999-12-31.
    #[must_use]
    pub fn from_day_number_clamped(day_number: i64) -> Self {
        let number = day_number.clamp(Self::EARLIEST.day_number(), Self::LATEST.day_number());
        let shifted = number + 719_468;
        let era = shifted.div_euclid(146_097);
        let day_of_era = shifted - era * 146_097;
        let year_of_era =
            (day_of_era - day_of_era / 1460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
        let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
        let shifted_month = (5 * day_of_year + 2) / 153;
        let day = day_of_year - (153 * shifted_month + 2) / 5 + 1;
        let month = if shifted_month < 10 {
            shifted_month + 3
        } else {
            shifted_month - 9
        };
        let year = year_of_era + era * 400 + i64::from(month <= 2);
        Self {
            year: u16::try_from(year).unwrap_or(1),
            month: u8::try_from(month).unwrap_or(1),
            day: u8::try_from(day).unwrap_or(1),
        }
    }

    /// The day `days` later (earlier when negative), clamped to the supported
    /// range. Never overflows.
    #[must_use]
    pub fn add_days(self, days: i64) -> Self {
        Self::from_day_number_clamped(self.day_number().saturating_add(days))
    }

    /// Whole days from `self` to `other`: positive when `other` is later.
    #[must_use]
    pub fn days_until(self, other: Self) -> i64 {
        other.day_number() - self.day_number()
    }

    /// The day Unix second `unix_seconds` falls on in `zone`. Instants outside
    /// the supported range clamp to its first or last day.
    #[must_use]
    pub fn of_instant(unix_seconds: i64, zone: &TimeZone) -> Self {
        // Two days of margin covers every UTC offset.
        let lowest = (Self::EARLIEST.day_number() - 2) * SECONDS_PER_DAY;
        let highest = (Self::LATEST.day_number() + 2) * SECONDS_PER_DAY;
        if unix_seconds <= lowest {
            return Self::EARLIEST;
        }
        if unix_seconds >= highest {
            return Self::LATEST;
        }
        let local = unix_seconds + i64::from(zone.offset_seconds_at(unix_seconds));
        Self::from_day_number_clamped(local.div_euclid(SECONDS_PER_DAY))
    }

    /// The instant (Unix seconds) of local wall-clock time `seconds_of_day`
    /// (0..86 400) on this day in `zone`, with Python `fold=0` semantics for a
    /// DST gap or repeated time (see the module documentation).
    ///
    /// Total: at the extremes of the supported range (where Python's
    /// `astimezone(UTC)` raises `OverflowError`) the offset at the nearest
    /// representable instant is used.
    #[must_use]
    pub fn at_local_time(self, seconds_of_day: u32, zone: &TimeZone) -> i64 {
        let seconds = seconds_of_day.min(86_399);
        let civil = i8::try_from(seconds / 3600)
            .ok()
            .zip(i8::try_from(seconds % 3600 / 60).ok())
            .zip(i8::try_from(seconds % 60).ok())
            .and_then(|((hour, minute), second)| {
                DateTime::new(
                    i16::try_from(self.year).ok()?,
                    i8::try_from(self.month).ok()?,
                    i8::try_from(self.day).ok()?,
                    hour,
                    minute,
                    second,
                    0,
                )
                .ok()
            });
        let local = self.day_number() * SECONDS_PER_DAY + i64::from(seconds);
        match civil.and_then(|civil| zone.0.to_ambiguous_timestamp(civil).compatible().ok()) {
            Some(timestamp) => timestamp.as_second(),
            // Beyond the instants jiff can represent: keep the offset in force
            // at the nearest representable instant.
            None => local - i64::from(zone.offset_seconds_at(local)),
        }
    }

    /// The first instant of this day in `zone` (`formulation.due_start`):
    /// local midnight, resolved with Python `fold=0` semantics. A day a zone
    /// skipped entirely starts at the same instant as the day after it.
    #[must_use]
    pub fn start_instant(self, zone: &TimeZone) -> i64 {
        self.at_local_time(0, zone)
    }
}

impl fmt::Display for CalendarDay {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:04}-{:02}-{:02}", self.year, self.month, self.day)
    }
}

impl FromStr for CalendarDay {
    type Err = InvalidCalendarDay;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::parse_iso(value)
    }
}

/// Days in `month` of `year` under the Gregorian leap-year rule.
#[must_use]
pub fn days_in_month(year: u16, month: u8) -> u8 {
    match month {
        2 if (year.is_multiple_of(4) && !year.is_multiple_of(100)) || year.is_multiple_of(400) => {
            29
        }
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

/// A string that is not an RFC 3339 instant a Python `datetime` can hold: the
/// shape is wrong, a field is out of range (including the leap second `:60`,
/// which `datetime.fromisoformat` refuses), or the UTC result falls outside
/// years 0001 to 9999.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InvalidInstant;

impl fmt::Display for InvalidInstant {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("expected an RFC 3339 instant within years 0001 to 9999")
    }
}

impl std::error::Error for InvalidInstant {}

const MICROS_PER_SECOND: i64 = 1_000_000;

/// A point in time, normalized to UTC with microsecond precision: what
/// `from_isoformat(value)` (`backend/app/utils/time.py`) returns as an aware
/// UTC `datetime`. The bb-protocol `Instant` is validated text with no order;
/// this is the value the rules compare and add spans to.
///
/// The range is 0001-01-01T00:00:00Z through 9999-12-31T23:59:59.999999Z, like
/// `datetime`. Where Python raises `OverflowError` for arithmetic past it, the
/// result here clamps to the range, so every value renders and parses again.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct UtcInstant {
    micros: i64,
}

impl UtcInstant {
    /// 0001-01-01T00:00:00Z.
    pub const EARLIEST: Self = Self {
        micros: -62_135_596_800 * MICROS_PER_SECOND,
    };
    /// 9999-12-31T23:59:59.999999Z.
    pub const LATEST: Self = Self {
        micros: 253_402_300_800 * MICROS_PER_SECOND - 1,
    };

    /// Microseconds since the Unix epoch, clamped to the supported range.
    #[must_use]
    pub fn from_unix_micros_clamped(micros: i64) -> Self {
        Self {
            micros: micros.clamp(Self::EARLIEST.micros, Self::LATEST.micros),
        }
    }

    /// Whole Unix seconds, clamped to the supported range.
    #[must_use]
    pub fn from_unix_seconds_clamped(seconds: i64) -> Self {
        Self::from_unix_micros_clamped(seconds.saturating_mul(MICROS_PER_SECOND))
    }

    /// Microseconds since the Unix epoch.
    #[must_use]
    pub fn unix_micros(self) -> i64 {
        self.micros
    }

    /// Unix seconds, rounded toward negative infinity.
    #[must_use]
    pub fn unix_seconds(self) -> i64 {
        self.micros.div_euclid(MICROS_PER_SECOND)
    }

    /// This instant `micros` later (earlier when negative), clamped.
    #[must_use]
    pub fn plus_micros(self, micros: i64) -> Self {
        Self::from_unix_micros_clamped(self.micros.saturating_add(micros))
    }

    /// This instant `seconds` later (earlier when negative), clamped.
    #[must_use]
    pub fn plus_seconds(self, seconds: i64) -> Self {
        self.plus_micros(seconds.saturating_mul(MICROS_PER_SECOND))
    }

    /// Microseconds from `earlier` to `self`: positive when `self` is later.
    #[must_use]
    pub fn micros_since(self, earlier: Self) -> i64 {
        self.micros - earlier.micros
    }

    /// Parses an RFC 3339 instant (`Z` or a numeric `±hh:mm` offset, optional
    /// fraction) and normalizes it to UTC. A fraction past six digits is
    /// truncated, as `datetime.fromisoformat` does.
    ///
    /// # Errors
    ///
    /// [`InvalidInstant`] for any other text.
    pub fn parse_rfc3339(value: &str) -> Result<Self, InvalidInstant> {
        let bytes = value.as_bytes();
        if !value.is_ascii() || bytes.len() < 20 {
            return Err(InvalidInstant);
        }
        let number = |range: std::ops::Range<usize>| -> Option<i64> {
            bytes[range].iter().try_fold(0_i64, |acc, byte| {
                byte.is_ascii_digit()
                    .then(|| acc * 10 + i64::from(byte - b'0'))
            })
        };
        let separators = bytes[4] == b'-'
            && bytes[7] == b'-'
            && matches!(bytes[10], b'T' | b't')
            && bytes[13] == b':'
            && bytes[16] == b':';
        let fields = (
            number(0..4),
            number(5..7),
            number(8..10),
            number(11..13),
            number(14..16),
            number(17..19),
        );
        let (Some(year), Some(month), Some(day), Some(hour), Some(minute), Some(second)) = fields
        else {
            return Err(InvalidInstant);
        };
        if !separators || hour > 23 || minute > 59 || second > 59 {
            return Err(InvalidInstant);
        }
        let date = CalendarDay::new(
            i32::try_from(year).map_err(|_| InvalidInstant)?,
            u32::try_from(month).map_err(|_| InvalidInstant)?,
            u32::try_from(day).map_err(|_| InvalidInstant)?,
        )
        .ok_or(InvalidInstant)?;

        let mut rest = &value[19..];
        let mut micros = 0_i64;
        if let Some(fraction) = rest.strip_prefix('.') {
            let digits = fraction.bytes().take_while(u8::is_ascii_digit).count();
            if digits == 0 {
                return Err(InvalidInstant);
            }
            let kept = &fraction[..digits.min(6)];
            let scale = 10_i64.pow(u32::try_from(6 - kept.len()).map_err(|_| InvalidInstant)?);
            micros = kept.parse::<i64>().map_err(|_| InvalidInstant)? * scale;
            rest = &fraction[digits..];
        }
        let offset_seconds = match rest.as_bytes() {
            [b'Z' | b'z'] => 0,
            [sign @ (b'+' | b'-'), h1, h2, b':', m1, m2]
                if [h1, h2, m1, m2].iter().all(|b| b.is_ascii_digit()) =>
            {
                let hours = i64::from((h1 - b'0') * 10 + (h2 - b'0'));
                let minutes = i64::from((m1 - b'0') * 10 + (m2 - b'0'));
                if hours > 23 || minutes > 59 {
                    return Err(InvalidInstant);
                }
                let magnitude = hours * 3600 + minutes * 60;
                if *sign == b'-' { -magnitude } else { magnitude }
            }
            _ => return Err(InvalidInstant),
        };

        let local_seconds =
            date.day_number() * SECONDS_PER_DAY + hour * 3600 + minute * 60 + second;
        let total = (local_seconds - offset_seconds) * MICROS_PER_SECOND + micros;
        if (Self::EARLIEST.micros..=Self::LATEST.micros).contains(&total) {
            Ok(Self { micros: total })
        } else {
            Err(InvalidInstant)
        }
    }

    /// The server's wire spelling: UTC with a `Z` suffix, whole seconds, and
    /// `.ffffff` only when the microseconds are not zero (`isoformat()` as
    /// pydantic serializes an aware `datetime`).
    #[must_use]
    pub fn to_rfc3339(self) -> String {
        let seconds = self.unix_seconds();
        let micros = self.micros.rem_euclid(MICROS_PER_SECOND);
        let day = CalendarDay::from_day_number_clamped(seconds.div_euclid(SECONDS_PER_DAY));
        let in_day = seconds.rem_euclid(SECONDS_PER_DAY);
        let clock = format!(
            "{:02}:{:02}:{:02}",
            in_day / 3600,
            in_day % 3600 / 60,
            in_day % 60
        );
        if micros == 0 {
            format!("{day}T{clock}Z")
        } else {
            format!("{day}T{clock}.{micros:06}Z")
        }
    }
}

impl fmt::Display for UtcInstant {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.to_rfc3339())
    }
}

impl FromStr for UtcInstant {
    type Err = InvalidInstant;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::parse_rfc3339(value)
    }
}

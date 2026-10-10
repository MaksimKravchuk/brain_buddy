//! Checked scalars: PATCH values, Unicode-scalar bounded text, identifiers and
//! calendar/clock strings. Every value is validated when it is parsed, so a
//! value of one of these types is always well formed. Wire counters, instants
//! and command IDs are `bb_protocol::wire` types and are not redefined here.

use super::errors::{DomainError, Reason};
use serde::de::Error as _;
use serde::{Deserialize, Deserializer, Serialize, Serializer};

/// A PATCH field: omitted (unchanged), `null` (clear) or a value (set).
///
/// Use with `#[serde(default, skip_serializing_if = "Patch::is_unchanged")]`;
/// without the skip an unchanged field would serialize as `null` (clear).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub enum Patch<T> {
    #[default]
    Unchanged,
    Clear,
    Set(T),
}

impl<T> Patch<T> {
    pub fn is_unchanged(&self) -> bool {
        matches!(self, Patch::Unchanged)
    }
}

impl<'de, T: Deserialize<'de>> Deserialize<'de> for Patch<T> {
    /// Only reached when the key is present: `null` clears, anything else sets.
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Ok(Option::<T>::deserialize(deserializer)?.map_or(Patch::Clear, Patch::Set))
    }
}

impl<T: Serialize> Serialize for Patch<T> {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Patch::Set(value) => value.serialize(serializer),
            Patch::Clear | Patch::Unchanged => serializer.serialize_none(),
        }
    }
}

/// An optional field that may be omitted but is never sent as `null`: a field
/// that cannot be cleared (title, priority) refuses `null` instead of reading
/// it as "omitted".
pub(crate) fn non_null<'de, D: Deserializer<'de>, T: Deserialize<'de>>(
    deserializer: D,
) -> Result<Option<T>, D::Error> {
    T::deserialize(deserializer).map(Some)
}

fn scalars_in(value: &str, min: usize, max: usize) -> bool {
    (min..=max).contains(&value.chars().count())
}

macro_rules! bounded_text {
    ($($(#[$doc:meta])* $name:ident: $min:literal..=$max:literal;)*) => {$(
        $(#[$doc])*
        #[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            pub const MIN_SCALARS: usize = $min;
            pub const MAX_SCALARS: usize = $max;

            /// Counts Unicode scalar values, never bytes.
            pub fn new(value: impl Into<String>) -> Result<Self, DomainError> {
                let value = value.into();
                if scalars_in(&value, $min, $max) {
                    Ok(Self(value))
                } else {
                    Err(DomainError::field(Reason::TextLength, stringify!($name)))
                }
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }

            pub fn into_string(self) -> String {
                self.0
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
                Self::new(String::deserialize(deserializer)?)
                    .map_err(|_| D::Error::custom(concat!("invalid ", stringify!($name))))
            }
        }
    )*};
}

bounded_text! {
    /// Task or subtask title: 1 to 500 scalars.
    Title: 1..=500;
    /// Task details: up to 20,000 scalars (may be empty).
    Details: 0..=20_000;
    /// Comment body: 1 to 20,000 scalars.
    CommentBody: 1..=20_000;
    /// Project or tag name: 1 to 500 scalars.
    Name: 1..=500;
    /// Project desired outcome as stored: 1 to 1,000 scalars, already trimmed.
    DesiredOutcome: 1..=1_000;
    /// Waiting-for metadata: up to 500 scalars.
    WaitingFor: 0..=500;
    /// Review short text (decision title, reason, extension reason): 1 to 500.
    ShortText: 1..=500;
    /// Project colour: up to 64 scalars.
    Color: 0..=64;
    /// IANA time-zone name as written: 1 to 64 scalars (zone validity is the
    /// calendar family's, `INVALID_TIME_ZONE`).
    ZoneName: 1..=64;
    /// Navigator provider label: 1 to 64 scalars.
    ProviderName: 1..=64;
}

impl DesiredOutcome {
    /// Request input: trimmed first, and blank means "no outcome" (spec 021).
    /// Trimming is Python's `str.strip()` (`_trim_outcome`), which also strips
    /// U+001C..U+001F; `str::trim` does not.
    pub fn from_input(value: &str) -> Result<Option<Self>, DomainError> {
        let trimmed = crate::normalization::strip(value);
        if trimmed.is_empty() {
            Ok(None)
        } else {
            Self::new(trimmed).map(Some)
        }
    }
}

/// `desired_outcome` on create: trimmed, blank is none.
pub(crate) fn outcome_input<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<DesiredOutcome>, D::Error> {
    match Option::<String>::deserialize(deserializer)? {
        None => Ok(None),
        Some(raw) => {
            DesiredOutcome::from_input(&raw).map_err(|_| D::Error::custom("invalid DesiredOutcome"))
        }
    }
}

/// `desired_outcome` on update: omitted keeps, `null` or blank clears.
pub(crate) fn outcome_patch<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Patch<DesiredOutcome>, D::Error> {
    Ok(outcome_input(deserializer)?.map_or(Patch::Clear, Patch::Set))
}

/// A free-text reason: trimmed first, so whitespace alone is empty (http §3).
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(transparent)]
pub struct ReasonText(String);

impl ReasonText {
    pub fn new(value: &str) -> Result<Self, DomainError> {
        // pydantic's `strip_whitespace=True` trims Unicode `White_Space` only
        // (it keeps U+001C..U+001F), unlike Python's `str.strip()`.
        let trimmed = value.trim();
        if scalars_in(trimmed, 1, 500) {
            Ok(Self(trimmed.to_owned()))
        } else {
            Err(DomainError::field(Reason::TextLength, "ReasonText"))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for ReasonText {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Self::new(&String::deserialize(deserializer)?)
            .map_err(|_| D::Error::custom("invalid ReasonText"))
    }
}

// ------------------------------------------------------------------ identifiers

fn is_lower_hex(byte: u8) -> bool {
    byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)
}

/// Lowercase UUID text, as client-created IDs and Navigator request IDs use.
fn is_lower_uuid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(i, b)| match i {
            8 | 13 | 18 | 23 => b == b'-',
            _ => is_lower_hex(b),
        })
}

/// Historical Swift formulation references retain their UUID text verbatim.
fn is_legacy_formulation_uuid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(i, b)| match i {
            8 | 13 | 18 | 23 => b == b'-',
            _ => b.is_ascii_hexdigit(),
        })
}

/// `<prefix>_<lowercase uuid>`, at most 64 characters: the shape a client mints.
fn is_client_shape(value: &str, prefix: &str) -> bool {
    value.len() <= 64
        && value
            .strip_prefix(prefix)
            .and_then(|rest| rest.strip_prefix('_'))
            .is_some_and(is_lower_uuid)
}

/// The client shape or the legacy server-minted `<prefix>_<12 lowercase hex>`:
/// what a reference to an existing record accepts.
fn is_reference_shape(value: &str, prefix: &str) -> bool {
    is_client_shape(value, prefix)
        || (value.len() <= 64
            && value
                .strip_prefix(prefix)
                .and_then(|rest| rest.strip_prefix('_'))
                .is_some_and(|rest| rest.len() == 12 && rest.bytes().all(is_lower_hex)))
}

macro_rules! id_type {
    ($(#[$doc:meta])* $name:ident, $check:expr) => {
        $(#[$doc])*
        #[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            /// Validates and wraps an identifier.
            pub fn parse(value: impl Into<String>) -> Result<Self, DomainError> {
                let value = value.into();
                let check: fn(&str) -> bool = $check;
                if check(&value) {
                    Ok(Self(value))
                } else {
                    Err(DomainError::field(Reason::InvalidValue, stringify!($name)))
                }
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }

            pub fn into_string(self) -> String {
                self.0
            }
        }

        impl std::fmt::Display for $name {
            fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
                f.write_str(&self.0)
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
                Self::parse(String::deserialize(deserializer)?)
                    .map_err(|_| D::Error::custom(concat!("invalid ", stringify!($name))))
            }
        }
    };
}

/// Task and organization identifiers keep every legacy and alias shape
/// verbatim (data-model.md): only emptiness is refused. `parse_new` checks the
/// shape new native records are minted in, `<prefix>_<lowercase uuid>`.
macro_rules! legacy_id {
    ($($(#[$doc:meta])* $name:ident: $prefix:literal;)*) => {$(
        id_type!($(#[$doc])* $name, |s| !s.is_empty());

        impl $name {
            pub const PREFIX: &'static str = $prefix;

            /// A new native ID: `<prefix>_<lowercase uuid>`.
            pub fn parse_new(value: impl Into<String>) -> Result<Self, DomainError> {
                let value = value.into();
                if is_client_shape(&value, $prefix) {
                    Ok(Self(value))
                } else {
                    Err(DomainError::field(Reason::InvalidValue, stringify!($name)))
                }
            }

            /// Whether this is a native-shaped ID (as opposed to a legacy or alias one).
            pub fn has_native_shape(&self) -> bool {
                is_client_shape(&self.0, $prefix)
            }
        }
    )*};
}

legacy_id! {
    TaskId: "task";
    ProjectId: "project";
    TagId: "tag";
    SubtaskId: "subtask";
    CommentId: "comment";
}

id_type!(
    /// The server-derived author of a comment; never read from a client payload.
    ActorId,
    |s| !s.is_empty()
);
id_type!(
    /// A source Capture identifier (never source text).
    CaptureId,
    |s| !s.is_empty()
);

/// Review identifiers are shape-checked (sync-v1 §2, http §1): the reference
/// type accepts the client or the legacy server-minted shape, `parse_new` only
/// the client shape.
macro_rules! review_id {
    ($($(#[$doc:meta])* $name:ident: $prefix:literal;)*) => {$(
        id_type!($(#[$doc])* $name, |s| is_reference_shape(s, $prefix));

        impl $name {
            pub const PREFIX: &'static str = $prefix;

            /// A new ID as a client mints it: `<prefix>_<lowercase uuid>`.
            pub fn parse_new(value: impl Into<String>) -> Result<Self, DomainError> {
                let value = value.into();
                if is_client_shape(&value, $prefix) {
                    Ok(Self(value))
                } else {
                    Err(DomainError::field(Reason::InvalidValue, stringify!($name)))
                }
            }

            pub fn has_client_shape(&self) -> bool {
                is_client_shape(&self.0, $prefix)
            }
        }
    )*};
}

id_type!(
    /// An existing formulation reference, including imported Swift UUIDs.
    FormulationId,
    |s| is_reference_shape(s, "form") || is_legacy_formulation_uuid(s)
);

impl FormulationId {
    pub const PREFIX: &'static str = "form";

    /// A new ID as a native client mints it: `form_<lowercase uuid>`.
    pub fn parse_new(value: impl Into<String>) -> Result<Self, DomainError> {
        let value = value.into();
        if is_client_shape(&value, Self::PREFIX) {
            Ok(Self(value))
        } else {
            Err(DomainError::field(Reason::InvalidValue, "FormulationId"))
        }
    }

    /// A newly allocated native or server ID; excludes historical bare UUIDs.
    pub fn parse_allocated(value: impl Into<String>) -> Result<Self, DomainError> {
        let value = value.into();
        if is_reference_shape(&value, Self::PREFIX) {
            Ok(Self(value))
        } else {
            Err(DomainError::field(Reason::InvalidValue, "FormulationId"))
        }
    }

    pub fn has_client_shape(&self) -> bool {
        is_client_shape(&self.0, Self::PREFIX)
    }
}

review_id! {
    /// A Review session reference.
    SessionId: "review";
    /// A decision reference.
    DecisionId: "decision";
    /// A bulk-release reference.
    BulkId: "bulk";
}

/// IDs a request creates carry the client shape only (http §1, §3, §6).
macro_rules! client_id {
    ($($(#[$doc:meta])* $name:ident: $prefix:literal => $wide:ident;)*) => {$(
        id_type!($(#[$doc])* $name, |s| is_client_shape(s, $prefix));

        impl From<$name> for $wide {
            fn from(value: $name) -> Self {
                $wide(value.0)
            }
        }
    )*};
}

client_id! {
    /// A formulation ID the request starts (`new_formulation_id`).
    NewFormulationId: "form" => FormulationId;
    /// A decision ID the client creates offline.
    NewDecisionId: "decision" => DecisionId;
    /// A follow-up task the decision creates.
    FollowUpTaskId: "task" => TaskId;
}

id_type!(
    /// The replay-safe identity of one Review progress merge.
    ProgressId,
    |s| is_client_shape(s, "progress")
);
id_type!(
    /// A Navigator request ID: a lowercase UUID, 36 characters.
    NavigatorRequestId,
    is_lower_uuid
);

// -------------------------------------------------------------- calendar & clock

/// Due day as `YYYY-MM-DD`, a real calendar date (year 1 to 9999). Date
/// arithmetic belongs to the calendar family.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize)]
#[serde(transparent)]
pub struct DueDay(String);

impl DueDay {
    pub fn parse(value: impl Into<String>) -> Result<Self, DomainError> {
        let value = value.into();
        if is_calendar_day(&value) {
            Ok(Self(value))
        } else {
            Err(DomainError::field(Reason::InvalidValue, "DueDay"))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// `(year, month, day)`.
    pub fn parts(&self) -> (u16, u8, u8) {
        let number = |range: std::ops::Range<usize>| self.0[range].parse::<u16>().unwrap_or(0);
        (number(0..4), number(5..7) as u8, number(8..10) as u8)
    }
}

fn is_calendar_day(value: &str) -> bool {
    let bytes = value.as_bytes();
    if bytes.len() != 10
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || !bytes
            .iter()
            .enumerate()
            .all(|(i, b)| matches!(i, 4 | 7) || b.is_ascii_digit())
    {
        return false;
    }
    let number = |range: std::ops::Range<usize>| value[range].parse::<u32>().unwrap_or(0);
    let (year, month, day) = (number(0..4), number(5..7), number(8..10));
    let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    let days = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if leap => 29,
        2 => 28,
        _ => return false,
    };
    year >= 1 && (1..=days).contains(&day)
}

impl<'de> Deserialize<'de> for DueDay {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Self::parse(String::deserialize(deserializer)?)
            .map_err(|_| D::Error::custom("invalid DueDay"))
    }
}

/// Review wall time `HH:MM`, 00:00 to 23:59, read in the settings' IANA zone.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize)]
#[serde(transparent)]
pub struct WallTime(String);

impl WallTime {
    pub fn parse(value: impl Into<String>) -> Result<Self, DomainError> {
        let value = value.into();
        if is_wall_time(&value) {
            Ok(Self(value))
        } else {
            Err(DomainError::field(Reason::InvalidValue, "WallTime"))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// `(hour, minute)`.
    pub fn hour_minute(&self) -> (u8, u8) {
        let number = |range: std::ops::Range<usize>| self.0[range].parse::<u8>().unwrap_or(0);
        (number(0..2), number(3..5))
    }
}

/// `^([01][0-9]|2[0-3]):[0-5][0-9]$`
fn is_wall_time(value: &str) -> bool {
    let [h1, h2, b':', m1, m2] = *value.as_bytes() else {
        return false;
    };
    let hour_ok = match h1 {
        b'0' | b'1' => h2.is_ascii_digit(),
        b'2' => matches!(h2, b'0'..=b'3'),
        _ => false,
    };
    hour_ok && matches!(m1, b'0'..=b'5') && m2.is_ascii_digit()
}

impl<'de> Deserialize<'de> for WallTime {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Self::parse(String::deserialize(deserializer)?)
            .map_err(|_| D::Error::custom("invalid WallTime"))
    }
}

/// Review threshold: one of 7, 14, 21 or 28 days.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize)]
#[serde(transparent)]
pub struct ThresholdDays(u8);

impl ThresholdDays {
    pub fn new(days: u8) -> Result<Self, DomainError> {
        match days {
            7 | 14 | 21 | 28 => Ok(Self(days)),
            _ => Err(DomainError::field(Reason::InvalidValue, "ThresholdDays")),
        }
    }

    pub fn get(self) -> u8 {
        self.0
    }
}

impl<'de> Deserialize<'de> for ThresholdDays {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Self::new(u8::deserialize(deserializer)?)
            .map_err(|_| D::Error::custom("invalid ThresholdDays"))
    }
}

/// Review weekday, ISO 1 (Monday) to 7 (Sunday).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize)]
#[serde(transparent)]
pub struct Weekday(u8);

impl Weekday {
    pub fn new(day: u8) -> Result<Self, DomainError> {
        if (1..=7).contains(&day) {
            Ok(Self(day))
        } else {
            Err(DomainError::field(Reason::InvalidValue, "Weekday"))
        }
    }

    pub fn get(self) -> u8 {
        self.0
    }
}

impl<'de> Deserialize<'de> for Weekday {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Self::new(u8::deserialize(deserializer)?).map_err(|_| D::Error::custom("invalid Weekday"))
    }
}

/// A Navigator consent-text version: 1 or more.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, Serialize)]
#[serde(transparent)]
pub struct TextVersion(u32);

impl TextVersion {
    pub fn new(version: u32) -> Result<Self, DomainError> {
        if version >= 1 {
            Ok(Self(version))
        } else {
            Err(DomainError::field(Reason::InvalidValue, "TextVersion"))
        }
    }

    pub fn get(self) -> u32 {
        self.0
    }
}

impl<'de> Deserialize<'de> for TextVersion {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Self::new(u32::deserialize(deserializer)?)
            .map_err(|_| D::Error::custom("invalid TextVersion"))
    }
}

/// The literal `true`: a flag that can only be switched on (`onboarded`,
/// `snapshot_decision_queue`). `false` is refused, not read as "off".
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(transparent)]
pub struct True(bool);

impl True {
    pub const VALUE: True = True(true);
}

impl<'de> Deserialize<'de> for True {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        if bool::deserialize(deserializer)? {
            Ok(Self(true))
        } else {
            Err(D::Error::custom("only true is accepted"))
        }
    }
}

/// A list with a request ceiling (bulk release 500, park acknowledgement 200,
/// skipped steps 10); longer lists are refused when decoded.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
#[serde(transparent)]
pub struct Limited<T, const MAX: usize>(Vec<T>);

impl<T, const MAX: usize> Limited<T, MAX> {
    pub const MAX_ITEMS: usize = MAX;

    pub fn new(items: Vec<T>) -> Result<Self, DomainError> {
        if items.len() <= MAX {
            Ok(Self(items))
        } else {
            Err(DomainError::new(Reason::TooManyItems))
        }
    }

    pub fn as_slice(&self) -> &[T] {
        &self.0
    }

    pub fn into_vec(self) -> Vec<T> {
        self.0
    }
}

impl<T, const MAX: usize> Default for Limited<T, MAX> {
    fn default() -> Self {
        Self(Vec::new())
    }
}

impl<'de, T: Deserialize<'de>, const MAX: usize> Deserialize<'de> for Limited<T, MAX> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        Self::new(Vec::<T>::deserialize(deserializer)?)
            .map_err(|_| D::Error::custom("too many items"))
    }
}

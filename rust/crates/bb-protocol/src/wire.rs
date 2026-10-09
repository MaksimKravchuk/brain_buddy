//! Validated scalar types and the shared decode entry point (sync-v1 §2, §11).
//!
//! Every counter, identifier and instant is checked when it is parsed, so a value
//! of one of these types is always well formed. Errors never echo input text.

use crate::strict_json;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Deserializer, Serialize, de};
use serde_json::{Map, Value};
use std::fmt;

/// The only protocol version this crate executes.
pub const PROTOCOL_VERSION: u32 = 1;

/// A content-free codec failure; every variant maps to a stable wire code.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CodecError {
    /// Not JSON, or JSON of the wrong shape. Carries only the parser position.
    Malformed { line: usize, column: usize },
    /// An object repeated a key (sync-v1 §4 step 1).
    DuplicateKey,
    /// A well-formed value that breaks a contract rule; names the rule only.
    Invalid(&'static str),
}

impl CodecError {
    /// The wire error code a server reports for this failure.
    pub fn code(&self) -> &'static str {
        "INVALID_REQUEST"
    }
}

impl fmt::Display for CodecError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Malformed { line, column } => write!(f, "malformed message at {line}:{column}"),
            Self::DuplicateKey => f.write_str("duplicate JSON object key"),
            Self::Invalid(what) => write!(f, "invalid {what}"),
        }
    }
}

impl std::error::Error for CodecError {}

impl From<serde_json::Error> for CodecError {
    fn from(error: serde_json::Error) -> Self {
        Self::Malformed {
            line: error.line(),
            column: error.column(),
        }
    }
}

/// A wire message with contract rules beyond its field types.
pub trait Wire: DeserializeOwned {
    /// Checks the cross-field rules of sync-v1 §11; the default has none.
    fn validate(&self) -> Result<(), CodecError> {
        Ok(())
    }
}

/// Decodes one wire message: duplicate keys and malformed shapes are errors,
/// then the message's own rules are checked.
pub fn decode<T: Wire>(json: &str) -> Result<T, CodecError> {
    strict_json::reject_duplicate_keys(json)?;
    let message: T = serde_json::from_str(json)?;
    message.validate()?;
    Ok(message)
}

macro_rules! wire_string {
    ($(#[$meta:meta])* $name:ident, $check:expr) => {
        $(#[$meta])*
        #[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            /// Validates and wraps a wire value.
            pub fn parse(value: impl Into<String>) -> Result<Self, CodecError> {
                let value = value.into();
                let check: fn(&str) -> bool = $check;
                if check(&value) { Ok(Self(value)) } else { Err(CodecError::Invalid(stringify!($name))) }
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
                Self::parse(String::deserialize(deserializer)?)
                    .map_err(|_| de::Error::custom(concat!("invalid ", stringify!($name))))
            }
        }
    };
}

wire_string!(
    /// Nonnegative canonical decimal string: no sign, no leading zeros except `"0"`.
    Counter,
    |s| s == "0" || (!s.is_empty() && !s.starts_with('0') && s.bytes().all(|b| b.is_ascii_digit()))
);
wire_string!(
    /// A command ID: a UUID. Distinct from [`CorrelationId`] by construction.
    CommandId,
    is_uuid
);
wire_string!(
    /// An opaque support reference; never a command identity.
    CorrelationId,
    |s| !s.is_empty()
);
wire_string!(
    /// A nonempty opaque identifier (scope, device, epoch, entity, transfer, ...).
    Id,
    |s| !s.is_empty()
);
wire_string!(
    /// An opaque server or feed generation.
    Generation,
    |s| !s.is_empty()
);
wire_string!(
    /// An RFC 3339 instant.
    Instant,
    is_rfc3339
);

impl From<u64> for Counter {
    fn from(value: u64) -> Self {
        Self(value.to_string())
    }
}

impl Counter {
    /// The value, or `None` when it does not fit in `u64`.
    pub fn to_u64(&self) -> Option<u64> {
        self.0.parse().ok()
    }
}

/// A record key: the key components of one record; empty for singletons.
pub type RecordKey = Vec<String>;

/// A version marker whose JSON type sync-v1 does not fix.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Marker {
    Text(String),
    Number(i64),
}

/// Fields carried by every authorized JSON response (sync-v1 §11).
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommonResponse {
    pub correlation_id: CorrelationId,
    pub scope_id: Id,
    pub server_generation: Generation,
    pub server_now: Instant,
}

/// An open JSON object whose inner keys the contract leaves to later layers.
pub type OpenObject = Map<String, Value>;

/// Deserializes a field that must be present but may be `null`.
pub(crate) fn required<'de, D: Deserializer<'de>, T: Deserialize<'de>>(
    deserializer: D,
) -> Result<Option<T>, D::Error> {
    Option::deserialize(deserializer)
}

/// Defines a closed string enum with `ALL`, `as_str` and `from_wire`.
macro_rules! wire_enum {
    ($(#[$meta:meta])* $name:ident { $($(#[$vmeta:meta])* $variant:ident => $wire:literal),+ $(,)? }) => {
        $(#[$meta])*
        #[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
        pub enum $name {
            $($(#[$vmeta])* $variant),+
        }

        impl $name {
            /// Every variant, in contract order.
            pub const ALL: &'static [Self] = &[$(Self::$variant),+];

            pub fn as_str(self) -> &'static str {
                match self { $(Self::$variant => $wire),+ }
            }

            pub fn from_wire(value: &str) -> Option<Self> {
                match value { $($wire => Some(Self::$variant),)+ _ => None }
            }
        }

        impl ::serde::Serialize for $name {
            fn serialize<S: ::serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
                serializer.serialize_str(self.as_str())
            }
        }

        impl<'de> ::serde::Deserialize<'de> for $name {
            fn deserialize<D: ::serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
                Self::from_wire(&<String as ::serde::Deserialize>::deserialize(deserializer)?)
                    .ok_or_else(|| ::serde::de::Error::custom(concat!("unknown ", stringify!($name))))
            }
        }
    };
}
pub(crate) use wire_enum;

fn is_uuid(s: &str) -> bool {
    let b = s.as_bytes();
    b.len() == 36
        && b.iter().enumerate().all(|(i, c)| match i {
            8 | 13 | 18 | 23 => *c == b'-',
            _ => c.is_ascii_hexdigit(),
        })
}

fn is_rfc3339(s: &str) -> bool {
    if !s.is_ascii() || s.len() < 20 {
        return false;
    }
    let b = s.as_bytes();
    let num = |r: std::ops::Range<usize>| -> Option<u32> {
        let digits = &b[r.clone()];
        if digits.iter().all(u8::is_ascii_digit) {
            s[r].parse().ok()
        } else {
            None
        }
    };
    let (Some(year), Some(month), Some(day), Some(hour), Some(minute), Some(second)) = (
        num(0..4),
        num(5..7),
        num(8..10),
        num(11..13),
        num(14..16),
        num(17..19),
    ) else {
        return false;
    };
    let separators = b[4] == b'-'
        && b[7] == b'-'
        && matches!(b[10], b'T' | b't')
        && b[13] == b':'
        && b[16] == b':';
    let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
    let days = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if leap => 29,
        2 => 28,
        _ => return false,
    };
    if !(separators && (1..=days).contains(&day) && hour < 24 && minute < 60 && second <= 60) {
        return false;
    }
    let mut rest = &s[19..];
    if let Some(fraction) = rest.strip_prefix('.') {
        let digits = fraction.bytes().take_while(u8::is_ascii_digit).count();
        if digits == 0 {
            return false;
        }
        rest = &fraction[digits..];
    }
    match rest.as_bytes() {
        [b'Z' | b'z'] => true,
        [b'+' | b'-', h1, h2, b':', m1, m2] => {
            [h1, h2, m1, m2].iter().all(|d| d.is_ascii_digit())
                && (h1 - b'0') * 10 + (h2 - b'0') < 24
                && (m1 - b'0') * 10 + (m2 - b'0') < 60
        }
        _ => false,
    }
}

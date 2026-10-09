//! Duplicate-key rejection (sync-v1 §4 step 1 and the fingerprint rules).
//!
//! `serde_json` silently keeps the last of two equal keys, which would let two
//! different documents produce one parsed value. Every decode path therefore
//! scans the raw text first.

use crate::wire::CodecError;
use serde::Deserialize;
use serde::de::{self, Deserializer};
use std::collections::HashSet;
use std::fmt;

/// Rejects any JSON object that repeats a key, at any depth, and any text that
/// is not exactly one JSON value.
pub fn reject_duplicate_keys(json: &str) -> Result<(), CodecError> {
    let mut deserializer = serde_json::Deserializer::from_str(json);
    match Strict::deserialize(&mut deserializer).and_then(|_| deserializer.end()) {
        Ok(()) => Ok(()),
        Err(error) if error.is_data() => Err(CodecError::DuplicateKey),
        Err(error) => Err(error.into()),
    }
}

struct Strict;

impl<'de> Deserialize<'de> for Strict {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_any(Strict)
    }
}

impl<'de> de::Visitor<'de> for Strict {
    type Value = Strict;

    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("JSON")
    }

    fn visit_bool<E>(self, _: bool) -> Result<Strict, E> {
        Ok(Strict)
    }

    fn visit_i64<E>(self, _: i64) -> Result<Strict, E> {
        Ok(Strict)
    }

    fn visit_u64<E>(self, _: u64) -> Result<Strict, E> {
        Ok(Strict)
    }

    fn visit_f64<E>(self, _: f64) -> Result<Strict, E> {
        Ok(Strict)
    }

    fn visit_str<E>(self, _: &str) -> Result<Strict, E> {
        Ok(Strict)
    }

    fn visit_unit<E>(self) -> Result<Strict, E> {
        Ok(Strict)
    }

    fn visit_seq<A: de::SeqAccess<'de>>(self, mut seq: A) -> Result<Strict, A::Error> {
        while seq.next_element::<Strict>()?.is_some() {}
        Ok(Strict)
    }

    fn visit_map<A: de::MapAccess<'de>>(self, mut map: A) -> Result<Strict, A::Error> {
        let mut keys = HashSet::new();
        while let Some(key) = map.next_key::<String>()? {
            if !keys.insert(key) {
                return Err(de::Error::custom("duplicate key"));
            }
            map.next_value::<Strict>()?;
        }
        Ok(Strict)
    }
}

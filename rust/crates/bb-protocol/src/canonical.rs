//! RFC 8785 bytes for protected immutable command fingerprints (sync-v1 §4).
//! This is separate from ordinary wire encoding and never normalizes Unicode.

use crate::{strict_json, wire::CodecError};
use serde_json::Value;

pub fn canonical_json(bytes: &[u8]) -> Result<Vec<u8>, CodecError> {
    let text = std::str::from_utf8(bytes).map_err(|_| CodecError::Invalid("JSON encoding"))?;
    strict_json::reject_duplicate_keys(text)?;
    let value: Value = serde_json::from_str(text)?;
    exact_integers(&value)?;
    Ok(serde_json_canonicalizer::to_vec(&value)?)
}

// Domain decoders preserve integer values. Refuse an integer a JCS binary64
// conversion would round, rather than fingerprint distinct executable bodies
// identically. Lossless protocol counters are strings and never pass here.
fn exact_integers(value: &Value) -> Result<(), CodecError> {
    match value {
        Value::Number(number) => {
            let rounded = number
                .as_u64()
                .is_some_and(|n| n as f64 as u128 != u128::from(n))
                || number
                    .as_i64()
                    .is_some_and(|n| n as f64 as i128 != i128::from(n));
            if rounded {
                return Err(CodecError::Invalid("non-I-JSON integer"));
            }
        }
        Value::Array(values) => {
            for value in values {
                exact_integers(value)?;
            }
        }
        Value::Object(values) => {
            for value in values.values() {
                exact_integers(value)?;
            }
        }
        _ => {}
    }
    Ok(())
}

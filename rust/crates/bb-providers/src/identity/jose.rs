//! Provider-token (JWS) verification with a closed algorithm allow-list.
//!
//! Fails closed: every defect maps to [`JoseError::Rejected`] and the caller
//! never learns which check failed (027-FR-007, research R14).

use std::collections::HashMap;
use std::fs::File;
use std::io::Read;

use jsonwebtoken::{Algorithm, DecodingKey, Validation, decode, decode_header};
use serde_json::Value;

/// A provider public key (JWK). EC keys use `x`/`y`; RSA keys use `n`/`e`.
#[derive(Clone, Debug, PartialEq, Eq, Default)]
pub struct Jwk {
    pub kid: String,
    pub kty: String,
    pub crv: String,
    pub x: String,
    pub y: String,
    pub n: String,
    pub e: String,
}

/// What the caller requires of the token.
pub struct Expect<'a> {
    pub issuer: &'a str,
    pub audience: &'a str,
    pub nonce: &'a str,
    /// Seconds since the Unix epoch.
    pub now: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Verified {
    pub subject: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum JoseError {
    Rejected,
}

/// Seconds a browser/device-grant handoff stays redeemable.
pub const HANDOFF_TTL_SECS: u64 = 600;

/// `kid` from the unverified header, used only to pick the verification key.
pub fn token_kid(token: &str) -> Result<String, JoseError> {
    let header = decode_header(token).map_err(|_| JoseError::Rejected)?;
    header
        .kid
        .filter(|k| !k.is_empty())
        .ok_or(JoseError::Rejected)
}

fn key_for(alg: Algorithm, jwk: &Jwk) -> Result<DecodingKey, JoseError> {
    let key = match (alg, jwk.kty.as_str()) {
        (Algorithm::ES256, "EC") if jwk.crv == "P-256" => {
            DecodingKey::from_ec_components(&jwk.x, &jwk.y)
        }
        (Algorithm::RS256, "RSA") => DecodingKey::from_rsa_components(&jwk.n, &jwk.e),
        _ => return Err(JoseError::Rejected),
    };
    key.map_err(|_| JoseError::Rejected)
}

fn audience_matches(aud: Option<&Value>, want: &str) -> bool {
    match aud {
        Some(Value::String(s)) => s == want,
        Some(Value::Array(a)) => a.iter().any(|v| v.as_str() == Some(want)),
        _ => false,
    }
}

/// Verifies signature, algorithm, issuer, audience, nonce, `exp` and `nbf`.
pub fn verify(token: &str, jwk: &Jwk, expect: &Expect<'_>) -> Result<Verified, JoseError> {
    let alg = decode_header(token).map_err(|_| JoseError::Rejected)?.alg;
    if !matches!(alg, Algorithm::ES256 | Algorithm::RS256) || expect.nonce.is_empty() {
        return Err(JoseError::Rejected);
    }
    let mut rules = Validation::new(alg);
    rules.required_spec_claims.clear();
    rules.validate_exp = false;
    rules.validate_nbf = false;
    rules.validate_aud = false;
    let claims = decode::<Value>(token, &key_for(alg, jwk)?, &rules)
        .map_err(|_| JoseError::Rejected)?
        .claims;

    let live = claims["exp"].as_u64().is_some_and(|exp| exp > expect.now)
        && claims["nbf"].as_u64().is_none_or(|nbf| nbf <= expect.now);
    let bound = claims["iss"].as_str() == Some(expect.issuer)
        && audience_matches(claims.get("aud"), expect.audience)
        && claims["nonce"].as_str() == Some(expect.nonce);
    let subject = claims["sub"].as_str().filter(|s| !s.is_empty());
    match (live && bound, subject) {
        (true, Some(sub)) => Ok(Verified {
            subject: sub.to_owned(),
        }),
        _ => Err(JoseError::Rejected),
    }
}

fn random_id() -> String {
    let mut bytes = [0u8; 32];
    File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .expect("operating-system randomness is available");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

/// Single-use, session-bound handoffs (in memory; the store-backed variant
/// lands with the sign-in lanes). A wrong-session attempt does not consume it.
#[derive(Default)]
pub struct HandoffRegistry {
    open: HashMap<String, (String, u64)>,
}

impl HandoffRegistry {
    pub fn issue(&mut self, session: &str, now: u64) -> String {
        let id = random_id();
        self.open.insert(id.clone(), (session.to_owned(), now));
        id
    }

    pub fn redeem(&mut self, handoff: &str, session: &str, now: u64) -> Result<(), JoseError> {
        match self.open.get(handoff) {
            Some((owner, at)) if owner == session && now <= at + HANDOFF_TTL_SECS => {
                self.open.remove(handoff);
                Ok(())
            }
            _ => Err(JoseError::Rejected),
        }
    }
}

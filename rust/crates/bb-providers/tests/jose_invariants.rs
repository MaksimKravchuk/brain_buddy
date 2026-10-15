//! Provider-token verification invariants (research R14, 027_FR_007) proven with
//! locally signed JWS fixtures. Each rejection names the single defect it covers.

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{Arc, Mutex};

use bb_allure::allure_test;
use bb_providers::identity::jose::{Expect, HandoffRegistry, JoseError, Jwk, token_kid, verify};
use bb_providers::identity::jwks::{FetchError, JwksSource, JwksVerifier};
use p256::ecdsa::signature::Signer;
use p256::ecdsa::{Signature, SigningKey};
use serde_json::{Value, json};

const ISS: &str = "https://accounts.example";
const AUD: &str = "client-1";
const NONCE: &str = "nonce-1";
const NOW: u64 = 1_000_000;

fn b64(data: &[u8]) -> String {
    const A: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    for c in data.chunks(3) {
        let n = c
            .iter()
            .enumerate()
            .fold(0u32, |a, (i, b)| a | (u32::from(*b) << (16 - 8 * i)));
        for i in 0..=c.len() {
            out.push(A[((n >> (18 - 6 * i)) & 63) as usize] as char);
        }
    }
    out
}

fn key(seed: u8) -> SigningKey {
    SigningKey::from_slice(&[seed; 32]).expect("valid scalar")
}

fn jwk(kid: &str, sk: &SigningKey) -> Jwk {
    let p = sk.verifying_key().to_sec1_point(false);
    Jwk {
        kid: kid.into(),
        kty: "EC".into(),
        crv: "P-256".into(),
        x: b64(p.x().expect("x")),
        y: b64(p.y().expect("y")),
        ..Jwk::default()
    }
}

fn claims() -> Value {
    json!({"iss": ISS, "aud": AUD, "nonce": NONCE, "sub": "user-1",
           "exp": NOW + 600, "nbf": NOW - 60, "iat": NOW - 60})
}

fn sign_with(header: &Value, claims: &Value, sk: &SigningKey) -> String {
    let input = format!(
        "{}.{}",
        b64(header.to_string().as_bytes()),
        b64(claims.to_string().as_bytes())
    );
    let sig: Signature = sk.sign(input.as_bytes());
    format!("{input}.{}", b64(&sig.to_bytes()))
}

fn token(kid: &str, claims: &Value, sk: &SigningKey) -> String {
    sign_with(
        &json!({"alg": "ES256", "typ": "JWT", "kid": kid}),
        claims,
        sk,
    )
}

fn expect() -> Expect<'static> {
    Expect {
        issuer: ISS,
        audience: AUD,
        nonce: NONCE,
        now: NOW,
    }
}

fn with(field: &str, value: Value) -> Value {
    let mut c = claims();
    c[field] = value;
    c
}

fn without(field: &str) -> Value {
    let mut c = claims();
    c.as_object_mut().expect("object").remove(field);
    c
}

fn rejects(t: &str, k: &Jwk) {
    assert_eq!(verify(t, k, &expect()), Err(JoseError::Rejected));
}

fn case(name: &str, f: impl FnOnce()) {
    allure_test!(
        "Rust server",
        "Provider identity",
        "027-FR-007 token verification",
        name,
        |t| {
            t.step(name, f);
        }
    );
}

#[test]
fn t027_fr_007_accepts_only_the_exact_valid_token() {
    case("027_FR_007 valid token is accepted", || {
        let sk = key(7);
        let ok = verify(&token("k1", &claims(), &sk), &jwk("k1", &sk), &expect()).expect("valid");
        assert_eq!(ok.subject, "user-1");
    });
}

#[test]
fn t027_fr_007_rejects_wrong_issuer_audience_and_nonce() {
    case("027_FR_007 issuer, audience and nonce are bound", || {
        let sk = key(7);
        let k = jwk("k1", &sk);
        rejects(
            &token("k1", &with("iss", json!("https://evil.example")), &sk),
            &k,
        );
        rejects(&token("k1", &with("aud", json!("client-2")), &sk), &k);
        rejects(
            &token("k1", &with("aud", json!(["client-2", "client-3"])), &sk),
            &k,
        );
        rejects(&token("k1", &with("nonce", json!("other")), &sk), &k);
        rejects(&token("k1", &without("nonce"), &sk), &k);
        rejects(&token("k1", &without("iss"), &sk), &k);
        rejects(&token("k1", &without("aud"), &sk), &k);
        rejects(&token("k1", &without("sub"), &sk), &k);
        rejects(&token("k1", &with("sub", json!("")), &sk), &k);
        let blank = Expect {
            nonce: "",
            ..expect()
        };
        assert!(verify(&token("k1", &with("nonce", json!("")), &sk), &k, &blank).is_err());
        let ok = token("k1", &with("aud", json!([AUD, "other"])), &sk);
        assert!(verify(&ok, &k, &expect()).is_ok());
    });
}

#[test]
fn t027_fr_007_rejects_none_and_non_allow_listed_algorithms() {
    case(
        "027_FR_007 alg none and non-allow-listed algorithms are rejected",
        || {
            let sk = key(7);
            let k = jwk("k1", &sk);
            let c = b64(claims().to_string().as_bytes());
            for alg in ["none", "None", "HS256", "ES384", "PS256", "RS512", ""] {
                let h = b64(json!({"alg": alg, "kid": "k1"}).to_string().as_bytes());
                rejects(&format!("{h}.{c}."), &k);
                rejects(&format!("{h}.{c}.{}", b64(&[1u8; 64])), &k);
            }
            // RS256 is allow-listed but cannot be verified with an EC key.
            rejects(
                &sign_with(&json!({"alg": "RS256", "kid": "k1"}), &claims(), &sk),
                &k,
            );
            rejects(&sign_with(&json!({"kid": "k1"}), &claims(), &sk), &k);
        },
    );
}

#[test]
fn t027_fr_007_rejects_bad_signature_and_malformed_tokens() {
    case(
        "027_FR_007 tampered, foreign-key and malformed tokens are rejected",
        || {
            let sk = key(7);
            let k = jwk("k1", &sk);
            rejects(&token("k1", &claims(), &key(9)), &k);
            let good = token("k1", &claims(), &sk);
            let parts: Vec<&str> = good.split('.').collect();
            let forged = b64(with("sub", json!("admin")).to_string().as_bytes());
            rejects(&format!("{}.{forged}.{}", parts[0], parts[2]), &k);
            let two = format!("{}.{}", parts[0], parts[1]);
            for bad in ["", "a", "a.b", "a.b.c", "a.b.c.d", "...", two.as_str()] {
                rejects(bad, &k);
            }
            assert!(token_kid("not-a-jwt").is_err());
            assert_eq!(token_kid(&good).as_deref(), Ok("k1"));
            let no_kid = sign_with(&json!({"alg": "ES256"}), &claims(), &sk);
            assert!(token_kid(&no_kid).is_err());
        },
    );
}

#[test]
fn t027_fr_007_rejects_expired_and_not_yet_valid_tokens() {
    case(
        "027_FR_007 exp and nbf are enforced at the boundary",
        || {
            let sk = key(7);
            let k = jwk("k1", &sk);
            rejects(&token("k1", &with("exp", json!(NOW)), &sk), &k);
            rejects(&token("k1", &with("exp", json!(NOW - 1)), &sk), &k);
            rejects(&token("k1", &without("exp"), &sk), &k);
            rejects(&token("k1", &with("nbf", json!(NOW + 1)), &sk), &k);
            assert!(
                verify(
                    &token("k1", &with("exp", json!(NOW + 1)), &sk),
                    &k,
                    &expect()
                )
                .is_ok()
            );
            assert!(verify(&token("k1", &with("nbf", json!(NOW)), &sk), &k, &expect()).is_ok());
        },
    );
}

#[test]
fn t027_fr_007_handoff_is_single_use_and_session_bound() {
    case(
        "027_FR_007 handoffs cannot be replayed or used by another session",
        || {
            let mut r = HandoffRegistry::default();
            let h = r.issue("session-a", NOW);
            assert_eq!(r.redeem(&h, "session-b", NOW + 1), Err(JoseError::Rejected));
            assert_eq!(
                r.redeem("unknown", "session-a", NOW + 1),
                Err(JoseError::Rejected)
            );
            assert_eq!(r.redeem(&h, "session-a", NOW + 1), Ok(()));
            assert_eq!(r.redeem(&h, "session-a", NOW + 2), Err(JoseError::Rejected));
            let late = r.issue("session-a", NOW);
            assert_eq!(
                r.redeem(&late, "session-a", NOW + 601),
                Err(JoseError::Rejected)
            );
            assert_ne!(r.issue("session-a", NOW), r.issue("session-a", NOW));
        },
    );
}

type Sets = Vec<Result<Vec<Jwk>, FetchError>>;

struct Source {
    sets: Mutex<Sets>,
    calls: Arc<AtomicUsize>,
}

impl Source {
    fn new(sets: Sets) -> (Self, Arc<AtomicUsize>) {
        let calls = Arc::new(AtomicUsize::new(0));
        let source = Self {
            sets: Mutex::new(sets),
            calls: calls.clone(),
        };
        (source, calls)
    }
}

impl JwksSource for Source {
    async fn fetch(&self) -> Result<Vec<Jwk>, FetchError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        let mut s = self.sets.lock().expect("lock");
        if s.len() > 1 {
            s.remove(0)
        } else {
            s[0].clone()
        }
    }
}

fn run<F: std::future::Future>(f: F) -> F::Output {
    tokio::runtime::Builder::new_current_thread()
        .build()
        .expect("rt")
        .block_on(f)
}

#[test]
fn t027_fr_007_unknown_kid_and_fetch_failure_fail_closed() {
    case(
        "027_FR_007 unknown kid and JWKS fetch failure fail closed",
        || {
            let sk = key(7);
            let (src, calls) = Source::new(vec![Ok(vec![jwk("k1", &sk)])]);
            let v = JwksVerifier::new(src);
            assert!(run(v.verify(&token("k1", &claims(), &sk), &expect())).is_ok());
            assert!(run(v.verify(&token("ghost", &claims(), &sk), &expect())).is_err());
            assert_eq!(
                calls.load(Ordering::SeqCst),
                2,
                "unknown kid triggers one refresh"
            );
            let (down, _) = Source::new(vec![Err(FetchError)]);
            let v = JwksVerifier::new(down);
            assert!(run(v.verify(&token("k1", &claims(), &sk), &expect())).is_err());
        },
    );
}

#[test]
fn t027_fr_007_jwks_rotation_replaces_keys_and_retired_keys_fail() {
    case(
        "027_FR_007 JWKS rotation adopts new keys and retires old ones",
        || {
            let (old, new) = (key(7), key(8));
            let (src, _) = Source::new(vec![
                Ok(vec![jwk("old", &old)]),
                Ok(vec![jwk("new", &new)]),
                Err(FetchError),
            ]);
            let v = JwksVerifier::new(src);
            assert!(run(v.verify(&token("old", &claims(), &old), &expect())).is_ok());
            // Unknown kid forces a refresh that rotates the set.
            assert!(run(v.verify(&token("new", &claims(), &new), &expect())).is_ok());
            // The retired key no longer verifies, even though it was cached before.
            assert!(run(v.verify(&token("old", &claims(), &old), &expect())).is_err());
            // A failing refresh never accepts anything unknown.
            assert!(run(v.verify(&token("newer", &claims(), &new), &expect())).is_err());
            // The still-published key keeps working from cache during the outage.
            assert!(run(v.verify(&token("new", &claims(), &new), &expect())).is_ok());
        },
    );
}

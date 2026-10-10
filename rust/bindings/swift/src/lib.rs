//! UniFFI bridge from the Apple clients to the shared Rust core (spec 026, T005).
//!
//! The Swift module is `BrainBuddyRustBindings` (generated at build time by
//! `ios/scripts/build-rust-bridge.sh`, never committed); the hand-written, Foundation-only
//! facade over it is `BrainBuddyCore/BrainBuddyRustBridge.swift`. It mirrors the Python
//! bridge (`rust/bindings/python`) and its boundary rules (contracts/runtime-ffi.md):
//!
//! * every value crosses as an owned copy (`Vec<u8>`, `String`, records): Swift never
//!   holds a pointer into Rust memory;
//! * a panic never unwinds into Swift: it is contained, poisons the runtime and
//!   surfaces as `INTERNAL_ERROR`;
//! * failures are the typed [`BridgeError`] `(code, retryable, field)`; `field` is a
//!   static rule name and no error ever carries payload text;
//! * the runtime handle is bounded: `close` is final and idempotent, a call racing it
//!   reports `CANCELLED`, and a closed handle reports `WORKSPACE_CLOSED`.
//!
//! Only completed codecs cross this early bridge. Rule dispatch (`decide` / `query`)
//! is connected by a later slice; there is no placeholder export for it.

use std::cell::Cell;
use std::panic::{self, AssertUnwindSafe};
use std::sync::Once;
use std::sync::atomic::{AtomicU8, Ordering};

use bb_protocol::command::{self, Decoded, Unsupported};
use bb_protocol::wire::{CodecError, PROTOCOL_VERSION};

uniffi::setup_scaffolding!();

const OPEN: u8 = 0;
const CLOSED: u8 = 1;
const POISONED: u8 = 2;

/// A content-free failure: a stable code, retryability and a static field name.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Error)]
pub enum BridgeError {
    Failed {
        code: String,
        retryable: bool,
        field: Option<String>,
    },
}

impl std::fmt::Display for BridgeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let Self::Failed { code, .. } = self;
        write!(f, "bridge failure {code}")
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct Failure {
    code: &'static str,
    retryable: bool,
    field: Option<&'static str>,
}

impl Failure {
    const fn new(code: &'static str, field: Option<&'static str>) -> Self {
        Self {
            code,
            retryable: false,
            field,
        }
    }
}

impl From<CodecError> for Failure {
    fn from(error: CodecError) -> Self {
        // `Malformed` carries a parser position and `DuplicateKey` nothing: the
        // position is dropped so no input-derived detail crosses the boundary.
        let field = match error {
            CodecError::Invalid(rule) => Some(rule),
            CodecError::Malformed { .. } | CodecError::DuplicateKey => None,
        };
        Self::new(error.code(), field)
    }
}

impl From<Failure> for BridgeError {
    fn from(failure: Failure) -> Self {
        Self::Failed {
            code: failure.code.to_owned(),
            retryable: failure.retryable,
            field: failure.field.map(str::to_owned),
        }
    }
}

thread_local! {
    static IN_BRIDGE: Cell<bool> = const { Cell::new(false) };
}

/// Silences the default panic report for panics raised inside a bridge call.
///
/// The report prints the panic message, which could embed input text, to stderr.
/// Panics elsewhere in the process still reach the previously installed hook.
fn install_quiet_panic_hook() {
    static INSTALL: Once = Once::new();
    INSTALL.call_once(|| {
        let previous = panic::take_hook();
        panic::set_hook(Box::new(move |info| {
            if !IN_BRIDGE.with(Cell::get) {
                previous(info);
            }
        }));
    });
}

/// Run one pure call against the runtime state.
///
/// A panic is contained, poisons an open runtime and surfaces as `INTERNAL_ERROR`.
/// A `close` that lands while the call runs discards its result as `CANCELLED`;
/// close always wins over poisoning.
fn guarded<T>(state: &AtomicU8, work: impl FnOnce() -> Result<T, Failure>) -> Result<T, Failure> {
    match state.load(Ordering::Acquire) {
        CLOSED => return Err(Failure::new("WORKSPACE_CLOSED", None)),
        POISONED => return Err(Failure::new("INTERNAL_ERROR", None)),
        _ => {}
    }
    install_quiet_panic_hook();
    IN_BRIDGE.with(|flag| flag.set(true));
    let outcome = panic::catch_unwind(AssertUnwindSafe(work));
    IN_BRIDGE.with(|flag| flag.set(false));
    let outcome = outcome.unwrap_or_else(|payload| {
        // The payload may hold input text; it is dropped here, never inspected.
        drop(payload);
        let _ = state.compare_exchange(OPEN, POISONED, Ordering::AcqRel, Ordering::Acquire);
        Err(Failure::new("INTERNAL_ERROR", None))
    });
    // A concurrent call that panicked poisons the runtime for every call still in
    // flight: none of them may report success from an unusable runtime.
    match state.load(Ordering::Acquire) {
        CLOSED => Err(Failure::new("CANCELLED", None)),
        POISONED => Err(Failure::new("INTERNAL_ERROR", None)),
        _ => outcome,
    }
}

/// A decoded command envelope; every value is owned by this record.
#[derive(Debug, Clone, PartialEq, Eq, uniffi::Record)]
pub struct BridgeCommand {
    pub protocol_version: u32,
    pub command_id: String,
    pub scope_id: String,
    pub device_id: String,
    /// Decimal string: counters can exceed what JSON numbers (and `Double`) hold exactly.
    pub local_sequence: String,
    pub command_type: String,
    pub command_version: u32,
    pub entity_id: String,
    /// True when this build can execute the command; otherwise it is the stable
    /// recovery form and `unsupported_reason` says why (maps to `UPGRADE_REQUIRED`).
    pub executable: bool,
    pub unsupported_reason: Option<String>,
    /// The stable envelope as wire bytes; omitted optional fields stay omitted.
    pub wire: Vec<u8>,
}

fn unsupported_reason(reason: &Unsupported) -> &'static str {
    match reason {
        Unsupported::ProtocolVersion => "protocol_version",
        Unsupported::CommandType => "command_type",
        Unsupported::CommandVersion => "command_version",
    }
}

/// Decode one command from wire bytes into owned values.
fn decode_command(data: &[u8]) -> Result<BridgeCommand, Failure> {
    let json = std::str::from_utf8(data).map_err(|_| Failure::new("INVALID_REQUEST", None))?;
    let (stable, executable, reason) = match command::decode_command(json)? {
        Decoded::Executable(command) => (command.envelope, true, None),
        Decoded::Unsupported { reason, envelope } => {
            (envelope, false, Some(unsupported_reason(&reason)))
        }
    };
    let wire = serde_json::to_vec(&stable).map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
    Ok(BridgeCommand {
        protocol_version: stable.protocol_version,
        command_id: stable.command_id.as_str().to_owned(),
        scope_id: stable.scope_id.as_str().to_owned(),
        device_id: stable.device_id.as_str().to_owned(),
        local_sequence: stable.local_sequence.as_str().to_owned(),
        command_type: stable.command_type.clone(),
        command_version: stable.command_version,
        entity_id: stable.entity_id.as_str().to_owned(),
        executable,
        unsupported_reason: reason.map(str::to_owned),
        wire,
    })
}

/// One bridge runtime handle. `close` is idempotent and final.
#[derive(uniffi::Object)]
pub struct BridgeRuntime {
    state: AtomicU8,
}

impl BridgeRuntime {
    fn try_new(protocol_version: u32) -> Result<Self, Failure> {
        if protocol_version != PROTOCOL_VERSION {
            return Err(Failure::new("UPGRADE_REQUIRED", Some("protocol_version")));
        }
        Ok(Self {
            state: AtomicU8::new(OPEN),
        })
    }
}

#[uniffi::export]
impl BridgeRuntime {
    /// Open a runtime for the given sync protocol version.
    #[uniffi::constructor]
    pub fn new(protocol_version: u32) -> Result<Self, BridgeError> {
        Ok(Self::try_new(protocol_version)?)
    }

    /// Close the runtime. Idempotent; calls in flight report `CANCELLED`.
    pub fn close(&self) {
        self.state.store(CLOSED, Ordering::Release);
    }

    pub fn is_open(&self) -> bool {
        self.state.load(Ordering::Acquire) == OPEN
    }

    /// Decode and validate one command envelope (sync-v1 section 3).
    pub fn decode_command(&self, data: Vec<u8>) -> Result<BridgeCommand, BridgeError> {
        Ok(guarded(&self.state, || decode_command(&data))?)
    }
}

/// The sync protocol version this build speaks.
#[uniffi::export]
pub fn bridge_protocol_version() -> u32 {
    PROTOCOL_VERSION
}

#[cfg(test)]
mod bridge_tests {
    use super::*;

    const COMMAND: &str = r#"{
        "protocol_version": 1,
        "command_id": "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11",
        "scope_id": "scope-1",
        "device_id": "device-1",
        "device_epoch": "epoch-1",
        "local_sequence": "9007199254740993",
        "type": "task.create",
        "command_version": 1,
        "entity_id": "task-1",
        "preconditions": [],
        "depends_on": [],
        "issued_at": "2026-10-09T12:00:00Z",
        "payload": {"title": "Buy milk"}
    }"#;

    fn failed(error: BridgeError) -> (String, bool, Option<String>) {
        let BridgeError::Failed {
            code,
            retryable,
            field,
        } = error;
        (code, retryable, field)
    }

    #[test]
    fn bridge_026_fr_025_contains_panic_and_poisons_runtime() {
        let state = AtomicU8::new(OPEN);
        let panicked: Result<(), _> = guarded(&state, || panic!("payload must not leak"));
        assert_eq!(panicked, Err(Failure::new("INTERNAL_ERROR", None)));
        assert_eq!(state.load(Ordering::Acquire), POISONED);
        assert_eq!(
            guarded(&state, || Ok(1)),
            Err(Failure::new("INTERNAL_ERROR", None))
        );
        assert!(!IN_BRIDGE.with(Cell::get));
    }

    #[test]
    fn bridge_026_fr_025_rejects_calls_after_close_and_cancels_in_flight() {
        let state = AtomicU8::new(CLOSED);
        assert_eq!(
            guarded(&state, || Ok(())),
            Err(Failure::new("WORKSPACE_CLOSED", None))
        );
        let state = AtomicU8::new(OPEN);
        let result = guarded(&state, || {
            state.store(CLOSED, Ordering::Release);
            Ok(7)
        });
        assert_eq!(result, Err(Failure::new("CANCELLED", None)));
        let state = AtomicU8::new(OPEN);
        let result: Result<(), _> = guarded(&state, || {
            state.store(CLOSED, Ordering::Release);
            panic!("late");
        });
        assert_eq!(result, Err(Failure::new("CANCELLED", None)));
        assert_eq!(state.load(Ordering::Acquire), CLOSED);
    }

    #[test]
    fn bridge_026_fr_025_poisoning_mid_flight_fails_a_concurrent_success() {
        let state = AtomicU8::new(OPEN);
        let result = guarded(&state, || {
            state.store(POISONED, Ordering::Release);
            Ok(7)
        });
        assert_eq!(result, Err(Failure::new("INTERNAL_ERROR", None)));
    }

    #[test]
    fn bridge_026_fr_025_repeated_open_close_cycles_are_final_and_idempotent() {
        for _ in 0..50 {
            let runtime = BridgeRuntime::new(PROTOCOL_VERSION).expect("opens");
            assert!(runtime.is_open());
            runtime.close();
            runtime.close();
            assert!(!runtime.is_open());
            let error = runtime.decode_command(COMMAND.into()).expect_err("closed");
            assert_eq!(failed(error).0, "WORKSPACE_CLOSED");
        }
    }

    #[test]
    fn bridge_026_fr_025_shares_one_handle_across_threads() {
        let runtime = std::sync::Arc::new(BridgeRuntime::new(PROTOCOL_VERSION).expect("opens"));
        let workers: Vec<_> = (0..8)
            .map(|_| {
                let runtime = std::sync::Arc::clone(&runtime);
                std::thread::spawn(move || {
                    (0..50).all(|_| {
                        runtime
                            .decode_command(COMMAND.into())
                            .is_ok_and(|command| command.executable)
                    })
                })
            })
            .collect();
        for worker in workers {
            assert!(worker.join().expect("worker finished"));
        }
        runtime.close();
        assert!(!runtime.is_open());
    }

    #[test]
    fn bridge_026_fr_002_refuses_an_unsupported_protocol_version() {
        let error = BridgeRuntime::new(PROTOCOL_VERSION + 1)
            .err()
            .expect("refused");
        assert_eq!(
            failed(error),
            (
                "UPGRADE_REQUIRED".to_owned(),
                false,
                Some("protocol_version".to_owned())
            )
        );
        assert_eq!(bridge_protocol_version(), PROTOCOL_VERSION);
    }

    #[test]
    fn bridge_026_fr_002_decodes_a_command_and_keeps_counters_exact() {
        let runtime = BridgeRuntime::new(PROTOCOL_VERSION).expect("opens");
        let command = runtime.decode_command(COMMAND.into()).expect("decodes");
        assert!(command.executable);
        assert_eq!(command.unsupported_reason, None);
        assert_eq!(command.command_id, "5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11");
        assert_eq!(command.command_type, "task.create");
        assert_eq!(command.local_sequence, "9007199254740993");
        let wire: serde_json::Value = serde_json::from_slice(&command.wire).expect("json");
        assert_eq!(wire["local_sequence"], "9007199254740993");
        assert!(wire.get("supersedes_command_id").is_none());
    }

    #[test]
    fn bridge_026_fr_002_reports_unsupported_commands_as_values_not_errors() {
        let json = COMMAND.replace("task.create", "task.from_the_future");
        let command = decode_command(json.as_bytes()).expect("decodes");
        assert!(!command.executable);
        assert_eq!(command.unsupported_reason.as_deref(), Some("command_type"));
    }

    #[test]
    fn bridge_026_fr_002_maps_codec_errors_without_payload_text() {
        let secret = "Buy milk";
        let cases = [
            &b"{\"title\": \"Buy milk\""[..],
            &b"\xff\xfe"[..],
            &br#"{"a":1,"a":2}"#[..],
        ];
        for data in cases {
            let failure = decode_command(data).expect_err("rejected");
            assert_eq!(failure, Failure::new("INVALID_REQUEST", None));
        }
        let bad_id = COMMAND.replace("5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11", "not-a-uuid");
        let failure = decode_command(bad_id.as_bytes()).expect_err("rejected");
        assert_eq!(failure.code, "INVALID_REQUEST");
        let error = BridgeError::from(failure);
        assert!(!format!("{error:?}{error}").contains(secret));
    }
}

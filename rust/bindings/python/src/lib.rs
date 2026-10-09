//! PyO3 bridge from the FastAPI backend to the shared Rust core (spec 026, T004).
//!
//! This crate is the Python module `bb_core`. It exposes the `bb-protocol`
//! command-envelope codec and, since T018, the shared rule dispatch
//! (`bb_domain::dispatch::decide_envelope` / `query`, runtime-ffi.md "Pure
//! core") as [`Runtime::decide`] and [`Runtime::query`]. Both go through the
//! same [`guarded`] seam and cross as JSON bytes: read set, envelope, retained
//! receipts and execution inputs in; a typed outcome out. An expected domain
//! refusal is a value (`{"status": "refused", ...}`), never a [`BridgeError`].
//!
//! Boundary rules (contracts/runtime-ffi.md):
//! * every call copies its input into owned Rust values, then releases the GIL
//!   for the pure work;
//! * a panic never unwinds into Python: it is contained, poisons the runtime and
//!   surfaces as `INTERNAL_ERROR`;
//! * failures are the typed [`BridgeError`] `(code, retryable, field)`; `field`
//!   is a static rule name and no error ever carries payload text.

use std::cell::Cell;
use std::panic::{self, AssertUnwindSafe};
use std::sync::atomic::{AtomicU8, Ordering};
use std::sync::{Arc, Once};

use bb_domain::dispatch;
use bb_domain::types::{DomainError, ExecutionInputs, Query, QueryInputs, QueryResult, ReadSet};
use bb_protocol::command::{self, Decoded, Unsupported};
use bb_protocol::receipt::Receipt;
use bb_protocol::wire::{CodecError, PROTOCOL_VERSION};
use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use serde::Serialize;
use serde::de::DeserializeOwned;

create_exception!(
    bb_core,
    BridgeError,
    PyException,
    "Typed bridge failure; args are (code, retryable, field)."
);

const OPEN: u8 = 0;
const CLOSED: u8 = 1;
const POISONED: u8 = 2;

/// A content-free failure: a stable code, retryability and a static field name.
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

impl From<Failure> for PyErr {
    fn from(failure: Failure) -> Self {
        BridgeError::new_err((failure.code, failure.retryable, failure.field))
    }
}

thread_local! {
    static IN_BRIDGE: Cell<bool> = const { Cell::new(false) };
}

/// Silences the default panic report for panics raised inside a bridge call.
///
/// The report prints the panic message, which could embed input text, to
/// stderr. Panics elsewhere in the process (other extensions, Python's own
/// threads) still reach the previously installed hook untouched.
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
/// A panic is contained, poisons an open runtime and surfaces as
/// `INTERNAL_ERROR`. A `close` that lands while the call runs discards its
/// result as `CANCELLED`; close always wins over poisoning.
fn guarded<T>(state: &AtomicU8, work: impl FnOnce() -> Result<T, Failure>) -> Result<T, Failure> {
    match state.load(Ordering::Acquire) {
        CLOSED => return Err(Failure::new("WORKSPACE_CLOSED", None)),
        POISONED => return Err(Failure::new("INTERNAL_ERROR", None)),
        _ => {}
    }
    IN_BRIDGE.with(|flag| flag.set(true));
    let outcome = panic::catch_unwind(AssertUnwindSafe(work));
    IN_BRIDGE.with(|flag| flag.set(false));
    let outcome = outcome.unwrap_or_else(|payload| {
        // The payload may hold input text; it is dropped here, never inspected.
        drop(payload);
        let _ = state.compare_exchange(OPEN, POISONED, Ordering::AcqRel, Ordering::Acquire);
        Err(Failure::new("INTERNAL_ERROR", None))
    });
    // A concurrent call that panicked poisons the runtime for every call still
    // in flight: none of them may report success from an unusable runtime.
    match state.load(Ordering::Acquire) {
        CLOSED => Err(Failure::new("CANCELLED", None)),
        POISONED => Err(Failure::new("INTERNAL_ERROR", None)),
        _ => outcome,
    }
}

/// What `decide` returns across the boundary: a change set or a typed refusal.
#[derive(Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
enum Decision {
    Changed {
        change_set: bb_domain::types::ChangeSet,
    },
    Refused {
        error: DomainError,
    },
}

/// What `query` returns across the boundary.
#[derive(Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
enum Answer {
    Answered { result: Box<QueryResult> },
    Refused { error: DomainError },
}

/// Parses one JSON input; the failure names the argument, never its content.
fn parse_json<T: DeserializeOwned>(data: &[u8], field: &'static str) -> Result<T, Failure> {
    serde_json::from_slice(data).map_err(|_| Failure::new("INVALID_REQUEST", Some(field)))
}

fn to_json<T: Serialize>(value: &T) -> Result<Vec<u8>, Failure> {
    serde_json::to_vec(value).map_err(|_| Failure::new("INTERNAL_ERROR", None))
}

/// Decide one executable command envelope against an owned read set.
fn decide_envelope(
    read_set: &[u8],
    envelope: &[u8],
    receipts: &[u8],
    inputs: &[u8],
) -> Result<Vec<u8>, Failure> {
    let read_set: ReadSet = parse_json(read_set, "read_set")?;
    let receipts: Vec<Receipt> = parse_json(receipts, "receipts")?;
    let inputs: ExecutionInputs = parse_json(inputs, "execution_inputs")?;
    let json = std::str::from_utf8(envelope).map_err(|_| Failure::new("INVALID_REQUEST", None))?;
    let envelope = match command::decode_command(json)? {
        Decoded::Executable(envelope) => envelope,
        Decoded::Unsupported { .. } => {
            return Err(Failure::new("UPGRADE_REQUIRED", Some("command_type")));
        }
    };
    to_json(
        &match dispatch::decide_envelope(&read_set, &envelope, receipts.as_slice(), &inputs) {
            Ok(change_set) => Decision::Changed { change_set },
            Err(error) => Decision::Refused { error },
        },
    )
}

/// Answer one query over an owned read set.
fn answer_query(read_set: &[u8], query: &[u8], inputs: &[u8]) -> Result<Vec<u8>, Failure> {
    let read_set: ReadSet = parse_json(read_set, "read_set")?;
    let query: Query = parse_json(query, "query")?;
    let inputs: QueryInputs = parse_json(inputs, "query_inputs")?;
    to_json(&match dispatch::query(&read_set, &query, &inputs) {
        Ok(result) => Answer::Answered {
            result: Box::new(result),
        },
        Err(error) => Answer::Refused { error },
    })
}

/// A decoded command envelope; every value is owned by this object.
#[pyclass(frozen, module = "bb_core")]
struct Command {
    stable: bb_protocol::command::StableEnvelope,
    executable: bool,
    unsupported_reason: Option<&'static str>,
    wire: Vec<u8>,
}

fn unsupported_reason(reason: &Unsupported) -> &'static str {
    match reason {
        Unsupported::ProtocolVersion => "protocol_version",
        Unsupported::CommandType => "command_type",
        Unsupported::CommandVersion => "command_version",
    }
}

/// Decode one command from wire bytes into owned values (no Python objects).
fn decode_command(data: &[u8]) -> Result<Command, Failure> {
    let json = std::str::from_utf8(data).map_err(|_| Failure::new("INVALID_REQUEST", None))?;
    let (stable, executable, reason) = match command::decode_command(json)? {
        Decoded::Executable(command) => (command.envelope, true, None),
        Decoded::Unsupported { reason, envelope } => {
            (envelope, false, Some(unsupported_reason(&reason)))
        }
    };
    let wire = serde_json::to_vec(&stable).map_err(|_| Failure::new("INTERNAL_ERROR", None))?;
    Ok(Command {
        stable,
        executable,
        unsupported_reason: reason,
        wire,
    })
}

#[pymethods]
impl Command {
    #[getter]
    fn protocol_version(&self) -> u32 {
        self.stable.protocol_version
    }
    #[getter]
    fn command_id(&self) -> &str {
        self.stable.command_id.as_str()
    }
    #[getter]
    fn scope_id(&self) -> &str {
        self.stable.scope_id.as_str()
    }
    #[getter]
    fn device_id(&self) -> &str {
        self.stable.device_id.as_str()
    }
    /// Decimal string: counters can exceed what JSON numbers hold exactly.
    #[getter]
    fn local_sequence(&self) -> &str {
        self.stable.local_sequence.as_str()
    }
    #[getter]
    fn command_type(&self) -> &str {
        &self.stable.command_type
    }
    #[getter]
    fn command_version(&self) -> u32 {
        self.stable.command_version
    }
    #[getter]
    fn entity_id(&self) -> &str {
        self.stable.entity_id.as_str()
    }
    /// True when this build can execute the command; otherwise it is the stable
    /// recovery form and `unsupported_reason` says why (maps to UPGRADE_REQUIRED).
    #[getter]
    fn executable(&self) -> bool {
        self.executable
    }
    #[getter]
    fn unsupported_reason(&self) -> Option<&'static str> {
        self.unsupported_reason
    }
    /// The stable envelope as wire bytes; omitted optional fields stay omitted.
    fn to_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.wire)
    }
}

/// One bridge runtime handle. `close` is idempotent and final.
#[pyclass(frozen, module = "bb_core")]
struct Runtime {
    state: Arc<AtomicU8>,
}

impl Runtime {
    fn try_new(protocol_version: u32) -> Result<Self, Failure> {
        if protocol_version != PROTOCOL_VERSION {
            return Err(Failure::new("UPGRADE_REQUIRED", Some("protocol_version")));
        }
        Ok(Self {
            state: Arc::new(AtomicU8::new(OPEN)),
        })
    }
}

#[pymethods]
impl Runtime {
    #[new]
    fn new(protocol_version: u32) -> PyResult<Self> {
        Ok(Self::try_new(protocol_version)?)
    }

    fn close(&self) {
        self.state.store(CLOSED, Ordering::Release);
    }

    #[getter]
    fn is_open(&self) -> bool {
        self.state.load(Ordering::Acquire) == OPEN
    }

    /// Decode and validate one command envelope (sync-v1 §3).
    fn decode_command(&self, py: Python<'_>, data: &[u8]) -> PyResult<Command> {
        let owned = data.to_vec();
        let state = Arc::clone(&self.state);
        let decoded = py.detach(move || guarded(&state, || decode_command(&owned)))?;
        Ok(decoded)
    }

    /// Decide one command envelope (runtime-ffi.md "Pure core"): JSON bytes in,
    /// a `Decision` as JSON bytes out. The pure rule work runs without the GIL
    /// on copies of every argument.
    fn decide<'py>(
        &self,
        py: Python<'py>,
        read_set: &[u8],
        envelope: &[u8],
        receipts: &[u8],
        inputs: &[u8],
    ) -> PyResult<Bound<'py, PyBytes>> {
        let (read_set, envelope) = (read_set.to_vec(), envelope.to_vec());
        let (receipts, inputs) = (receipts.to_vec(), inputs.to_vec());
        let state = Arc::clone(&self.state);
        let out = py.detach(move || {
            guarded(&state, || {
                decide_envelope(&read_set, &envelope, &receipts, &inputs)
            })
        })?;
        Ok(PyBytes::new(py, &out))
    }

    /// Answer one query: JSON bytes in, an `Answer` as JSON bytes out.
    fn query<'py>(
        &self,
        py: Python<'py>,
        read_set: &[u8],
        query: &[u8],
        inputs: &[u8],
    ) -> PyResult<Bound<'py, PyBytes>> {
        let (read_set, query, inputs) = (read_set.to_vec(), query.to_vec(), inputs.to_vec());
        let state = Arc::clone(&self.state);
        let out =
            py.detach(move || guarded(&state, || answer_query(&read_set, &query, &inputs)))?;
        Ok(PyBytes::new(py, &out))
    }
}

#[pymodule]
fn bb_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    install_quiet_panic_hook();
    module.add("BridgeError", module.py().get_type::<BridgeError>())?;
    module.add("PROTOCOL_VERSION", PROTOCOL_VERSION)?;
    module.add_class::<Runtime>()?;
    module.add_class::<Command>()?;
    Ok(())
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

    fn open_state() -> AtomicU8 {
        AtomicU8::new(OPEN)
    }

    #[test]
    fn bridge_contains_panic_and_poisons_runtime() {
        install_quiet_panic_hook();
        let state = open_state();
        let panicked: Result<(), _> = guarded(&state, || panic!("payload must not leak"));
        assert_eq!(panicked, Err(Failure::new("INTERNAL_ERROR", None)));
        assert_eq!(state.load(Ordering::Acquire), POISONED);
        assert_eq!(
            guarded(&state, || Ok(1)),
            Err(Failure::new("INTERNAL_ERROR", None))
        );
    }

    #[test]
    fn bridge_panic_flag_is_cleared_so_other_panics_still_report() {
        install_quiet_panic_hook();
        let state = open_state();
        let _ = guarded(&state, || -> Result<(), Failure> { panic!("contained") });
        assert!(!IN_BRIDGE.with(Cell::get));
    }

    #[test]
    fn bridge_rejects_calls_after_close() {
        let state = open_state();
        state.store(CLOSED, Ordering::Release);
        assert_eq!(
            guarded(&state, || Ok(())),
            Err(Failure::new("WORKSPACE_CLOSED", None))
        );
    }

    #[test]
    fn bridge_cancels_a_call_closed_mid_flight() {
        let state = open_state();
        let result = guarded(&state, || {
            state.store(CLOSED, Ordering::Release);
            Ok(7)
        });
        assert_eq!(result, Err(Failure::new("CANCELLED", None)));
    }

    #[test]
    fn bridge_poisoning_mid_flight_fails_a_concurrent_success() {
        let state = open_state();
        let result = guarded(&state, || {
            // Another thread's call panics while this one is running.
            state.store(POISONED, Ordering::Release);
            Ok(7)
        });
        assert_eq!(result, Err(Failure::new("INTERNAL_ERROR", None)));
    }

    #[test]
    fn bridge_close_wins_over_a_panic_mid_flight() {
        install_quiet_panic_hook();
        let state = open_state();
        let result: Result<(), _> = guarded(&state, || {
            state.store(CLOSED, Ordering::Release);
            panic!("late");
        });
        assert_eq!(result, Err(Failure::new("CANCELLED", None)));
        assert_eq!(state.load(Ordering::Acquire), CLOSED);
    }

    #[test]
    fn bridge_close_is_final_and_idempotent_across_reopen_cycles() {
        for _ in 0..50 {
            let runtime = Runtime::try_new(PROTOCOL_VERSION).expect("opens");
            assert!(runtime.is_open());
            runtime.close();
            runtime.close();
            assert!(!runtime.is_open());
        }
    }

    #[test]
    fn bridge_refuses_an_unsupported_protocol_version() {
        let error = Runtime::try_new(PROTOCOL_VERSION + 1).err();
        assert_eq!(
            error,
            Some(Failure::new("UPGRADE_REQUIRED", Some("protocol_version")))
        );
    }

    #[test]
    fn bridge_decodes_an_executable_command_and_keeps_counters_exact() {
        let command = decode_command(COMMAND.as_bytes()).expect("decodes");
        assert!(command.executable);
        assert_eq!(command.unsupported_reason, None);
        assert_eq!(command.stable.local_sequence.as_str(), "9007199254740993");
        let wire: serde_json::Value = serde_json::from_slice(&command.wire).expect("json");
        assert_eq!(wire["local_sequence"], "9007199254740993");
        assert!(wire.get("supersedes_command_id").is_none());
    }

    #[test]
    fn bridge_reports_unsupported_commands_as_values_not_errors() {
        let json = COMMAND.replace("task.create", "task.from_the_future");
        let command = decode_command(json.as_bytes()).expect("decodes");
        assert!(!command.executable);
        assert_eq!(command.unsupported_reason, Some("command_type"));
    }

    #[test]
    fn bridge_maps_codec_errors_without_payload_text() {
        let secret = "Buy milk";
        let cases = [
            (&b"{\"title\": \"Buy milk\""[..], None),
            (&b"\xff\xfe"[..], None),
            (&br#"{"a":1,"a":2}"#[..], None),
        ];
        for (data, field) in cases {
            let failure = decode_command(data).err().expect("rejected");
            assert_eq!(failure, Failure::new("INVALID_REQUEST", field));
        }
        let bad_id = COMMAND.replace("5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d11", "not-a-uuid");
        let failure = decode_command(bad_id.as_bytes()).err().expect("rejected");
        assert_eq!(failure.code, "INVALID_REQUEST");
        assert!(!format!("{failure:?}").contains(secret));
    }

    const TASK_ID: &str = "task_5b0f6f0e-8f1b-4f6e-9a57-2a0f0c1f4d12";
    const INPUTS: &str = r#"{
        "rule_version": 1, "now": "2026-10-09T12:00:00Z", "time_zone": "UTC",
        "origin": "legacy", "actor_id": "owner-1", "authoritative": true,
        "allocated_ids": [],
        "policy": {"weekly_review": false, "navigator_provider": null,
                   "navigator_available": false, "consent_text_version": 1}
    }"#;

    fn create_envelope(entity_id: &str) -> String {
        COMMAND.replace("\"task-1\"", &format!("\"{entity_id}\""))
    }

    fn decide_json(read_set: &str, envelope: &str) -> Result<serde_json::Value, Failure> {
        decide_envelope(
            read_set.as_bytes(),
            envelope.as_bytes(),
            b"[]",
            INPUTS.as_bytes(),
        )
        .map(|out| serde_json::from_slice(&out).expect("json"))
    }

    #[test]
    fn bridge_decides_a_command_into_an_owned_change_set() {
        let out = decide_json("{}", &create_envelope(TASK_ID)).expect("decides");
        assert_eq!(out["status"], "changed");
        let change = &out["change_set"]["changes"][0];
        assert_eq!(change["value"]["id"], TASK_ID);
        assert_eq!(change["value"]["revision"], "1");
    }

    #[test]
    fn bridge_reports_a_domain_refusal_as_a_value() {
        // A legacy-shaped ID is not a native new ID: the rule refuses, the bridge does not fail.
        let out = decide_json("{}", &create_envelope("task-1")).expect("decides");
        assert_eq!(out["status"], "refused");
        assert_eq!(out["error"]["reason"], "invalid_value");
    }

    #[test]
    fn bridge_maps_bad_decide_inputs_without_content() {
        let failure =
            decide_json("{\"tasks\": 7}", &create_envelope(TASK_ID)).expect_err("rejected");
        assert_eq!(failure, Failure::new("INVALID_REQUEST", Some("read_set")));
        let unsupported = COMMAND.replace("task.create", "task.from_the_future");
        let failure = decide_json("{}", &unsupported).expect_err("rejected");
        assert_eq!(
            failure,
            Failure::new("UPGRADE_REQUIRED", Some("command_type"))
        );
    }

    #[test]
    fn bridge_answers_a_query_over_an_owned_read_set() {
        let query_inputs = r#"{"now": "2026-10-09T12:00:00Z", "device_zone": "UTC",
            "policy": {"weekly_review": false, "navigator_provider": null,
                       "navigator_available": false, "consent_text_version": 1}}"#;
        let out =
            answer_query(b"{}", br#"{"kind": "tags"}"#, query_inputs.as_bytes()).expect("answers");
        let out: serde_json::Value = serde_json::from_slice(&out).expect("json");
        assert_eq!(out["status"], "answered");
        let failure = answer_query(b"{}", br#"{"kind": "nope"}"#, query_inputs.as_bytes())
            .expect_err("rejected");
        assert_eq!(failure, Failure::new("INVALID_REQUEST", Some("query")));
    }
}

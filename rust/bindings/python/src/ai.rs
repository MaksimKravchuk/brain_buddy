//! AI policy and proposal validation across the Python bridge (spec 026, T048).
//!
//! Thin JSON wrappers over `bb_domain::ai_policy` and `bb_domain::proposal`; no
//! policy lives here. The server is remote-only, so [`route`] is called with no
//! local executors and `RemoteAllowed`; the local half of the policy belongs to
//! the device adapters (UniFFI). A refusal is a value, never a `BridgeError`:
//! only a malformed request is one, and it names the argument, not its content.

use bb_domain::ai_policy::{
    self, ConsentEcho, ConsentState, Denial, OwnerConsent, PrivacyMode, RemoteFacts, Route,
    RouteRequest, Terms,
};
use bb_domain::proposal::{
    self, Candidate, CommandProposal, Confirmation, CurrentFacts, NAVIGATOR_COMMANDS,
    NavigatorInput, NavigatorKind, NavigatorOutput, ProposalBasis, ProposalRefusal,
    SuggestionSource,
};
use bb_domain::types::{ConsentGrant, Id, NavigatorConsent, ProviderName, RevisionCheck};
use bb_domain::types::{DomainError, TextVersion};
use bb_protocol::catalog::CommandType;
use bb_protocol::wire::{Counter, OpenObject};
use serde::Deserialize;

use crate::{Failure, parse_json, to_json};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct TermsWire {
    timeout_ms: u32,
    max_input_tokens: u32,
    max_output_tokens: u32,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EchoWire {
    external_processing_allowed: bool,
    provider: ProviderName,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredConsentWire {
    owner: Id,
    provider: ProviderName,
    consent: Option<ConsentGrant>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RemoteWire {
    provider: Option<ProviderName>,
    credentials_configured: bool,
    consent_text_version: TextVersion,
    echoed_consent: Option<EchoWire>,
    consents: Vec<StoredConsentWire>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RouteWire {
    owner: Id,
    cancelled: bool,
    deterministic_sufficient: bool,
    remote: Option<RemoteWire>,
    estimated_input_tokens: u32,
    terms: TermsWire,
}

fn terms_json(terms: Terms) -> serde_json::Value {
    serde_json::json!({
        "timeout_ms": terms.timeout_ms,
        "max_input_tokens": terms.max_input_tokens,
        "max_output_tokens": terms.max_output_tokens,
    })
}

fn consent_state_name(state: ConsentState) -> &'static str {
    match state {
        ConsentState::Current => "current",
        ConsentState::Missing => "missing",
        ConsentState::Revoked => "revoked",
        ConsentState::TextOutdated => "text_outdated",
    }
}

fn denial_json(denial: &Denial) -> serde_json::Value {
    let (name, state) = match denial {
        Denial::Cancelled => ("cancelled", None),
        Denial::LocalUnavailable(_) => ("local_unavailable", None),
        Denial::RemoteDisabled => ("remote_disabled", None),
        Denial::CredentialsMissing => ("credentials_missing", None),
        Denial::ProviderMismatch => ("provider_mismatch", None),
        Denial::ConsentRequired(state) => ("consent_required", Some(consent_state_name(*state))),
        Denial::InputTooLarge => ("input_too_large", None),
    };
    serde_json::json!({
        "route": "denied",
        "denial": name,
        "consent_state": state,
        "reason": denial.reason(),
    })
}

/// `ai_policy::route` for the remote-only server.
pub(crate) fn route(request: &[u8]) -> Result<Vec<u8>, Failure> {
    let wire: RouteWire = parse_json(request, "route_request")?;
    let consents: Vec<OwnerConsent> = wire
        .remote
        .as_ref()
        .map(|remote| {
            remote
                .consents
                .iter()
                .map(|stored| OwnerConsent {
                    owner: stored.owner.clone(),
                    consent: NavigatorConsent {
                        provider: stored.provider.clone(),
                        consent: stored.consent.clone(),
                    },
                })
                .collect()
        })
        .unwrap_or_default();
    let remote = wire.remote.map(|remote| RemoteFacts {
        provider: remote.provider,
        credentials_configured: remote.credentials_configured,
        consent_text_version: remote.consent_text_version,
        echoed_consent: remote.echoed_consent.map(|echo| ConsentEcho {
            external_processing_allowed: echo.external_processing_allowed,
            provider: echo.provider,
        }),
        consents: &consents,
    });
    let terms = Terms {
        timeout_ms: wire.terms.timeout_ms,
        max_input_tokens: wire.terms.max_input_tokens,
        max_output_tokens: wire.terms.max_output_tokens,
    };
    let routed = ai_policy::route(&RouteRequest {
        owner: &wire.owner,
        language: None,
        privacy: PrivacyMode::RemoteAllowed,
        deterministic_sufficient: wire.deterministic_sufficient,
        cancelled: wire.cancelled,
        local: &[],
        failed_local: &[],
        remote,
        estimated_input_tokens: wire.estimated_input_tokens,
        terms,
    });
    to_json(&match &routed {
        Route::Deterministic => serde_json::json!({"route": "deterministic"}),
        Route::Local { terms, .. } => {
            serde_json::json!({"route": "local", "terms": terms_json(*terms)})
        }
        Route::Remote { grant, terms } => serde_json::json!({
            "route": "remote",
            "provider": grant.provider().as_str(),
            "consent_text_version": grant.consent_text_version().get(),
            "terms": terms_json(*terms),
        }),
        Route::Denied(denial) => denial_json(denial),
    })
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum KindWire {
    FirstStep,
    Reformulate,
    ProjectNextAction,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ValidateWire {
    kind: KindWire,
    task_title: Option<String>,
    task_notes: Option<String>,
    stall_reason: Option<String>,
    project_name: Option<String>,
    open_task_titles: Vec<String>,
    proposals: Vec<String>,
    clarifying_question: Option<String>,
}

/// `proposal::validate_navigator_output`: rules 1-4 of the navigator contract.
pub(crate) fn validate_navigator(request: &[u8]) -> Result<Vec<u8>, Failure> {
    let wire: ValidateWire = parse_json(request, "navigator_output")?;
    let input = NavigatorInput {
        kind: match wire.kind {
            KindWire::FirstStep => NavigatorKind::FirstStep,
            KindWire::Reformulate => NavigatorKind::Reformulate,
            KindWire::ProjectNextAction => NavigatorKind::ProjectNextAction,
        },
        task_title: wire.task_title,
        task_notes: wire.task_notes,
        stall_reason: wire.stall_reason,
        project_name: wire.project_name,
        open_task_titles: wire.open_task_titles,
    };
    to_json(&match proposal::validate_navigator_output(
        &input,
        &wire.proposals,
        wire.clarifying_question.as_deref(),
    ) {
        Ok(NavigatorOutput::Proposals(proposals)) => {
            serde_json::json!({"status": "proposals", "proposals": proposals})
        }
        Ok(NavigatorOutput::Question(question)) => {
            serde_json::json!({"status": "question", "question": question})
        }
        Err(refusal) => serde_json::json!({
            "status": "refused",
            "refusal": match refusal {
                ProposalRefusal::Malformed => "malformed",
                ProposalRefusal::NoUsefulSuggestion => "no_useful_suggestion",
            },
        }),
    })
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum LocalSourceWire {
    AppleOnDevice,
    DownloadedOnDevice,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum SourceWire {
    Local { source: LocalSourceWire },
    Remote { provider: ProviderName },
}

impl SourceWire {
    fn into_source(self) -> SuggestionSource {
        use bb_domain::ai_policy::LocalSource;
        match self {
            Self::Local {
                source: LocalSourceWire::AppleOnDevice,
            } => SuggestionSource::Local(LocalSource::AppleOnDevice),
            Self::Local {
                source: LocalSourceWire::DownloadedOnDevice,
            } => SuggestionSource::Local(LocalSource::DownloadedOnDevice),
            Self::Remote { provider } => SuggestionSource::Remote(provider),
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CandidateWire {
    command_type: CommandType,
    target: Id,
    payload: OpenObject,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BasisWire {
    check: RevisionCheck,
    source: SourceWire,
    consent_text_version: Option<TextVersion>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CurrentWire {
    edit_revision: Option<Counter>,
    source: SourceWire,
    consent_text_version: Option<TextVersion>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ConfirmWire {
    candidate: CandidateWire,
    basis: BasisWire,
    current: CurrentWire,
}

fn refused(error: &DomainError) -> serde_json::Value {
    serde_json::json!({"status": "refused", "error": error})
}

/// Types a proposed command, then applies an explicit confirmation to it.
///
/// The server calls this only once the person confirmed (`explicit_apply`); an
/// unconfirmed proposal is never passed across.
pub(crate) fn confirm_proposal(request: &[u8]) -> Result<Vec<u8>, Failure> {
    let wire: ConfirmWire = parse_json(request, "proposal")?;
    let candidate = Candidate {
        command_type: wire.candidate.command_type,
        target: wire.candidate.target,
        payload: wire.candidate.payload,
    };
    let basis = ProposalBasis {
        check: wire.basis.check,
        source: wire.basis.source.into_source(),
        consent_text_version: wire.basis.consent_text_version,
    };
    let current = CurrentFacts {
        edit_revision: wire.current.edit_revision,
        source: wire.current.source.into_source(),
        consent_text_version: wire.current.consent_text_version,
    };
    let confirmed = CommandProposal::new(&candidate, basis, NAVIGATOR_COMMANDS)
        .and_then(|proposed| proposed.confirm(Confirmation::explicit_apply(), &current));
    to_json(&match confirmed {
        Ok(command) => serde_json::json!({
            "status": "confirmed",
            "target": command.target,
            "command": command.command,
            "preconditions": command.preconditions,
        }),
        Err(error) => refused(&error),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::{Value, json};

    const OWNER: &str = "owner-1";

    fn route_json(request: &Value) -> Value {
        let out = route(request.to_string().as_bytes()).expect("routes");
        serde_json::from_slice(&out).expect("json")
    }

    fn remote(overrides: Value) -> Value {
        let mut base = json!({
            "provider": "openai",
            "credentials_configured": true,
            "consent_text_version": 1,
            "echoed_consent": {"external_processing_allowed": true, "provider": "openai"},
            "consents": [{"owner": OWNER, "provider": "openai", "consent": {
                "granted_at": "2026-10-09T12:00:00Z", "revoked_at": null,
                "consent_text_version": 1}}],
        });
        for (key, value) in overrides.as_object().expect("object") {
            base[key] = value.clone();
        }
        base
    }

    fn request(remote: Value) -> Value {
        json!({
            "owner": OWNER, "cancelled": false, "deterministic_sufficient": false,
            "remote": remote, "estimated_input_tokens": 10,
            "terms": {"timeout_ms": 8000, "max_input_tokens": 100, "max_output_tokens": 50},
        })
    }

    #[test]
    fn route_grants_a_remote_call_only_with_current_consent() {
        let out = route_json(&request(remote(json!({}))));
        assert_eq!(out["route"], "remote");
        assert_eq!(out["provider"], "openai");
        assert_eq!(out["terms"]["max_output_tokens"], 50);
    }

    #[test]
    fn route_denies_without_a_stored_consent_before_any_provider_call() {
        let out = route_json(&request(remote(json!({"consents": []}))));
        assert_eq!(out["route"], "denied");
        assert_eq!(out["denial"], "consent_required");
        assert_eq!(out["consent_state"], "missing");
        assert_eq!(out["reason"], "consent_required");
    }

    #[test]
    fn route_reports_outdated_and_revoked_consent_distinctly() {
        let outdated = route_json(&request(remote(json!({"consent_text_version": 2}))));
        assert_eq!(outdated["consent_state"], "text_outdated");
        let revoked = route_json(&request(remote(json!({"consents": [{
            "owner": OWNER, "provider": "openai", "consent": {
                "granted_at": "2026-10-09T12:00:00Z",
                "revoked_at": "2026-10-10T12:00:00Z", "consent_text_version": 1}}]}))));
        assert_eq!(revoked["consent_state"], "revoked");
    }

    #[test]
    fn route_denies_disabled_unconfigured_and_oversized_requests() {
        let disabled = route_json(&request(remote(json!({"provider": null}))));
        assert_eq!(disabled["denial"], "remote_disabled");
        let no_key = route_json(&request(remote(json!({"credentials_configured": false}))));
        assert_eq!(no_key["denial"], "credentials_missing");
        assert_eq!(no_key["reason"], "provider_unavailable");
        let mut large = request(remote(json!({})));
        large["estimated_input_tokens"] = json!(101);
        assert_eq!(route_json(&large)["denial"], "input_too_large");
    }

    #[test]
    fn route_cancellation_wins_over_a_valid_grant() {
        let mut cancelled = request(remote(json!({})));
        cancelled["cancelled"] = json!(true);
        let out = route_json(&cancelled);
        assert_eq!(out["denial"], "cancelled");
        assert_eq!(out["reason"], Value::Null);
    }

    #[test]
    fn route_refuses_a_malformed_request_without_echoing_it() {
        let failure = route(br#"{"owner": "secret text"}"#).expect_err("rejected");
        assert_eq!(
            failure,
            Failure::new("INVALID_REQUEST", Some("route_request"))
        );
    }

    fn validate_json(proposals: &[&str], question: Option<&str>) -> Value {
        let request = json!({
            "kind": "first_step", "task_title": "Write the report", "task_notes": null,
            "stall_reason": null, "project_name": null, "open_task_titles": [],
            "proposals": proposals, "clarifying_question": question,
        });
        let out = validate_navigator(request.to_string().as_bytes()).expect("validates");
        serde_json::from_slice(&out).expect("json")
    }

    #[test]
    fn validate_navigator_keeps_grounded_one_line_proposals() {
        let out = validate_json(&["Open the report file", "Smart #tag add"], None);
        assert_eq!(out["status"], "proposals");
        assert_eq!(out["proposals"], json!(["Open the report file"]));
    }

    #[test]
    fn validate_navigator_falls_back_to_a_question_then_refuses() {
        let question = validate_json(&[], Some("Which report is meant?"));
        assert_eq!(question["status"], "question");
        let refused = validate_json(&["Call Alice on 5 May"], None);
        assert_eq!(refused["status"], "refused");
        assert_eq!(refused["refusal"], "malformed");
    }

    fn confirm_json(command_type: &str, target: &str, payload: Value, now: Value) -> Value {
        let request = json!({
            "candidate": {"command_type": command_type, "target": target, "payload": payload},
            "basis": {
                "check": {"entity_type": "task", "entity_id": "task-1", "edit_revision": "3"},
                "source": {"kind": "remote", "provider": "openai"},
                "consent_text_version": 1},
            "current": {
                "edit_revision": now,
                "source": {"kind": "remote", "provider": "openai"},
                "consent_text_version": 1},
        });
        let out = confirm_proposal(request.to_string().as_bytes()).expect("answers");
        serde_json::from_slice(&out).expect("json")
    }

    #[test]
    fn proposal_confirms_only_on_the_basis_the_model_saw() {
        let update = json!({"title": "Open the report"});
        let current = confirm_json("task.update", "task-1", update.clone(), json!("3"));
        assert_eq!(current["status"], "confirmed");
        assert_eq!(current["preconditions"][0]["edit_revision"], "3");
        let stale = confirm_json("task.update", "task-1", update, json!("4"));
        assert_eq!(stale["error"]["reason"], "revision_conflict");
    }

    #[test]
    fn proposal_refuses_commands_off_the_allow_list() {
        let complete = confirm_json("task.transition", "task-1", json!({}), json!("3"));
        assert_eq!(complete["status"], "refused");
        assert_eq!(complete["error"]["reason"], "invalid_value");
    }
}

//! JSON adapters over the shared AI route policy and navigator answer
//! validation (`bb_domain::ai_policy`, `bb_domain::proposal`; tasks.md T049).
//!
//! These carry no policy of their own: they decode the caller's facts into the
//! domain types, call [`route`] / [`validate_navigator_output`] and encode the
//! outcome. A malformed request fails as `INVALID_REQUEST` naming only the
//! argument, never its content.

use super::{Failure, parse_json, to_json};
use bb_domain::ai_policy::{
    ConsentEcho, ConsentState, Denial, LocalExecutor, LocalSource, OwnerConsent, PrivacyMode,
    RemoteFacts, Route, RouteRequest, RuntimeState, Terms, UnavailableReason, route,
};
use bb_domain::proposal::{
    NavigatorInput, NavigatorKind, NavigatorOutput, ProposalRefusal, drop_known_duplicates,
    reduce_notes, validate_navigator_output,
};
use bb_domain::types::{NavigatorConsent, ProviderName, TextVersion};
use bb_protocol::wire::Id;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum PrivacyIn {
    OnDeviceOnly,
    RemoteAllowed,
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum SourceIn {
    AppleOnDevice,
    DownloadedOnDevice,
}

impl From<SourceIn> for LocalSource {
    fn from(source: SourceIn) -> Self {
        match source {
            SourceIn::AppleOnDevice => Self::AppleOnDevice,
            SourceIn::DownloadedOnDevice => Self::DownloadedOnDevice,
        }
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum RuntimeIn {
    Ready,
    DeviceNotEligible,
    SystemFeatureOff,
    ModelNotReady,
    NotDownloaded,
    Disabled,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LocalIn {
    source: SourceIn,
    runtime: RuntimeIn,
    supported_languages: Vec<String>,
    free_memory_mb: u64,
    required_memory_mb: u64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct EchoIn {
    external_processing_allowed: bool,
    provider: ProviderName,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct OwnerConsentIn {
    owner: Id,
    consent: NavigatorConsent,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RemoteIn {
    provider: Option<ProviderName>,
    credentials_configured: bool,
    consent_text_version: TextVersion,
    echoed_consent: Option<EchoIn>,
    consents: Vec<OwnerConsentIn>,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TermsIo {
    timeout_ms: u32,
    max_input_tokens: u32,
    max_output_tokens: u32,
}

impl From<TermsIo> for Terms {
    fn from(terms: TermsIo) -> Self {
        Self {
            timeout_ms: terms.timeout_ms,
            max_input_tokens: terms.max_input_tokens,
            max_output_tokens: terms.max_output_tokens,
        }
    }
}

impl From<Terms> for TermsIo {
    fn from(terms: Terms) -> Self {
        Self {
            timeout_ms: terms.timeout_ms,
            max_input_tokens: terms.max_input_tokens,
            max_output_tokens: terms.max_output_tokens,
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RouteIn {
    owner: Id,
    language: Option<String>,
    privacy: PrivacyIn,
    deterministic_sufficient: bool,
    cancelled: bool,
    local: Vec<LocalIn>,
    failed_local: Vec<SourceIn>,
    remote: Option<RemoteIn>,
    estimated_input_tokens: u32,
    terms: TermsIo,
}

fn source_name(source: LocalSource) -> &'static str {
    match source {
        LocalSource::AppleOnDevice => "apple_on_device",
        LocalSource::DownloadedOnDevice => "downloaded_on_device",
    }
}

fn unavailable_name(reason: UnavailableReason) -> &'static str {
    match reason {
        UnavailableReason::DeviceNotEligible => "device_not_eligible",
        UnavailableReason::SystemFeatureOff => "system_feature_off",
        UnavailableReason::ModelNotReady => "model_not_ready",
        UnavailableReason::NotDownloaded => "not_downloaded",
        UnavailableReason::Disabled => "disabled",
        UnavailableReason::UnsupportedLanguage => "unsupported_language",
        UnavailableReason::InsufficientMemory => "insufficient_memory",
        UnavailableReason::FailedThisRequest => "failed_this_request",
    }
}

fn consent_name(state: ConsentState) -> &'static str {
    match state {
        ConsentState::Current => "current",
        ConsentState::Missing => "missing",
        ConsentState::Revoked => "revoked",
        ConsentState::TextOutdated => "text_outdated",
    }
}

fn denial_json(denial: &Denial) -> Value {
    let reason = denial.reason().map(|reason| reason.as_str());
    let (kind, extra) = match denial {
        Denial::Cancelled => ("cancelled", Value::Null),
        Denial::LocalUnavailable(unavailable) => (
            "local_unavailable",
            json!(
                unavailable
                    .iter()
                    .map(|(source, reason)| {
                        json!({"source": source_name(*source), "reason": unavailable_name(*reason)})
                    })
                    .collect::<Vec<_>>()
            ),
        ),
        Denial::RemoteDisabled => ("remote_disabled", Value::Null),
        Denial::CredentialsMissing => ("credentials_missing", Value::Null),
        Denial::ProviderMismatch => ("provider_mismatch", Value::Null),
        Denial::ConsentRequired(state) => ("consent_required", json!(consent_name(*state))),
        Denial::InputTooLarge => ("input_too_large", Value::Null),
    };
    json!({"kind": kind, "detail": extra, "reason": reason})
}

/// `route(request)` over JSON facts; the answer names the executor or the denial.
pub(crate) fn route_json(data: &[u8]) -> Result<Vec<u8>, Failure> {
    let input: RouteIn = parse_json(data, "request")?;
    let local: Vec<LocalExecutor> = input
        .local
        .into_iter()
        .map(|executor| LocalExecutor {
            source: executor.source.into(),
            runtime: match executor.runtime {
                RuntimeIn::Ready => RuntimeState::Ready,
                RuntimeIn::DeviceNotEligible => RuntimeState::DeviceNotEligible,
                RuntimeIn::SystemFeatureOff => RuntimeState::SystemFeatureOff,
                RuntimeIn::ModelNotReady => RuntimeState::ModelNotReady,
                RuntimeIn::NotDownloaded => RuntimeState::NotDownloaded,
                RuntimeIn::Disabled => RuntimeState::Disabled,
            },
            supported_languages: executor.supported_languages,
            free_memory_mb: executor.free_memory_mb,
            required_memory_mb: executor.required_memory_mb,
        })
        .collect();
    let failed: Vec<LocalSource> = input.failed_local.into_iter().map(Into::into).collect();
    let consents: Vec<OwnerConsent> = input
        .remote
        .as_ref()
        .map(|remote| {
            remote
                .consents
                .iter()
                .map(|entry| OwnerConsent {
                    owner: entry.owner.clone(),
                    consent: entry.consent.clone(),
                })
                .collect()
        })
        .unwrap_or_default();
    let remote = input.remote.map(|remote| RemoteFacts {
        provider: remote.provider,
        credentials_configured: remote.credentials_configured,
        consent_text_version: remote.consent_text_version,
        echoed_consent: remote.echoed_consent.map(|echo| ConsentEcho {
            external_processing_allowed: echo.external_processing_allowed,
            provider: echo.provider,
        }),
        consents: &consents,
    });
    let request = RouteRequest {
        owner: &input.owner,
        language: input.language.as_deref(),
        privacy: match input.privacy {
            PrivacyIn::OnDeviceOnly => PrivacyMode::OnDeviceOnly,
            PrivacyIn::RemoteAllowed => PrivacyMode::RemoteAllowed,
        },
        deterministic_sufficient: input.deterministic_sufficient,
        cancelled: input.cancelled,
        local: &local,
        failed_local: &failed,
        remote,
        estimated_input_tokens: input.estimated_input_tokens,
        terms: input.terms.into(),
    };
    let answer = match route(&request) {
        Route::Deterministic => json!({"route": "deterministic"}),
        Route::Local { source, terms } => json!({
            "route": "local",
            "source": source_name(source),
            "terms": TermsIo::from(terms),
        }),
        Route::Remote { grant, terms } => json!({
            "route": "remote",
            "provider": grant.provider().as_str(),
            "consent_text_version": grant.consent_text_version().get(),
            "terms": TermsIo::from(terms),
        }),
        Route::Denied(denial) => json!({"route": "denied", "denial": denial_json(&denial)}),
    };
    to_json(&answer)
}

#[derive(Deserialize)]
#[serde(rename_all = "snake_case")]
enum KindIn {
    FirstStep,
    Reformulate,
    ProjectNextAction,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ValidateIn {
    kind: KindIn,
    task_title: Option<String>,
    task_notes: Option<String>,
    stall_reason: Option<String>,
    project_name: Option<String>,
    open_task_titles: Vec<String>,
    /// Open task titles of the whole project the client holds (rule 5).
    #[serde(default)]
    project_open_titles: Vec<String>,
    proposals: Vec<String>,
    clarifying_question: Option<String>,
}

/// Rules 1-4 and then rule 5 of the navigator contract over one model answer.
pub(crate) fn validate_json(data: &[u8]) -> Result<Vec<u8>, Failure> {
    let input: ValidateIn = parse_json(data, "answer")?;
    let navigator = NavigatorInput {
        kind: match input.kind {
            KindIn::FirstStep => NavigatorKind::FirstStep,
            KindIn::Reformulate => NavigatorKind::Reformulate,
            KindIn::ProjectNextAction => NavigatorKind::ProjectNextAction,
        },
        task_title: input.task_title,
        task_notes: input.task_notes,
        stall_reason: input.stall_reason,
        project_name: input.project_name,
        open_task_titles: input.open_task_titles,
    };
    let current_title = navigator.task_title.clone().unwrap_or_default();
    let checked = validate_navigator_output(
        &navigator,
        &input.proposals,
        input.clarifying_question.as_deref(),
    )
    .and_then(|output| drop_known_duplicates(output, &current_title, &input.project_open_titles));
    let answer = match checked {
        Ok(NavigatorOutput::Proposals(proposals)) => {
            json!({"outcome": "proposals", "proposals": proposals})
        }
        Ok(NavigatorOutput::Question(question)) => {
            json!({"outcome": "question", "question": question})
        }
        Err(ProposalRefusal::Malformed) => json!({"outcome": "malformed"}),
        Err(ProposalRefusal::NoUsefulSuggestion) => json!({"outcome": "no_useful_suggestion"}),
    };
    to_json(&answer)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NotesIn {
    notes: String,
}

/// The shared notes reduction (navigator contract section 1): at most 6 003 scalars.
pub(crate) fn reduce_notes_json(data: &[u8]) -> Result<Vec<u8>, Failure> {
    let input: NotesIn = parse_json(data, "notes")?;
    let (notes, truncated) = reduce_notes(&input.notes);
    to_json(&json!({"notes": notes, "truncated": truncated}))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn route_with(overrides: Value) -> Value {
        let mut request = json!({
            "owner": "00000000-0000-4000-8000-000000000001",
            "language": "en",
            "privacy": "on_device_only",
            "deterministic_sufficient": false,
            "cancelled": false,
            "local": [],
            "failed_local": [],
            "remote": null,
            "estimated_input_tokens": 10,
            "terms": {"timeout_ms": 1000, "max_input_tokens": 100, "max_output_tokens": 50},
        });
        for (key, value) in overrides.as_object().expect("object") {
            request[key] = value.clone();
        }
        let bytes = route_json(&serde_json::to_vec(&request).expect("json"))
            .unwrap_or_else(|failure| panic!("route failed: {}", failure.code));
        serde_json::from_slice(&bytes).expect("answer")
    }

    #[test]
    fn ai_026_fr_018_on_device_only_without_executor_is_denied_not_remote() {
        let answer = route_with(json!({}));
        assert_eq!(answer["route"], "denied");
        assert_eq!(answer["denial"]["kind"], "local_unavailable");
        assert_eq!(answer["denial"]["reason"], "provider_unavailable");
    }

    #[test]
    fn ai_026_fr_018_ready_local_executor_is_chosen() {
        let answer = route_with(json!({"local": [{
            "source": "apple_on_device", "runtime": "ready",
            "supported_languages": ["en-US"], "free_memory_mb": 900, "required_memory_mb": 500,
        }]}));
        assert_eq!(answer["route"], "local");
        assert_eq!(answer["source"], "apple_on_device");
    }

    #[test]
    fn ai_026_fr_019_remote_without_consent_is_denied_before_any_call() {
        let answer = route_with(json!({
            "privacy": "remote_allowed",
            "remote": {
                "provider": "openai", "credentials_configured": true,
                "consent_text_version": 1,
                "echoed_consent": {"external_processing_allowed": true, "provider": "openai"},
                "consents": [],
            },
        }));
        assert_eq!(answer["route"], "denied");
        assert_eq!(answer["denial"]["kind"], "consent_required");
        assert_eq!(answer["denial"]["detail"], "missing");
    }

    #[test]
    fn ai_026_fr_019_malformed_request_names_the_argument_only() {
        let failure = route_json(b"{\"owner\": 1}").expect_err("fails");
        assert_eq!(failure.code, "INVALID_REQUEST");
        assert_eq!(failure.field, Some("request"));
    }

    #[test]
    fn ai_026_fr_020_validation_rejects_an_ungrounded_answer() {
        let request = json!({
            "kind": "first_step", "task_title": "Plan the garden", "task_notes": null,
            "stall_reason": null, "project_name": null, "open_task_titles": [],
            "proposals": ["Wire money to account 4"], "clarifying_question": null,
        });
        let bytes = validate_json(&serde_json::to_vec(&request).expect("json")).expect("ok");
        let answer: Value = serde_json::from_slice(&bytes).expect("answer");
        assert_eq!(answer["outcome"], "malformed");
    }

    #[test]
    fn ai_026_fr_019_notes_reduction_is_the_shared_head_tail_rule() {
        let long = (0..3000)
            .map(|n| format!("line {n}"))
            .collect::<Vec<_>>()
            .join("\n");
        let request = json!({"notes": long});
        let bytes = reduce_notes_json(&serde_json::to_vec(&request).expect("json")).expect("ok");
        let answer: Value = serde_json::from_slice(&bytes).expect("answer");
        assert_eq!(answer["truncated"], true);
        assert!(answer["notes"].as_str().expect("text").chars().count() <= 6_003);
        let short = reduce_notes_json(b"{\"notes\":\"abc\"}").expect("ok");
        let answer: Value = serde_json::from_slice(&short).expect("answer");
        assert_eq!(answer["truncated"], false);
    }
}

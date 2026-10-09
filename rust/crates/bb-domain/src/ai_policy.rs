//! Shared AI route policy (026 FR-018, FR-019; tasks.md T047).
//!
//! A pure decision: given what the device can run, what the person allowed and
//! what the server is configured with, [`route`] says which executor may see
//! the input, or why none may. It calls no model and no network, reads no
//! clock, and a model's answer can never widen it:
//!
//! 1. Cancellation wins over everything and sends nothing.
//! 2. When deterministic rules already solve the task, no model runs.
//! 3. A suitable local executor (language, runtime, memory) is preferred.
//! 4. "On-device only" never leads to a remote route, including after a local
//!    executor failed (`failed_local`).
//! 5. A remote route needs a configured provider with credentials, the
//!    request's echoed consent and the stored, unrevoked consent of this owner
//!    for this provider at the current consent-text version. Anything missing
//!    is a denial before any provider call (ADR-0002, `NavigatorService._admit`).
//!
//! The only way to hold a [`RemoteGrant`] is to be handed one by [`route`], so
//! a remote call site cannot be reached around the consent check.
//!
//! Stateful admission (daily cost reservation, rate limiting) stays with the
//! server; this module owns the stateless part of it: the input-size guard and
//! the timeout and output limits the adapter must apply.

use crate::normalization::{casefold, strip};
use crate::types::{DomainError, Id, NavigatorConsent, ProviderName, Reason, TextVersion};

/// On-device or remote processing, as the person chose.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PrivacyMode {
    /// Remote inference is prohibited, also as a fallback after an error.
    OnDeviceOnly,
    /// The person chose a remote provider when no local executor is suitable.
    RemoteAllowed,
}

/// Where an on-device suggestion runs.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum LocalSource {
    AppleOnDevice,
    DownloadedOnDevice,
}

/// The runtime condition of a local executor, as its adapter reports it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RuntimeState {
    Ready,
    DeviceNotEligible,
    SystemFeatureOff,
    ModelNotReady,
    NotDownloaded,
    Disabled,
}

/// Why a local executor cannot take this request (navigator contract §4).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum UnavailableReason {
    DeviceNotEligible,
    SystemFeatureOff,
    ModelNotReady,
    NotDownloaded,
    Disabled,
    UnsupportedLanguage,
    InsufficientMemory,
    /// The executor failed on this request; the person is not silently moved on.
    FailedThisRequest,
}

/// One local executor: its runtime, languages and memory.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LocalExecutor {
    pub source: LocalSource,
    pub runtime: RuntimeState,
    /// BCP-47 tags the model supports; only the primary subtag is compared.
    pub supported_languages: Vec<String>,
    pub free_memory_mb: u64,
    pub required_memory_mb: u64,
}

impl LocalExecutor {
    /// `Ok(())` when the executor can take a request in `language`. An
    /// undetected language is unsupported: an unpinned model may answer in the
    /// wrong language, so the person gets the choice instead.
    pub fn availability(&self, language: Option<&str>) -> Result<(), UnavailableReason> {
        match self.runtime {
            RuntimeState::Ready => {}
            RuntimeState::DeviceNotEligible => return Err(UnavailableReason::DeviceNotEligible),
            RuntimeState::SystemFeatureOff => return Err(UnavailableReason::SystemFeatureOff),
            RuntimeState::ModelNotReady => return Err(UnavailableReason::ModelNotReady),
            RuntimeState::NotDownloaded => return Err(UnavailableReason::NotDownloaded),
            RuntimeState::Disabled => return Err(UnavailableReason::Disabled),
        }
        let wanted = language.map(primary_subtag);
        let supported = wanted.is_some_and(|wanted| {
            !wanted.is_empty()
                && self
                    .supported_languages
                    .iter()
                    .any(|tag| primary_subtag(tag) == wanted)
        });
        if !supported {
            return Err(UnavailableReason::UnsupportedLanguage);
        }
        if self.free_memory_mb < self.required_memory_mb {
            return Err(UnavailableReason::InsufficientMemory);
        }
        Ok(())
    }
}

fn primary_subtag(tag: &str) -> String {
    let tag = strip(tag);
    casefold(tag.split(['-', '_']).next().unwrap_or(""))
}

/// One owner's stored consent for one provider.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OwnerConsent {
    pub owner: Id,
    pub consent: NavigatorConsent,
}

/// What consent an owner currently has for a provider.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ConsentState {
    Current,
    /// Never granted, or a grant for another owner or provider.
    Missing,
    Revoked,
    /// Granted for an older consent text; counts as absent (data-model E8).
    TextOutdated,
}

/// The state of `owner`'s consent for `provider` at `current_version`.
///
/// Like the server, the first stored entry for the provider decides.
pub fn consent_state(
    ledger: &[OwnerConsent],
    owner: &Id,
    provider: &ProviderName,
    current_version: TextVersion,
) -> ConsentState {
    let stored = ledger
        .iter()
        .find(|entry| &entry.owner == owner && &entry.consent.provider == provider);
    let Some(grant) = stored.and_then(|entry| entry.consent.consent.as_ref()) else {
        return ConsentState::Missing;
    };
    if grant.revoked_at.is_some() {
        ConsentState::Revoked
    } else if grant.consent_text_version != current_version {
        ConsentState::TextOutdated
    } else {
        ConsentState::Current
    }
}

/// The consent the request itself carries (`NavigatorSuggestionRequest.consent`).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConsentEcho {
    pub external_processing_allowed: bool,
    pub provider: ProviderName,
}

/// The server-side facts about the remote provider.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RemoteFacts<'a> {
    /// The configured provider category; `None` when remote AI is switched off.
    pub provider: Option<ProviderName>,
    pub credentials_configured: bool,
    pub consent_text_version: TextVersion,
    pub echoed_consent: Option<ConsentEcho>,
    pub consents: &'a [OwnerConsent],
}

/// Limits the adapter must apply to whichever executor runs.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Terms {
    pub timeout_ms: u32,
    pub max_input_tokens: u32,
    pub max_output_tokens: u32,
}

/// Everything [`route`] decides on.
#[derive(Clone, Debug)]
pub struct RouteRequest<'a> {
    pub owner: &'a Id,
    /// Dominant language of the task text, detected on the device.
    pub language: Option<&'a str>,
    pub privacy: PrivacyMode,
    /// The deterministic rules already solve the task.
    pub deterministic_sufficient: bool,
    /// The person (or the lifecycle) cancelled the request.
    pub cancelled: bool,
    /// Local executors in order of preference.
    pub local: &'a [LocalExecutor],
    /// Executors that already failed on this request.
    pub failed_local: &'a [LocalSource],
    pub remote: Option<RemoteFacts<'a>>,
    pub estimated_input_tokens: u32,
    pub terms: Terms,
}

/// Permission to send the reduced input to one provider. Only [`route`] makes it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RemoteGrant {
    provider: ProviderName,
    consent_text_version: TextVersion,
}

impl RemoteGrant {
    pub fn provider(&self) -> &ProviderName {
        &self.provider
    }

    pub fn consent_text_version(&self) -> TextVersion {
        self.consent_text_version
    }
}

/// Which executor may run, with the limits it must keep.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Route {
    /// No model: deterministic rules suffice.
    Deterministic,
    Local {
        source: LocalSource,
        terms: Terms,
    },
    Remote {
        grant: RemoteGrant,
        terms: Terms,
    },
    /// Nothing runs and nothing is sent; manual task work stays available.
    Denied(Denial),
}

impl Route {
    pub fn is_remote(&self) -> bool {
        matches!(self, Self::Remote { .. })
    }
}

/// Why no executor may run.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Denial {
    Cancelled,
    /// On-device only (or no remote choice) and no local executor is suitable.
    LocalUnavailable(Vec<(LocalSource, UnavailableReason)>),
    /// Remote AI is not configured on the server.
    RemoteDisabled,
    CredentialsMissing,
    /// The echoed consent names another provider than the configured one.
    ProviderMismatch,
    ConsentRequired(ConsentState),
    InputTooLarge,
}

impl Denial {
    /// The canonical refusal reason with the server's wire code. A cancellation
    /// is not a refusal and has none.
    pub fn reason(&self) -> Option<Reason> {
        match self {
            Self::Cancelled => None,
            Self::LocalUnavailable(_) | Self::RemoteDisabled | Self::CredentialsMissing => {
                Some(Reason::ProviderUnavailable)
            }
            Self::ProviderMismatch | Self::ConsentRequired(_) => Some(Reason::ConsentRequired),
            Self::InputTooLarge => Some(Reason::TextLength),
        }
    }

    pub fn to_error(&self) -> Option<DomainError> {
        self.reason().map(DomainError::new)
    }
}

/// Chooses the executor for one request. Pure and total.
pub fn route(request: &RouteRequest<'_>) -> Route {
    if request.cancelled {
        return Route::Denied(Denial::Cancelled);
    }
    if request.deterministic_sufficient {
        return Route::Deterministic;
    }
    let mut unavailable = Vec::new();
    for executor in request.local {
        let outcome = if request.failed_local.contains(&executor.source) {
            Err(UnavailableReason::FailedThisRequest)
        } else {
            executor.availability(request.language)
        };
        match outcome {
            Ok(()) => {
                return sized(request, |terms| Route::Local {
                    source: executor.source,
                    terms,
                });
            }
            Err(reason) => unavailable.push((executor.source, reason)),
        }
    }
    if request.privacy == PrivacyMode::OnDeviceOnly {
        return Route::Denied(Denial::LocalUnavailable(unavailable));
    }
    let Some(remote) = &request.remote else {
        return Route::Denied(Denial::LocalUnavailable(unavailable));
    };
    match remote_grant(request.owner, remote) {
        Ok(grant) => sized(request, |terms| Route::Remote { grant, terms }),
        Err(denial) => Route::Denied(denial),
    }
}

/// The input-size guard: a model is not called when the reduced input does not
/// fit (contracts/navigator.md §1).
fn sized(request: &RouteRequest<'_>, build: impl FnOnce(Terms) -> Route) -> Route {
    if request.estimated_input_tokens > request.terms.max_input_tokens {
        Route::Denied(Denial::InputTooLarge)
    } else {
        build(request.terms)
    }
}

/// The order of `NavigatorService._admit`: provider, credentials, echoed
/// consent, stored consent.
fn remote_grant(owner: &Id, remote: &RemoteFacts<'_>) -> Result<RemoteGrant, Denial> {
    let Some(provider) = &remote.provider else {
        return Err(Denial::RemoteDisabled);
    };
    if !remote.credentials_configured {
        return Err(Denial::CredentialsMissing);
    }
    // The request must echo consent for this provider, as `_admit` requires:
    // a missing echo is a refusal, never a pass to the stored-consent check.
    let Some(echo) = &remote.echoed_consent else {
        return Err(Denial::ConsentRequired(ConsentState::Missing));
    };
    if !echo.external_processing_allowed {
        return Err(Denial::ConsentRequired(ConsentState::Missing));
    }
    if &echo.provider != provider {
        return Err(Denial::ProviderMismatch);
    }
    match consent_state(
        remote.consents,
        owner,
        provider,
        remote.consent_text_version,
    ) {
        ConsentState::Current => Ok(RemoteGrant {
            provider: provider.clone(),
            consent_text_version: remote.consent_text_version,
        }),
        other => Err(Denial::ConsentRequired(other)),
    }
}

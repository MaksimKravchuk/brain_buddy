//! Parity of the shared AI policy and proposal validation with the existing
//! navigator vectors, plus the policy risks no vector covers (tasks.md T047,
//! 026-FR-018..020).
//!
//! The vector tests run the byte-identical files the server, Swift core and web
//! run (`backend/tests/fixtures/navigator/`) and count what they executed, so a
//! missing or empty section fails instead of passing vacuously.

mod support;

use bb_domain::ai_policy::{
    ConsentEcho, ConsentState, Denial, LocalExecutor, LocalSource, OwnerConsent, PrivacyMode,
    RemoteFacts, Route, RouteRequest, RuntimeState, Terms, UnavailableReason, consent_state, route,
};
use bb_domain::proposal::{
    self, Candidate, CommandProposal, Confirmation, CurrentFacts, NAVIGATOR_COMMANDS,
    NavigatorInput, NavigatorKind, NavigatorOutput, ProposalBasis, ProposalRefusal,
    SuggestionSource, drop_known_duplicates, reduce_notes, validate_navigator_output,
};
use bb_domain::types::{
    Command, ConsentGrant, DomainError, EntityType, Id, NavigatorConsent, ProviderName, Reason,
    RevisionCheck, TextVersion,
};
use bb_protocol::catalog::CommandType;
use bb_protocol::wire::{CommandId, Counter, Instant};
use serde_json::{Value, json};
use std::path::PathBuf;
use support::{cases, text};

// ---------------------------------------------------------------- vectors

fn navigator_file(name: &str) -> Value {
    let path: PathBuf = support::repo_root()
        .join("backend/tests/fixtures/navigator")
        .join(name);
    let body = std::fs::read_to_string(&path)
        .unwrap_or_else(|error| panic!("cannot read {}: {error}", path.display()));
    serde_json::from_str(&body).unwrap_or_else(|error| panic!("invalid {name}: {error}"))
}

fn strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .unwrap_or_else(|| panic!("not an array: {value}"))
        .iter()
        .map(|item| item.as_str().unwrap_or_else(|| panic!("{item}")).to_owned())
        .collect()
}

fn optional(value: &Value) -> Option<String> {
    value.as_str().map(str::to_owned)
}

fn vector_input(fields: &Value) -> NavigatorInput {
    NavigatorInput {
        kind: match text(fields, "kind") {
            "first_step" => NavigatorKind::FirstStep,
            "reformulate" => NavigatorKind::Reformulate,
            "project_next_action" => NavigatorKind::ProjectNextAction,
            other => panic!("unknown kind {other}"),
        },
        task_title: optional(&fields["task_title"]),
        task_notes: optional(&fields["task_notes"]),
        stall_reason: optional(&fields["stall_reason"]),
        project_name: optional(&fields["project_name"]),
        open_task_titles: strings(&fields["open_task_titles"]),
    }
}

/// `[text, count]` pairs, repeated and concatenated.
fn expand(segments: &Value) -> String {
    segments
        .as_array()
        .expect("segments")
        .iter()
        .map(|pair| {
            let count = pair[1].as_u64().expect("count");
            pair[0].as_str().expect("text").repeat(count as usize)
        })
        .collect()
}

#[test]
fn ai_policy_026_fr_020_validator_vectors_match_the_server() {
    let file = navigator_file("validator_vectors.json");
    let vectors = cases(&file, "vectors");
    let mut ran = 0;
    let (mut proposals, mut questions, mut malformed) = (0, 0, 0);
    for vector in vectors {
        let id = text(vector, "id");
        let input = vector_input(&file["inputs"][text(vector, "input")]);
        let raw = strings(&vector["proposals"]);
        let question = optional(&vector["clarifying_question"]);
        let got = validate_navigator_output(&input, &raw, question.as_deref());
        let expect = &vector["expect"];
        match text(expect, "kind") {
            "proposals" => {
                proposals += 1;
                assert_eq!(
                    got,
                    Ok(NavigatorOutput::Proposals(strings(&expect["proposals"]))),
                    "{id}"
                );
            }
            "question" => {
                questions += 1;
                assert_eq!(
                    got,
                    Ok(NavigatorOutput::Question(
                        text(expect, "clarifying_question").to_owned()
                    )),
                    "{id}"
                );
            }
            "malformed" => {
                malformed += 1;
                assert_eq!(got, Err(ProposalRefusal::Malformed), "{id}");
            }
            other => panic!("{id}: unknown expectation {other}"),
        }
        ran += 1;
    }
    assert_eq!(ran, vectors.len());
    // The file's mix, so a vector filter cannot quietly drop a whole outcome.
    assert!(proposals > 90 && questions >= 2 && malformed >= 6);
}

#[test]
fn ai_policy_026_fr_020_rule_3_word_tables_are_the_vector_files() {
    let file = navigator_file("validator_vectors.json");
    let table = &file["date_words"];
    let same = |key: &str, ours: &[&str]| {
        assert_eq!(strings(&table[key]), ours, "{key}");
    };
    same("en_words", proposal::EN_DATE_WORDS);
    same("ru_stems", proposal::RU_DATE_STEMS);
    same("ru_words", proposal::RU_DATE_WORDS);
    same("phrases", proposal::DATE_PHRASES);
    same("prompt_sourced_words", proposal::PROMPT_SOURCED_WORDS);
    same("minute_words", proposal::MINUTE_WORDS);
    assert_eq!(table["minute_stem"], proposal::MINUTE_STEM);
    assert_eq!(
        table["max_exempt_duration_minutes"],
        proposal::MAX_EXEMPT_DURATION_MINUTES
    );
    assert!(!proposal::EN_DATE_WORDS.contains(&"may"));
}

#[test]
fn ai_policy_026_fr_020_reduce_notes_vectors_match_the_server() {
    let file = navigator_file("reduce_notes_vectors.json");
    let budget = &file["budget"];
    assert_eq!(budget["notes"], proposal::NOTES_BUDGET_CHARS);
    assert_eq!(budget["head"], proposal::NOTES_HEAD_CHARS);
    assert_eq!(budget["tail"], proposal::NOTES_TAIL_CHARS);
    assert_eq!(budget["separator"], proposal::NOTES_SEPARATOR);
    let vectors = cases(&file, "vectors");
    let mut truncated = 0;
    for vector in vectors {
        let id = text(vector, "id");
        let notes = expand(&vector["notes"]);
        let expected = if vector["expected"].is_null() {
            notes.clone()
        } else {
            expand(&vector["expected"])
        };
        let (reduced, dropped) = reduce_notes(&notes);
        assert_eq!(reduced, expected, "{id}");
        assert_eq!(
            dropped,
            vector["truncated"].as_bool().expect("flag"),
            "{id}"
        );
        assert!(reduced.chars().count() <= 6_003, "{id}");
        assert_eq!(reduce_notes(&reduced).0, reduced, "{id}: not stable");
        truncated += usize::from(dropped);
    }
    assert!(truncated > 0, "no vector truncated");
}

// -------------------------------------------------------------- rule 5

fn one_task_input() -> NavigatorInput {
    NavigatorInput {
        kind: NavigatorKind::FirstStep,
        task_title: Some("Renovate the bathroom".into()),
        task_notes: None,
        stall_reason: None,
        project_name: Some("Flat".into()),
        open_task_titles: vec![],
    }
}

#[test]
fn ai_policy_026_fr_020_rule_5_filters_a_title_that_was_not_among_the_20_sent() {
    // 25 open tasks, only 20 sent: the 21st is a duplicate the server cannot see.
    let titles: Vec<String> = ('a'..='y').map(|c| format!("Open task {c}{c}")).collect();
    let sent = titles[..20].to_vec();
    let mut input = one_task_input();
    input.open_task_titles = sent;
    let raw = vec!["Open task uu".to_owned()];
    // The server's rules 1-4 keep it ...
    let server = validate_navigator_output(&input, &raw, None);
    assert_eq!(
        server,
        Ok(NavigatorOutput::Proposals(vec!["Open task uu".into()]))
    );
    // ... and the client's rule 5 filters it, leaving "no useful suggestion".
    assert_eq!(
        drop_known_duplicates(server.expect("kept"), "Renovate the bathroom", &titles),
        Err(ProposalRefusal::NoUsefulSuggestion)
    );
}

#[test]
fn ai_policy_026_fr_020_rule_5_keeps_other_proposals_and_questions() {
    let kept = drop_known_duplicates(
        NavigatorOutput::Proposals(vec!["Buy paint!".into(), "Measure the wall".into()]),
        "Renovate the bathroom",
        &["buy paint".to_owned()],
    );
    assert_eq!(
        kept,
        Ok(NavigatorOutput::Proposals(vec!["Measure the wall".into()]))
    );
    let question = NavigatorOutput::Question("Which room?".into());
    assert_eq!(
        drop_known_duplicates(question.clone(), "x", &[]),
        Ok(question)
    );
}

// --------------------------------------------------------- output shape

#[test]
fn ai_policy_026_fr_020_one_question_or_proposals_never_neither_never_more_than_three() {
    let input = one_task_input();
    let many: Vec<String> = [
        "Measure the wall",
        "Buy tiles",
        "Call a tiler",
        "Clear the floor",
    ]
    .map(str::to_owned)
    .to_vec();
    // Four grounded proposals: at most three are shown.
    match validate_navigator_output(&input, &many, None) {
        Ok(NavigatorOutput::Proposals(shown)) => assert_eq!(shown.len(), 3),
        other => panic!("{other:?}"),
    }
    // Proposals win over a question that came with them.
    let both = validate_navigator_output(&input, &many[..1], Some("Which room?"));
    assert!(matches!(both, Ok(NavigatorOutput::Proposals(_))));
    // No proposal and no question is malformed, as is an ungrounded question.
    assert_eq!(
        validate_navigator_output(&input, &[], None),
        Err(ProposalRefusal::Malformed)
    );
    assert_eq!(
        validate_navigator_output(&input, &["   ".into()], Some("Ask Boris?")),
        Err(ProposalRefusal::Malformed)
    );
    // A question must be one line.
    assert_eq!(
        validate_navigator_output(&input, &[], Some("Which\nroom?")),
        Err(ProposalRefusal::Malformed)
    );
}

// ----------------------------------------------------------- route policy

const OWNER: &str = "owner-a";
const CURRENT: u32 = 2;

fn id(value: &str) -> Id {
    Id::parse(value).expect("id")
}

fn provider(name: &str) -> ProviderName {
    ProviderName::new(name).expect("provider")
}

fn version(n: u32) -> TextVersion {
    TextVersion::new(n).expect("version")
}

fn terms() -> Terms {
    Terms {
        timeout_ms: 20_000,
        max_input_tokens: 6_000,
        max_output_tokens: 300,
    }
}

fn apple(runtime: RuntimeState) -> LocalExecutor {
    LocalExecutor {
        source: LocalSource::AppleOnDevice,
        runtime,
        supported_languages: vec!["en-US".into(), "de".into()],
        free_memory_mb: 3_000,
        required_memory_mb: 2_000,
    }
}

fn grant(owner: &str, name: &str, ver: u32, revoked: bool) -> OwnerConsent {
    OwnerConsent {
        owner: id(owner),
        consent: NavigatorConsent {
            provider: provider(name),
            consent: Some(ConsentGrant {
                granted_at: Instant::parse("2026-10-01T09:00:00Z").expect("instant"),
                revoked_at: revoked
                    .then(|| Instant::parse("2026-10-02T09:00:00Z").expect("instant")),
                consent_text_version: version(ver),
            }),
        },
    }
}

struct Scenario {
    owner: Id,
    local: Vec<LocalExecutor>,
    failed: Vec<LocalSource>,
    consents: Vec<OwnerConsent>,
    privacy: PrivacyMode,
    language: Option<&'static str>,
    cancelled: bool,
    deterministic: bool,
    provider: Option<ProviderName>,
    credentials: bool,
    echo: Option<ConsentEcho>,
    tokens: u32,
}

impl Scenario {
    fn new() -> Self {
        Self {
            owner: id(OWNER),
            local: vec![apple(RuntimeState::Ready)],
            failed: vec![],
            consents: vec![grant(OWNER, "openai", CURRENT, false)],
            privacy: PrivacyMode::RemoteAllowed,
            language: Some("en"),
            cancelled: false,
            deterministic: false,
            provider: Some(provider("openai")),
            credentials: true,
            echo: Some(ConsentEcho {
                external_processing_allowed: true,
                provider: provider("openai"),
            }),
            tokens: 500,
        }
    }

    fn route(&self) -> Route {
        route(&RouteRequest {
            owner: &self.owner,
            language: self.language,
            privacy: self.privacy,
            deterministic_sufficient: self.deterministic,
            cancelled: self.cancelled,
            local: &self.local,
            failed_local: &self.failed,
            remote: Some(RemoteFacts {
                provider: self.provider.clone(),
                credentials_configured: self.credentials,
                consent_text_version: version(CURRENT),
                echoed_consent: self.echo.clone(),
                consents: &self.consents,
            }),
            estimated_input_tokens: self.tokens,
            terms: terms(),
        })
    }
}

#[test]
fn ai_policy_026_fr_018_a_suitable_local_executor_is_preferred_even_with_consent() {
    let scenario = Scenario::new();
    assert_eq!(
        scenario.route(),
        Route::Local {
            source: LocalSource::AppleOnDevice,
            terms: terms()
        }
    );
}

#[test]
fn ai_policy_026_fr_018_deterministic_rules_run_no_model_and_basic_work_needs_no_ai() {
    let mut scenario = Scenario::new();
    scenario.deterministic = true;
    assert_eq!(scenario.route(), Route::Deterministic);
    // No executor, no remote choice, nothing configured: still a clean denial,
    // never a panic or a forced remote call.
    let mut bare = Scenario::new();
    bare.local.clear();
    bare.privacy = PrivacyMode::OnDeviceOnly;
    bare.provider = None;
    assert!(matches!(
        bare.route(),
        Route::Denied(Denial::LocalUnavailable(reasons)) if reasons.is_empty()
    ));
}

#[test]
fn ai_policy_026_fr_018_local_suitability_names_language_runtime_and_memory() {
    let reasons = |runtime, language: Option<&'static str>, free| {
        let mut executor = apple(runtime);
        executor.free_memory_mb = free;
        executor.availability(language)
    };
    assert_eq!(reasons(RuntimeState::Ready, Some("en-GB"), 3_000), Ok(()));
    assert_eq!(reasons(RuntimeState::Ready, Some("DE_de"), 3_000), Ok(()));
    assert_eq!(
        reasons(RuntimeState::Ready, Some("ru"), 3_000),
        Err(UnavailableReason::UnsupportedLanguage)
    );
    assert_eq!(
        reasons(RuntimeState::Ready, None, 3_000),
        Err(UnavailableReason::UnsupportedLanguage)
    );
    assert_eq!(
        reasons(RuntimeState::Ready, Some("en"), 1_999),
        Err(UnavailableReason::InsufficientMemory)
    );
    for (runtime, reason) in [
        (
            RuntimeState::DeviceNotEligible,
            UnavailableReason::DeviceNotEligible,
        ),
        (
            RuntimeState::SystemFeatureOff,
            UnavailableReason::SystemFeatureOff,
        ),
        (
            RuntimeState::ModelNotReady,
            UnavailableReason::ModelNotReady,
        ),
        (
            RuntimeState::NotDownloaded,
            UnavailableReason::NotDownloaded,
        ),
        (RuntimeState::Disabled, UnavailableReason::Disabled),
    ] {
        assert_eq!(reasons(runtime, Some("en"), 3_000), Err(reason));
    }
}

#[test]
fn ai_policy_026_fr_018_on_device_only_never_routes_remote_whatever_else_is_true() {
    // Every combination of local state, failure and consent, with full remote
    // consent available: on-device only must never produce a remote route.
    for runtime in [RuntimeState::Ready, RuntimeState::NotDownloaded] {
        for failed in [false, true] {
            for language in [Some("en"), Some("ru"), None] {
                let mut scenario = Scenario::new();
                scenario.privacy = PrivacyMode::OnDeviceOnly;
                scenario.local = vec![apple(runtime)];
                scenario.language = language;
                if failed {
                    scenario.failed = vec![LocalSource::AppleOnDevice];
                }
                let routed = scenario.route();
                assert!(!routed.is_remote(), "{runtime:?} {failed} {language:?}");
            }
        }
    }
}

#[test]
fn ai_policy_026_fr_018_a_local_error_is_not_silently_retried_remotely_when_on_device_only() {
    let mut scenario = Scenario::new();
    scenario.privacy = PrivacyMode::OnDeviceOnly;
    scenario.failed = vec![LocalSource::AppleOnDevice];
    assert_eq!(
        scenario.route(),
        Route::Denied(Denial::LocalUnavailable(vec![(
            LocalSource::AppleOnDevice,
            UnavailableReason::FailedThisRequest
        )]))
    );
}

#[test]
fn ai_policy_026_fr_019_remote_needs_current_consent_for_this_owner_and_provider() {
    let remote_only = || {
        let mut scenario = Scenario::new();
        scenario.local.clear();
        scenario
    };
    // Current consent, configured provider: remote with a grant naming it.
    match remote_only().route() {
        Route::Remote { grant, terms: t } => {
            assert_eq!(grant.provider(), &provider("openai"));
            assert_eq!(grant.consent_text_version(), version(CURRENT));
            assert_eq!(t, terms());
        }
        other => panic!("{other:?}"),
    }
    let denied = |scenario: &Scenario| match scenario.route() {
        Route::Denied(denial) => denial,
        other => panic!("{other:?}"),
    };
    // Never granted, another owner's grant, another provider's grant.
    let mut none = remote_only();
    none.consents.clear();
    assert_eq!(
        denied(&none),
        Denial::ConsentRequired(ConsentState::Missing)
    );
    let mut other_owner = remote_only();
    other_owner.consents = vec![grant("owner-b", "openai", CURRENT, false)];
    assert_eq!(
        denied(&other_owner),
        Denial::ConsentRequired(ConsentState::Missing)
    );
    let mut other_provider = remote_only();
    other_provider.consents = vec![grant(OWNER, "anthropic", CURRENT, false)];
    assert_eq!(
        denied(&other_provider),
        Denial::ConsentRequired(ConsentState::Missing)
    );
    // Revoked, and a grant for an older consent text, both count as absent.
    let mut revoked = remote_only();
    revoked.consents = vec![grant(OWNER, "openai", CURRENT, true)];
    assert_eq!(
        denied(&revoked),
        Denial::ConsentRequired(ConsentState::Revoked)
    );
    let mut outdated = remote_only();
    outdated.consents = vec![grant(OWNER, "openai", CURRENT - 1, false)];
    assert_eq!(
        denied(&outdated),
        Denial::ConsentRequired(ConsentState::TextOutdated)
    );
    // Sync consent is not AI consent: no ledger entry is no consent, whatever
    // else about the account is true.
    assert_eq!(denied(&none).reason(), Some(Reason::ConsentRequired));
}

#[test]
fn ai_policy_026_fr_019_declined_echo_provider_mismatch_and_configuration_short_circuit() {
    let remote_only = || {
        let mut scenario = Scenario::new();
        scenario.local.clear();
        scenario
    };
    let denial = |scenario: Scenario| match scenario.route() {
        Route::Denied(denial) => denial,
        other => panic!("{other:?}"),
    };
    let mut declined = remote_only();
    declined.echo = Some(ConsentEcho {
        external_processing_allowed: false,
        provider: provider("openai"),
    });
    assert!(matches!(denial(declined), Denial::ConsentRequired(_)));
    let mut mismatch = remote_only();
    mismatch.echo = Some(ConsentEcho {
        external_processing_allowed: true,
        provider: provider("anthropic"),
    });
    assert_eq!(denial(mismatch), Denial::ProviderMismatch);
    // Current stored consent never stands in for the request's own echo.
    let mut no_echo = remote_only();
    no_echo.echo = None;
    assert_eq!(
        denial(no_echo),
        Denial::ConsentRequired(ConsentState::Missing)
    );
    let mut disabled = remote_only();
    disabled.provider = None;
    assert_eq!(denial(disabled), Denial::RemoteDisabled);
    let mut no_credentials = remote_only();
    no_credentials.credentials = false;
    assert_eq!(denial(no_credentials), Denial::CredentialsMissing);
    let mut too_large = remote_only();
    too_large.tokens = 6_001;
    assert_eq!(denial(too_large), Denial::InputTooLarge);
    assert_eq!(
        Denial::ProviderMismatch.reason(),
        Some(Reason::ConsentRequired)
    );
    assert_eq!(
        Denial::RemoteDisabled.reason(),
        Some(Reason::ProviderUnavailable)
    );
}

#[test]
fn ai_policy_026_fr_019_no_remote_route_without_a_remote_choice() {
    // Local unavailable, remote facts absent (not offered): choice screen, no call.
    let mut scenario = Scenario::new();
    scenario.local = vec![apple(RuntimeState::NotDownloaded)];
    let result = route(&RouteRequest {
        owner: &scenario.owner,
        language: Some("en"),
        privacy: PrivacyMode::RemoteAllowed,
        deterministic_sufficient: false,
        cancelled: false,
        local: &scenario.local,
        failed_local: &[],
        remote: None,
        estimated_input_tokens: 10,
        terms: terms(),
    });
    assert_eq!(
        result,
        Route::Denied(Denial::LocalUnavailable(vec![(
            LocalSource::AppleOnDevice,
            UnavailableReason::NotDownloaded
        )]))
    );
}

#[test]
fn ai_policy_026_fr_019_cancellation_wins_over_every_route() {
    let mut scenario = Scenario::new();
    scenario.cancelled = true;
    scenario.deterministic = true;
    assert_eq!(scenario.route(), Route::Denied(Denial::Cancelled));
    assert_eq!(Denial::Cancelled.reason(), None);
    assert_eq!(Denial::Cancelled.to_error(), None);
    scenario.local.clear();
    assert_eq!(scenario.route(), Route::Denied(Denial::Cancelled));
}

#[test]
fn ai_policy_026_fr_019_local_input_too_large_sends_nothing() {
    let mut scenario = Scenario::new();
    scenario.tokens = 6_001;
    assert_eq!(scenario.route(), Route::Denied(Denial::InputTooLarge));
}

#[test]
fn ai_policy_026_fr_019_revoke_takes_effect_for_the_next_request() {
    let ledger = |revoked| [grant(OWNER, "openai", CURRENT, revoked)];
    let state = |entries: &[OwnerConsent]| {
        consent_state(entries, &id(OWNER), &provider("openai"), version(CURRENT))
    };
    assert_eq!(state(&ledger(false)), ConsentState::Current);
    assert_eq!(state(&ledger(true)), ConsentState::Revoked);
    assert_eq!(state(&[]), ConsentState::Missing);
    // A stored entry without a grant is not consent.
    let mut empty = grant(OWNER, "openai", CURRENT, false);
    empty.consent.consent = None;
    assert_eq!(state(&[empty]), ConsentState::Missing);
}

// ------------------------------------------------------- command proposals

const TASK: &str = "task_9f3c2a1b4d5e";

fn basis(revision: u64) -> ProposalBasis {
    ProposalBasis {
        check: RevisionCheck {
            entity_type: EntityType::Task,
            entity_id: id(TASK),
            edit_revision: Counter::from(revision),
        },
        source: SuggestionSource::Remote(provider("openai")),
        consent_text_version: Some(version(CURRENT)),
    }
}

fn current(revision: Option<u64>) -> CurrentFacts {
    CurrentFacts {
        edit_revision: revision.map(Counter::from),
        source: SuggestionSource::Remote(provider("openai")),
        consent_text_version: Some(version(CURRENT)),
    }
}

fn candidate(command_type: CommandType, payload: Value) -> Candidate {
    Candidate {
        command_type,
        target: id(TASK),
        payload: payload.as_object().expect("object").clone(),
    }
}

fn reformulate() -> Candidate {
    candidate(
        CommandType::ReviewDecide,
        json!({
            "decision_id": "decision_0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
            "type": "reformulate",
            "formulation_id": "form_0b1c2d3e-4f50-4a6b-8c7d-9e0f1a2b3c4d",
            "title": "Measure the bathroom wall",
            "ai_use": "as_is"
        }),
    )
}

fn reason(error: Result<CommandProposal, DomainError>) -> Reason {
    error.expect_err("refused").reason
}

#[test]
fn ai_policy_026_fr_020_a_proposal_off_the_allow_list_is_refused_before_anything_else() {
    // A model cannot propose completion, consent, settings or bulk commands.
    for refused in [
        candidate(CommandType::TaskTransition, json!({ "action": "complete" })),
        candidate(
            CommandType::ReviewConsentGrant,
            json!({ "provider": "openai", "consent_text_version": 2 }),
        ),
        candidate(CommandType::ReviewConsentRevoke, json!({ "provider": "x" })),
        candidate(CommandType::ReviewSettings, json!({ "threshold_days": 1 })),
        candidate(CommandType::ReviewBulkUndo, json!({})),
        candidate(CommandType::TagDelete, json!({})),
    ] {
        assert_eq!(
            reason(CommandProposal::new(&refused, basis(3), NAVIGATOR_COMMANDS)),
            Reason::InvalidValue,
            "{:?}",
            refused.command_type
        );
    }
    for allowed in NAVIGATOR_COMMANDS {
        assert!(!matches!(
            allowed,
            CommandType::TaskTransition
                | CommandType::ReviewConsentGrant
                | CommandType::ReviewConsentRevoke
        ));
    }
}

#[test]
fn ai_policy_026_fr_020_a_proposal_must_be_a_well_formed_catalog_payload() {
    // Unknown field, wrong type, empty title: structural refusals, no command.
    for bad in [
        json!({ "title": "ok", "state": "completed" }),
        json!({ "title": 5 }),
        json!({ "title": "" }),
    ] {
        let candidate = candidate(CommandType::TaskUpdate, bad);
        assert_eq!(
            reason(CommandProposal::new(
                &candidate,
                basis(3),
                NAVIGATOR_COMMANDS
            )),
            Reason::InvalidPayload
        );
    }
    // A decision that the shape rules refuse (title missing for reformulate).
    let mut incomplete = reformulate();
    incomplete.payload.remove("title");
    assert_eq!(
        reason(CommandProposal::new(
            &incomplete,
            basis(3),
            NAVIGATOR_COMMANDS
        )),
        Reason::DecisionFieldsMissing
    );
}

#[test]
fn ai_policy_026_fr_020_a_decision_proposal_cannot_complete_or_cancel_the_task() {
    for decision in ["complete", "cancel", "someday", "waiting", "extend"] {
        let mut candidate = reformulate();
        candidate.payload.insert("type".into(), json!(decision));
        candidate
            .payload
            .insert("waiting_for".into(), json!("someone"));
        candidate.payload.insert("reason".into(), json!("why"));
        let refused = CommandProposal::new(&candidate, basis(3), NAVIGATOR_COMMANDS);
        assert_eq!(reason(refused), Reason::DecisionNotAllowed, "{decision}");
    }
}

#[test]
fn ai_policy_026_fr_020_an_explicit_apply_yields_the_ordinary_command_with_its_revision_fence() {
    let proposal =
        CommandProposal::new(&reformulate(), basis(3), NAVIGATOR_COMMANDS).expect("valid proposal");
    // Holding a proposal changes nothing and carries no way to execute it.
    assert!(matches!(proposal.command(), Command::ReviewDecide(_)));
    let confirmed = proposal
        .confirm(Confirmation::explicit_apply(), &current(Some(3)))
        .expect("current basis");
    assert_eq!(confirmed.preconditions, vec![basis(3).check]);
    let command_id = CommandId::parse("8f14e45f-ceea-467a-9575-0a8c5d1d3a7f").expect("uuid");
    let issued = Instant::parse("2026-10-09T10:00:00Z").expect("instant");
    let domain = confirmed.into_domain_command(command_id.clone(), issued.clone());
    assert_eq!(domain.command_id, command_id);
    assert_eq!(domain.issued_at, issued);
    assert_eq!(domain.entity_id, id(TASK));
    assert_eq!(domain.command_type(), CommandType::ReviewDecide);
    assert_eq!(domain.preconditions.len(), 1);
}

#[test]
fn ai_policy_026_fr_020_a_stale_proposal_is_refused_not_applied() {
    let proposal =
        CommandProposal::new(&reformulate(), basis(3), NAVIGATOR_COMMANDS).expect("valid proposal");
    let apply = |facts: &CurrentFacts| {
        proposal
            .confirm(Confirmation::explicit_apply(), facts)
            .expect_err("stale")
    };
    // The task was edited since the model ran: revision conflict naming the
    // current revision.
    let edited = apply(&current(Some(4)));
    assert_eq!(edited.reason, Reason::RevisionConflict);
    assert_eq!(edited.current_revision, Some(Counter::from(4u64)));
    // The task is gone.
    assert_eq!(apply(&current(None)).reason, Reason::NotFound);
    // The provider changed.
    let mut other_provider = current(Some(3));
    other_provider.source = SuggestionSource::Remote(provider("anthropic"));
    assert_eq!(apply(&other_provider).reason, Reason::ProviderUnavailable);
    let mut local = current(Some(3));
    local.source = SuggestionSource::Local(LocalSource::AppleOnDevice);
    assert_eq!(apply(&local).reason, Reason::ProviderUnavailable);
    // The consent text changed after the proposal was produced.
    let mut text_changed = current(Some(3));
    text_changed.consent_text_version = Some(version(CURRENT + 1));
    assert_eq!(apply(&text_changed).reason, Reason::ConsentTextOutdated);
    // Consent revoked (no current text version at all) is the same refusal.
    let mut revoked = current(Some(3));
    revoked.consent_text_version = None;
    assert_eq!(apply(&revoked).reason, Reason::ConsentTextOutdated);
}

#[test]
fn ai_policy_026_fr_020_creating_a_task_from_a_project_proposal_is_fenced_on_the_project() {
    let project_basis = ProposalBasis {
        check: RevisionCheck {
            entity_type: EntityType::Project,
            entity_id: id("project_3b2a1c0d9e8f"),
            edit_revision: Counter::from(7u64),
        },
        source: SuggestionSource::Local(LocalSource::AppleOnDevice),
        consent_text_version: None,
    };
    let create = candidate(
        CommandType::TaskCreate,
        json!({ "title": "Call the plumber", "project_id": "project_3b2a1c0d9e8f" }),
    );
    let proposal = CommandProposal::new(&create, project_basis, NAVIGATOR_COMMANDS).expect("valid");
    let facts = CurrentFacts {
        edit_revision: Some(Counter::from(7u64)),
        source: SuggestionSource::Local(LocalSource::AppleOnDevice),
        consent_text_version: None,
    };
    let confirmed = proposal
        .confirm(Confirmation::explicit_apply(), &facts)
        .expect("current");
    assert!(matches!(confirmed.command, Command::TaskCreate(_)));
    assert_eq!(confirmed.preconditions[0].entity_type, EntityType::Project);
}

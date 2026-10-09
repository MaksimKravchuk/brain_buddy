//! AI output validation and the proposal boundary (026 FR-020; tasks.md T047).
//!
//! Two layers, neither of which applies anything:
//!
//! * **Text output** ([`validate_navigator_output`]): rules 1-4 of
//!   `specs/020-weekly-review/contracts/navigator.md` section 2, ported from
//!   `validate_navigator_output` in `backend/app/modules/tasks/navigator.py`
//!   and verified against the same shared vectors. A result is one to three
//!   grounded one-line proposals, or exactly one clarifying question, or a
//!   [`ProposalRefusal`]. [`reduce_notes`] (section 1) and the client-side
//!   duplicate filter (rule 5, [`drop_known_duplicates`]) live here too.
//! * **Command proposals** ([`CommandProposal`]): a typed catalog command an
//!   adapter wants to propose. It must be on the allow-list, must parse as its
//!   catalog payload and pass its shape rules, and is inert: only
//!   [`CommandProposal::confirm`], given an explicit [`Confirmation`] and the
//!   current facts, yields a [`ConfirmedCommand`] that the caller submits
//!   through the ordinary command pipeline. A stale basis (the task changed, the
//!   provider changed, the consent text changed) is refused there, and the
//!   ordinary execute boundary re-validates against current state regardless.
//!
//! A model response grants no capability: nothing in this module consults the
//! response to decide permissions, and no function here mutates anything.

use crate::ai_policy::LocalSource;
use crate::normalization::{formulation_key, is_space, scalar_len, strip};
use crate::types::{
    Command, DecisionType, DomainCommand, DomainError, Id, ProviderName, Reason, RevisionCheck,
    TextVersion,
};
use bb_protocol::catalog::CommandType;
use bb_protocol::wire::{CommandId, Counter, Instant, OpenObject};
use std::collections::BTreeSet;
use unicode_general_category::{GeneralCategory, get_general_category};

// ------------------------------------------------------------------ input

/// Which suggestion is asked for.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NavigatorKind {
    FirstStep,
    Reformulate,
    ProjectNextAction,
}

/// FR-019: the only data any model receives. No ids, dates or language.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NavigatorInput {
    pub kind: NavigatorKind,
    pub task_title: Option<String>,
    pub task_notes: Option<String>,
    pub stall_reason: Option<String>,
    pub project_name: Option<String>,
    pub open_task_titles: Vec<String>,
}

pub const NOTES_BUDGET_CHARS: usize = 6_000;
pub const NOTES_HEAD_CHARS: usize = 2_000;
pub const NOTES_TAIL_CHARS: usize = 4_000;
/// U+000A U+2026 U+000A: the one line put between the kept head and tail.
pub const NOTES_SEPARATOR: &str = "\n\u{2026}\n";

/// How many leading `lines`, joined by U+000A, fit `budget` scalars.
fn fitting_count<'a>(lines: impl Iterator<Item = &'a str>, budget: usize) -> usize {
    let mut used = 0;
    let mut count = 0;
    for line in lines {
        let cost = scalar_len(line) + usize::from(count > 0);
        if used + cost > budget {
            return count;
        }
        used += cost;
        count += 1;
    }
    count
}

/// The one shared notes reduction (navigator contract section 1): notes of at
/// most 6 000 scalars are unchanged; longer notes keep whole first lines up to
/// 2 000 scalars and whole last lines up to 4 000, joined by
/// [`NOTES_SEPARATOR`]. The flag is `true` when a line was dropped.
#[must_use]
pub fn reduce_notes(notes: &str) -> (String, bool) {
    if scalar_len(notes) <= NOTES_BUDGET_CHARS {
        return (notes.to_owned(), false);
    }
    let lines: Vec<&str> = notes
        .split('\n')
        .map(|line| line.strip_suffix('\r').unwrap_or(line))
        .collect();
    let head = fitting_count(lines.iter().copied(), NOTES_HEAD_CHARS);
    let tail = fitting_count(lines[head..].iter().rev().copied(), NOTES_TAIL_CHARS);
    if head + tail == lines.len() {
        return (lines.join("\n"), false);
    }
    let kept_head = lines[..head].join("\n");
    let kept_tail = lines[lines.len() - tail..].join("\n");
    (format!("{kept_head}{NOTES_SEPARATOR}{kept_tail}"), true)
}

// ----------------------------------------------------------------- output

pub const MAX_PROPOSALS: usize = 3;
pub const MAX_PROPOSAL_CHARS: usize = 200;
pub const MAX_QUESTION_CHARS: usize = 500;
pub const MAX_EXEMPT_DURATION_MINUTES: u64 = 30;

/// The normative rule 3 tables (`date_words` of `validator_vectors.json`), in
/// `formulation_key` form.
pub const EN_DATE_WORDS: &[&str] = &[
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "tonight",
    "tomorrow",
];
pub const RU_DATE_STEMS: &[&str] = &[
    "январ",
    "феврал",
    "март",
    "апрел",
    "июн",
    "июл",
    "август",
    "сентябр",
    "октябр",
    "ноябр",
    "декабр",
    "понедельник",
    "вторник",
    "четверг",
    "пятниц",
    "суббот",
    "воскресень",
];
pub const RU_DATE_WORDS: &[&str] = &[
    "май",
    "мая",
    "мае",
    "маю",
    "маем",
    "среда",
    "среду",
    "среды",
    "среде",
    "средой",
    "завтра",
    "послезавтра",
];
pub const DATE_PHRASES: &[&str] = &[
    "next week",
    "next month",
    "this weekend",
    "на следующей неделе",
];
pub const PROMPT_SOURCED_WORDS: &[&str] = &["today", "сегодня"];
pub const MINUTE_WORDS: &[&str] = &["min", "mins", "minute", "minutes", "мин"];
pub const MINUTE_STEM: &str = "минут";

/// A validated model answer: one to three proposals, or one question.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum NavigatorOutput {
    Proposals(Vec<String>),
    Question(String),
}

/// Why a model answer is not shown.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProposalRefusal {
    /// Nothing usable survived rules 1-4 (`navigator_malformed_output`).
    Malformed,
    /// Rule 5 left no proposal ("No useful suggestion this time").
    NoUsefulSuggestion,
}

/// Python's `str.splitlines()` boundaries.
fn is_line_break(c: char) -> bool {
    matches!(
        c,
        '\n' | '\r'
            | '\u{0B}'
            | '\u{0C}'
            | '\u{1C}'
            | '\u{1D}'
            | '\u{1E}'
            | '\u{85}'
            | '\u{2028}'
            | '\u{2029}'
    )
}

/// Rule 1 shape: trimmed, non-empty, one line, at most `limit` scalars.
fn single_line(value: &str, limit: usize) -> Option<&str> {
    let text = strip(value);
    if text.is_empty() || text.chars().any(is_line_break) || scalar_len(text) > limit {
        None
    } else {
        Some(text)
    }
}

/// Python's `str.isalpha` for one scalar: category `L*`.
fn is_letter(c: char) -> bool {
    matches!(
        get_general_category(c),
        GeneralCategory::UppercaseLetter
            | GeneralCategory::LowercaseLetter
            | GeneralCategory::TitlecaseLetter
            | GeneralCategory::ModifierLetter
            | GeneralCategory::OtherLetter
    )
}

fn is_name_char(c: char) -> bool {
    c == '_'
        || is_letter(c)
        || matches!(
            get_general_category(c),
            GeneralCategory::NonspacingMark
                | GeneralCategory::SpacingMark
                | GeneralCategory::EnclosingMark
                | GeneralCategory::DecimalNumber
                | GeneralCategory::LetterNumber
                | GeneralCategory::OtherNumber
        )
}

/// A `#`/`@` tag or `!` priority marker the task parser would read. The sigil
/// must start a word (string start, whitespace or an opening bracket).
fn has_smart_add_token(text: &str) -> bool {
    let chars: Vec<char> = text.chars().collect();
    for (index, &sigil) in chars.iter().enumerate() {
        if !matches!(sigil, '#' | '@' | '!') {
            continue;
        }
        if index > 0 && !(is_space(chars[index - 1]) || matches!(chars[index - 1], '(' | '[' | '{'))
        {
            continue;
        }
        let Some(&following) = chars.get(index + 1) else {
            continue;
        };
        let reads = if sigil == '!' {
            !is_space(following)
        } else {
            following == '"' || is_name_char(following)
        };
        if reads {
            return true;
        }
    }
    false
}

/// A month, weekday or relative day word (`formulation_key` form).
#[must_use]
pub fn is_date_word(key: &str) -> bool {
    EN_DATE_WORDS.contains(&key)
        || RU_DATE_WORDS.contains(&key)
        || RU_DATE_STEMS.iter().any(|stem| key.starts_with(stem))
}

/// Rule 3 triggers: a capitalised word after the first, a number, a currency
/// amount or a date expression.
fn needs_grounding(token: &str, first: bool, key: &str) -> bool {
    let capitalised = token
        .chars()
        .find(|&c| is_letter(c))
        .is_some_and(char::is_uppercase);
    (capitalised && !first)
        || token
            .chars()
            .any(|c| get_general_category(c) == GeneralCategory::DecimalNumber)
        || token
            .chars()
            .any(|c| get_general_category(c) == GeneralCategory::CurrencySymbol)
        || is_date_word(key)
}

fn is_minute_word(word: &str) -> bool {
    MINUTE_WORDS.contains(&word) || word.starts_with(MINUTE_STEM)
}

/// ASCII digits only, at most [`MAX_EXEMPT_DURATION_MINUTES`].
fn is_short_minutes(word: &str) -> bool {
    !word.is_empty()
        && word.bytes().all(|b| b.is_ascii_digit())
        && word
            .parse::<u64>()
            .is_ok_and(|minutes| minutes <= MAX_EXEMPT_DURATION_MINUTES)
}

fn words(key: &str) -> Vec<&str> {
    key.split(is_space)
        .filter(|word| !word.is_empty())
        .collect()
}

/// Tokens of a duration of at most 30 minutes: a number joined to its minute
/// word ("2-minute") or followed by one ("10 minutes").
fn duration_tokens(keys: &[String]) -> BTreeSet<usize> {
    let mut exempt = BTreeSet::new();
    for (index, key) in keys.iter().enumerate() {
        let parts = words(key);
        let Some(first) = parts.first() else { continue };
        if !is_short_minutes(first) {
            continue;
        }
        if parts.len() == 2 && is_minute_word(parts[1]) {
            exempt.insert(index);
        } else if parts.len() == 1
            && let Some(next) = keys.get(index + 1)
            && words(next).first().is_some_and(|word| is_minute_word(word))
        {
            exempt.insert(index);
            exempt.insert(index + 1);
        }
    }
    exempt
}

/// What rule 3 must find in the input, as `formulation_key` text.
fn grounding_terms(text: &str) -> Vec<String> {
    let tokens: Vec<&str> = text.split(is_space).filter(|t| !t.is_empty()).collect();
    let keys: Vec<String> = tokens.iter().map(|token| formulation_key(token)).collect();
    let mut exempt = duration_tokens(&keys);
    exempt.extend(
        keys.iter()
            .enumerate()
            .filter(|(_, key)| PROMPT_SOURCED_WORDS.contains(&key.as_str()))
            .map(|(index, _)| index),
    );
    let mut terms: Vec<String> = tokens
        .iter()
        .zip(&keys)
        .enumerate()
        .filter(|(index, (token, key))| {
            !key.is_empty() && !exempt.contains(index) && needs_grounding(token, *index == 0, key)
        })
        .map(|(_, (_, key))| key.clone())
        .collect();
    let keyed = format!(" {} ", formulation_key(text));
    terms.extend(
        DATE_PHRASES
            .iter()
            .filter(|phrase| keyed.contains(&format!(" {phrase} ")))
            .map(|phrase| (*phrase).to_owned()),
    );
    terms
}

fn input_keys(input: &NavigatorInput) -> Vec<String> {
    input
        .task_title
        .iter()
        .chain(&input.task_notes)
        .chain(&input.project_name)
        .chain(&input.open_task_titles)
        .filter(|value| !value.is_empty())
        .map(|value| format!(" {} ", formulation_key(value)))
        .collect()
}

/// Rule 3 (FR-021): every grounding term occurs as whole words in one input field.
fn is_grounded(text: &str, keys: &[String]) -> bool {
    grounding_terms(text).iter().all(|term| {
        let needle = format!(" {term} ");
        keys.iter().any(|field| field.contains(&needle))
    })
}

/// Rule 2 and rule 5: drops a proposal whose formulation key equals the
/// current title's, any listed open task's or an earlier proposal's.
fn drop_duplicates<'a>(
    proposals: impl IntoIterator<Item = &'a str>,
    current_title: &str,
    open_titles: &[String],
) -> Vec<&'a str> {
    let mut seen: BTreeSet<String> = open_titles.iter().map(|t| formulation_key(t)).collect();
    seen.insert(formulation_key(current_title));
    proposals
        .into_iter()
        .filter(|proposal| seen.insert(formulation_key(proposal)))
        .collect()
}

/// Rules 1-4 of the navigator contract section 2. `proposals` and
/// `clarifying_question` are the model's raw answer. Identical to the server's
/// and the other clients' validators; rule 5 is [`drop_known_duplicates`].
pub fn validate_navigator_output(
    input: &NavigatorInput,
    proposals: &[String],
    clarifying_question: Option<&str>,
) -> Result<NavigatorOutput, ProposalRefusal> {
    let shaped = proposals
        .iter()
        .filter_map(|value| single_line(value, MAX_PROPOSAL_CHARS))
        .filter(|text| !has_smart_add_token(text));
    let unique = drop_duplicates(
        shaped,
        input.task_title.as_deref().unwrap_or(""),
        &input.open_task_titles,
    );
    let keys = input_keys(input);
    let grounded: Vec<String> = unique
        .into_iter()
        .filter(|text| is_grounded(text, &keys))
        .take(MAX_PROPOSALS)
        .map(str::to_owned)
        .collect();
    if !grounded.is_empty() {
        return Ok(NavigatorOutput::Proposals(grounded));
    }
    clarifying_question
        .and_then(|question| single_line(question, MAX_QUESTION_CHARS))
        .filter(|question| is_grounded(question, &keys))
        .map(|question| NavigatorOutput::Question(question.to_owned()))
        .ok_or(ProposalRefusal::Malformed)
}

/// Rule 5, run by every client after rules 1-4: drops proposals equal to the
/// current title or to any open task of the project the client holds (not only
/// the 20 titles sent), or to an earlier proposal. A question passes.
pub fn drop_known_duplicates(
    output: NavigatorOutput,
    current_title: &str,
    project_open_titles: &[String],
) -> Result<NavigatorOutput, ProposalRefusal> {
    match output {
        NavigatorOutput::Question(_) => Ok(output),
        NavigatorOutput::Proposals(proposals) => {
            let kept = drop_duplicates(
                proposals.iter().map(String::as_str),
                current_title,
                project_open_titles,
            );
            if kept.is_empty() {
                Err(ProposalRefusal::NoUsefulSuggestion)
            } else {
                Ok(NavigatorOutput::Proposals(
                    kept.into_iter().map(str::to_owned).collect(),
                ))
            }
        }
    }
}

// --------------------------------------------------------------- commands

/// Who produced a suggestion; a change of source makes a proposal stale.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SuggestionSource {
    Local(LocalSource),
    Remote(ProviderName),
}

/// What a proposal was computed from.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProposalBasis {
    /// The record and edit revision the model saw.
    pub check: RevisionCheck,
    pub source: SuggestionSource,
    /// The consent text a remote proposal was produced under.
    pub consent_text_version: Option<TextVersion>,
}

/// The same facts now.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CurrentFacts {
    /// `None` when the record is gone.
    pub edit_revision: Option<Counter>,
    pub source: SuggestionSource,
    pub consent_text_version: Option<TextVersion>,
}

/// The catalog commands an AI proposal may carry. It never includes
/// lifecycle transitions (completion stays a separate, explicit Tasks
/// command), consent, settings or bulk commands.
pub const NAVIGATOR_COMMANDS: &[CommandType] = &[
    CommandType::TaskCreate,
    CommandType::TaskUpdate,
    CommandType::SubtaskCreate,
    CommandType::ReviewDecide,
];

/// A command as an adapter proposes it, before typing.
#[derive(Clone, Debug, PartialEq)]
pub struct Candidate {
    pub command_type: CommandType,
    /// The envelope `entity_id`.
    pub target: Id,
    pub payload: OpenObject,
}

/// Proof that a person explicitly chose to apply a proposal. UI adapters build
/// it from the Apply action only; there is no `Default`.
#[derive(Clone, Copy, Debug)]
pub struct Confirmation(());

impl Confirmation {
    #[must_use]
    pub fn explicit_apply() -> Self {
        Self(())
    }
}

/// A typed, allow-listed, inert command proposal.
#[derive(Clone, Debug, PartialEq)]
pub struct CommandProposal {
    target: Id,
    command: Command,
    basis: ProposalBasis,
}

impl CommandProposal {
    /// Types and checks `candidate` against `allowed` (normally
    /// [`NAVIGATOR_COMMANDS`]). A decision proposal may only reformulate or
    /// name a first step.
    pub fn new(
        candidate: &Candidate,
        basis: ProposalBasis,
        allowed: &[CommandType],
    ) -> Result<Self, DomainError> {
        if !allowed.contains(&candidate.command_type) {
            return Err(DomainError::field(Reason::InvalidValue, "type"));
        }
        let command = Command::from_payload(candidate.command_type, &candidate.payload)?;
        if let Command::ReviewDecide(decide) = &command
            && !matches!(
                decide.decision_type,
                DecisionType::Reformulate | DecisionType::FirstStep
            )
        {
            return Err(DomainError::field(Reason::DecisionNotAllowed, "type"));
        }
        command.check_shape()?;
        Ok(Self {
            target: candidate.target.clone(),
            command,
            basis,
        })
    }

    pub fn command(&self) -> &Command {
        &self.command
    }

    pub fn basis(&self) -> &ProposalBasis {
        &self.basis
    }

    /// Refuses a proposal whose basis changed since the model ran.
    pub fn check_current(&self, current: &CurrentFacts) -> Result<(), DomainError> {
        let RevisionCheck {
            entity_type,
            entity_id,
            edit_revision,
        } = &self.basis.check;
        let key = vec![entity_id.as_str().to_owned()];
        match &current.edit_revision {
            None => return Err(DomainError::about(Reason::NotFound, *entity_type, key)),
            Some(now) if now != edit_revision => {
                return Err(DomainError::stale(*entity_type, key, now.clone()));
            }
            Some(_) => {}
        }
        if current.source != self.basis.source {
            return Err(DomainError::field(Reason::ProviderUnavailable, "source"));
        }
        if current.consent_text_version != self.basis.consent_text_version {
            return Err(DomainError::new(Reason::ConsentTextOutdated));
        }
        Ok(())
    }

    /// The only way out of a proposal: an explicit apply on a current basis
    /// yields the command to submit through the ordinary pipeline, with the
    /// revision the model saw as its precondition.
    pub fn confirm(
        &self,
        _confirmation: Confirmation,
        current: &CurrentFacts,
    ) -> Result<ConfirmedCommand, DomainError> {
        self.check_current(current)?;
        Ok(ConfirmedCommand {
            target: self.target.clone(),
            command: self.command.clone(),
            preconditions: vec![self.basis.check.clone()],
        })
    }
}

/// A command a person confirmed, not yet executed.
#[derive(Clone, Debug, PartialEq)]
pub struct ConfirmedCommand {
    pub target: Id,
    pub command: Command,
    pub preconditions: Vec<RevisionCheck>,
}

impl ConfirmedCommand {
    /// The ordinary command for the execute boundary; its identity and issue
    /// time are inputs, never generated here.
    #[must_use]
    pub fn into_domain_command(self, command_id: CommandId, issued_at: Instant) -> DomainCommand {
        DomainCommand {
            command_id,
            entity_id: self.target,
            issued_at,
            preconditions: self.preconditions,
            command: self.command,
        }
    }
}

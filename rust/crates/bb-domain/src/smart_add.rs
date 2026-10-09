//! The Smart Add rule family (026 PR-11): the deterministic text grammar, the
//! resolution of its `#tag` / `@project` tokens against the protected read set,
//! and the pure decision for the `task.smart_add` catalog command.
//!
//! Three entry points, one per concern:
//!
//! * [`parse`]: the grammar. Ported from the Swift `SmartAddParser`, which is
//!   the normative parser (tasks.md T011); the web tokenizer
//!   (`smartAdd.ts`, `smart-add-web/1`) is a presentation adapter that must
//!   agree with it, and its documented divergences are the web's.
//! * [`resolve`] / [`propose`]: the Swift `CapturePlanner` resolution. Draft
//!   text plus the read set give the clean title, the project and tags it
//!   would use or create, the first problem, and the proposed `task.smart_add`
//!   payload. No clock, no randomness: the proposed classification IDs are
//!   minted by the caller's closures.
//! * [`decide`]: the server rule (`TaskService.smart_add_task`,
//!   `_resolve_smart_add_project`, `_resolve_smart_add_tags`) on a structured
//!   payload. The parser never runs on the server.
//!
//! | Reference | Decision |
//! | --- | --- |
//! | `{id}` | the record must exist and be active (`organize::check_references`) |
//! | `{name, proposed_id}` | the active namesake (normalized key) is reused; an inactive namesake and no active one is refused; otherwise a record is created under `proposed_id` |
//! | tags | duplicates collapse to one membership; first occurrence keeps the position |
//! | receipt | `id_bindings` holds `proposed_id -> resolved id` for every by-name reference (identity when the record was created), content-free |
//!
//! Changes come in application order: the new project, the new tags, then the
//! task. Waiting is checked first, then the project, then the tags, as the
//! server does, so a refusal never leaves a partial write.

use crate::normalization as norm;
use crate::organize;
use crate::task_rules;
use crate::types::{
    Binding, ChangeOutcome, ChangeSet, ClassificationRef, Command, Counter, Details, DomainChange,
    DomainCommand, DomainError, DueDay, EntityType, ExecutionInputs, Name, OpenList, Priority,
    Project, ProjectId, ProjectState, ReadSet, Reason, Record, ResultRefs, SmartAdd, Tag, TagId,
    TagState, TaskCreate, TaskId, Title, WaitingFor,
};
use unicode_general_category::{GeneralCategory, get_general_category};

/// Whether this family decides `command`.
#[must_use]
pub fn handles(command: &Command) -> bool {
    matches!(command, Command::TaskSmartAdd(_))
}

// ----------------------------------------------------------------------- grammar

/// Which sigil opened a token.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TokenKind {
    /// `@project`
    Project,
    /// `#tag`
    Tag,
}

/// A completed token, for highlighting and resolution.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Token {
    pub kind: TokenKind,
    /// Offsets in UTF-16 code units (sigil to one past the body), so they map
    /// directly onto the platform text ranges that highlight them.
    pub utf16_start: usize,
    pub utf16_end: usize,
    /// The decoded body after NFKC, trim and whitespace collapse. A legacy
    /// sigil inside a quoted name (`#"#work"`) is still there; resolution
    /// drops it.
    pub name: String,
}

/// What the grammar makes of a text.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Parsed {
    /// The stored title: completed tokens, brackets that wrapped a lone token
    /// and escape backslashes removed, whitespace runs collapsed to one space,
    /// ends trimmed, and no space before `,.;:!?)]}`.
    pub clean_title: String,
    /// Every completed token in text order, including duplicate tags and
    /// superseded projects (they leave the title too).
    pub tokens: Vec<Token>,
}

struct Span {
    kind: TokenKind,
    /// Scalar offsets: `start` is the sigil, `end` is one past the body.
    start: usize,
    end: usize,
    name: String,
}

/// Exactly JavaScript's `\s` (WhiteSpace and LineTerminator), so boundaries and
/// title cleanup agree with the web character for character. It differs from
/// Unicode `White_Space` in U+FEFF (included) and U+0085 (excluded), and from
/// the server's `str.isspace()` in U+001C..U+001F.
const fn is_js_space(c: char) -> bool {
    matches!(
        c,
        '\u{09}'..='\u{0D}'
            | '\u{20}'
            | '\u{A0}'
            | '\u{1680}'
            | '\u{2000}'..='\u{200A}'
            | '\u{2028}'
            | '\u{2029}'
            | '\u{202F}'
            | '\u{205F}'
            | '\u{3000}'
            | '\u{FEFF}'
    )
}

/// Unicode Letter, Number or Mark, or `_` (the web's `[\p{L}\p{N}\p{M}_]`).
fn is_name_char(c: char) -> bool {
    c == '_'
        || matches!(
            get_general_category(c),
            GeneralCategory::UppercaseLetter
                | GeneralCategory::LowercaseLetter
                | GeneralCategory::TitlecaseLetter
                | GeneralCategory::ModifierLetter
                | GeneralCategory::OtherLetter
                | GeneralCategory::DecimalNumber
                | GeneralCategory::LetterNumber
                | GeneralCategory::OtherNumber
                | GeneralCategory::NonspacingMark
                | GeneralCategory::SpacingMark
                | GeneralCategory::EnclosingMark
        )
}

fn has_left_boundary(chars: &[char], index: usize) -> bool {
    index == 0 || {
        let previous = chars[index - 1];
        is_js_space(previous) || matches!(previous, '(' | '[' | '{')
    }
}

/// `quote` is the opening `"`. `None` when the quote never closes or a line
/// break comes first: the token is then incomplete and stays literal.
fn parse_quoted(chars: &[char], quote: usize) -> Option<(String, usize)> {
    let mut name = String::new();
    let mut index = quote + 1;
    while index < chars.len() {
        let c = chars[index];
        if c == '\n' || c == '\r' {
            return None;
        }
        if c == '\\' && matches!(chars.get(index + 1), Some('"' | '\\')) {
            name.push(chars[index + 1]);
            index += 2;
            continue;
        }
        if c == '"' {
            return Some((name, index + 1));
        }
        // Any other backslash is kept as written (`#"literal \q"`).
        name.push(c);
        index += 1;
    }
    None
}

/// Name characters, with `-` or `.` inside the name only when a name character
/// follows.
fn parse_unquoted(chars: &[char], start: usize) -> Option<(String, usize)> {
    if !chars.get(start).copied().is_some_and(is_name_char) {
        return None;
    }
    let mut end = start + 1;
    while end < chars.len() {
        let c = chars[end];
        let inner = matches!(c, '-' | '.') && chars.get(end + 1).copied().is_some_and(is_name_char);
        if is_name_char(c) || inner {
            end += 1;
        } else {
            break;
        }
    }
    Some((chars[start..end].iter().collect(), end))
}

/// Collapses whitespace runs to one ASCII space and trims the ends. With
/// `tighten`, a run before closing punctuation is dropped.
fn collapsed(chars: impl IntoIterator<Item = char>, tighten: bool) -> String {
    let mut output = String::new();
    let mut pending_space = false;
    for c in chars {
        if is_js_space(c) {
            pending_space = !output.is_empty();
            continue;
        }
        let closing = matches!(c, ',' | '.' | ';' | ':' | '!' | '?' | ')' | ']' | '}');
        if pending_space && !(tighten && closing) {
            output.push(' ');
        }
        pending_space = false;
        output.push(c);
    }
    output
}

/// The Smart Add grammar.
///
/// * `#tag` and `@project`; quoted `#"deep work"` / `@"Two words"` with `\"`
///   and `\\` escapes, no line break, and an unterminated quote stays literal.
/// * `\#` and `\@` at a token boundary are literal sigils; the backslash is
///   dropped from the title.
/// * A token needs a left boundary (start, whitespace, `(`, `[`, `{`), so `C#`
///   and `max@example.com` stay literal.
/// * Unquoted names are Unicode letters, marks and numbers plus `_`, with `-`
///   or `.` inside the name only when a name character follows.
///
/// The text is walked by Unicode scalar. The web walks UTF-16 code units, which
/// differs only outside the Basic Multilingual Plane; the scalar reading is the
/// one the contract describes.
#[must_use]
pub fn parse(text: &str) -> Parsed {
    let chars: Vec<char> = text.chars().collect();
    let mut utf16 = Vec::with_capacity(chars.len() + 1);
    utf16.push(0usize);
    for c in &chars {
        utf16.push(utf16[utf16.len() - 1] + c.len_utf16());
    }

    let mut spans: Vec<Span> = Vec::new();
    let mut escapes: Vec<usize> = Vec::new();
    let mut index = 0;
    while index < chars.len() {
        let c = chars[index];
        let next = chars.get(index + 1).copied();
        if c == '\\' && matches!(next, Some('#' | '@')) && has_left_boundary(&chars, index) {
            escapes.push(index);
            index += 2;
            continue;
        }
        if !matches!(c, '#' | '@') || !has_left_boundary(&chars, index) {
            index += 1;
            continue;
        }
        let body = if next == Some('"') {
            parse_quoted(&chars, index + 1)
        } else {
            parse_unquoted(&chars, index + 1)
        };
        let Some((raw, end)) = body else {
            index += 1;
            continue;
        };
        let name = collapsed(norm::nfkc(&raw).chars(), false);
        if name.is_empty() {
            index += 1;
            continue;
        }
        let kind = if c == '#' {
            TokenKind::Tag
        } else {
            TokenKind::Project
        };
        spans.push(Span {
            kind,
            start: index,
            end,
            name,
        });
        index = end;
    }

    let clean_title = clean_title(&chars, &spans, &escapes);
    let tokens = spans
        .into_iter()
        .map(|span| Token {
            kind: span.kind,
            utf16_start: utf16[span.start],
            utf16_end: utf16[span.end],
            name: span.name,
        })
        .collect();
    Parsed {
        clean_title,
        tokens,
    }
}

fn wrapper_close(open: char) -> Option<char> {
    match open {
        '(' => Some(')'),
        '[' => Some(']'),
        '{' => Some('}'),
        _ => None,
    }
}

fn clean_title(chars: &[char], spans: &[Span], escapes: &[usize]) -> String {
    let mut removed = vec![false; chars.len()];
    for span in spans {
        let (mut start, mut end) = (span.start, span.end);
        // Everything between a bracket found here and the token is whitespace,
        // so a matching pair wraps the token alone.
        let mut left = start;
        while left > 0 && is_js_space(chars[left - 1]) {
            left -= 1;
        }
        let mut right = end;
        while right < chars.len() && is_js_space(chars[right]) {
            right += 1;
        }
        if left > 0
            && right < chars.len()
            && wrapper_close(chars[left - 1]).is_some_and(|close| chars[right] == close)
        {
            start = left - 1;
            end = right + 1;
        }
        removed[start..end].fill(true);
    }
    for &position in escapes {
        removed[position] = true;
    }
    collapsed(
        chars
            .iter()
            .zip(&removed)
            .filter(|(_, gone)| !**gone)
            .map(|(c, _)| *c),
        true,
    )
}

// -------------------------------------------------------------------- resolution

/// What capture holds: text that may contain tokens plus the structured fields
/// of the sheet. `context_*` is the project or tag screen the capture started
/// from; it applies unless a token overrides it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Draft {
    pub text: String,
    pub list: OpenList,
    pub waiting_for: String,
    pub details: String,
    pub due_date: Option<DueDay>,
    pub priority: Priority,
    pub context_project: Option<ProjectId>,
    pub context_tag: Option<TagId>,
}

impl Draft {
    /// An Inbox draft of `text` with nothing else set.
    #[must_use]
    pub fn new(text: impl Into<String>) -> Self {
        Self {
            text: text.into(),
            list: OpenList::Inbox,
            waiting_for: String::new(),
            details: String::new(),
            due_date: None,
            priority: Priority::None,
            context_project: None,
            context_tag: None,
        }
    }
}

/// A project or tag capture would use or create.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Classification<I> {
    /// An existing record, with its stored name.
    Existing { id: I, name: String },
    /// A record capture would create, in display form.
    New { name: String },
}

impl<I> Classification<I> {
    /// The name the classification shows.
    #[must_use]
    pub fn name(&self) -> &str {
        match self {
            Self::Existing { name, .. } | Self::New { name } => name,
        }
    }

    /// Whether capture would create it.
    #[must_use]
    pub fn is_new(&self) -> bool {
        matches!(self, Self::New { .. })
    }
}

/// How a draft becomes a project, tags and a task, shared by the preview that
/// is drawn on every keystroke and by [`propose`], so the two cannot disagree.
#[derive(Clone, Debug, PartialEq)]
pub struct Resolution {
    pub title: String,
    pub tokens: Vec<Token>,
    pub project: Option<Classification<ProjectId>>,
    pub tags: Vec<Classification<TagId>>,
    /// Trimmed; only when the draft is for Waiting.
    pub waiting_for: Option<String>,
    /// `None` when blank; otherwise exactly as typed.
    pub details: Option<String>,
    /// The first problem in reading order: title, project, tags, waiting note,
    /// notes.
    pub problem: Option<DomainError>,
}

fn drop_sigil(name: &str, sigils: &[char]) -> String {
    let mut chars = name.chars();
    match chars.next() {
        Some(first) if sigils.contains(&first) => chars.collect(),
        _ => name.to_owned(),
    }
}

/// A stored name as the web compares it: display form, one legacy sigil gone.
fn legacy_project_key(name: &str) -> String {
    norm::project_key(&drop_sigil(&norm::project_display(name), &['@']))
}

fn legacy_tag_key(name: &str) -> String {
    norm::tag_key(&drop_sigil(&norm::project_display(name), &['#', '@']))
}

fn about(reason: Reason, entity_type: EntityType, id: &str, field: &str) -> DomainError {
    DomainError {
        field: Some(field.to_owned()),
        ..DomainError::about(reason, entity_type, vec![id.to_owned()])
    }
}

type Resolved<T> = (Option<T>, Option<DomainError>);

/// The last `@project` token wins; superseded names are neither resolved nor
/// created. Without a token the context project applies.
fn resolve_project(
    read_set: &ReadSet,
    draft: &Draft,
    tokens: &[Token],
) -> Resolved<Classification<ProjectId>> {
    let Some(token) = tokens.iter().rfind(|t| t.kind == TokenKind::Project) else {
        let Some(context) = &draft.context_project else {
            return (None, None);
        };
        let Some(record) = read_set.projects.get(context) else {
            return (
                None,
                Some(DomainError::about(
                    Reason::NotFound,
                    EntityType::Project,
                    vec![context.as_str().to_owned()],
                )),
            );
        };
        let problem = (record.state != ProjectState::Active).then(|| {
            about(
                Reason::ProjectNotActive,
                EntityType::Project,
                record.id.as_str(),
                "project_id",
            )
        });
        return (Some(existing_project(record)), problem);
    };
    let name = norm::project_display(&drop_sigil(&token.name, &['@']));
    let key = norm::project_key(&name);
    if key.is_empty() {
        return (None, Some(DomainError::field(Reason::EmptyName, "name")));
    }
    // Ties go to the lowest ID, the order the read set keeps.
    let active = read_set
        .projects
        .values()
        .filter(|p| p.state == ProjectState::Active);
    let found = active
        .clone()
        .find(|p| norm::project_key(p.name.as_str()) == key)
        .or_else(|| {
            active
                .clone()
                .find(|p| legacy_project_key(p.name.as_str()) == key)
        });
    if let Some(record) = found {
        return (Some(existing_project(record)), None);
    }
    // The server refuses a Smart Add name that belongs to an archived project,
    // so capture stops here instead of creating a second project of that name.
    if let Some(archived) = read_set
        .projects
        .values()
        .find(|p| p.state == ProjectState::Archived && norm::project_key(p.name.as_str()) == key)
    {
        let problem = about(
            Reason::ProjectNotActive,
            EntityType::Project,
            archived.id.as_str(),
            "project_id",
        );
        return (Some(existing_project(archived)), Some(problem));
    }
    let problem = (!norm::within_scalar_limit(&name, Name::MAX_SCALARS))
        .then(|| DomainError::field(Reason::TextLength, "name"));
    (Some(Classification::New { name }), problem)
}

fn existing_project(record: &Project) -> Classification<ProjectId> {
    Classification::Existing {
        id: record.id.clone(),
        name: record.name.as_str().to_owned(),
    }
}

/// The context tag first (when still active), then each `#tag` token in order,
/// de-duplicated by record and, for new tags, by normalized name. A deleted tag
/// with the same name does not block the proposal: a new tag is proposed.
fn resolve_tags(
    read_set: &ReadSet,
    draft: &Draft,
    tokens: &[Token],
) -> (Vec<Classification<TagId>>, Option<DomainError>) {
    let mut tags: Vec<Classification<TagId>> = Vec::new();
    let mut problem: Option<DomainError> = None;
    let mut seen_ids: Vec<&TagId> = Vec::new();
    let mut seen_new_keys: Vec<String> = Vec::new();

    if let Some(record) = draft
        .context_tag
        .as_ref()
        .and_then(|id| read_set.tags.get(id))
        .filter(|tag| tag.state == TagState::Active)
    {
        tags.push(existing_tag(record));
        seen_ids.push(&record.id);
    }

    let active = read_set
        .tags
        .values()
        .filter(|t| t.state == TagState::Active);
    for token in tokens.iter().filter(|t| t.kind == TokenKind::Tag) {
        let name = norm::project_display(&drop_sigil(&token.name, &['#', '@']));
        let key = norm::tag_key(&name);
        if key.is_empty() {
            problem = problem.or_else(|| Some(DomainError::field(Reason::EmptyName, "name")));
            continue;
        }
        let found = active
            .clone()
            .find(|t| norm::tag_key(t.name.as_str()) == key)
            .or_else(|| {
                active
                    .clone()
                    .find(|t| legacy_tag_key(t.name.as_str()) == key)
            });
        if let Some(record) = found {
            if !seen_ids.contains(&&record.id) {
                seen_ids.push(&record.id);
                tags.push(existing_tag(record));
            }
        } else if !seen_new_keys.contains(&key) {
            seen_new_keys.push(key);
            if !norm::within_scalar_limit(&name, Name::MAX_SCALARS) {
                problem = problem.or_else(|| Some(DomainError::field(Reason::TextLength, "name")));
            }
            tags.push(Classification::New { name });
        }
    }
    (tags, problem)
}

fn existing_tag(record: &Tag) -> Classification<TagId> {
    Classification::Existing {
        id: record.id.clone(),
        name: record.name.as_str().to_owned(),
    }
}

/// Resolves a draft against the read set, as capture would right now.
#[must_use]
pub fn resolve(read_set: &ReadSet, draft: &Draft) -> Resolution {
    let parsed = parse(&draft.text);
    let (project, project_problem) = resolve_project(read_set, draft, &parsed.tokens);
    let (tags, tags_problem) = resolve_tags(read_set, draft, &parsed.tokens);

    let mut waiting_for = None;
    let mut waiting_problem = None;
    if draft.list == OpenList::Waiting {
        // Trimmed exactly as the server trims it, so a note it would call blank
        // (only U+001C..U+001F, say) is blank here too.
        let trimmed = norm::strip(&draft.waiting_for);
        if trimmed.is_empty() {
            waiting_problem = Some(DomainError::field(
                Reason::WaitingForRequired,
                "waiting_for",
            ));
        } else if !norm::within_scalar_limit(trimmed, WaitingFor::MAX_SCALARS) {
            waiting_problem = Some(DomainError::field(Reason::TextLength, "waiting_for"));
        }
        waiting_for = (!trimmed.is_empty()).then(|| trimmed.to_owned());
    }

    let details = (!draft.details.chars().all(char::is_whitespace)).then(|| draft.details.clone());
    let details_problem = details
        .as_deref()
        .filter(|text| !norm::within_scalar_limit(text, Details::MAX_SCALARS))
        .map(|_| DomainError::field(Reason::TextLength, "details"));

    let length = norm::scalar_len(&parsed.clean_title);
    let title_problem = if length == 0 {
        Some(DomainError::field(Reason::EmptyTitle, "title"))
    } else if length > Title::MAX_SCALARS {
        Some(DomainError::field(Reason::TextLength, "title"))
    } else {
        None
    };

    Resolution {
        title: parsed.clean_title,
        tokens: parsed.tokens,
        project,
        tags,
        waiting_for,
        details,
        problem: title_problem
            .or(project_problem)
            .or(tags_problem)
            .or(waiting_problem)
            .or(details_problem),
    }
}

/// The `task.smart_add` payload capture would send: the clean title, the
/// existing records by ID and the new names with the IDs `mint_project` and
/// `mint_tag` supply (project first, then each new tag in order). The caller
/// owns the task ID and envelope; the first problem of [`resolve`] is returned
/// instead when capture is blocked.
pub fn propose(
    read_set: &ReadSet,
    draft: &Draft,
    mut mint_project: impl FnMut() -> ProjectId,
    mut mint_tag: impl FnMut() -> TagId,
) -> Result<SmartAdd, DomainError> {
    let resolution = resolve(read_set, draft);
    if let Some(problem) = resolution.problem {
        return Err(problem);
    }
    let project = match resolution.project {
        None => None,
        Some(Classification::Existing { id, .. }) => Some(ClassificationRef::Existing { id }),
        Some(Classification::New { name }) => Some(ClassificationRef::ByName {
            name: Name::new(name)?,
            proposed_id: mint_project(),
        }),
    };
    let tags = resolution
        .tags
        .into_iter()
        .map(|tag| match tag {
            Classification::Existing { id, .. } => Ok(ClassificationRef::Existing { id }),
            Classification::New { name } => Ok(ClassificationRef::ByName {
                name: Name::new(name)?,
                proposed_id: mint_tag(),
            }),
        })
        .collect::<Result<Vec<_>, DomainError>>()?;
    Ok(SmartAdd {
        title: Title::new(resolution.title)?,
        details: resolution.details.map(Details::new).transpose()?,
        state: draft.list,
        waiting_for: resolution.waiting_for.map(WaitingFor::new).transpose()?,
        due_date: draft.due_date.clone(),
        priority: draft.priority,
        project,
        tags,
        new_formulation_id: None,
    })
}

// ----------------------------------------------------------------------- decide

/// Decides `task.smart_add`: the task plus the classifications it names,
/// atomically. The command's `entity_id` is the new task; each by-name
/// reference carries the ID its record gets when it is created.
///
/// A command of another family is refused as [`Reason::InvalidPayload`]
/// (`field = "type"`); the dispatcher asks [`handles`] first.
pub fn decide(
    read_set: &ReadSet,
    command: &DomainCommand,
    inputs: &ExecutionInputs,
) -> Result<ChangeSet, DomainError> {
    let Command::TaskSmartAdd(payload) = &command.command else {
        return Err(DomainError::field(Reason::InvalidPayload, "type"));
    };
    let task_id = TaskId::parse(command.entity_id.as_str())?;
    if read_set.tasks.contains_key(&task_id) {
        return Err(about(
            Reason::IdAlreadyExists,
            EntityType::Task,
            task_id.as_str(),
            "entity_id",
        ));
    }
    // The server settles the Waiting note before it touches a classification.
    if payload.state == OpenList::Waiting {
        task_rules::required_waiting_for(payload.waiting_for.as_ref())?;
    }

    let mut plan = Plan::default();
    let project_id = match &payload.project {
        None => None,
        Some(reference) => Some(plan.project(read_set, reference)?),
    };
    for reference in &payload.tags {
        plan.tag(read_set, reference)?;
    }

    let create = TaskCreate {
        title: payload.title.clone(),
        details: payload.details.clone(),
        state: payload.state,
        project_id,
        tag_ids: plan.tag_ids,
        due_date: payload.due_date.clone(),
        priority: payload.priority,
        waiting_for: payload.waiting_for.clone(),
        source_capture_ids: Vec::new(),
        new_formulation_id: payload.new_formulation_id.clone(),
    };
    let task = task_rules::new_task(read_set, task_id, &create, inputs)?;

    let changes = plan
        .created_projects
        .into_iter()
        .map(Record::Project)
        .chain(plan.created_tags.into_iter().map(Record::Tag))
        .chain([Record::Task(task)])
        .map(DomainChange::Upsert)
        .collect();
    Ok(ChangeSet {
        outcome: ChangeOutcome::Applied,
        changes,
        result: ResultRefs {
            id_bindings: plan.bindings,
            ..ResultRefs::default()
        },
        effects: Vec::new(),
    })
}

/// The classifications one Smart Add resolved or creates.
#[derive(Default)]
struct Plan {
    created_projects: Vec<Project>,
    created_tags: Vec<Tag>,
    tag_ids: Vec<TagId>,
    bindings: Vec<Binding>,
}

impl Plan {
    /// `_resolve_smart_add_project`.
    fn project(
        &mut self,
        read_set: &ReadSet,
        reference: &ClassificationRef<ProjectId>,
    ) -> Result<ProjectId, DomainError> {
        let (name, proposed) = match reference {
            ClassificationRef::Existing { id } => {
                organize::check_references(read_set, Some(id), None, None)?;
                return Ok(id.clone());
            }
            ClassificationRef::ByName { name, proposed_id } => (name, proposed_id),
        };
        let display = norm::project_display(name.as_str());
        if display.is_empty() {
            return Err(DomainError::field(Reason::EmptyName, "project"));
        }
        let resolved =
            if let Some(active) = organize::active_project_named(read_set, &display, proposed) {
                active.id.clone()
            } else {
                let key = norm::project_key(&display);
                if let Some(inactive) = read_set.projects.values().find(|p| {
                    p.state != ProjectState::Active && norm::project_key(p.name.as_str()) == key
                }) {
                    return Err(about(
                        Reason::ProjectNotActive,
                        EntityType::Project,
                        inactive.id.as_str(),
                        "project",
                    ));
                }
                if read_set.projects.contains_key(proposed) {
                    return Err(about(
                        Reason::IdAlreadyExists,
                        EntityType::Project,
                        proposed.as_str(),
                        "project",
                    ));
                }
                self.created_projects.push(Project {
                    id: proposed.clone(),
                    name: Name::new(display)
                        .map_err(|_| DomainError::field(Reason::TextLength, "project"))?,
                    color: None,
                    state: ProjectState::Active,
                    revision: Counter::from(1),
                    desired_outcome: None,
                    archived_at: None,
                    archived_before_lossless: false,
                });
                proposed.clone()
            };
        self.bind(EntityType::Project, proposed.as_str(), resolved.as_str())?;
        Ok(resolved)
    }

    /// `_resolve_smart_add_tags` for one reference: a tag already in the list
    /// is not added twice.
    fn tag(
        &mut self,
        read_set: &ReadSet,
        reference: &ClassificationRef<TagId>,
    ) -> Result<(), DomainError> {
        let resolved = match reference {
            ClassificationRef::Existing { id } => {
                organize::check_references(read_set, None, Some(std::slice::from_ref(id)), None)?;
                id.clone()
            }
            ClassificationRef::ByName { name, proposed_id } => {
                let resolved = self.tag_by_name(read_set, name, proposed_id)?;
                self.bind(EntityType::Tag, proposed_id.as_str(), resolved.as_str())?;
                resolved
            }
        };
        if !self.tag_ids.contains(&resolved) {
            self.tag_ids.push(resolved);
        }
        Ok(())
    }

    fn tag_by_name(
        &mut self,
        read_set: &ReadSet,
        name: &Name,
        proposed: &TagId,
    ) -> Result<TagId, DomainError> {
        let display = norm::tag_display(name.as_str());
        if display.is_empty() {
            return Err(DomainError::field(Reason::EmptyName, "tags"));
        }
        if let Some(active) = organize::active_tag_named(read_set, &display, proposed) {
            return Ok(active.id.clone());
        }
        let key = norm::tag_key(&display);
        if let Some(inactive) = read_set
            .tags
            .values()
            .find(|t| t.state != TagState::Active && norm::tag_key(t.name.as_str()) == key)
        {
            return Err(about(
                Reason::TagNotActive,
                EntityType::Tag,
                inactive.id.as_str(),
                "tags",
            ));
        }
        // Two names that key alike in one request are one new tag.
        if let Some(created) = self
            .created_tags
            .iter()
            .find(|t| norm::tag_key(t.name.as_str()) == key)
        {
            return Ok(created.id.clone());
        }
        if read_set.tags.contains_key(proposed)
            || self.created_tags.iter().any(|t| &t.id == proposed)
        {
            return Err(about(
                Reason::IdAlreadyExists,
                EntityType::Tag,
                proposed.as_str(),
                "tags",
            ));
        }
        self.created_tags.push(Tag {
            id: proposed.clone(),
            name: Name::new(display).map_err(|_| DomainError::field(Reason::TextLength, "tags"))?,
            state: TagState::Active,
            revision: Counter::from(1),
        });
        Ok(proposed.clone())
    }

    /// Records `alias -> resolved` once per typed alias.
    fn bind(
        &mut self,
        entity_type: EntityType,
        alias: &str,
        resolved: &str,
    ) -> Result<(), DomainError> {
        let id = |value: &str| {
            crate::types::Id::parse(value)
                .map_err(|_| DomainError::field(Reason::InvalidValue, "id_bindings"))
        };
        let alias_id = id(alias)?;
        if !self
            .bindings
            .iter()
            .any(|b| b.entity_type == entity_type && b.alias_id == alias_id)
        {
            self.bindings.push(Binding {
                entity_type,
                alias_id,
                entity_id: id(resolved)?,
            });
        }
        Ok(())
    }
}

//! Local Review form overlays. Immutable import carriers are never edited, and
//! a cleared or expired overlay continues to shadow its original carrier.
use crate::{ExecuteError, QueryError, Store, StoreError, sha256_hex};
use bb_domain::calendar::UtcInstant;
use bb_domain::types::{
    DomainError, FormulationId, ProjectId, Reason, SessionId, StepCode, TaskId,
};
use bb_protocol::{catalog::EntityType, wire::Instant};
use rusqlite::{Connection, OptionalExtension, params};
use serde::{Deserialize, Serialize};

const OVERLAY: &str = "runtime_form_overlay";
const RETENTION_MICROS: i64 = 7 * 86_400 * 1_000_000;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ReviewFormDraft {
    pub text: String,
    pub saved_at: Instant,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReviewFormCount {
    pub live_count: u64,
    pub projection_generation: u64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReviewFormLoaded {
    pub source_key: String,
    pub draft: Option<ReviewFormDraft>,
    pub live_count: u64,
    pub projection_generation: u64,
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
enum Overlay {
    Saved { draft: ReviewFormDraft },
    Cleared,
}

fn invalid(field: &str) -> ExecuteError {
    ExecuteError::Refused(DomainError::field(Reason::InvalidValue, field))
}
fn parse_time(time: &Instant) -> Result<i64, ExecuteError> {
    UtcInstant::parse_rfc3339(time.as_str())
        .map(|instant| instant.unix_micros())
        .map_err(|_| invalid("now"))
}
fn decode<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T, ExecuteError> {
    serde_json::from_slice(bytes).map_err(|_| StoreError::Corrupt.into())
}
fn workspace(conn: &Connection) -> Result<String, ExecuteError> {
    Ok(conn.query_row("SELECT workspace_id FROM sync_meta", [], |row| row.get(0))?)
}
fn overlay_id(key: &str) -> String {
    format!("runtime:review-form:{}", sha256_hex(key.as_bytes()))
}
fn bare_uuid(id: &str) -> bool {
    id.len() == 36
        && id.bytes().enumerate().all(|(index, byte)| {
            if matches!(index, 8 | 13 | 18 | 23) {
                byte == b'-'
            } else {
                byte.is_ascii_hexdigit()
            }
        })
}
type TaskClocks = (Option<String>, Option<String>);
fn task_clocks(
    conn: &Connection,
    workspace: &str,
    task: &str,
) -> Result<Option<TaskClocks>, ExecuteError> {
    let key = serde_json::to_string(&vec![task]).map_err(|_| StoreError::Corrupt)?;
    Ok(conn.query_row("SELECT json_extract(CAST(body AS TEXT),'$.formulation.id'),json_extract(CAST(body AS TEXT),'$.parked.formulation_id') FROM visible_records WHERE workspace_id=?1 AND record_type='task' AND record_key=?2",params![workspace,key],|row|Ok((row.get(0)?,row.get(1)?))).optional()?)
}

#[derive(Clone)]
enum FormKey<'a> {
    Decision {
        kind: &'a str,
        task: &'a str,
        formulation: &'a str,
    },
    Project(&'a str),
    Step {
        session: &'a str,
        step: &'a str,
        item: &'a str,
    },
}
fn key_parts(key: &str) -> Result<FormKey<'_>, ExecuteError> {
    if key.len() > 512 || key.chars().any(char::is_control) {
        return Err(invalid("key"));
    }
    let parts: Vec<_> = key.splitn(4, ':').collect();
    match parts.as_slice() {
        ["form", kind, task, formulation]
            if matches!(
                *kind,
                "reformulate"
                    | "first_step"
                    | "waiting_for"
                    | "extension_reason"
                    | "follow_up"
                    | "return_to_next"
            ) && !task.is_empty()
                && !formulation.is_empty()
                && !formulation.contains(':') =>
        {
            Ok(FormKey::Decision {
                kind,
                task,
                formulation,
            })
        }
        ["project", id] if !id.is_empty() => Ok(FormKey::Project(id)),
        ["step", session, step, item]
            if !session.is_empty()
                && !item.is_empty()
                && serde_json::from_value::<StepCode>(serde_json::Value::String(
                    (*step).to_owned(),
                ))
                .is_ok() =>
        {
            Ok(FormKey::Step {
                session,
                step,
                item,
            })
        }
        _ => Err(invalid("key")),
    }
}
fn typed_identity(kind: EntityType, id: &str) -> bool {
    use bb_domain::types::{BulkId, CommentId, DecisionId, SubtaskId, TagId};
    match kind {
        EntityType::Task => TaskId::parse(id).is_ok(),
        EntityType::Project => ProjectId::parse(id).is_ok(),
        EntityType::ReviewSession => SessionId::parse(id).is_ok(),
        EntityType::Tag => TagId::parse(id).is_ok(),
        EntityType::Subtask => SubtaskId::parse(id).is_ok(),
        EntityType::Comment => CommentId::parse(id).is_ok(),
        EntityType::ReviewDecision => DecisionId::parse(id).is_ok(),
        EntityType::ReviewBulkRelease => BulkId::parse(id).is_ok(),
        _ => false,
    }
}
/// At most one source identity may stand for a canonical identity. Absence of
/// proof is represented by None; callers keep the canonical identity verbatim.
pub(crate) fn reverse_in(
    conn: &Connection,
    workspace: &str,
    kind: EntityType,
    canonical: &str,
) -> Result<Option<String>, ExecuteError> {
    if !typed_identity(kind, canonical) {
        return Err(invalid("canonical_id"));
    }
    let mut statement = conn.prepare("SELECT old_local_id FROM identity_aliases WHERE workspace_id=?1 AND entity_type=?2 AND server_id=?3 ORDER BY old_local_id LIMIT 2")?;
    let mut rows = statement.query(params![workspace, kind.as_str(), canonical])?;
    let first = rows
        .next()?
        .map(|row| row.get::<_, String>(0))
        .transpose()?;
    if rows.next()?.is_some() {
        return Err(invalid("identity_ambiguity"));
    }
    Ok(first)
}
fn forward_in(
    conn: &Connection,
    workspace: &str,
    kind: EntityType,
    source: &str,
) -> Result<String, ExecuteError> {
    Ok(conn.query_row("SELECT server_id FROM identity_aliases WHERE workspace_id=?1 AND entity_type=?2 AND old_local_id=?3", params![workspace,kind.as_str(),source], |row| row.get(0)).optional()?.unwrap_or_else(|| source.to_owned()))
}
pub fn reverse_workspace_identities(
    store: &mut Store,
    items: &[(EntityType, String)],
) -> Result<Vec<Option<String>>, QueryError> {
    if items.len() > 200 {
        return Err(QueryError::Refused(DomainError::field(
            Reason::TooManyItems,
            "items",
        )));
    }
    store
        .read(|tx| {
            Ok((|| {
                let workspace = workspace(tx)?;
                items
                    .iter()
                    .map(|(kind, id)| reverse_in(tx, &workspace, *kind, id))
                    .collect::<Result<_, ExecuteError>>()
            })())
        })?
        .map_err(QueryError::from)
}

fn source_candidate(conn: &Connection, workspace: &str, key: &str) -> Result<String, ExecuteError> {
    Ok(match key_parts(key)? {
        FormKey::Decision {
            kind,
            task,
            formulation,
        } => {
            if TaskId::parse(task).is_err()
                || (formulation != "-" && FormulationId::parse(formulation).is_err())
            {
                return Err(invalid("key"));
            }
            if formulation != "-"
                && !bare_uuid(formulation)
                && task_clocks(conn, workspace, task)?.is_some_and(|(clock, park)| {
                    let ids = [clock, park];
                    !ids.iter().flatten().any(|id| id == formulation)
                        && ids.iter().flatten().any(|id| bare_uuid(id))
                })
            {
                return Err(invalid("formulation_identity_unproven"));
            }
            let source = reverse_in(conn, workspace, EntityType::Task, task)?
                .unwrap_or_else(|| task.to_owned());
            format!("form:{kind}:{source}:{formulation}")
        }
        FormKey::Project(project) => format!(
            "project:{}",
            reverse_in(conn, workspace, EntityType::Project, project)?
                .unwrap_or_else(|| project.to_owned())
        ),
        FormKey::Step {
            session,
            step,
            item,
        } => format!(
            "step:{}:{step}:{item}",
            reverse_in(conn, workspace, EntityType::ReviewSession, session)?
                .unwrap_or_else(|| session.to_owned())
        ),
    })
}
fn present(conn: &Connection, workspace: &str, key: &str) -> Result<bool, ExecuteError> {
    // A persistent content-free tombstone is not a second authored draft.
    // Expired saved content remains ambiguous until upkeep clears it.
    Ok(effective_form(conn, workspace, key)?.is_some())
}
fn unproven_carrier(
    conn: &Connection,
    workspace: &str,
    key: &str,
    now: i64,
) -> Result<(), ExecuteError> {
    let requested = key_parts(key)?;
    let mut statement=conn.prepare("SELECT d.draft_id,d.record_key,d.fields FROM drafts d WHERE d.workspace_id=?1 AND d.editor_kind='review_form_draft' AND NOT EXISTS(SELECT 1 FROM drafts o WHERE o.workspace_id=d.workspace_id AND o.editor_kind='runtime_form_overlay' AND o.record_key=d.record_key)")?;
    let mut rows = statement.query([workspace])?;
    while let Some(row) = rows.next()? {
        let (id, source, bytes): (String, String, Vec<u8>) =
            (row.get(0)?, row.get(1)?, row.get(2)?);
        let relation = match (&requested, key_parts(&source)?) {
            (FormKey::Project(requested), FormKey::Project(source))
                if requested != &source && bare_uuid(source) =>
            {
                Some((EntityType::Project, source))
            }
            (
                FormKey::Step {
                    session: requested,
                    step,
                    item,
                },
                FormKey::Step {
                    session,
                    step: source_step,
                    item: source_item,
                },
            ) if requested != &session
                && *step == source_step
                && *item == source_item
                && bare_uuid(session) =>
            {
                Some((EntityType::ReviewSession, session))
            }
            _ => None,
        };
        if let Some((kind, source_id)) = relation {
            let form =
                row_form(&id, "review_form_draft", &source, &bytes)?.ok_or(StoreError::Corrupt)?;
            if i128::from(now) - i128::from(parse_time(&form.saved_at)?)
                >= i128::from(RETENTION_MICROS)
            {
                continue;
            }
            let alias:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM identity_aliases WHERE workspace_id=?1 AND entity_type=?2 AND old_local_id=?3)",params![workspace,kind.as_str(),source_id],|row|row.get(0))?;
            let record_key =
                serde_json::to_string(&vec![source_id]).map_err(|_| StoreError::Corrupt)?;
            let same:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM visible_records WHERE workspace_id=?1 AND record_type=?2 AND record_key=?3)",params![workspace,kind.as_str(),record_key],|row|row.get(0))?;
            if !alias && !same {
                return Err(invalid("form_identity_unproven"));
            }
        }
    }
    Ok(())
}
fn resolve_key(
    conn: &Connection,
    workspace: &str,
    key: &str,
    now: i64,
) -> Result<String, ExecuteError> {
    let source = source_candidate(conn, workspace, key)?;
    if source == key {
        unproven_carrier(conn, workspace, key, now)?;
    }
    if source != key && present(conn, workspace, key)? {
        if present(conn, workspace, &source)? {
            return Err(invalid("identity_ambiguity"));
        }
        return Ok(key.to_owned());
    }
    Ok(source)
}
fn checked_form(form: ReviewFormDraft) -> Result<ReviewFormDraft, ExecuteError> {
    if form.text.len() > 2 * 1024 * 1024 {
        return Err(invalid("text"));
    }
    parse_time(&form.saved_at).map_err(|_| invalid("saved_at"))?;
    Ok(form)
}
fn row_form(
    id: &str,
    kind: &str,
    key: &str,
    bytes: &[u8],
) -> Result<Option<ReviewFormDraft>, ExecuteError> {
    key_parts(key)?;
    let form = match kind {
        OVERLAY if id == overlay_id(key) => match decode::<Overlay>(bytes)? {
            Overlay::Saved { draft } => Some(draft),
            Overlay::Cleared => None,
        },
        "review_form_draft" if id == format!("legacy-form:{key}") => {
            Some(decode::<ReviewFormDraft>(bytes)?)
        }
        _ => return Err(StoreError::Corrupt.into()),
    };
    form.map(checked_form).transpose()
}
fn effective_form(
    conn: &Connection,
    workspace: &str,
    key: &str,
) -> Result<Option<ReviewFormDraft>, ExecuteError> {
    let row:Option<(String,String,Vec<u8>)>=conn.query_row("SELECT draft_id,editor_kind,fields FROM drafts WHERE workspace_id=?1 AND record_key=?2 AND editor_kind IN ('review_form_draft','runtime_form_overlay') ORDER BY editor_kind DESC LIMIT 1",params![workspace,key],|row|Ok((row.get(0)?,row.get(1)?,row.get(2)?))).optional()?;
    row.map(|(id, kind, bytes)| row_form(&id, &kind, key, &bytes))
        .transpose()
        .map(Option::flatten)
}
fn live(
    conn: &Connection,
    workspace: &str,
    key: &str,
    form: &ReviewFormDraft,
    now: i64,
) -> Result<bool, ExecuteError> {
    if i128::from(now) - i128::from(parse_time(&form.saved_at)?) >= i128::from(RETENTION_MICROS) {
        return Ok(false);
    }
    let FormKey::Decision {
        task, formulation, ..
    } = key_parts(key)?
    else {
        return Ok(true);
    };
    let canonical = forward_in(conn, workspace, EntityType::Task, task)?;
    let clocks = task_clocks(conn, workspace, &canonical)?;
    if clocks.is_none() && bare_uuid(task) && canonical == task {
        return Err(invalid("form_identity_unproven"));
    }
    Ok(clocks.is_some_and(|(clock, park)| {
        formulation == "-"
            || clock.as_deref() == Some(formulation)
            || park.as_deref() == Some(formulation)
    }))
}
fn count_in(conn: &Connection, workspace: &str, now: i64) -> Result<ReviewFormCount, ExecuteError> {
    let mut statement=conn.prepare("SELECT d.draft_id,d.editor_kind,d.record_key,d.fields FROM drafts d WHERE d.workspace_id=?1 AND (d.editor_kind='runtime_form_overlay' OR (d.editor_kind='review_form_draft' AND NOT EXISTS(SELECT 1 FROM drafts o WHERE o.workspace_id=d.workspace_id AND o.editor_kind='runtime_form_overlay' AND o.record_key=d.record_key)))")?;
    let mut rows = statement.query([workspace])?;
    let mut live_count = 0;
    while let Some(row) = rows.next()? {
        let (id, kind, key, bytes): (String, String, String, Vec<u8>) =
            (row.get(0)?, row.get(1)?, row.get(2)?, row.get(3)?);
        if let Some(form) = row_form(&id, &kind, &key, &bytes)?
            && live(conn, workspace, &key, &form, now)?
        {
            live_count += 1;
        }
    }
    let generation: i64 =
        conn.query_row("SELECT projection_generation FROM sync_meta", [], |row| {
            row.get(0)
        })?;
    Ok(ReviewFormCount {
        live_count,
        projection_generation: u64::try_from(generation).map_err(|_| StoreError::Corrupt)?,
    })
}
pub fn review_form_count(store: &mut Store, now: &Instant) -> Result<ReviewFormCount, QueryError> {
    store
        .read(|tx| Ok((|| count_in(tx, &workspace(tx)?, parse_time(now)?))()))?
        .map_err(QueryError::from)
}
pub fn load_review_form(
    store: &mut Store,
    key: &str,
    now: &Instant,
) -> Result<ReviewFormLoaded, QueryError> {
    store
        .read(|tx| {
            Ok((|| {
                let workspace = workspace(tx)?;
                let now = parse_time(now)?;
                let source_key = resolve_key(tx, &workspace, key, now)?;
                let draft = match effective_form(tx, &workspace, &source_key)? {
                    Some(form) if live(tx, &workspace, &source_key, &form, now)? => Some(form),
                    _ => None,
                };
                let count = count_in(tx, &workspace, now)?;
                Ok::<_, ExecuteError>(ReviewFormLoaded {
                    source_key,
                    draft,
                    live_count: count.live_count,
                    projection_generation: count.projection_generation,
                })
            })())
        })?
        .map_err(QueryError::from)
}
fn put(
    conn: &Connection,
    workspace: &str,
    key: &str,
    draft: Option<&ReviewFormDraft>,
    now: &Instant,
) -> Result<(), ExecuteError> {
    let id = overlay_id(key);
    let existing: Option<(String, Option<String>)> = conn
        .query_row(
            "SELECT editor_kind,record_key FROM drafts WHERE workspace_id=?1 AND draft_id=?2",
            params![workspace, id],
            |row| Ok((row.get(0)?, row.get(1)?)),
        )
        .optional()?;
    if existing.is_some_and(|(kind, held)| kind != OVERLAY || held.as_deref() != Some(key)) {
        return Err(StoreError::Corrupt.into());
    }
    let overlay = match draft {
        Some(draft) => Overlay::Saved {
            draft: draft.clone(),
        },
        None => Overlay::Cleared,
    };
    let bytes = serde_json::to_vec(&overlay).map_err(|_| StoreError::Corrupt)?;
    conn.execute("INSERT INTO drafts(workspace_id,draft_id,editor_kind,record_type,record_key,fields,updated_at) VALUES (?1,?2,'runtime_form_overlay','review_form',?3,?4,?5) ON CONFLICT(workspace_id,draft_id) DO UPDATE SET fields=excluded.fields,updated_at=excluded.updated_at",params![workspace,id,key,bytes,now.as_str()])?;
    Ok(())
}
pub fn save_review_form_with(
    store: &mut Store,
    key: &str,
    source_key: Option<&str>,
    draft: Option<&ReviewFormDraft>,
    now: &Instant,
    before_commit: impl FnOnce() -> Result<(), ExecuteError>,
) -> Result<ReviewFormCount, ExecuteError> {
    let now_micros = parse_time(now)?;
    let draft = draft.cloned().map(checked_form).transpose()?;
    store.try_write(|tx| {
        let workspace = workspace(tx)?;
        let resolved = resolve_key(tx, &workspace, key, now_micros)?;
        if source_key.is_some_and(|source| source != resolved) {
            return Err(invalid("source_key"));
        }
        put(tx, &workspace, &resolved, draft.as_ref(), now)?;
        tx.execute(
            "UPDATE sync_meta SET projection_generation=projection_generation+1",
            [],
        )?;
        let result = count_in(tx, &workspace, now_micros)?;
        before_commit()?;
        Ok(result)
    })
}
pub fn clear_review_forms_for_task_with(
    store: &mut Store,
    canonical_task_id: &str,
    now: &Instant,
    before_commit: impl FnOnce() -> Result<(), ExecuteError>,
) -> Result<ReviewFormCount, ExecuteError> {
    if TaskId::parse(canonical_task_id).is_err() {
        return Err(invalid("task_id"));
    }
    let now_micros = parse_time(now)?;
    store.try_write(|tx| {
        let workspace=workspace(tx)?;
        reverse_in(tx,&workspace,EntityType::Task,canonical_task_id)?;
        // The key list has no form content; bodies are streamed only for the
        // effective count. Clear includes expired forms and legacy fallbacks.
        let mut statement=tx.prepare("SELECT DISTINCT record_key FROM drafts WHERE workspace_id=?1 AND editor_kind IN ('review_form_draft','runtime_form_overlay')")?;
        let rows=statement.query_map([&workspace],|row|row.get::<_,String>(0))?;
        let mut keys=Vec::new();
        for row in rows {
            let key=row?;
            if let FormKey::Decision {task,..}=key_parts(&key)? && forward_in(tx,&workspace,EntityType::Task,task)?==canonical_task_id {keys.push(key);}
        }
        drop(statement);
        for key in &keys {put(tx,&workspace,key,None,now)?;}
        if !keys.is_empty() {tx.execute("UPDATE sync_meta SET projection_generation=projection_generation+1",[])?;}
        let result=count_in(tx,&workspace,now_micros)?;
        before_commit()?;
        Ok(result)
    })
}

/// Existing upkeep removes stale mutable content without revealing a legacy
/// fallback. Identity uncertainty and malformed relevant rows abort pruning.
pub fn prune_review_forms_with(
    store: &mut Store,
    now: &Instant,
    before_commit: impl FnOnce() -> Result<(), ExecuteError>,
) -> Result<ReviewFormCount, ExecuteError> {
    let now_micros = parse_time(now)?;
    store.try_write(|tx| {
        let workspace=workspace(tx)?;
        let mut statement=tx.prepare("SELECT draft_id,record_key,fields FROM drafts WHERE workspace_id=?1 AND editor_kind='runtime_form_overlay'")?;
        let mut rows=statement.query([&workspace])?;
        let mut stale=Vec::new();
        while let Some(row)=rows.next()? {
            let (id,key,bytes):(String,String,Vec<u8>)=(row.get(0)?,row.get(1)?,row.get(2)?);
            if let Some(form)=row_form(&id,OVERLAY,&key,&bytes)? && !live(tx,&workspace,&key,&form,now_micros)? {stale.push(key);}
        }
        drop(rows);
        drop(statement);
        for key in &stale {put(tx,&workspace,key,None,now)?;}
        if !stale.is_empty() {tx.execute("UPDATE sync_meta SET projection_generation=projection_generation+1",[])?;}
        let result=count_in(tx,&workspace,now_micros)?;
        before_commit()?;
        Ok(result)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{OpenOptions, workspace_watch};
    use serde_json::json;
    use std::{fs, time::Duration};
    const NOW: &str = "2026-10-10T09:00:00.123456Z";
    fn now() -> Instant {
        Instant::parse(NOW).unwrap()
    }
    fn open(name: &str) -> (Store, OpenOptions) {
        let path = std::env::temp_dir()
            .join(format!("bb-review-forms-{name}-{}", std::process::id()))
            .join("store.sqlite3");
        let _ = fs::remove_dir_all(path.parent().unwrap());
        let options = OpenOptions {
            path,
            workspace_id: "local".into(),
            busy_timeout: Duration::from_secs(2),
        };
        (Store::open(&options).unwrap(), options)
    }
    fn draft(text: &str, time: &str) -> ReviewFormDraft {
        ReviewFormDraft {
            text: text.into(),
            saved_at: Instant::parse(time).unwrap(),
        }
    }
    fn legacy(store: &mut Store, key: &str, text: &str, time: &str) {
        store.write(|tx| {
            tx.execute("INSERT INTO drafts(workspace_id,draft_id,editor_kind,record_key,fields,updated_at) VALUES ('local',?1,'review_form_draft',?2,?3,?4)",params![format!("legacy-form:{key}"),key,serde_json::to_vec(&draft(text,time)).unwrap(),time])?;
            Ok(())
        }).unwrap();
    }
    fn task(store: &mut Store, id: &str, form: Option<&str>, park: Option<&str>) {
        store.write(|tx| {
            tx.execute("INSERT INTO visible_records(workspace_id,record_type,record_key,body) VALUES ('local','task',?1,?2)",params![serde_json::to_string(&vec![id]).unwrap(),serde_json::to_vec(&json!({"formulation":form.map(|id|json!({"id":id})),"parked":park.map(|id|json!({"formulation_id":id}))})).unwrap()])?;
            Ok(())
        }).unwrap();
    }
    fn alias(store: &mut Store, kind: EntityType, source: &str, canonical: &str) {
        store.write(|tx| {
            tx.execute("INSERT INTO identity_aliases(workspace_id,entity_type,old_local_id,server_id,provenance) VALUES ('local',?1,?2,?3,'legacy-import:server-id')",params![kind.as_str(),source,canonical])?;
            Ok(())
        }).unwrap();
    }
    #[test]
    fn review_forms_026_fr_013_fallback_edit_clear_reopen_and_expired_shadow() {
        let (mut store, options) = open("shadow");
        let key = "project:project_local";
        legacy(&mut store, key, "Original private text", NOW);
        let loaded = load_review_form(&mut store, key, &now()).unwrap();
        assert_eq!(loaded.source_key, key);
        assert_eq!(loaded.draft.unwrap().text, "Original private text");
        assert_eq!(loaded.live_count, 1);
        let save = save_review_form_with(
            &mut store,
            key,
            Some(key),
            Some(&draft("New text", NOW)),
            &now(),
            || Ok(()),
        )
        .unwrap();
        assert_eq!(save.live_count, 1);
        save_review_form_with(&mut store, key, Some(key), None, &now(), || Ok(())).unwrap();
        drop(store);
        let mut store = Store::open(&options).unwrap();
        assert!(
            load_review_form(&mut store, key, &now())
                .unwrap()
                .draft
                .is_none()
        );
        save_review_form_with(
            &mut store,
            key,
            None,
            Some(&draft("Expired overlay", "2026-10-03T09:00:00.123456Z")),
            &now(),
            || Ok(()),
        )
        .unwrap();
        assert_eq!(review_form_count(&mut store, &now()).unwrap().live_count, 0);
        assert!(
            load_review_form(&mut store, key, &now())
                .unwrap()
                .draft
                .is_none()
        );
        let original: Vec<u8> = store
            .read(|tx| {
                tx.query_row(
                    "SELECT fields FROM drafts WHERE editor_kind='review_form_draft'",
                    [],
                    |row| row.get(0),
                )
            })
            .unwrap();
        assert_eq!(
            decode::<ReviewFormDraft>(&original).unwrap().text,
            "Original private text"
        );
    }
    #[test]
    fn review_forms_026_fr_052_exact_boundary_task_and_formulation_liveness() {
        let (mut store, _) = open("liveness");
        task(
            &mut store,
            "task-current",
            Some("form_0123456789ab"),
            Some("form_0123456789ac"),
        );
        for (key, time, expected) in [
            (
                "project:deleted-project",
                "2026-10-03T09:00:00.123456Z",
                false,
            ),
            ("project:other", "2026-10-03T09:00:00.123457Z", true),
            (
                "step:review_0123456789ab:rest_of_next:opaque:item",
                NOW,
                true,
            ),
            ("form:reformulate:task-missing:-", NOW, false),
            ("form:reformulate:task-current:-", NOW, true),
            ("form:first_step:task-current:form_0123456789ab", NOW, true),
            ("form:follow_up:task-current:form_0123456789ac", NOW, true),
            (
                "form:waiting_for:task-current:form_0123456789ad",
                NOW,
                false,
            ),
        ] {
            legacy(&mut store, key, key, time);
            assert_eq!(
                load_review_form(&mut store, key, &now())
                    .unwrap()
                    .draft
                    .is_some(),
                expected,
                "{key}"
            );
        }
        assert_eq!(review_form_count(&mut store, &now()).unwrap().live_count, 5);
    }
    #[test]
    fn review_forms_026_fr_013_typed_alias_ambiguity_and_opaque_step_items() {
        let (mut store, _) = open("aliases");
        task(&mut store, "task-server", None, None);
        alias(&mut store, EntityType::Task, "source-task", "task-server");
        legacy(
            &mut store,
            "form:reformulate:source-task:-",
            "Exact legacy text",
            NOW,
        );
        let loaded =
            load_review_form(&mut store, "form:reformulate:task-server:-", &now()).unwrap();
        assert_eq!(loaded.source_key, "form:reformulate:source-task:-");
        assert_eq!(loaded.draft.unwrap().text, "Exact legacy text");
        assert!(
            save_review_form_with(
                &mut store,
                "form:reformulate:task-server:-",
                Some("form:reformulate:invented:-"),
                None,
                &now(),
                || Ok(())
            )
            .is_err()
        );
        legacy(
            &mut store,
            "form:reformulate:task-server:-",
            "Independent text",
            NOW,
        );
        assert!(load_review_form(&mut store, "form:reformulate:task-server:-", &now()).is_err());
        assert!(
            save_review_form_with(
                &mut store,
                "form:reformulate:task-server:-",
                None,
                None,
                &now(),
                || Ok(())
            )
            .is_err()
        );
        alias(
            &mut store,
            EntityType::ReviewSession,
            "00000000-0000-4000-8000-000000000001",
            "review_0123456789ab",
        );
        legacy(
            &mut store,
            "step:00000000-0000-4000-8000-000000000001:rest_of_next:task-server:opaque",
            "Opaque step",
            NOW,
        );
        assert_eq!(
            load_review_form(
                &mut store,
                "step:review_0123456789ab:rest_of_next:task-server:opaque",
                &now()
            )
            .unwrap()
            .source_key,
            "step:00000000-0000-4000-8000-000000000001:rest_of_next:task-server:opaque"
        );
        alias(&mut store, EntityType::Task, "second-source", "task-server");
        assert!(
            reverse_workspace_identities(&mut store, &[(EntityType::Task, "task-server".into())])
                .is_err()
        );
        assert!(
            reverse_workspace_identities(
                &mut store,
                &vec![(EntityType::Task, "task-server".into()); 201]
            )
            .is_err()
        );
    }
    #[test]
    fn review_forms_026_fr_001_multi_form_clear_and_cancel_are_atomic() {
        let (mut store, _) = open("clear");
        task(&mut store, "task-server", None, None);
        alias(&mut store, EntityType::Task, "source-task", "task-server");
        for key in [
            "form:reformulate:source-task:-",
            "form:reformulate:task-server:-",
            "form:waiting_for:source-task:form_0123456789ab",
        ] {
            legacy(&mut store, key, "Preserve until commit", NOW);
        }
        legacy(&mut store, "project:project-other", "Other form", NOW);
        let before = review_form_count(&mut store, &now()).unwrap();
        assert!(load_review_form(&mut store, "form:reformulate:task-server:-", &now()).is_err());
        assert_eq!(
            clear_review_forms_for_task_with(&mut store, "task-server", &now(), || Err(
                ExecuteError::Cancelled
            )),
            Err(ExecuteError::Cancelled)
        );
        assert_eq!(review_form_count(&mut store, &now()).unwrap(), before);
        let after =
            clear_review_forms_for_task_with(&mut store, "task-server", &now(), || Ok(())).unwrap();
        assert_eq!(after.live_count, 1);
        assert_eq!(
            after.projection_generation,
            before.projection_generation + 1
        );
        assert!(
            load_review_form(&mut store, "form:reformulate:task-server:-", &now())
                .unwrap()
                .draft
                .is_none()
        );
        assert_eq!(
            store
                .read(|tx| tx.query_row(
                    "SELECT COUNT(*) FROM drafts WHERE editor_kind='runtime_form_overlay'",
                    [],
                    |row| row.get::<_, i64>(0)
                ))
                .unwrap(),
            3
        );
        assert_eq!(
            save_review_form_with(
                &mut store,
                "form:reformulate:task-server:-",
                None,
                Some(&draft("Fresh editor text after explicit task clear", NOW)),
                &now(),
                || Ok(())
            )
            .unwrap()
            .live_count,
            2
        );
        assert_eq!(
            load_review_form(&mut store, "form:reformulate:task-server:-", &now())
                .unwrap()
                .draft
                .unwrap()
                .text,
            "Fresh editor text after explicit task clear"
        );
    }
    #[test]
    fn review_forms_026_fr_001_draft_only_commit_invalidates_second_connection_and_blocks_generic_crud()
     {
        let (mut first, options) = open("watch");
        let mut second = Store::open(&options).unwrap();
        let before = workspace_watch(&mut second).unwrap();
        let result = save_review_form_with(
            &mut first,
            "project:project-1",
            None,
            Some(&draft("Second connection sees this", NOW)),
            &now(),
            || Ok(()),
        )
        .unwrap();
        let after = workspace_watch(&mut second).unwrap();
        assert_eq!(after.projection_generation, result.projection_generation);
        assert_ne!(before.projection_generation, after.projection_generation);
        assert_eq!(
            review_form_count(&mut second, &now()).unwrap().live_count,
            1
        );
        let id = overlay_id("project:project-1");
        assert!(crate::delete_workspace_draft_with(&mut first, &id, || Ok(())).is_err());
        let generic = crate::WorkspaceDraft {
            draft_id: "runtime:other".into(),
            editor_kind: OVERLAY.into(),
            record_type: None,
            record_key: Some("project:project-1".into()),
            base_revision: None,
            fields: json!({"state":"cleared"}),
            updated_at: NOW.into(),
        };
        assert!(crate::save_workspace_draft_with(&mut first, &generic, || Ok(())).is_err());
        assert!(crate::load_workspace_draft(&mut first, &id).is_err());
        assert_eq!(
            save_review_form_with(&mut first, "project:project-1", None, None, &now(), || Err(
                ExecuteError::Cancelled
            )),
            Err(ExecuteError::Cancelled)
        );
        assert_eq!(review_form_count(&mut second, &now()).unwrap(), result);
    }
    #[test]
    fn review_forms_026_fr_013_malformed_relevant_data_returns_safe_error() {
        let (mut store, _) = open("malformed");
        legacy(&mut store, "project:project-1", "Text", NOW);
        store
            .write(|tx| {
                tx.execute("UPDATE drafts SET fields=x'7b7d'", [])?;
                Ok(())
            })
            .unwrap();
        assert!(load_review_form(&mut store, "project:project-1", &now()).is_err());
        assert!(review_form_count(&mut store, &now()).is_err());
    }

    #[test]
    fn review_forms_026_fr_013_unproven_old_import_refuses_until_expiry_without_rewriting() {
        let (mut store, _) = open("unproven");
        let source = "00000000-0000-4000-8000-000000000001";
        let key = format!("form:reformulate:{source}:-");
        legacy(&mut store, &key, "Uncertain lineage retained", NOW);
        task(&mut store, &format!("task_{source}"), None, None);
        assert!(
            load_review_form(
                &mut store,
                &format!("form:reformulate:task_{source}:-"),
                &now()
            )
            .is_err()
        );
        assert!(review_form_count(&mut store, &now()).is_err());
        let expired = Instant::parse("2026-10-17T09:00:00.123456Z").unwrap();
        assert_eq!(
            review_form_count(&mut store, &expired).unwrap().live_count,
            0
        );
        assert_eq!(
            store
                .read(
                    |tx| tx.query_row("SELECT COUNT(*) FROM identity_aliases", [], |row| row
                        .get::<_, i64>(0))
                )
                .unwrap(),
            0
        );
        let retained: Vec<u8> = store
            .read(|tx| {
                tx.query_row(
                    "SELECT fields FROM drafts WHERE editor_kind='review_form_draft'",
                    [],
                    |row| row.get(0),
                )
            })
            .unwrap();
        assert_eq!(
            decode::<ReviewFormDraft>(&retained).unwrap().text,
            "Uncertain lineage retained"
        );
    }
    #[test]
    fn review_forms_026_fr_013_formulation_prefix_mismatch_is_not_an_identity_alias() {
        let (mut store, _) = open("form-proof");
        let source = "00000000-0000-4000-8000-000000000001";
        task(&mut store, "task-owned", Some(source), None);
        legacy(
            &mut store,
            &format!("form:reformulate:task-owned:{source}"),
            "Keep exact formulation",
            NOW,
        );
        assert!(
            load_review_form(
                &mut store,
                &format!("form:reformulate:task-owned:form_{source}"),
                &now()
            )
            .is_err()
        );
        assert_eq!(review_form_count(&mut store, &now()).unwrap().live_count, 1);
        assert_eq!(
            store
                .read(
                    |tx| tx.query_row("SELECT COUNT(*) FROM identity_aliases", [], |row| row
                        .get::<_, i64>(0))
                )
                .unwrap(),
            0
        );
    }

    #[test]
    fn review_forms_026_fr_052_prune_removes_mutable_stale_content_atomically_without_fallback_or_generation_churn()
     {
        let (mut store, options) = open("prune");
        let mut observer = Store::open(&options).unwrap();
        task(&mut store, "task-orphan", None, None);
        task(&mut store, "task-changed", Some("form_0123456789ab"), None);
        legacy(
            &mut store,
            "project:project-expired",
            "Immutable live source",
            NOW,
        );
        for (key, saved_at) in [
            ("project:project-expired", "2026-10-03T09:00:00.123456Z"),
            ("project:project-live", "2026-10-03T09:00:00.123457Z"),
            ("form:reformulate:task-orphan:-", NOW),
            ("form:reformulate:task-changed:form_0123456789ac", NOW),
        ] {
            save_review_form_with(
                &mut store,
                key,
                None,
                Some(&draft("Mutable private text", saved_at)),
                &now(),
                || Ok(()),
            )
            .unwrap();
        }
        store
            .write(|tx| {
                tx.execute(
                    "DELETE FROM visible_records WHERE record_key='[\"task-orphan\"]'",
                    [],
                )?;
                Ok(())
            })
            .unwrap();
        let before = workspace_watch(&mut observer).unwrap();
        let fields_before:Vec<Vec<u8>>=store.read(|tx|tx.prepare("SELECT fields FROM drafts WHERE editor_kind='runtime_form_overlay' ORDER BY draft_id")?.query_map([],|row|row.get(0))?.collect()).unwrap();
        assert_eq!(
            prune_review_forms_with(&mut store, &now(), || Err(ExecuteError::Cancelled)),
            Err(ExecuteError::Cancelled)
        );
        assert_eq!(workspace_watch(&mut observer).unwrap(), before);
        let fields_after_cancel:Vec<Vec<u8>>=store.read(|tx|tx.prepare("SELECT fields FROM drafts WHERE editor_kind='runtime_form_overlay' ORDER BY draft_id")?.query_map([],|row|row.get(0))?.collect()).unwrap();
        assert_eq!(fields_after_cancel, fields_before);
        let result = prune_review_forms_with(&mut store, &now(), || Ok(())).unwrap();
        assert_eq!(result.live_count, 1);
        assert_eq!(
            result.projection_generation,
            before.projection_generation + 1
        );
        assert_eq!(
            workspace_watch(&mut observer)
                .unwrap()
                .projection_generation,
            result.projection_generation
        );
        assert!(
            load_review_form(&mut observer, "project:project-expired", &now())
                .unwrap()
                .draft
                .is_none()
        );
        assert_eq!(store.read(|tx|tx.query_row("SELECT COUNT(*) FROM drafts WHERE editor_kind='runtime_form_overlay' AND CAST(fields AS TEXT)='{\"state\":\"cleared\"}'",[],|row|row.get::<_,i64>(0))).unwrap(),3);
        assert_eq!(
            prune_review_forms_with(&mut store, &now(), || Ok(())).unwrap(),
            result
        );
        let original: Vec<u8> = store
            .read(|tx| {
                tx.query_row(
                    "SELECT fields FROM drafts WHERE editor_kind='review_form_draft'",
                    [],
                    |row| row.get(0),
                )
            })
            .unwrap();
        assert_eq!(
            decode::<ReviewFormDraft>(&original).unwrap().text,
            "Immutable live source"
        );
    }
    #[test]
    fn review_forms_026_fr_013_old_step_and_project_refuse_discovery_without_alias_and_keep_age_only_counts()
     {
        let (mut store, _) = open("old-step-project");
        let source = "00000000-0000-4000-8000-000000000001";
        legacy(
            &mut store,
            &format!("project:{source}"),
            "Unknown source project",
            NOW,
        );
        legacy(
            &mut store,
            &format!("step:{source}:rest_of_next:opaque:item"),
            "Unknown source session",
            NOW,
        );
        assert_eq!(review_form_count(&mut store, &now()).unwrap().live_count, 2);
        assert!(
            load_review_form(&mut store, &format!("project:project_{source}"), &now()).is_err()
        );
        assert!(
            load_review_form(
                &mut store,
                &format!("step:review_{source}:rest_of_next:opaque:item"),
                &now()
            )
            .is_err()
        );
        assert!(
            load_review_form(
                &mut store,
                &format!("step:review_{source}:rest_of_next:different:item"),
                &now()
            )
            .unwrap()
            .draft
            .is_none()
        );
        let expired = Instant::parse("2026-10-17T09:00:00.123456Z").unwrap();
        assert!(
            load_review_form(&mut store, &format!("project:project_{source}"), &expired)
                .unwrap()
                .draft
                .is_none()
        );
        assert_eq!(
            review_form_count(&mut store, &expired).unwrap().live_count,
            0
        );
    }

    #[test]
    fn review_forms_026_fr_013_changed_verbatim_formulation_prunes_without_inventing_alias() {
        let (mut store, _) = open("bare-clock-changed");
        let before = "00000000-0000-4000-8000-000000000001";
        let after = "00000000-0000-4000-8000-000000000002";
        let key = format!("form:reformulate:task-owned:{before}");
        task(&mut store, "task-owned", Some(before), None);
        legacy(&mut store, &key, "Immutable original private text", NOW);
        assert_eq!(
            save_review_form_with(
                &mut store,
                &key,
                None,
                Some(&draft("Mutable stale text", NOW)),
                &now(),
                || Ok(())
            )
            .unwrap()
            .live_count,
            1
        );
        store
            .write(|tx| {
                tx.execute(
                    "UPDATE visible_records SET body=?1 WHERE record_type='task'",
                    [
                        serde_json::to_vec(&json!({"formulation":{"id":after},"parked":null}))
                            .unwrap(),
                    ],
                )?;
                Ok(())
            })
            .unwrap();
        assert_eq!(review_form_count(&mut store, &now()).unwrap().live_count, 0);
        assert!(
            load_review_form(&mut store, &key, &now())
                .unwrap()
                .draft
                .is_none()
        );
        let result = prune_review_forms_with(&mut store, &now(), || Ok(())).unwrap();
        assert_eq!(result.live_count, 0);
        let overlay: Vec<u8> = store
            .read(|tx| {
                tx.query_row(
                    "SELECT fields FROM drafts WHERE editor_kind='runtime_form_overlay'",
                    [],
                    |row| row.get(0),
                )
            })
            .unwrap();
        assert_eq!(
            serde_json::from_slice::<serde_json::Value>(&overlay).unwrap(),
            json!({"state":"cleared"})
        );
        assert_eq!(
            store
                .read(
                    |tx| tx.query_row("SELECT COUNT(*) FROM identity_aliases", [], |row| row
                        .get::<_, i64>(0))
                )
                .unwrap(),
            0
        );
    }
}

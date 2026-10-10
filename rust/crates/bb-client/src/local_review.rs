//! Explicit accountless authority: private Review evidence and atomic local base
//! settlement. Neither missing credentials nor an envelope field grants it.
use crate::{ExecuteError, Store, StoreError};
use bb_domain::{calendar::UtcInstant, types::*};
use bb_protocol::{
    catalog::EntityType,
    wire::{CommandId, Counter, Instant, RecordKey},
};
use rusqlite::{Connection, OptionalExtension, Transaction, params};
use serde::{Deserialize, Serialize};
use serde_json::json;

const KIND: &str = "runtime_local_review_private";
const PREFIX: &str = "runtime:local-review-private:";

fn invalid(field: &str) -> ExecuteError {
    DomainError::field(Reason::InvalidValue, field).into()
}

/// True only for the explicit durable, completely unbound local mode.
pub(crate) fn account_less(conn: &Connection) -> Result<bool, StoreError> {
    let (mode, account, scope, device): (String, Option<String>, Option<String>, Option<String>) =
        conn.query_row(
            "SELECT account_link_state,account_id,scope_id,device_id FROM sync_meta",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
        )?;
    if mode != "account_less" {
        return Ok(false);
    }
    let remote:bool=conn.query_row("SELECT server_generation IS NOT NULL OR cursor IS NOT NULL OR base_watermark IS NOT NULL OR device_epoch_state='active' OR EXISTS(SELECT 1 FROM command_receipts) OR EXISTS(SELECT 1 FROM outbox WHERE ever_sent=1 OR state IN ('sending','unknown','accepted_awaiting_feed')) FROM sync_meta",[],|r|r.get(0))?;
    if remote || account.is_some() || scope.is_some() || device.is_some() {
        return Err(StoreError::Corrupt);
    }
    Ok(true)
}

/// Trusted lifecycle operation. A populated imported base needs separately
/// verified immutable source proof; an unchosen workspace is not local authority.
pub fn establish_account_less_with(
    store: &mut Store,
    before_commit: impl FnOnce() -> Result<(), ExecuteError>,
) -> Result<(), ExecuteError> {
    store.try_write(|tx| {
        if account_less(tx)? { return before_commit(); }
        let denied: bool = tx.query_row(
            "SELECT account_link_state<>'unchosen' OR account_id IS NOT NULL OR scope_id IS NOT NULL OR device_id IS NOT NULL
             OR server_generation IS NOT NULL OR cursor IS NOT NULL OR base_watermark IS NOT NULL
             OR device_epoch_state<>'none' OR next_local_seq<>1 OR link_checkpoint IS NOT NULL
             OR EXISTS(SELECT 1 FROM command_receipts) OR EXISTS(SELECT 1 FROM outbox WHERE ever_sent=1 OR state IN ('sending','unknown','accepted_awaiting_feed')
                OR json_extract(CAST(envelope AS TEXT),'$.scope_id') IS NOT NULL OR json_extract(CAST(envelope AS TEXT),'$.device_id') IS NOT NULL)
             OR EXISTS(SELECT 1 FROM confirmed_records) OR EXISTS(SELECT 1 FROM outbox)
             OR EXISTS(SELECT 1 FROM staging_bases WHERE state='activated')
             FROM sync_meta", [], |r|r.get(0))?;
        if denied { return Err(invalid("account_less_setup")); }
        tx.execute("UPDATE sync_meta SET account_link_state='account_less'", [])?;
        before_commit()
    })
}

/// Trusted imported-base setup using the importer-owned exact source proof.
/// The proof is rechecked under the write lock before new conversions can run.
pub fn establish_account_less_from_import_with(
    store: &mut Store,
    proof: &crate::import::AccountlessImportProof,
    before_commit: impl FnOnce() -> Result<(), ExecuteError>,
) -> Result<(), ExecuteError> {
    store.try_write(|tx| {
        let workspace:String=tx.query_row("SELECT workspace_id FROM sync_meta",[],|r|r.get(0))?;
        if workspace!=proof.workspace {return Err(invalid("account_less_import"));}
        let row:Option<(Vec<u8>,Vec<u8>)>=tx.query_row("SELECT manifest,manifest_digest FROM staging_bases WHERE workspace_id=?1 AND activation_id=?2 AND state='activated'",params![workspace,proof.activation],|r|Ok((r.get(0)?,r.get(1)?))).optional()?;
        let(manifest,digest)=row.ok_or_else(||invalid("account_less_import"))?;
        if crate::sha256_hex(&manifest)!=proof.marker_sha256 || crate::execute::sha256(&manifest).as_slice()!=digest.as_slice() {return Err(invalid("account_less_import"));}
        let marker:crate::ImportMarker=serde_json::from_slice(&manifest).map_err(|_|StoreError::Corrupt)?;
        if marker.source_sha256!=proof.source_sha256 || marker.source_bytes!=proof.source_bytes || marker.source_version!=proof.source_version || marker.source_generation!=proof.source_generation {return Err(invalid("account_less_import"));}
        if account_less(tx)? {return before_commit();}
        let denied:bool=tx.query_row("SELECT account_link_state<>'unchosen' OR account_id IS NOT NULL OR scope_id IS NOT NULL OR device_id IS NOT NULL OR server_generation IS NOT NULL OR cursor IS NOT NULL OR base_watermark IS NOT NULL OR device_epoch_state<>'none' OR next_local_seq<>1 OR link_checkpoint IS NOT NULL OR EXISTS(SELECT 1 FROM outbox) OR EXISTS(SELECT 1 FROM command_receipts) FROM sync_meta",[],|r|r.get(0))?;
        if denied || crate::legacy_outbox::has_remote_history_in(tx).map_err(|_|invalid("account_less_import"))? {return Err(invalid("account_less_import"));}
        tx.execute("UPDATE sync_meta SET account_link_state='account_less'",[])?;
        before_commit()
    })
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(
    tag = "kind",
    content = "fields",
    rename_all = "snake_case",
    deny_unknown_fields
)]
enum PrivateFields {
    TaskPark(ParkPrivate),
    Settings(SettingsPrivate),
    Session(SessionPrivate),
    Decision(DecisionUndo),
    ParkAck(ParkAckPrivate),
    Bulk(Vec<Option<ReleasedPrivate>>),
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Provenance {
    LocalCommand { command_id: CommandId },
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Overlay {
    version: u32,
    workspace: String,
    entity_type: EntityType,
    record_key: RecordKey,
    provenance: Provenance,
    public_sha256: String,
    source_at: Instant,
    deadline: Option<Instant>,
    private: PrivateFields,
}

fn instant(at: &Instant) -> Result<UtcInstant, StoreError> {
    UtcInstant::parse_rfc3339(at.as_str()).map_err(|_| StoreError::Corrupt)
}
fn deadline(at: &Instant) -> Result<Instant, StoreError> {
    Instant::parse(instant(at)?.plus_seconds(7 * 86_400).to_rfc3339())
        .map_err(|_| StoreError::Corrupt)
}
fn fingerprint(record: &Record) -> Result<String, StoreError> {
    Ok(crate::sha256_hex(
        &serde_json::to_vec(&record.public()).map_err(|_| StoreError::Corrupt)?,
    ))
}
fn draft_id(kind: EntityType, key: &RecordKey) -> String {
    format!(
        "{PREFIX}{}",
        crate::sha256_hex(json!([kind, key]).to_string().as_bytes())
    )
}
fn extract(
    record: &Record,
    now: &Instant,
) -> Result<Option<(PrivateFields, Instant, Option<Instant>)>, StoreError> {
    let value = match record {
        Record::Task(task) => task.parked.as_ref().and_then(|park| {
            park.private
                .clone()
                .map(|p| (PrivateFields::TaskPark(p), park.at.clone(), None))
        }),
        Record::ReviewSettings(row) => row
            .private
            .clone()
            .map(|p| (PrivateFields::Settings(p), now.clone(), None)),
        Record::ReviewSession(row) => row
            .private
            .clone()
            .map(|p| (PrivateFields::Session(p), row.started_at.clone(), None)),
        Record::ReviewDecision(row) => row.private.clone().map(|p| {
            (
                PrivateFields::Decision(p),
                row.decided_at.clone(),
                Some(row.decided_at.clone()),
            )
        }),
        Record::ReviewParkAck(row) => row
            .private
            .clone()
            .map(|p| (PrivateFields::ParkAck(p), row.parked_at.clone(), None)),
        Record::ReviewBulkRelease(row) if row.released.iter().any(|r| r.private.is_some()) => {
            Some((
                PrivateFields::Bulk(row.released.iter().map(|r| r.private.clone()).collect()),
                row.created_at.clone(),
                Some(row.created_at.clone()),
            ))
        }
        _ => None,
    };
    value
        .map(|(p, at, expiry)| Ok((p, at, expiry.as_ref().map(deadline).transpose()?)))
        .transpose()
}
fn inject(record: &mut Record, private: PrivateFields) -> Result<(), StoreError> {
    match (record, private) {
        (Record::Task(task), PrivateFields::TaskPark(p)) => {
            task.parked.as_mut().ok_or(StoreError::Corrupt)?.private = Some(p)
        }
        (Record::ReviewSettings(row), PrivateFields::Settings(p)) => row.private = Some(p),
        (Record::ReviewSession(row), PrivateFields::Session(p)) => row.private = Some(p),
        (Record::ReviewDecision(row), PrivateFields::Decision(p)) => row.private = Some(p),
        (Record::ReviewParkAck(row), PrivateFields::ParkAck(p)) => row.private = Some(p),
        (Record::ReviewBulkRelease(row), PrivateFields::Bulk(p))
            if p.len() == row.released.len() =>
        {
            for (row, private) in row.released.iter_mut().zip(p) {
                row.private = private;
            }
        }
        _ => return Err(StoreError::Corrupt),
    }
    Ok(())
}

/// Inject only evidence paired with the exact retained public record. The public
/// read set stays separate and is never replaced by a reconstructed snapshot.
pub(crate) fn private_read_set(
    conn: &Connection,
    workspace: &str,
    public: &ReadSet,
    now: &Instant,
) -> Result<ReadSet, ExecuteError> {
    let now = instant(now)?;
    let mut result = public.clone();
    let mut statement = conn.prepare(
        "SELECT record_type,record_key,fields FROM drafts WHERE workspace_id=?1 AND editor_kind=?2",
    )?;
    for row in statement.query_map(params![workspace, KIND], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, String>(1)?,
            r.get::<_, Vec<u8>>(2)?,
        ))
    })? {
        let (kind, key, bytes) = row?;
        let overlay: Overlay = serde_json::from_slice(&bytes).map_err(|_| StoreError::Corrupt)?;
        if overlay.version != 1
            || overlay.workspace != workspace
            || overlay.entity_type.as_str() != kind
            || json!(overlay.record_key).to_string() != key
        {
            return Err(StoreError::Corrupt.into());
        }
        if overlay
            .deadline
            .as_ref()
            .map(instant)
            .transpose()?
            .is_some_and(|at| now >= at)
        {
            continue;
        }
        let body:Option<Vec<u8>>=conn.query_row("SELECT body FROM visible_records WHERE workspace_id=?1 AND record_type=?2 AND record_key=?3",params![workspace,kind,key],|r|r.get(0)).optional()?;
        let Some(body) = body else {
            continue;
        };
        let mut record = crate::execute::record_from(&kind, &body)?.public();
        if record.record_key() != overlay.record_key
            || fingerprint(&record)? != overlay.public_sha256
        {
            continue;
        }
        let source = match &record {
            Record::ReviewDecision(row) => Some(&row.decided_at),
            Record::ReviewBulkRelease(row) => Some(&row.created_at),
            _ => None,
        };
        if let Some(source) = source {
            if overlay.source_at != *source || overlay.deadline.as_ref() != Some(&deadline(source)?)
            {
                return Err(StoreError::Corrupt.into());
            }
        } else if overlay.deadline.is_some() {
            return Err(StoreError::Corrupt.into());
        }
        let Provenance::LocalCommand { command_id } = overlay.provenance;
        let proven:bool=conn.query_row("SELECT EXISTS(SELECT 1 FROM outbox WHERE workspace_id=?1 AND command_id=?2 AND state='completed' AND ever_sent=0 AND json_extract(CAST(envelope AS TEXT),'$.scope_id') IS NULL AND json_extract(CAST(envelope AS TEXT),'$.device_id') IS NULL)",params![workspace,command_id.as_str()],|r|r.get(0))?;
        if !proven {
            return Err(StoreError::Corrupt.into());
        }
        inject(&mut record, overlay.private)?;
        crate::execute::file(&mut result, record);
    }
    Ok(result)
}

/// Settles final public after-images in the existing local base with per-record
/// monotonically advancing versions, including retained tombstones.
pub(crate) fn settle_change(
    tx: &Transaction<'_>,
    workspace: &str,
    command: &CommandId,
    change: &DomainChange,
    now: &Instant,
) -> Result<(), ExecuteError> {
    let kind = change.entity_type();
    let key = change.record_key();
    let key_json = json!(key).to_string();
    let id = draft_id(kind, &key);
    let stored:Option<String>=tx.query_row("SELECT record_version FROM confirmed_records WHERE workspace_id=?1 AND record_type=?2 AND record_key=?3",params![workspace,kind.as_str(),key_json],|r|r.get(0)).optional()?;
    let version = match stored {
        None => "1".to_owned(),
        Some(stored) => {
            Counter::parse(&stored).map_err(|_| StoreError::Corrupt)?;
            let mut digits = stored.into_bytes();
            let mut carry = true;
            for digit in digits.iter_mut().rev() {
                if *digit == b'9' {
                    *digit = b'0';
                } else {
                    *digit += 1;
                    carry = false;
                    break;
                }
            }
            if carry {
                digits.insert(0, b'1');
            }
            String::from_utf8(digits).map_err(|_| StoreError::Corrupt)?
        }
    };
    let (body, revision) = match change {
        DomainChange::Upsert(record) => {
            if let Some((private, source_at, deadline)) = extract(record, now)? {
                let overlay = Overlay {
                    version: 1,
                    workspace: workspace.to_owned(),
                    entity_type: kind,
                    record_key: key.clone(),
                    provenance: Provenance::LocalCommand {
                        command_id: command.clone(),
                    },
                    public_sha256: fingerprint(record)?,
                    source_at,
                    deadline,
                    private,
                };
                tx.execute("INSERT OR REPLACE INTO drafts(workspace_id,draft_id,editor_kind,record_type,record_key,fields,updated_at,base_revision) VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",params![workspace,id,KIND,kind.as_str(),key_json,serde_json::to_vec(&overlay).map_err(|_|StoreError::Corrupt)?,now.as_str(),overlay.deadline.as_ref().map(instant).transpose()?.map(|at|at.unix_micros().to_string())])?;
            } else {
                tx.execute(
                    "DELETE FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3",
                    params![workspace, id, KIND],
                )?;
            }
            (
                Some(
                    json!(record.public())["value"]
                        .take()
                        .to_string()
                        .into_bytes(),
                ),
                crate::execute::edit_revision(record).map(|v| v.as_str().to_owned()),
            )
        }
        DomainChange::Tombstone { .. } => {
            tx.execute(
                "DELETE FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3",
                params![workspace, id, KIND],
            )?;
            (None, None)
        }
    };
    tx.execute("INSERT OR REPLACE INTO confirmed_records(workspace_id,record_type,record_key,record_version,edit_revision,tombstone,body) VALUES(?1,?2,?3,?4,?5,?6,?7)",params![workspace,kind.as_str(),key_json,version.to_string(),revision,i64::from(body.is_none()),body])?;
    Ok(())
}

/// Coalescable upkeep, independent of Review exposure. Original source deadlines
/// never move and completed public effects are untouched.
pub fn prune_local_review_private_with(
    store: &mut Store,
    now: &Instant,
    limit: u32,
    before_commit: impl FnOnce() -> Result<(), ExecuteError>,
) -> Result<u32, ExecuteError> {
    if !(1..=200).contains(&limit) {
        return Err(invalid("limit"));
    }
    let now = instant(now)?;
    store.try_write(|tx|{
        let workspace:String=tx.query_row("SELECT workspace_id FROM sync_meta",[],|r|r.get(0))?;
        let mut statement=tx.prepare("SELECT draft_id,fields FROM drafts WHERE workspace_id=?1 AND editor_kind=?2 AND base_revision IS NOT NULL AND CAST(base_revision AS INTEGER)<=?3 ORDER BY base_revision,draft_id LIMIT ?4")?;
        let rows=statement.query_map(params![workspace,KIND,now.unix_micros(),limit],|r|Ok((r.get::<_,String>(0)?,r.get::<_,Vec<u8>>(1)?)))?.collect::<Result<Vec<_>,_>>()?;
        let mut removed=0;
        for(id,body)in rows{let overlay:Overlay=serde_json::from_slice(&body).map_err(|_|StoreError::Corrupt)?;if overlay.deadline.as_ref().map(instant).transpose()?.is_some_and(|at|now>=at){removed+=tx.execute("DELETE FROM drafts WHERE workspace_id=?1 AND draft_id=?2 AND editor_kind=?3",params![workspace,id,KIND])?;}}
        before_commit()?;
        u32::try_from(removed).map_err(|_|StoreError::Corrupt.into())
    })
}

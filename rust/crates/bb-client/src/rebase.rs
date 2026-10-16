//! The explicit first-sign-in merge (spec 026, T044, FR-003; data-model "Local durable
//! records"): account-less local records become new owner-bound device commands, queued for the
//! transport, in the same transaction that links the workspace to the account.
//!
//! An account-less workspace settles every gesture locally: its records are the confirmed base
//! and its outbox rows are `completed`, with envelopes that never had a scope or a device. Those
//! are not server envelopes, so nothing is relabelled. [`link_and_merge_with`] instead
//!
//! 1. reads the visible records (tasks, projects, tags, subtasks, comments),
//! 2. removes them from the confirmed base and the projection, so they are held by commands and
//!    nothing else (`visible = confirmed + replay(pending)`; a server snapshot activated later
//!    keeps them on top of its base until their commands are confirmed),
//! 3. binds the account, scope and device and marks the workspace `linked`, and
//! 4. decides one fresh command per fact through the ordinary execute path (the same rules, the
//!    same dependency and `after_command` bookkeeping), in dependency order: tags and projects,
//!    tasks (created straight into their list with their project, tags, dates and waiting-for),
//!    the terminal transition of completed and cancelled tasks, project archives, subtasks and
//!    their transitions, comments.
//!
//! Command ids are name-based UUIDs (version 5 layout over SHA-256) of the workspace, the entity
//! type, the record key, the revision the record had and the step, so the same record always maps
//! to the same command and the execute path's known-command check recognises a repeat. The whole
//! thing is one write transaction: a crash before the commit leaves the account-less workspace
//! exactly as it was, and after it the workspace is `linked`, which a retry reports as
//! [`MergeOutcome::AlreadyLinked`] without creating a second import. The `link_checkpoint` column
//! records what was included.
//!
//! Instants: each command is decided at the instant its record carries (creation, completion,
//! archive), so `created_at`, `completed_at` and the order keys keep their meaning.
//!
//! What does not travel, by design of this slice: Review records (sessions, decisions, queues,
//! receipts, park acknowledgements, bulk releases, settings, consent) and the private overlays
//! (`runtime:local-review-private:`) stay in the local base and are counted in
//! [`MergeOutcome::Merged::review_records_kept_local`]; the formulation clock restarts at the
//! merge for a task in Next, and park markers and stalled counts are not carried.

use crate::execute::{
    ExecuteContext, ExecuteError, ExecuteRequest, RandomIds, execute_batch_in, read_projection,
    sha256,
};
use crate::storage::{Store, StoreError};
use bb_domain::types::{Comment, Project, ReadSet, ReviewSettings, Subtask, Tag, Task};
use bb_protocol::catalog::{CommandType, EntityType};
use bb_protocol::command::{AfterCommandPrecondition, CommandRef, Precondition};
use bb_protocol::wire::{CommandId, Id, Instant};
use rusqlite::params;
use serde_json::{Value, json};

/// The reserved draft namespace of the Review records a merge keeps (see `link_and_merge_with`).
pub(crate) const RETAINED_PREFIX: &str = "merge-retained:";
pub(crate) const RETAINED_KIND: &str = "merge_retained_record";

fn invalid(field: &str) -> ExecuteError {
    bb_domain::types::DomainError::field(bb_domain::types::Reason::InvalidValue, field).into()
}

/// Who the workspace becomes: the account that signed in, its scope (the account's own) and this
/// device.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AccountBinding {
    pub account: Id,
    pub scope: Id,
    pub device: Id,
}

/// What linking with a merge did.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum MergeOutcome {
    /// The workspace is the account's now. `commands` were queued from `records` local records.
    Merged {
        records: u64,
        commands: u64,
        review_records_kept_local: u64,
    },
    /// It already was this account's (a retry): nothing was queued again.
    AlreadyLinked,
    /// Another account owns it: nothing changed.
    OtherAccount,
}

/// Links the workspace to `binding.account` and queues its local records as new commands. See
/// the module documentation. `context.now` is only the fallback instant; `before_commit` runs
/// right before the commit and may refuse it.
///
/// # Errors
///
/// [`ExecuteError`] when a record cannot be expressed as a command (the whole merge is refused
/// and nothing changes), the store cannot be written, or `before_commit` refuses.
pub fn link_and_merge_with(
    store: &mut Store,
    binding: &AccountBinding,
    context: &ExecuteContext,
    before_commit: impl FnOnce() -> Result<(), ExecuteError>,
) -> Result<MergeOutcome, ExecuteError> {
    store.try_write(|tx| {
        let (workspace, state, held): (String, String, Option<String>) = tx
            .query_row(
                "SELECT workspace_id, account_link_state, account_id FROM sync_meta",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .map_err(StoreError::from)?;
        match state.as_str() {
            "linked" if held.as_deref() == Some(binding.account.as_str()) => {
                before_commit()?;
                return Ok(MergeOutcome::AlreadyLinked);
            }
            "linked" => return Ok(MergeOutcome::OtherAccount),
            "unchosen" | "account_less" => {}
            _ => return Err(invalid("account_link_state")),
        }
        let unsettled: i64 = tx
            .query_row(
                "SELECT COUNT(*) FROM outbox WHERE state <> 'completed'",
                [],
                |row| row.get(0),
            )
            .map_err(StoreError::from)?;
        if unsettled > 0 {
            return Err(invalid("account_less_queue"));
        }
        let read = read_projection(tx, &workspace)?;
        let plan = Plan::build(&workspace, binding.scope.as_str(), &read, context)?;
        let records = plan.records;
        let commands = plan.requests.len() as u64;
        let kept = review_records(&read) - u64::from(plan.settings_migrated);
        let checkpoint = json!({
            "version": 1,
            "account": binding.account.as_str(),
            "records": records,
            "commands": commands,
            "plan_sha256": plan.digest(),
        })
        .to_string()
        .into_bytes();

        // Review records are not expressible as commands here: they describe outcomes already
        // applied to tasks, under a session, a formulation and an Undo window that no longer
        // exist. They stay in the base as they are, and a copy is kept in a reserved draft
        // namespace (invisible to host draft CRUD) so that a snapshot activation, which
        // replaces the confirmed base, puts back whatever the server does not hold
        // (`snapshot::retain_merged_review`). Private overlays are drafts already.
        tx.execute(
            "INSERT OR REPLACE INTO drafts (workspace_id, draft_id, editor_kind, record_type,
                record_key, fields, base_revision, updated_at)
             SELECT workspace_id, ?1 || record_type || ':' || record_key, ?2, record_type,
                    record_key, body, NULL, ?3
             FROM visible_records
             WHERE record_type LIKE 'review\\_%' ESCAPE '\\'
               AND NOT (record_type = 'review_settings' AND ?4)",
            params![
                RETAINED_PREFIX,
                RETAINED_KIND,
                context.now.as_str(),
                plan.settings_migrated
            ],
        )
        .map_err(StoreError::from)?;
        if plan.settings_migrated {
            for table in ["visible_records", "confirmed_records"] {
                tx.execute(
                    &format!("DELETE FROM {table} WHERE record_type = 'review_settings'"),
                    [],
                )
                .map_err(StoreError::from)?;
            }
        }
        for kind in ["task", "project", "tag", "subtask", "comment"] {
            tx.execute(
                "DELETE FROM visible_records WHERE record_type = ?1",
                params![kind],
            )
            .map_err(StoreError::from)?;
            tx.execute(
                "DELETE FROM confirmed_records WHERE record_type = ?1",
                params![kind],
            )
            .map_err(StoreError::from)?;
        }
        tx.execute(
            "UPDATE sync_meta SET account_id = ?1, scope_id = ?2, device_id = ?3,
                account_link_state = 'linked', link_checkpoint = ?4,
                workspace_generation = workspace_generation + 1",
            params![
                binding.account.as_str(),
                binding.scope.as_str(),
                binding.device.as_str(),
                checkpoint
            ],
        )
        .map_err(StoreError::from)?;
        if !plan.requests.is_empty() {
            execute_batch_in(tx, &mut RandomIds, &plan.requests)?;
        }
        before_commit()?;
        Ok(MergeOutcome::Merged {
            records,
            commands,
            review_records_kept_local: kept,
        })
    })
}

fn review_records(read: &ReadSet) -> u64 {
    (usize::from(read.settings.is_some())
        + read.sessions.len()
        + read.decision_queues.len()
        + read.decisions.len()
        + read.receipts.len()
        + read.park_acks.len()
        + read.bulk_releases.len()
        + read.consents.len()) as u64
}

/// The commands, in the order they are decided.
struct Plan {
    requests: Vec<ExecuteRequest>,
    records: u64,
    /// The settings record is carried by commands, so the copy in the base is dropped.
    settings_migrated: bool,
}

impl Plan {
    fn build(
        workspace: &str,
        scope: &str,
        read: &ReadSet,
        context: &ExecuteContext,
    ) -> Result<Self, ExecuteError> {
        let mut plan = Self {
            requests: Vec::new(),
            records: 0,
            settings_migrated: false,
        };
        let mut maker = Maker { workspace, context };

        let mut tags: Vec<&Tag> = read
            .tags
            .values()
            .filter(|tag| tag.state == bb_domain::types::TagState::Active)
            .collect();
        tags.sort_by(|a, b| {
            (counter(&a.revision), a.id.as_str()).cmp(&(counter(&b.revision), b.id.as_str()))
        });
        for tag in &tags {
            plan.records += 1;
            plan.requests.push(maker.tag_create(tag)?);
        }

        let mut projects: Vec<&Project> = read.projects.values().collect();
        projects.sort_by(|a, b| {
            (a.created_at.as_str(), a.id.as_str()).cmp(&(b.created_at.as_str(), b.id.as_str()))
        });
        for project in &projects {
            plan.records += 1;
            plan.requests.push(maker.project_create(project)?);
        }

        let mut tasks: Vec<&Task> = read.tasks.values().collect();
        tasks.sort_by(|a, b| {
            (counter(&a.order_key), a.id.as_str()).cmp(&(counter(&b.order_key), b.id.as_str()))
        });
        for task in &tasks {
            plan.records += 1;
            plan.requests.push(maker.task_create(task, read)?);
            if let Some(request) = maker.task_start_clock(task)? {
                plan.requests.push(request);
            }
            if let Some(request) = maker.task_finish(task)? {
                plan.requests.push(request);
            }
        }

        // An archived project holds its tasks first and is archived after them.
        for project in &projects {
            if project.state == bb_domain::types::ProjectState::Archived {
                plan.requests.push(maker.project_archive(project)?);
            }
        }

        let mut subtasks: Vec<&Subtask> = read.subtasks.values().collect();
        subtasks.sort_by(|a, b| {
            (a.task_id.as_str(), counter(&a.order_key), a.id.as_str()).cmp(&(
                b.task_id.as_str(),
                counter(&b.order_key),
                b.id.as_str(),
            ))
        });
        for subtask in &subtasks {
            let Some(parent) = read.tasks.get(&subtask.task_id) else {
                continue; // an orphan has nothing to belong to
            };
            plan.records += 1;
            plan.requests.push(maker.subtask_create(subtask, parent)?);
            if let Some(request) = maker.subtask_finish(subtask, parent)? {
                plan.requests.push(request);
            }
        }

        let mut comments: Vec<&Comment> = read.comments.values().collect();
        comments.sort_by(|a, b| {
            (a.created_at.as_str(), a.id.as_str()).cmp(&(b.created_at.as_str(), b.id.as_str()))
        });
        for comment in &comments {
            if !read.tasks.contains_key(&comment.task_id) {
                continue;
            }
            plan.records += 1;
            plan.requests.push(maker.comment_create(comment)?);
        }
        // The owner's Review settings and activation: a singleton the commands recreate on the
        // account. Only while Review is exposed on this device; otherwise the record is kept.
        if let Some(settings) = read
            .settings
            .as_ref()
            .filter(|_| context.policy.weekly_review)
        {
            for request in maker.settings(settings, scope)? {
                plan.requests.push(request);
                plan.settings_migrated = true;
            }
        }
        Ok(plan)
    }

    /// A digest of the plan's command ids and kinds, kept in the link checkpoint.
    fn digest(&self) -> String {
        let mut text = String::new();
        for request in &self.requests {
            text.push_str(request.command_id.as_str());
            text.push(':');
            text.push_str(request.command_type.as_str());
            text.push('\n');
        }
        sha256(text.as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect()
    }
}

fn counter(value: &bb_protocol::wire::Counter) -> u64 {
    value.to_u64().unwrap_or(u64::MAX)
}

struct Maker<'a> {
    workspace: &'a str,
    context: &'a ExecuteContext,
}

impl Maker<'_> {
    /// Name-based UUID (version 5 layout over SHA-256) of one step on one record.
    fn id(
        &self,
        kind: &str,
        key: &str,
        revision: &str,
        step: &str,
    ) -> Result<CommandId, ExecuteError> {
        let name = format!(
            "bb-merge-v1\0{}\0{kind}\0{key}\0{revision}\0{step}",
            self.workspace
        );
        let digest = sha256(name.as_bytes());
        let mut bytes = [0u8; 16];
        bytes.copy_from_slice(&digest[..16]);
        bytes[6] = (bytes[6] & 0x0f) | 0x50;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        let hex: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
        CommandId::parse(format!(
            "{}-{}-{}-{}-{}",
            &hex[..8],
            &hex[8..12],
            &hex[12..16],
            &hex[16..20],
            &hex[20..]
        ))
        .map_err(|_| invalid("command_id"))
    }

    /// The formulation id a Next task starts its clock with, derived from its create command so
    /// the envelope carries it (the server needs it in the payload; locally it is the same
    /// id the rules would have allocated from the command id).
    fn formulation(&self, command: &CommandId) -> String {
        let digest = sha256(format!("bb-merge-v1-form\0{}", command.as_str()).as_bytes());
        let mut bytes = [0u8; 16];
        bytes.copy_from_slice(&digest[..16]);
        bytes[6] = (bytes[6] & 0x0f) | 0x50;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        let hex: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
        format!(
            "form_{}-{}-{}-{}-{}",
            &hex[..8],
            &hex[8..12],
            &hex[12..16],
            &hex[16..20],
            &hex[20..]
        )
    }

    fn request(
        &self,
        id: CommandId,
        command_type: CommandType,
        entity: &str,
        payload: Value,
        depends: Vec<Precondition>,
        at: &Instant,
    ) -> Result<ExecuteRequest, ExecuteError> {
        let Value::Object(payload) = payload else {
            return Err(invalid("payload"));
        };
        // Only what is set: an absent field is the default, and the server's schema takes
        // no explicit null for the create payloads.
        let payload: serde_json::Map<String, Value> = payload
            .into_iter()
            .filter(|(_, value)| !value.is_null() && value.as_array().is_none_or(|a| !a.is_empty()))
            .collect();
        let mut context = self.context.clone();
        context.now = at.clone();
        Ok(ExecuteRequest {
            command_id: id,
            command_type,
            entity_id: Some(Id::parse(entity).map_err(|_| invalid("entity_id"))?),
            payload,
            preconditions: depends,
            depends_on: Vec::new(),
            admission_tokens: Vec::new(),
            context,
        })
    }

    fn after(
        &self,
        command: &CommandId,
        entity_type: EntityType,
        entity: &str,
    ) -> Result<Vec<Precondition>, ExecuteError> {
        Ok(vec![Precondition::AfterCommand(AfterCommandPrecondition {
            after_command: CommandRef {
                command_id: command.clone(),
                entity_type,
                entity_id: Id::parse(entity).map_err(|_| invalid("entity_id"))?,
            },
        })])
    }

    /// `review.explainer_ack` (activation) and `review.settings` for the owner's singleton, at
    /// the instants the record carries.
    fn settings(
        &mut self,
        settings: &ReviewSettings,
        scope: &str,
    ) -> Result<Vec<ExecuteRequest>, ExecuteError> {
        let mut requests = Vec::new();
        let revision = settings.revision.as_str();
        let mut ack: Option<CommandId> = None;
        if let Some(at) = &settings.activated_at {
            let id = self.id("review_settings", scope, revision, "ack")?;
            requests.push(self.request(
                id.clone(),
                CommandType::ReviewExplainerAck,
                scope,
                json!({ "time_zone": settings.time_zone }),
                vec![],
                at,
            )?);
            ack = Some(id);
        }
        let mut payload = serde_json::Map::new();
        if settings.threshold_days.get() != 14 {
            payload.insert("threshold_days".into(), json!(settings.threshold_days));
        }
        if settings.review_weekday.get() != 5 {
            payload.insert("review_weekday".into(), json!(settings.review_weekday));
        }
        if serde_json::to_value(&settings.review_time).ok() != Some(json!("16:00")) {
            payload.insert("review_time".into(), json!(settings.review_time));
        }
        if serde_json::to_value(&settings.time_zone).ok() != Some(json!("UTC")) && ack.is_none() {
            payload.insert("time_zone".into(), json!(settings.time_zone));
        }
        if settings.onboarded_at.is_some() {
            payload.insert("onboarded".into(), json!(true));
        }
        if !payload.is_empty() {
            let id = self.id("review_settings", scope, revision, "settings")?;
            let after = match &ack {
                Some(ack) => self.after(ack, EntityType::ReviewSettings, scope)?,
                None => vec![Precondition::Revision(
                    bb_protocol::command::RevisionPrecondition {
                        entity_type: EntityType::ReviewSettings,
                        entity_id: Id::parse(scope).map_err(|_| invalid("entity_id"))?,
                        edit_revision: bb_protocol::wire::Counter::from(1),
                    },
                )],
            };
            let at = settings
                .onboarded_at
                .clone()
                .or_else(|| settings.activated_at.clone())
                .unwrap_or_else(|| self.context.now.clone());
            requests.push(self.request(
                id,
                CommandType::ReviewSettings,
                scope,
                Value::Object(payload),
                after,
                &at,
            )?);
        }
        Ok(requests)
    }

    fn tag_create(&mut self, tag: &Tag) -> Result<ExecuteRequest, ExecuteError> {
        let id = self.id("tag", tag.id.as_str(), tag.revision.as_str(), "create")?;
        self.request(
            id,
            CommandType::TagCreate,
            tag.id.as_str(),
            json!({ "name": tag.name }),
            vec![],
            &tag.created_at,
        )
    }

    fn project_create(&mut self, project: &Project) -> Result<ExecuteRequest, ExecuteError> {
        let id = self.id(
            "project",
            project.id.as_str(),
            project.revision.as_str(),
            "create",
        )?;
        self.request(
            id,
            CommandType::ProjectCreate,
            project.id.as_str(),
            json!({
                "name": project.name,
                "color": project.color,
                "desired_outcome": project.desired_outcome,
            }),
            vec![],
            &project.created_at,
        )
    }

    fn project_archive(&mut self, project: &Project) -> Result<ExecuteRequest, ExecuteError> {
        let created = self.id(
            "project",
            project.id.as_str(),
            project.revision.as_str(),
            "create",
        )?;
        let id = self.id(
            "project",
            project.id.as_str(),
            project.revision.as_str(),
            "archive",
        )?;
        let at = project
            .archived_at
            .clone()
            .unwrap_or_else(|| project.created_at.clone());
        let after = self.after(&created, EntityType::Project, project.id.as_str())?;
        self.request(
            id,
            CommandType::ProjectArchive,
            project.id.as_str(),
            json!({}),
            after,
            &at,
        )
    }

    fn task_create(&mut self, task: &Task, read: &ReadSet) -> Result<ExecuteRequest, ExecuteError> {
        let id = self.id("task", task.id.as_str(), task.revision.as_str(), "create")?;
        // Straight into the open list it is in; a finished task is created in the Inbox and
        // finished by the next command, which is how the rules reach a terminal state.
        let state = bb_domain::types::OpenList::from_wire(task.state.as_str())
            .map_or("inbox", bb_domain::types::OpenList::as_str);
        // A Next task with a running clock is created in the Inbox and moved to Next at the
        // instant its clock started (`task_start_clock`), under the clock's own formulation
        // id, so the creation and the clock keep their own times.
        let state = if state == "next" && task.formulation.is_some() {
            "inbox"
        } else {
            state
        };
        let project = task
            .project_id
            .as_ref()
            .filter(|id| read.projects.contains_key(*id));
        let tags: Vec<&bb_domain::types::TagId> = task
            .tag_ids
            .iter()
            .filter(|id| {
                read.tags
                    .get(*id)
                    .is_some_and(|tag| tag.state == bb_domain::types::TagState::Active)
            })
            .collect();
        let waiting = if state == "waiting" {
            task.waiting_for.as_ref()
        } else {
            None
        };
        let at = if state == "waiting" {
            task.waiting_since
                .clone()
                .unwrap_or_else(|| task.created_at.clone())
        } else {
            task.created_at.clone()
        };
        let formulation = (state == "next").then(|| self.formulation(&id));
        self.request(
            id,
            CommandType::TaskCreate,
            task.id.as_str(),
            json!({
                "title": task.title,
                "details": task.details,
                "state": state,
                "project_id": project,
                "tag_ids": tags,
                "due_date": task.due_date,
                "waiting_for": waiting,
                "new_formulation_id": formulation,
            }),
            vec![],
            &at,
        )
    }

    fn task_start_clock(&mut self, task: &Task) -> Result<Option<ExecuteRequest>, ExecuteError> {
        let (bb_domain::types::TaskState::Next, Some(clock)) =
            (task.state, task.formulation.as_ref())
        else {
            return Ok(None);
        };
        let created = self.id("task", task.id.as_str(), task.revision.as_str(), "create")?;
        let id = self.id(
            "task",
            task.id.as_str(),
            task.revision.as_str(),
            "start_clock",
        )?;
        let after = self.after(&created, EntityType::Task, task.id.as_str())?;
        self.request(
            id,
            CommandType::TaskTransition,
            task.id.as_str(),
            json!({ "action": "move", "to_state": "next", "new_formulation_id": clock.id }),
            after,
            &clock.started_at,
        )
        .map(Some)
    }

    fn task_finish(&mut self, task: &Task) -> Result<Option<ExecuteRequest>, ExecuteError> {
        let (action, at) = match task.state {
            bb_domain::types::TaskState::Completed => ("complete", task.completed_at.clone()),
            bb_domain::types::TaskState::Cancelled => ("cancel", task.cancelled_at.clone()),
            _ => return Ok(None),
        };
        let at = at.unwrap_or_else(|| task.updated_at.clone());
        let created = self.id("task", task.id.as_str(), task.revision.as_str(), "create")?;
        let id = self.id("task", task.id.as_str(), task.revision.as_str(), action)?;
        let after = self.after(&created, EntityType::Task, task.id.as_str())?;
        self.request(
            id,
            CommandType::TaskTransition,
            task.id.as_str(),
            json!({ "action": action }),
            after,
            &at,
        )
        .map(Some)
    }

    fn subtask_create(
        &mut self,
        subtask: &Subtask,
        parent: &Task,
    ) -> Result<ExecuteRequest, ExecuteError> {
        let id = self.id(
            "subtask",
            subtask.id.as_str(),
            subtask.revision.as_str(),
            "create",
        )?;
        self.request(
            id,
            CommandType::SubtaskCreate,
            subtask.id.as_str(),
            json!({ "task_id": subtask.task_id, "title": subtask.title }),
            vec![],
            &parent.created_at,
        )
    }

    fn subtask_finish(
        &mut self,
        subtask: &Subtask,
        parent: &Task,
    ) -> Result<Option<ExecuteRequest>, ExecuteError> {
        let action = match subtask.state {
            bb_domain::types::ChildState::Open => return Ok(None),
            bb_domain::types::ChildState::Completed => "complete",
            bb_domain::types::ChildState::Cancelled => "cancel",
        };
        let created = self.id(
            "subtask",
            subtask.id.as_str(),
            subtask.revision.as_str(),
            "create",
        )?;
        let id = self.id(
            "subtask",
            subtask.id.as_str(),
            subtask.revision.as_str(),
            action,
        )?;
        let after = self.after(&created, EntityType::Subtask, subtask.id.as_str())?;
        let at = parent.updated_at.clone();
        self.request(
            id,
            CommandType::SubtaskTransition,
            subtask.id.as_str(),
            json!({ "task_id": subtask.task_id, "action": action }),
            after,
            &at,
        )
        .map(Some)
    }

    fn comment_create(&mut self, comment: &Comment) -> Result<ExecuteRequest, ExecuteError> {
        let id = self.id(
            "comment",
            comment.id.as_str(),
            comment.revision.as_str(),
            "create",
        )?;
        self.request(
            id,
            CommandType::CommentCreate,
            comment.id.as_str(),
            json!({ "task_id": comment.task_id, "body": comment.body }),
            vec![],
            &comment.created_at,
        )
    }
}

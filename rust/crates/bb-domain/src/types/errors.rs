//! Typed refusals. A [`DomainError`] names a canonical reason and, at most, the
//! field or record it concerns: never user text (026-FR-022). The set follows
//! Swift `GTDValidationError`, `TaskService` and the Review http codes.

use super::vocabulary::vocab;
use bb_protocol::catalog::EntityType;
use bb_protocol::wire::{Counter, RecordKey};
use serde::{Deserialize, Serialize};

vocab! {
    /// Canonical refusal reasons; the wire spelling is the receipt error code's `reason`.
    Reason {
        TextLength => "text_length",
        InvalidValue => "invalid_value",
        InvalidPayload => "invalid_payload",
        UnsupportedCommandVersion => "unsupported_command_version",
        DependencyPending => "dependency_pending",
        DependencyRejected => "dependency_rejected",
        IncompleteReadSet => "incomplete_read_set",
        RevisionConflict => "revision_conflict",
        EntityDeleted => "entity_deleted",
        NotFound => "not_found",
        IdAlreadyExists => "id_already_exists",
        EmptyTitle => "empty_title",
        WaitingForRequired => "waiting_for_required",
        WaitingForOnlyOnWaitingTasks => "waiting_for_only_on_waiting_tasks",
        EmptyName => "empty_name",
        DuplicateProjectName => "duplicate_project_name",
        DuplicateTagName => "duplicate_tag_name",
        ProjectNotActive => "project_not_active",
        ProjectArchived => "project_archived",
        ProjectAlreadyArchived => "project_already_archived",
        UnarchiveNameInUse => "unarchive_name_in_use",
        TagNotActive => "tag_not_active",
        TagAlreadyDeleted => "tag_already_deleted",
        DuplicateTag => "duplicate_tag",
        TagChangesOverlap => "tag_changes_overlap",
        TaskNotOpen => "task_not_open",
        TaskNotClosed => "task_not_closed",
        MoveRequiresDestination => "move_requires_destination",
        MoveRequiresDifferentList => "move_requires_different_list",
        ReopenRequiresDestination => "reopen_requires_destination",
        SubtaskAlreadyInState => "subtask_already_in_state",
        NothingToChange => "nothing_to_change",
        PriorityRequired => "priority_required",
        SmartAddRefInvalid => "smart_add_ref_invalid",
        DecisionNotAllowed => "decision_not_allowed",
        DecisionFieldsMissing => "decision_fields_missing",
        ExtensionAlreadyUsed => "extension_already_used",
        ExtensionNotDue => "extension_not_due",
        ExtensionReasonRequired => "extension_reason_required",
        FormulationChanged => "formulation_changed",
        FormulationIdRequired => "formulation_id_required",
        UndoUnavailable => "undo_unavailable",
        UndoExpired => "undo_expired",
        UndoBlockedByChildren => "undo_blocked_by_children",
        ReviewUnavailable => "review_unavailable",
        ReviewNotActivated => "review_not_activated",
        SessionNotOpen => "session_not_open",
        SessionNotFound => "session_not_found",
        StepNotInReview => "step_not_in_review",
        InvalidTimeZone => "invalid_time_zone",
        TooManyItems => "too_many_items",
        ConsentRequired => "consent_required",
        ConsentTextOutdated => "consent_text_outdated",
        ProviderUnavailable => "provider_unavailable",
    }
}

/// A refusal: reason, optionally the field or record concerned, and the
/// current revision a stale check saw.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DomainError {
    pub reason: Reason,
    pub field: Option<String>,
    pub entity: Option<(EntityType, RecordKey)>,
    pub current_revision: Option<Counter>,
}

impl DomainError {
    pub fn new(reason: Reason) -> Self {
        Self {
            reason,
            field: None,
            entity: None,
            current_revision: None,
        }
    }

    /// A refusal naming the request field (a type name or payload key).
    pub fn field(reason: Reason, field: &str) -> Self {
        Self {
            field: Some(field.to_owned()),
            ..Self::new(reason)
        }
    }

    /// A refusal about one record.
    pub fn about(reason: Reason, entity_type: EntityType, key: RecordKey) -> Self {
        Self {
            entity: Some((entity_type, key)),
            ..Self::new(reason)
        }
    }

    /// A fact the protected read set did not load; reported, never defaulted.
    pub fn missing(entity_type: EntityType, key: RecordKey) -> Self {
        Self::about(Reason::IncompleteReadSet, entity_type, key)
    }

    /// A stale revision check, with the revision the record is at.
    pub fn stale(entity_type: EntityType, key: RecordKey, current: Counter) -> Self {
        Self {
            current_revision: Some(current),
            ..Self::about(Reason::RevisionConflict, entity_type, key)
        }
    }
}

impl std::fmt::Display for DomainError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.reason.as_str())?;
        if let Some(field) = &self.field {
            write!(f, " ({field})")?;
        }
        Ok(())
    }
}

impl std::error::Error for DomainError {}

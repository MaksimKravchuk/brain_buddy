//! The frozen command catalog (contracts/command-catalog.md): entity and
//! command types. A test pins both lists to `sync-v1.schema.json`.

use crate::wire::wire_enum;

wire_enum!(
    /// Replicated entity types: the Tasks aggregate and native-task Review.
    EntityType {
        Task => "task",
        Project => "project",
        Tag => "tag",
        Subtask => "subtask",
        Comment => "comment",
        ReviewSettings => "review_settings",
        ReviewSession => "review_session",
        ReviewDecisionQueue => "review_decision_queue",
        ReviewDecision => "review_decision",
        ReviewReceipt => "review_receipt",
        ReviewParkAck => "review_park_ack",
        ReviewBulkRelease => "review_bulk_release",
        ReviewNavigatorConsent => "review_navigator_consent",
    }
);

wire_enum!(
    /// Executable command types of protocol v1.
    CommandType {
        ProjectCreate => "project.create",
        ProjectUpdate => "project.update",
        ProjectArchive => "project.archive",
        ProjectUnarchive => "project.unarchive",
        TagCreate => "tag.create",
        TagUpdate => "tag.update",
        TagDelete => "tag.delete",
        TaskCreate => "task.create",
        TaskSmartAdd => "task.smart_add",
        TaskUpdate => "task.update",
        TaskTags => "task.tags",
        TaskTransition => "task.transition",
        SubtaskCreate => "subtask.create",
        SubtaskUpdate => "subtask.update",
        SubtaskTransition => "subtask.transition",
        CommentCreate => "comment.create",
        CommentUpdate => "comment.update",
        ReviewDecide => "review.decide",
        ReviewUndoDecision => "review.undo_decision",
        ReviewAutoPark => "review.auto_park",
        ReviewExplainerAck => "review.explainer_ack",
        ReviewSettings => "review.settings",
        ReviewParksAck => "review.parks_ack",
        ReviewSessionStart => "review.session_start",
        ReviewSessionProgress => "review.session_progress",
        ReviewSessionFinish => "review.session_finish",
        ReviewBulkRelease => "review.bulk_release",
        ReviewBulkUndo => "review.bulk_undo",
        ReviewConsentGrant => "review.consent_grant",
        ReviewConsentRevoke => "review.consent_revoke",
    }
);

impl CommandType {
    /// Command versions this build executes.
    pub fn supported_versions(self) -> &'static [u32] {
        &[1]
    }

    /// Whether the payload must name its parent `task_id` (subtasks, comments).
    pub fn is_child(self) -> bool {
        matches!(
            self,
            Self::SubtaskCreate
                | Self::SubtaskUpdate
                | Self::SubtaskTransition
                | Self::CommentCreate
                | Self::CommentUpdate
        )
    }

    /// Ceiling on `payload.items`, for the two catalog commands that carry one.
    pub fn item_limit(self) -> Option<usize> {
        match self {
            Self::ReviewParksAck => Some(200),
            Self::ReviewBulkRelease => Some(500),
            _ => None,
        }
    }
}

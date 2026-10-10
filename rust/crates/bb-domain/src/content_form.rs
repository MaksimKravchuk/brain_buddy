//! The existing Apple RecordContentForm bytes, without hashing or I/O.
//! Name normalization preserves its original UTF-8; NFC is used only for Swift String ordering.

use crate::{
    normalization,
    types::{DomainError, ReadSet, Reason, SubtaskId, Task},
};
use std::{cmp::Ordering, collections::BTreeMap};
use unicode_normalization::UnicodeNormalization;

fn swift_compare(a: &str, b: &str) -> Ordering {
    a.nfc().cmp(b.nfc())
}
fn count(value: usize, out: &mut Vec<u8>) -> Result<(), DomainError> {
    let value = u32::try_from(value)
        .map_err(|_| DomainError::field(Reason::InvalidValue, "content_length"))?;
    out.extend_from_slice(&value.to_be_bytes());
    Ok(())
}
fn field(value: Option<&str>, out: &mut Vec<u8>) -> Result<(), DomainError> {
    if let Some(value) = value {
        out.push(1);
        count(value.len(), out)?;
        out.extend_from_slice(value.as_bytes());
    } else {
        out.push(0);
    }
    Ok(())
}

/// Full visible content; child identity is used only to reproduce the original tie order.
pub fn task_bytes(
    state: &ReadSet,
    task: &Task,
    logical_children: &BTreeMap<SubtaskId, String>,
) -> Result<Vec<u8>, DomainError> {
    let mut out = Vec::new();
    field(Some(task.title.as_str()), &mut out)?;
    field(task.details.as_ref().map(|v| v.as_str()), &mut out)?;
    field(Some(task.state.as_str()), &mut out)?;
    field(task.waiting_for.as_ref().map(|v| v.as_str()), &mut out)?;
    field(task.due_date.as_ref().map(|v| v.as_str()), &mut out)?;
    field(Some(task.priority.as_str()), &mut out)?;
    let project = task
        .project_id
        .as_ref()
        .and_then(|id| state.projects.get(id))
        .map(|p| normalization::project_key(p.name.as_str()));
    field(project.as_deref(), &mut out)?;
    let mut tags: Vec<String> = task
        .tag_ids
        .iter()
        .filter_map(|id| state.tags.get(id))
        .map(|tag| normalization::tag_key(tag.name.as_str()))
        .collect();
    tags.sort_by(|a, b| swift_compare(a, b));
    count(tags.len(), &mut out)?;
    for tag in tags {
        field(Some(&tag), &mut out)?;
    }
    let mut children = state
        .subtasks
        .values()
        .filter(|row| row.task_id == task.id)
        .map(|row| {
            let order = row
                .order_key
                .to_u64()
                .ok_or_else(|| DomainError::field(Reason::InvalidValue, "order_key"))?;
            let logical = logical_children
                .get(&row.id)
                .map_or(row.id.as_str(), String::as_str);
            Ok((order, logical, row))
        })
        .collect::<Result<Vec<_>, DomainError>>()?;
    children.sort_by(|a, b| a.0.cmp(&b.0).then_with(|| swift_compare(a.1, b.1)));
    if children.windows(2).any(|pair| {
        pair[0].0 == pair[1].0 && swift_compare(pair[0].1, pair[1].1) == Ordering::Equal
    }) {
        return Err(DomainError::field(
            Reason::InvalidValue,
            "content_identity_ambiguity",
        ));
    }
    count(children.len(), &mut out)?;
    for (_, _, child) in children {
        field(Some(child.title.as_str()), &mut out)?;
        field(Some(child.state.as_str()), &mut out)?;
    }
    Ok(out)
}

/// Project content has no header or task count: only byte-sorted length-prefixed task forms.
pub fn project_bytes(mut tasks: Vec<Vec<u8>>) -> Result<Vec<u8>, DomainError> {
    tasks.sort();
    let mut out = Vec::new();
    for task in tasks {
        count(task.len(), &mut out)?;
        out.extend_from_slice(&task);
    }
    Ok(out)
}

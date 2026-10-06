use crate::{
    command::{Cli, Request, Shape},
    error::{Error, Result},
};
use serde_json::{Map, Value, json};

const TASK_FIELDS: &[&str] = &[
    "id",
    "title",
    "state",
    "revision",
    "priority",
    "due_date",
    "project_id",
    "tag_ids",
];
const TASK_ALL: &[&str] = &[
    "id",
    "title",
    "state",
    "revision",
    "priority",
    "due_date",
    "project_id",
    "tag_ids",
    "details",
    "waiting_for",
    "waiting_since",
    "order_key",
    "source_capture_ids",
    "created_at",
    "updated_at",
    "completed_at",
    "cancelled_at",
    "subtasks",
    "comments",
    "formulation",
    "parked",
];
pub fn validate_fields(cli: &Cli, r: &Request) -> Result<Vec<String>> {
    let fields = cli
        .fields
        .as_ref()
        .map(|s| s.split(',').map(str::to_owned).collect::<Vec<_>>())
        .unwrap_or_default();
    for field in &fields {
        let parts = field.split('.').collect::<Vec<_>>();
        if parts.len() > 4
            || parts
                .iter()
                .any(|p| p.is_empty() || !p.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_'))
        {
            return Err(Error::invalid(
                "Field selectors must be comma-separated dotted property names.",
            ));
        }
        let roots = match r.shape {
            Shape::Task => TASK_ALL,
            Shape::Project => &[
                "id",
                "name",
                "color",
                "state",
                "revision",
                "open_task_count",
            ],
            Shape::Tag => &["id", "name", "state", "revision", "open_task_count"],
            Shape::Other => &[],
        };
        if !roots.is_empty() && !roots.contains(&parts[0]) {
            return Err(Error::invalid("Unknown field selector for this command."));
        }
        if parts.len() > 1
            && r.shape != Shape::Other
            && !["subtasks", "comments", "formulation", "parked"].contains(&parts[0])
        {
            return Err(Error::invalid("This field has no nested properties."));
        }
        if parts.len() > 1 && r.method != "GET" {
            return Err(Error::invalid(
                "Mutations support locally known top-level field selectors.",
            ));
        }
    }
    Ok(fields)
}

fn project(value: &Value, fields: &[String], strict: bool) -> Result<Value> {
    if let Some(items) = value.as_array() {
        return items
            .iter()
            .map(|v| project(v, fields, strict))
            .collect::<Result<Vec<_>>>()
            .map(Value::Array);
    }
    let source = value.as_object().ok_or_else(Error::protocol)?;
    let mut result = Map::new();
    let mut groups = std::collections::BTreeMap::<&str, Vec<String>>::new();
    for field in fields {
        let (name, tail) = field.split_once('.').unwrap_or((field.as_str(), ""));
        groups.entry(name).or_default().push(tail.to_owned());
    }
    for (name, tails) in groups {
        if let Some(value) = source.get(name) {
            let selected = if tails.iter().any(String::is_empty) || value.is_null() {
                value.clone()
            } else {
                project(value, &tails, strict)?
            };
            result.insert(name.into(), selected);
        } else if strict {
            return Err(Error::invalid("Selected response field is unavailable."));
        }
    }
    for key in ["id", "revision"] {
        if let Some(value) = source.get(key) {
            result.insert(key.into(), value.clone());
        }
    }
    Ok(Value::Object(result))
}

pub fn format(cli: &Cli, r: &Request, mut value: Value, selectors: &[String]) -> Result<Value> {
    let mut page = None;
    if r.shape == Shape::Task && r.list {
        page = Some(
            json!({"has_more":value.get("has_more").and_then(Value::as_bool).ok_or_else(Error::protocol)?,"next_cursor":value.get("next_cursor").cloned().ok_or_else(Error::protocol)?}),
        );
        let counts = value.get("counts_by_state").cloned();
        value = value
            .get("items")
            .cloned()
            .filter(Value::is_array)
            .ok_or_else(Error::protocol)?;
        if value.as_array().unwrap().len() > usize::from(cli.limit) {
            return Err(Error::protocol());
        }
        if cli.full {
            let mut result = json!({"data":value,"page":page});
            if let Some(counts) = counts {
                result["counts_by_state"] = counts;
            }
            return Ok(result);
        }
    } else if let Some(items) = value.as_array_mut() {
        if items.len() > usize::from(cli.limit) {
            items.truncate(usize::from(cli.limit));
            page = Some(json!({"has_more":false,"next_cursor":null,"truncated":true}));
        } else if r.list {
            page = Some(json!({"has_more":false,"next_cursor":null}));
        }
    }
    let defaults = TASK_FIELDS
        .iter()
        .map(|s| (*s).to_owned())
        .collect::<Vec<_>>();
    if !selectors.is_empty() {
        value = project(&value, selectors, r.shape == Shape::Other)?;
    } else if r.shape == Shape::Task && !cli.full {
        value = project(&value, &defaults, false)?;
    }
    let mut result = json!({"data":value});
    if let Some(page) = page {
        result["page"] = page;
    }
    Ok(result)
}

pub fn scoped_schema(document: Value, method: &str, path: &str) -> Result<Value> {
    let operation = document
        .get("paths")
        .and_then(|p| p.get(path))
        .and_then(|p| p.get(method.to_ascii_lowercase()))
        .cloned()
        .ok_or_else(|| Error::invalid("Schema operation is not available."))?;
    let schemas = document
        .pointer("/components/schemas")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let mut selected = Map::new();
    let mut pending = vec![operation.clone()];
    while let Some(value) = pending.pop() {
        match value {
            Value::Object(object) => {
                if let Some(reference) = object.get("$ref").and_then(Value::as_str) {
                    if let Some(name) = reference.strip_prefix("#/components/schemas/") {
                        if !selected.contains_key(name) {
                            let schema = schemas.get(name).cloned().ok_or_else(Error::protocol)?;
                            selected.insert(name.into(), schema.clone());
                            pending.push(schema);
                        }
                    } else {
                        return Err(Error::protocol());
                    }
                }
                pending.extend(object.into_values());
            }
            Value::Array(array) => pending.extend(array),
            _ => {}
        }
    }
    Ok(json!({"data":{"method":method,"path":path,"operation":operation,"schemas":selected}}))
}

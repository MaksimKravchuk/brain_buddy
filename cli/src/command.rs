use crate::error::{Error, Result};
use clap::{Args, CommandFactory, Parser, Subcommand};
use serde_json::{Map, Value, json};
use std::{
    fs::File,
    io::{self, Read},
    path::Path,
};

pub const INPUT_LIMIT: usize = 1024 * 1024;

#[derive(Parser)]
#[command(
    name = "bb",
    version,
    about = "BrainBuddy CLI for people and AI agents",
    disable_help_subcommand = true
)]
pub struct Cli {
    #[arg(
        long,
        global = true,
        help = "HTTPS server origin (loopback HTTP for development)"
    )]
    pub server: Option<String>,
    #[arg(long, global = true, help = "API prefix, default /api")]
    pub api_prefix: Option<String>,
    #[arg(long, global = true, help = "JSON object, @FILE, or @- for stdin")]
    pub json: Option<String>,
    #[arg(long, global = true, help = "Explicit reusable Idempotency-Key")]
    pub key: Option<String>,
    #[arg(long, global = true, help = "Explicit expected_revision")]
    pub revision: Option<u64>,
    #[arg(
        long,
        global = true,
        conflicts_with = "full",
        help = "Comma-separated response fields"
    )]
    pub fields: Option<String>,
    #[arg(long, global = true, help = "All bounded response fields")]
    pub full: bool,
    #[arg(long, global=true, default_value="20", value_parser=clap::value_parser!(u16).range(1..=200))]
    pub limit: u16,
    #[arg(long, global = true, help = "Opaque task continuation cursor")]
    pub cursor: Option<String>,
    #[arg(long, global=true, action=clap::ArgAction::Append, help="URL-encoded KEY=VALUE query parameter")]
    pub query: Vec<String>,
    #[arg(
        long,
        global = true,
        help = "Offline request preview; redact all payload values"
    )]
    pub dry_run: bool,
    #[command(subcommand)]
    pub command: Action,
}

#[derive(Subcommand)]
pub enum Action {
    /// Capture, find, edit and transition tasks
    Task {
        #[command(subcommand)]
        action: TaskAction,
    },
    /// Manage projects through existing API semantics
    Project {
        #[command(subcommand)]
        action: ProjectAction,
    },
    /// Manage tags through existing API semantics
    Tag {
        #[command(subcommand)]
        action: TagAction,
    },
    /// Inspect trees and existing CRT operations
    Tree {
        #[command(subcommand)]
        action: TreeAction,
    },
    /// Execute a deployed member business JSON operation
    Api(ApiArgs),
    /// Discover commands offline; optional scope such as task update
    Commands { scope: Vec<String> },
    /// Retrieve only one live OpenAPI operation and its referenced schemas
    Schema(ApiArgs),
    /// Connect, inspect identity, or revoke this CLI session
    Auth {
        #[command(subcommand)]
        action: AuthAction,
    },
}

#[derive(Subcommand)]
pub enum TaskAction {
    Add(TaskInput),
    List(TaskFilter),
    Get {
        id: String,
    },
    Update {
        id: String,
        #[command(flatten)]
        input: TaskInput,
    },
    Transition {
        id: String,
        #[arg(value_parser=["move","complete","reopen","cancel"])]
        action: String,
        #[arg(long)]
        to_state: Option<String>,
        #[arg(long)]
        waiting_for: Option<String>,
    },
}

#[derive(Args, Default)]
pub struct TaskInput {
    #[arg(long)]
    pub title: Option<String>,
    #[arg(long)]
    pub details: Option<String>,
    #[arg(long)]
    pub state: Option<String>,
    #[arg(long = "project")]
    pub project_id: Option<String>,
    #[arg(long="tag", action=clap::ArgAction::Append)]
    pub tag_ids: Vec<String>,
    #[arg(long)]
    pub priority: Option<String>,
    #[arg(long = "due")]
    pub due_date: Option<String>,
    #[arg(long)]
    pub waiting_for: Option<String>,
}

#[derive(Args)]
pub struct TaskFilter {
    #[arg(long)]
    pub q: Option<String>,
    #[arg(long)]
    pub state: Option<String>,
    #[arg(long = "project")]
    pub project_id: Option<String>,
    #[arg(long = "tag")]
    pub tag_id: Option<String>,
    #[arg(long, action=clap::ArgAction::Append)]
    pub priority: Vec<String>,
    #[arg(long)]
    pub sort: Option<String>,
    #[arg(long)]
    pub due_before: Option<String>,
    #[arg(long)]
    pub due_on: Option<String>,
    #[arg(long)]
    pub due_after: Option<String>,
    #[arg(long)]
    pub include_completed: bool,
    #[arg(long)]
    pub include_cancelled: bool,
    #[arg(long)]
    pub unassigned_project: bool,
}

#[derive(Subcommand)]
pub enum ProjectAction {
    List,
    Get {
        id: String,
    },
    Add {
        #[arg(long)]
        name: Option<String>,
        #[arg(long)]
        color: Option<String>,
    },
    Update {
        id: String,
        #[arg(long)]
        name: Option<String>,
        #[arg(long)]
        color: Option<String>,
    },
    Archive {
        id: String,
    },
}
#[derive(Subcommand)]
pub enum TagAction {
    List,
    Get {
        id: String,
    },
    Add {
        #[arg(long)]
        name: Option<String>,
    },
    Update {
        id: String,
        #[arg(long)]
        name: Option<String>,
    },
    Delete {
        id: String,
    },
}
#[derive(Subcommand)]
pub enum TreeAction {
    List,
    Get { id: String },
    Api(ApiArgs),
}
#[derive(Args)]
pub struct ApiArgs {
    #[arg(value_parser=["GET","POST","PUT","PATCH","DELETE"])]
    pub method: String,
    pub path: String,
}
#[derive(Subcommand)]
pub enum AuthAction {
    Login(LoginArgs),
    Status,
    Logout,
}
#[derive(Args)]
pub struct LoginArgs {
    #[arg(long)]
    pub no_browser: bool,
    #[arg(long, default_value="native", value_parser=["native","file"])]
    pub store: String,
    #[arg(long)]
    pub replace: bool,
}

#[derive(Clone, Copy, PartialEq)]
pub enum Shape {
    Task,
    Project,
    Tag,
    Other,
}

pub struct Request {
    pub method: String,
    pub path: String,
    pub query: Vec<(String, String)>,
    pub body: Option<Value>,
    pub key: Option<String>,
    pub shape: Shape,
    pub list: bool,
}

pub fn validate_path(path: &str) -> Result<()> {
    if !path.starts_with('/')
        || path.starts_with("//")
        || path.contains(['\\', '?', '#', '%'])
        || path.chars().any(|c| c.is_control() || c.is_whitespace())
        || path.split('/').any(|s| s == "." || s == "..")
    {
        return Err(Error::invalid(
            "Use a relative API path without traversal, escapes or query text.",
        ));
    }
    Ok(())
}

fn id(value: &str) -> Result<&str> {
    if value.is_empty()
        || value.len() > 500
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
    {
        return Err(Error::invalid(
            "Resource ID must be a nonempty opaque identifier.",
        ));
    }
    Ok(value)
}

pub fn business_path(path: &str) -> Result<()> {
    validate_path(path)?;
    let root = path.split('/').nth(1).unwrap_or("");
    if ![
        "tasks",
        "projects",
        "tags",
        "trees",
        "crt",
        "brain-dump-operations",
        "brain-dump-providers",
        "agent-connections",
        "agent-runs",
        "agent-run-summaries",
    ]
    .contains(&root)
    {
        return Err(Error::invalid(
            "Generic API is restricted to member business operations; use specialized auth commands.",
        ));
    }
    Ok(())
}

fn read_json(source: &str) -> Result<Value> {
    let bytes = if source == "@-" {
        bounded(io::stdin().lock())?
    } else if let Some(path) = source.strip_prefix('@') {
        if !Path::new(path).metadata().is_ok_and(|m| m.is_file()) {
            return Err(Error::invalid(
                "JSON input must be a readable regular file.",
            ));
        }
        bounded(File::open(path).map_err(|_| Error::invalid("Cannot read JSON input file."))?)?
    } else {
        if source.len() > INPUT_LIMIT {
            return Err(Error::invalid("JSON input exceeds 1 MiB."));
        }
        source.as_bytes().to_vec()
    };
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|_| Error::invalid("Input must contain valid UTF-8 JSON."))?;
    if !value.is_object() {
        return Err(Error::invalid("JSON input must be one object."));
    }
    Ok(value)
}
fn bounded(reader: impl Read) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    reader
        .take((INPUT_LIMIT + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| Error::invalid("Cannot read JSON input."))?;
    if bytes.len() > INPUT_LIMIT {
        return Err(Error::invalid("JSON input exceeds 1 MiB."));
    }
    Ok(bytes)
}

fn insert(map: &mut Map<String, Value>, name: &str, value: &Option<String>) {
    if let Some(value) = value {
        map.insert(name.to_owned(), json!(value));
    }
}
fn body(cli: &Cli, named: Map<String, Value>) -> Result<Map<String, Value>> {
    if let Some(source) = &cli.json {
        if !named.is_empty() {
            return Err(Error::invalid(
                "Named payload options and --json are mutually exclusive.",
            ));
        }
        Ok(read_json(source)?.as_object().cloned().unwrap())
    } else {
        Ok(named)
    }
}
fn revise(cli: &Cli, body: &mut Map<String, Value>, required: bool) -> Result<()> {
    if let Some(revision) = cli.revision {
        if revision == 0
            || body
                .get("expected_revision")
                .is_some_and(|v| v.as_u64() != Some(revision))
        {
            return Err(Error::invalid(
                "Revision must be positive and agree with JSON.",
            ));
        }
        body.insert("expected_revision".into(), json!(revision));
    }
    if required
        && !body
            .get("expected_revision")
            .is_some_and(|v| v.as_u64().is_some_and(|r| r > 0))
    {
        return Err(Error::invalid(
            "Provide --revision or JSON expected_revision for this mutation.",
        ));
    }
    Ok(())
}

fn named(
    cli: &Cli,
    method: &str,
    path: String,
    fields: Map<String, Value>,
    shape: Shape,
    list: bool,
    revision: bool,
) -> Result<Request> {
    let write = method != "GET";
    let mut data = if write {
        body(cli, fields)?
    } else {
        if cli.json.is_some() || cli.revision.is_some() || cli.key.is_some() {
            return Err(Error::invalid(
                "Read commands do not accept a mutation body, key or revision.",
            ));
        }
        Map::new()
    };
    revise(cli, &mut data, revision)?;
    if write && cli.key.is_none() {
        return Err(Error::invalid(
            "Provide an explicit reusable --key for this mutation.",
        ));
    }
    Ok(Request {
        method: method.into(),
        path,
        query: vec![],
        body: write.then_some(Value::Object(data)),
        key: cli.key.clone(),
        shape,
        list,
    })
}

pub fn compile(cli: &Cli) -> Result<Request> {
    if cli.key.as_ref().is_some_and(|k| {
        k.is_empty()
            || k.len() > 200
            || !k
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(&b))
    }) {
        return Err(Error::invalid(
            "Key must be 1–200 ASCII letters, digits, dot, underscore, colon or dash.",
        ));
    }
    let empty = Map::new();
    let mut r = match &cli.command {
        Action::Task { action } => match action {
            TaskAction::Add(input) | TaskAction::Update { input, .. } => {
                let mut fields = Map::new();
                insert(&mut fields, "title", &input.title);
                insert(&mut fields, "details", &input.details);
                insert(&mut fields, "state", &input.state);
                insert(&mut fields, "project_id", &input.project_id);
                insert(&mut fields, "priority", &input.priority);
                insert(&mut fields, "due_date", &input.due_date);
                insert(&mut fields, "waiting_for", &input.waiting_for);
                if !input.tag_ids.is_empty() {
                    fields.insert("tag_ids".into(), json!(input.tag_ids));
                }
                let (method, path, revision) = if let TaskAction::Update { id: resource, .. } =
                    action
                {
                    if input.state.is_some() {
                        return Err(Error::invalid("Use task transition to change task state."));
                    }
                    ("PATCH", format!("/tasks/{}", id(resource)?), true)
                } else {
                    ("POST", "/tasks".into(), false)
                };
                let r = named(cli, method, path, fields, Shape::Task, false, revision)?;
                if !revision
                    && !r
                        .body
                        .as_ref()
                        .and_then(|b| b.get("title"))
                        .is_some_and(|v| v.as_str().is_some_and(|s| !s.is_empty()))
                {
                    return Err(Error::invalid("Task add requires a title."));
                }
                r
            }
            TaskAction::Get { id: resource } => named(
                cli,
                "GET",
                format!("/tasks/{}", id(resource)?),
                empty,
                Shape::Task,
                false,
                false,
            )?,
            TaskAction::List(filter) => {
                let mut r = named(cli, "GET", "/tasks".into(), empty, Shape::Task, true, false)?;
                for (name, value) in [
                    ("q", &filter.q),
                    ("state", &filter.state),
                    ("project_id", &filter.project_id),
                    ("tag_id", &filter.tag_id),
                    ("sort", &filter.sort),
                    ("due_before", &filter.due_before),
                    ("due_on", &filter.due_on),
                    ("due_after", &filter.due_after),
                ] {
                    if let Some(v) = value {
                        r.query.push((name.into(), v.clone()));
                    }
                }
                for v in &filter.priority {
                    r.query.push(("priority".into(), v.clone()));
                }
                for (name, value) in [
                    ("include_completed", filter.include_completed),
                    ("include_cancelled", filter.include_cancelled),
                    ("unassigned_project", filter.unassigned_project),
                ] {
                    if value {
                        r.query.push((name.into(), "true".into()));
                    }
                }
                r.query.push(("limit".into(), cli.limit.to_string()));
                if let Some(cursor) = &cli.cursor {
                    r.query.push(("cursor".into(), cursor.clone()));
                }
                r
            }
            TaskAction::Transition {
                id: resource,
                action,
                to_state,
                waiting_for,
            } => {
                let mut fields = Map::new();
                fields.insert("action".into(), json!(action));
                insert(&mut fields, "to_state", to_state);
                insert(&mut fields, "waiting_for", waiting_for);
                named(
                    cli,
                    "POST",
                    format!("/tasks/{}/transitions", id(resource)?),
                    fields,
                    Shape::Task,
                    false,
                    true,
                )?
            }
        },
        Action::Project { action } => match action {
            ProjectAction::List => named(
                cli,
                "GET",
                "/projects".into(),
                empty,
                Shape::Project,
                true,
                false,
            )?,
            ProjectAction::Get { id: resource } => named(
                cli,
                "GET",
                format!("/projects/{}", id(resource)?),
                empty,
                Shape::Project,
                false,
                false,
            )?,
            ProjectAction::Add { name, color } | ProjectAction::Update { name, color, .. } => {
                let mut fields = Map::new();
                insert(&mut fields, "name", name);
                insert(&mut fields, "color", color);
                let (method, path, revision) =
                    if let ProjectAction::Update { id: resource, .. } = action {
                        ("PATCH", format!("/projects/{}", id(resource)?), true)
                    } else {
                        ("POST", "/projects".into(), false)
                    };
                let r = named(cli, method, path, fields, Shape::Project, false, revision)?;
                require_name(&r, revision)?;
                r
            }
            ProjectAction::Archive { id: resource } => named(
                cli,
                "POST",
                format!("/projects/{}/archive", id(resource)?),
                empty,
                Shape::Project,
                false,
                true,
            )?,
        },
        Action::Tag { action } => match action {
            TagAction::List => named(cli, "GET", "/tags".into(), empty, Shape::Tag, true, false)?,
            TagAction::Get { id: resource } => named(
                cli,
                "GET",
                format!("/tags/{}", id(resource)?),
                empty,
                Shape::Tag,
                false,
                false,
            )?,
            TagAction::Add { name } | TagAction::Update { name, .. } => {
                let mut fields = Map::new();
                insert(&mut fields, "name", name);
                let (method, path, revision) =
                    if let TagAction::Update { id: resource, .. } = action {
                        ("PATCH", format!("/tags/{}", id(resource)?), true)
                    } else {
                        ("POST", "/tags".into(), false)
                    };
                let r = named(cli, method, path, fields, Shape::Tag, false, revision)?;
                require_name(&r, revision)?;
                r
            }
            TagAction::Delete { id: resource } => {
                let mut r = named(
                    cli,
                    "DELETE",
                    format!("/tags/{}", id(resource)?),
                    empty,
                    Shape::Tag,
                    false,
                    true,
                )?;
                let revision = r.body.take().unwrap()["expected_revision"]
                    .as_u64()
                    .unwrap();
                r.query
                    .push(("expected_revision".into(), revision.to_string()));
                r
            }
        },
        Action::Tree {
            action: TreeAction::List,
        } => named(
            cli,
            "GET",
            "/trees".into(),
            empty,
            Shape::Other,
            true,
            false,
        )?,
        Action::Tree {
            action: TreeAction::Get { id: resource },
        } => named(
            cli,
            "GET",
            format!("/trees/{}", id(resource)?),
            empty,
            Shape::Other,
            false,
            false,
        )?,
        Action::Api(args)
        | Action::Tree {
            action: TreeAction::Api(args),
        } => {
            business_path(&args.path)?;
            let root = args.path.split('/').nth(1).unwrap_or("");
            let roots = [
                "tasks",
                "projects",
                "tags",
                "trees",
                "crt",
                "brain-dump-operations",
                "brain-dump-providers",
                "agent-connections",
                "agent-runs",
                "agent-run-summaries",
            ];
            if !roots.contains(&root)
                || (matches!(cli.command, Action::Tree { .. }) && !["trees", "crt"].contains(&root))
            {
                return Err(Error::invalid(
                    "Generic API is restricted to member business operations; use specialized auth commands.",
                ));
            }
            if args.method != "GET" && cli.fields.is_some() {
                return Err(Error::invalid(
                    "Generic mutations do not accept response field selection.",
                ));
            }
            let mut data = cli.json.as_ref().map(|s| read_json(s)).transpose()?;
            if args.method == "GET"
                && (data.is_some() || cli.revision.is_some() || cli.key.is_some())
            {
                return Err(Error::invalid(
                    "Generic GET does not accept mutation input.",
                ));
            }
            if cli.revision.is_some() {
                let mut fields = data.unwrap_or(json!({})).as_object().cloned().unwrap();
                revise(cli, &mut fields, false)?;
                data = Some(Value::Object(fields));
            }
            Request {
                method: args.method.clone(),
                path: args.path.clone(),
                query: vec![],
                body: data,
                key: cli.key.clone(),
                shape: Shape::Other,
                list: false,
            }
        }
        _ => {
            return Err(Error::invalid(
                "This operation uses its specialized command handler.",
            ));
        }
    };
    for pair in &cli.query {
        let Some((key, value)) = pair.split_once('=') else {
            return Err(Error::invalid("Query must use KEY=VALUE."));
        };
        if key.is_empty()
            || key.len() > 128
            || !key
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"_-".contains(&b))
        {
            return Err(Error::invalid("Invalid query parameter name."));
        }
        if r.query.iter().any(|(k, _)| k == key) && !["priority", "tag_id"].contains(&key) {
            return Err(Error::invalid(
                "Duplicate query parameter conflicts with command options.",
            ));
        }
        r.query.push((key.into(), value.into()));
    }
    if r.body
        .as_ref()
        .is_some_and(|b| b.to_string().len() > INPUT_LIMIT)
    {
        return Err(Error::invalid("JSON input exceeds 1 MiB."));
    }
    Ok(r)
}

fn require_name(r: &Request, revision: bool) -> Result<()> {
    if !revision
        && !r
            .body
            .as_ref()
            .and_then(|b| b.get("name"))
            .is_some_and(|v| v.as_str().is_some_and(|s| !s.is_empty()))
    {
        return Err(Error::invalid("Add requires a name."));
    }
    Ok(())
}

pub fn preview(r: &Request) -> Value {
    let fields: Map<String, Value> = r
        .body
        .as_ref()
        .and_then(Value::as_object)
        .map(|body| {
            body.iter()
                .map(|(k, v)| {
                    (
                        k.clone(),
                        json!(match v {
                            Value::Null => "null",
                            Value::Bool(_) => "boolean",
                            Value::Number(_) => "number",
                            Value::String(_) => "string",
                            Value::Array(_) => "array",
                            Value::Object(_) => "object",
                        }),
                    )
                })
                .collect()
        })
        .unwrap_or_default();
    let revision = r
        .body
        .as_ref()
        .and_then(|b| b.get("expected_revision"))
        .and_then(Value::as_u64)
        .filter(|value| *value > 0);
    json!({"data":{"method":r.method,"path":r.path,"query_keys":r.query.iter().map(|(k,_)|k).collect::<Vec<_>>(),"body_fields":fields,"revision":revision,"idempotency_key":r.key}})
}

pub fn discover(scope: &[String]) -> Result<Value> {
    let mut root = Cli::command();
    root.build();
    let mut command = &root;
    for name in scope {
        command = command
            .find_subcommand(name)
            .ok_or_else(|| Error::invalid("Unknown discovery scope."))?;
    }
    let commands: Vec<Value> = command
        .get_subcommands()
        .map(|c| json!({"name":c.get_name(),"description":c.get_about().map(ToString::to_string)}))
        .collect();
    let options:Vec<Value>=command.get_arguments().filter(|a| !a.is_hide_set()).map(|a|json!({"name":a.get_id().as_str(),"long":a.get_long(),"required":a.is_required_set(),"description":a.get_help().map(ToString::to_string),"values":a.get_possible_values().iter().map(|v|v.get_name()).collect::<Vec<_>>()})).collect();
    Ok(
        json!({"data":{"name":command.get_name(),"description":command.get_about().map(ToString::to_string),"commands":commands,"options":options}}),
    )
}

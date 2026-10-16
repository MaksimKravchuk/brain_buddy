#![cfg(feature = "live")]
//! Black-box conformance for projects, Tags, Smart Add, task detail, subtasks,
//! comments, edits with stale revisions, transitions, creation and the filtered
//! list (CAP-HTTP-121..142; 027-FR-001, 027-FR-003, 027-FR-008, 027-SC-003).
//!
//! Seeds only through the test control API and the public routes. Every test
//! names its capability ids, so the run report lists each CAP id it proves.

use bb_conformance::{Client, Config, Owner, Reply, TestControl, case};
use reqwest::Method;
use serde_json::{Value, json};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

struct Env {
    ctl: TestControl,
    anon: Client,
}

fn env() -> Env {
    let cfg = Config::from_env().expect("BB_CONFORMANCE_BASE_URL is set");
    Env {
        ctl: TestControl::new(&cfg).expect("test control client"),
        anon: Client::new(&cfg).expect("anonymous client"),
    }
}

/// Process-unique token for synthetic identities, keys and ids.
fn unique() -> String {
    static N: AtomicU64 = AtomicU64::new(0);
    let t = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos());
    format!("{t:x}{:x}", N.fetch_add(1, Ordering::Relaxed))
}

/// A new synthetic owner, signed up through an invite minted by the test
/// control API. The address uses `example.com`: the server rejects reserved
/// domains such as `.invalid`.
async fn owner(e: &Env) -> Owner {
    let invite = e.ctl.invites(1).await.expect("invite minted");
    let code = invite["codes"][0]
        .as_str()
        .expect("invite code")
        .to_string();
    let email = format!("owner-{}@example.com", unique());
    let mut client = e.anon.fresh();
    let reply = client
        .post(
            "/api/auth/signup",
            &json!({
                "email": email,
                "password": "Conformance-pass-1!",
                "invite_code": code,
            }),
        )
        .await
        .expect("signup request");
    assert_eq!(reply.status, 201, "signup: {}", reply.body);
    Owner { email, client }
}

async fn read(c: &Client, path: &str) -> Reply {
    let mut c = c.clone();
    c.send(Method::GET, path, None).await.expect("GET request")
}

/// A write with a fresh `Idempotency-Key`, the contract for every mutation.
async fn write(c: &Client, method: Method, path: &str, body: Option<Value>) -> Reply {
    let mut c = c
        .clone()
        .with_header("Idempotency-Key", &format!("conf-{}", unique()));
    c.send(method, path, body.as_ref())
        .await
        .expect("write request")
}

async fn post(c: &Client, path: &str, body: Value) -> Reply {
    write(c, Method::POST, path, Some(body)).await
}

async fn patch(c: &Client, path: &str, body: Value) -> Reply {
    write(c, Method::PATCH, path, Some(body)).await
}

fn expect_status(r: &Reply, status: u16) -> Value {
    assert_eq!(r.status, status, "unexpected status, body: {}", r.body);
    r.json().expect("JSON body")
}

fn id_of(v: &Value) -> String {
    v["id"].as_str().expect("id in body").to_string()
}

async fn new_project(c: &Client, name: &str) -> Value {
    expect_status(
        &post(c, "/api/projects", json!({ "name": name })).await,
        201,
    )
}

async fn new_tag(c: &Client, name: &str) -> Value {
    expect_status(&post(c, "/api/tags", json!({ "name": name })).await, 201)
}

async fn new_task(c: &Client, body: Value) -> Value {
    expect_status(&post(c, "/api/tasks", body).await, 201)
}

async fn new_subtask(c: &Client, task_id: &str, title: &str) -> Value {
    let path = format!("/api/tasks/{task_id}/subtasks");
    expect_status(&post(c, &path, json!({ "title": title })).await, 201)
}

async fn new_comment(c: &Client, task_id: &str, body: &str) -> Value {
    let path = format!("/api/tasks/{task_id}/comments");
    expect_status(&post(c, &path, json!({ "body": body })).await, 201)
}

/// The error envelope with the id replaced by a placeholder and the per-request
/// `reference_id` removed, so a foreign id and a missing id can be compared.
fn envelope(r: &Reply, id: &str) -> Value {
    let mut v: Value = serde_json::from_str(&r.body.replace(id, "<id>")).expect("JSON body");
    if let Some(map) = v.as_object_mut() {
        map.remove("reference_id");
    }
    v
}

/// Owner scope (027-FR-008): a foreign id answers exactly like a missing id.
fn assert_hidden(foreign: &Reply, foreign_id: &str, missing: &Reply, missing_id: &str) {
    assert_eq!(foreign.status, 404, "foreign id: {}", foreign.body);
    assert_eq!(missing.status, 404, "missing id: {}", missing.body);
    assert_eq!(
        envelope(foreign, foreign_id),
        envelope(missing, missing_id),
        "foreign id must be indistinguishable from a missing id"
    );
}

#[tokio::test]
async fn cap_http_121_create_project_returns_201_and_requires_key() {
    case(
        &["CAP-HTTP-121"],
        "cap_http_121_create_project_returns_201_and_requires_key",
        async {
            let e = env();
            let o = owner(&e).await;
            let v = expect_status(
                &post(
                    &o.client,
                    "/api/projects",
                    json!({ "name": "Home", "color": "blue", "desired_outcome": "Ship" }),
                )
                .await,
                201,
            );
            assert_eq!(v["name"], "Home");
            assert_eq!(v["state"], "active");
            assert_eq!(v["revision"], 1);
            assert_eq!(v["desired_outcome"], "Ship");

            let mut keyless = o.client.clone();
            let r = keyless
                .send(Method::POST, "/api/projects", Some(&json!({ "name": "x" })))
                .await
                .expect("POST request");
            assert_eq!(r.status, 400, "no Idempotency-Key: {}", r.body);
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_122_list_projects_includes_open_task_counts() {
    case(
        &["CAP-HTTP-122"],
        "cap_http_122_list_projects_includes_open_task_counts",
        async {
            let e = env();
            let o = owner(&e).await;
            let p = new_project(&o.client, "Counted").await;
            let pid = id_of(&p);
            new_task(&o.client, json!({ "title": "Open one", "project_id": pid })).await;
            new_task(&o.client, json!({ "title": "Open two", "project_id": pid })).await;

            let r = read(&o.client, "/api/projects?state=active").await;
            let items = expect_status(&r, 200);
            let found = items
                .as_array()
                .expect("list")
                .iter()
                .find(|item| item["id"] == pid)
                .expect("project listed");
            assert_eq!(found["open_task_count"], 2);
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_123_patch_project_bumps_revision_and_hides_foreign_ids() {
    case(
        &["CAP-HTTP-123"],
        "cap_http_123_patch_project_bumps_revision_and_hides_foreign_ids",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let pid = id_of(&new_project(&o.client, "Before").await);

            let v = expect_status(
                &patch(
                    &o.client,
                    &format!("/api/projects/{pid}"),
                    json!({ "name": "After", "expected_revision": 1 }),
                )
                .await,
                200,
            );
            assert_eq!(v["name"], "After");
            assert_eq!(v["revision"], 2);

            let stale = patch(
                &o.client,
                &format!("/api/projects/{pid}"),
                json!({ "name": "Stale", "expected_revision": 1 }),
            )
            .await;
            assert_eq!(stale.status, 409, "{}", stale.body);
            assert_eq!(stale.json().expect("json")["detail"]["resource"], "Project");

            let foreign = patch(
                &other.client,
                &format!("/api/projects/{pid}"),
                json!({ "name": "Hijack", "expected_revision": 2 }),
            )
            .await;
            let missing = patch(
                &other.client,
                "/api/projects/missing-project",
                json!({ "name": "Hijack", "expected_revision": 2 }),
            )
            .await;
            assert_hidden(&foreign, &pid, &missing, "missing-project");
            let still = expect_status(&read(&o.client, &format!("/api/projects/{pid}")).await, 200);
            assert_eq!(still["name"], "After");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_124_archive_project_sets_archived_state() {
    case(
        &["CAP-HTTP-124"],
        "cap_http_124_archive_project_sets_archived_state",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let pid = id_of(&new_project(&o.client, "To archive").await);

            let v = expect_status(
                &post(
                    &o.client,
                    &format!("/api/projects/{pid}/archive"),
                    json!({ "expected_revision": 1 }),
                )
                .await,
                200,
            );
            assert_eq!(v["state"], "archived");
            assert_eq!(v["revision"], 2);
            assert!(v["archived_at"].is_string(), "archived_at set: {v}");

            let stale = post(
                &o.client,
                &format!("/api/projects/{pid}/archive"),
                json!({ "expected_revision": 1 }),
            )
            .await;
            assert_eq!(stale.status, 409, "{}", stale.body);

            let foreign = post(
                &other.client,
                &format!("/api/projects/{pid}/archive"),
                json!({ "expected_revision": 2 }),
            )
            .await;
            let missing = post(
                &other.client,
                "/api/projects/missing-project/archive",
                json!({ "expected_revision": 2 }),
            )
            .await;
            assert_hidden(&foreign, &pid, &missing, "missing-project");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_125_unarchive_project_restores_active_state() {
    case(
        &["CAP-HTTP-125"],
        "cap_http_125_unarchive_project_restores_active_state",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let pid = id_of(&new_project(&o.client, "Round trip").await);
            expect_status(
                &post(
                    &o.client,
                    &format!("/api/projects/{pid}/archive"),
                    json!({ "expected_revision": 1 }),
                )
                .await,
                200,
            );

            let v = expect_status(
                &post(
                    &o.client,
                    &format!("/api/projects/{pid}/unarchive"),
                    json!({ "expected_revision": 2 }),
                )
                .await,
                200,
            );
            assert_eq!(v["state"], "active");
            assert_eq!(v["revision"], 3);
            assert!(v["archived_at"].is_null(), "archived_at cleared: {v}");

            let foreign = post(
                &other.client,
                &format!("/api/projects/{pid}/unarchive"),
                json!({ "expected_revision": 3 }),
            )
            .await;
            let missing = post(
                &other.client,
                "/api/projects/missing-project/unarchive",
                json!({ "expected_revision": 3 }),
            )
            .await;
            assert_hidden(&foreign, &pid, &missing, "missing-project");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_126_get_project_returns_detail_and_hides_foreign_ids() {
    case(
        &["CAP-HTTP-126"],
        "cap_http_126_get_project_returns_detail_and_hides_foreign_ids",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let pid = id_of(&new_project(&o.client, "Detail").await);

            let v = expect_status(&read(&o.client, &format!("/api/projects/{pid}")).await, 200);
            assert_eq!(v["id"], pid);
            assert_eq!(v["name"], "Detail");
            assert_eq!(v["revision"], 1);

            let foreign = read(&other.client, &format!("/api/projects/{pid}")).await;
            let missing = read(&other.client, "/api/projects/missing-project").await;
            assert_hidden(&foreign, &pid, &missing, "missing-project");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_127_create_tag_returns_201_and_rejects_duplicates() {
    case(
        &["CAP-HTTP-127"],
        "cap_http_127_create_tag_returns_201_and_rejects_duplicates",
        async {
            let e = env();
            let o = owner(&e).await;
            let v = expect_status(
                &post(&o.client, "/api/tags", json!({ "name": "Errand" })).await,
                201,
            );
            assert_eq!(v["name"], "Errand");
            assert_eq!(v["state"], "active");
            assert_eq!(v["revision"], 1);

            let dup = post(&o.client, "/api/tags", json!({ "name": "Errand" })).await;
            assert_eq!(dup.status, 409, "{}", dup.body);
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_128_list_tags_includes_open_task_counts() {
    case(
        &["CAP-HTTP-128"],
        "cap_http_128_list_tags_includes_open_task_counts",
        async {
            let e = env();
            let o = owner(&e).await;
            let tid = id_of(&new_tag(&o.client, "Phone").await);
            new_task(&o.client, json!({ "title": "Call", "tag_ids": [tid] })).await;

            let items = expect_status(&read(&o.client, "/api/tags").await, 200);
            let found = items
                .as_array()
                .expect("list")
                .iter()
                .find(|item| item["id"] == tid)
                .expect("tag listed");
            assert_eq!(found["name"], "Phone");
            assert_eq!(found["open_task_count"], 1);
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_129_patch_tag_renames_and_hides_foreign_ids() {
    case(
        &["CAP-HTTP-129"],
        "cap_http_129_patch_tag_renames_and_hides_foreign_ids",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid = id_of(&new_tag(&o.client, "Old").await);

            let v = expect_status(
                &patch(
                    &o.client,
                    &format!("/api/tags/{tid}"),
                    json!({ "name": "New", "expected_revision": 1 }),
                )
                .await,
                200,
            );
            assert_eq!(v["name"], "New");
            assert_eq!(v["revision"], 2);

            let stale = patch(
                &o.client,
                &format!("/api/tags/{tid}"),
                json!({ "name": "Stale", "expected_revision": 1 }),
            )
            .await;
            assert_eq!(stale.status, 409, "{}", stale.body);
            assert_eq!(stale.json().expect("json")["detail"]["resource"], "Tag");

            let foreign = patch(
                &other.client,
                &format!("/api/tags/{tid}"),
                json!({ "name": "Hijack", "expected_revision": 2 }),
            )
            .await;
            let missing = patch(
                &other.client,
                "/api/tags/missing-tag",
                json!({ "name": "Hijack", "expected_revision": 2 }),
            )
            .await;
            assert_hidden(&foreign, &tid, &missing, "missing-tag");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_130_delete_tag_answers_200_with_body() {
    case(
        &["CAP-HTTP-130"],
        "cap_http_130_delete_tag_answers_200_with_body",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid = id_of(&new_tag(&o.client, "Gone").await);

            let r = write(
                &o.client,
                Method::DELETE,
                &format!("/api/tags/{tid}?expected_revision=1"),
                None,
            )
            .await;
            let v = expect_status(&r, 200);
            assert_eq!(v["state"], "deleted");
            assert_eq!(v["revision"], 2);

            let stale = write(
                &o.client,
                Method::DELETE,
                &format!("/api/tags/{tid}?expected_revision=1"),
                None,
            )
            .await;
            assert_eq!(stale.status, 409, "{}", stale.body);

            let foreign = write(
                &other.client,
                Method::DELETE,
                &format!("/api/tags/{tid}?expected_revision=2"),
                None,
            )
            .await;
            let missing = write(
                &other.client,
                Method::DELETE,
                "/api/tags/missing-tag?expected_revision=2",
                None,
            )
            .await;
            assert_hidden(&foreign, &tid, &missing, "missing-tag");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_131_get_tag_returns_detail_and_hides_foreign_ids() {
    case(
        &["CAP-HTTP-131"],
        "cap_http_131_get_tag_returns_detail_and_hides_foreign_ids",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid = id_of(&new_tag(&o.client, "Detail tag").await);

            let v = expect_status(&read(&o.client, &format!("/api/tags/{tid}")).await, 200);
            assert_eq!(v["id"], tid);
            assert_eq!(v["name"], "Detail tag");

            let foreign = read(&other.client, &format!("/api/tags/{tid}")).await;
            let missing = read(&other.client, "/api/tags/missing-tag").await;
            assert_hidden(&foreign, &tid, &missing, "missing-tag");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_132_smart_add_creates_task_with_inline_refs() {
    case(
        &["CAP-HTTP-132"],
        "cap_http_132_smart_add_creates_task_with_inline_refs",
        async {
            let e = env();
            let o = owner(&e).await;
            let v = expect_status(
                &post(
                    &o.client,
                    "/api/tasks/smart-add",
                    json!({
                        "title": "Call mum",
                        "project": { "name": "Family" },
                        "tags": [{ "name": "Phone" }],
                    }),
                )
                .await,
                201,
            );
            assert_eq!(v["task"]["title"], "Call mum");
            assert_eq!(v["task"]["state"], "inbox");
            assert_eq!(v["project"]["name"], "Family");
            assert_eq!(v["tags"][0]["name"], "Phone");
            assert_eq!(v["created"]["project_id"], v["project"]["id"]);

            let keyless = o
                .client
                .clone()
                .send(
                    Method::POST,
                    "/api/tasks/smart-add",
                    Some(&json!({ "title": "x" })),
                )
                .await
                .expect("POST request");
            assert_eq!(keyless.status, 400, "no Idempotency-Key: {}", keyless.body);

            let both = post(
                &o.client,
                "/api/tasks/smart-add",
                json!({ "title": "x", "project": { "id": "p", "name": "p" } }),
            )
            .await;
            assert_eq!(both.status, 422, "{}", both.body);
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_133_get_task_returns_subtasks_and_comments() {
    case(
        &["CAP-HTTP-133"],
        "cap_http_133_get_task_returns_subtasks_and_comments",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid = id_of(&new_task(&o.client, json!({ "title": "Detail" })).await);
            new_subtask(&o.client, &tid, "Step").await;
            new_comment(&o.client, &tid, "A note").await;

            let v = expect_status(&read(&o.client, &format!("/api/tasks/{tid}")).await, 200);
            assert_eq!(v["id"], tid);
            assert_eq!(v["subtasks"][0]["title"], "Step");
            assert_eq!(v["comments"][0]["body"], "A note");

            let foreign = read(&other.client, &format!("/api/tasks/{tid}")).await;
            let missing = read(&other.client, "/api/tasks/missing-task").await;
            assert_hidden(&foreign, &tid, &missing, "missing-task");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_134_create_subtask_returns_201_and_hides_foreign_tasks() {
    case(
        &["CAP-HTTP-134"],
        "cap_http_134_create_subtask_returns_201_and_hides_foreign_tasks",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid = id_of(&new_task(&o.client, json!({ "title": "Parent" })).await);

            let v = new_subtask(&o.client, &tid, "Child").await;
            assert_eq!(v["title"], "Child");
            assert_eq!(v["state"], "open");
            assert_eq!(v["revision"], 1);

            let path = format!("/api/tasks/{tid}/subtasks");
            let foreign = post(&other.client, &path, json!({ "title": "Intrude" })).await;
            let missing = post(
                &other.client,
                "/api/tasks/missing-task/subtasks",
                json!({ "title": "Intrude" }),
            )
            .await;
            assert_hidden(&foreign, &tid, &missing, "missing-task");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_135_patch_subtask_renames_and_rejects_stale_revision() {
    case(
        &["CAP-HTTP-135"],
        "cap_http_135_patch_subtask_renames_and_rejects_stale_revision",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid = id_of(&new_task(&o.client, json!({ "title": "Parent" })).await);
            let sid = id_of(&new_subtask(&o.client, &tid, "Old").await);
            let path = format!("/api/tasks/{tid}/subtasks/{sid}");

            let v = expect_status(
                &patch(
                    &o.client,
                    &path,
                    json!({ "title": "New", "expected_revision": 1 }),
                )
                .await,
                200,
            );
            assert_eq!(v["title"], "New");
            assert_eq!(v["revision"], 2);

            let stale = patch(
                &o.client,
                &path,
                json!({ "title": "Stale", "expected_revision": 1 }),
            )
            .await;
            assert_eq!(stale.status, 409, "{}", stale.body);

            let foreign = patch(
                &other.client,
                &path,
                json!({ "title": "Hijack", "expected_revision": 2 }),
            )
            .await;
            assert_eq!(foreign.status, 404, "foreign subtask: {}", foreign.body);
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_136_subtask_transitions_complete_and_reopen() {
    case(
        &["CAP-HTTP-136"],
        "cap_http_136_subtask_transitions_complete_and_reopen",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid = id_of(&new_task(&o.client, json!({ "title": "Parent" })).await);
            let sid = id_of(&new_subtask(&o.client, &tid, "Step").await);
            let path = format!("/api/tasks/{tid}/subtasks/{sid}/transitions");

            let done = expect_status(
                &post(
                    &o.client,
                    &path,
                    json!({ "action": "complete", "expected_revision": 1 }),
                )
                .await,
                200,
            );
            assert_eq!(done["state"], "completed");
            assert_eq!(done["revision"], 2);

            let reopened = expect_status(
                &post(
                    &o.client,
                    &path,
                    json!({ "action": "reopen", "expected_revision": 2 }),
                )
                .await,
                200,
            );
            assert_eq!(reopened["state"], "open");

            let foreign = post(
                &other.client,
                &path,
                json!({ "action": "complete", "expected_revision": 3 }),
            )
            .await;
            assert_eq!(foreign.status, 404, "foreign subtask: {}", foreign.body);
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_137_create_comment_returns_201_and_hides_foreign_tasks() {
    case(
        &["CAP-HTTP-137"],
        "cap_http_137_create_comment_returns_201_and_hides_foreign_tasks",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid = id_of(&new_task(&o.client, json!({ "title": "Discuss" })).await);

            let v = new_comment(&o.client, &tid, "First thought").await;
            assert_eq!(v["body"], "First thought");
            assert_eq!(v["revision"], 1);
            assert!(v["edited_at"].is_null(), "not edited yet: {v}");

            let path = format!("/api/tasks/{tid}/comments");
            let foreign = post(&other.client, &path, json!({ "body": "Intrude" })).await;
            let missing = post(
                &other.client,
                "/api/tasks/missing-task/comments",
                json!({ "body": "Intrude" }),
            )
            .await;
            assert_hidden(&foreign, &tid, &missing, "missing-task");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_138_patch_comment_sets_edited_at_and_rejects_stale_revision() {
    case(
        &["CAP-HTTP-138"],
        "cap_http_138_patch_comment_sets_edited_at_and_rejects_stale_revision",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid = id_of(&new_task(&o.client, json!({ "title": "Discuss" })).await);
            let cid = id_of(&new_comment(&o.client, &tid, "Draft").await);
            let path = format!("/api/tasks/{tid}/comments/{cid}");

            let v = expect_status(
                &patch(
                    &o.client,
                    &path,
                    json!({ "body": "Final", "expected_revision": 1 }),
                )
                .await,
                200,
            );
            assert_eq!(v["body"], "Final");
            assert_eq!(v["revision"], 2);
            assert!(v["edited_at"].is_string(), "edited_at set: {v}");

            let stale = patch(
                &o.client,
                &path,
                json!({ "body": "Stale", "expected_revision": 1 }),
            )
            .await;
            assert_eq!(stale.status, 409, "{}", stale.body);
            assert_eq!(stale.json().expect("json")["detail"]["resource"], "Comment");

            let foreign = patch(
                &other.client,
                &path,
                json!({ "body": "Hijack", "expected_revision": 2 }),
            )
            .await;
            assert_eq!(foreign.status, 404, "foreign comment: {}", foreign.body);
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_139_patch_task_edits_fields_and_rejects_stale_revision() {
    case(
        &["CAP-HTTP-139"],
        "cap_http_139_patch_task_edits_fields_and_rejects_stale_revision",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid = id_of(&new_task(&o.client, json!({ "title": "Before" })).await);
            let path = format!("/api/tasks/{tid}");

            let v = expect_status(
                &patch(
                    &o.client,
                    &path,
                    json!({ "title": "After", "expected_revision": 1 }),
                )
                .await,
                200,
            );
            assert_eq!(v["title"], "After");
            assert_eq!(v["revision"], 2);

            let stale = patch(
                &o.client,
                &path,
                json!({ "title": "Stale", "expected_revision": 1 }),
            )
            .await;
            assert_eq!(stale.status, 409, "{}", stale.body);
            let detail = stale.json().expect("json");
            assert_eq!(detail["detail"]["resource"], "Task");
            assert_eq!(detail["detail"]["id"], tid);

            let foreign = patch(
                &other.client,
                &path,
                json!({ "title": "Hijack", "expected_revision": 2 }),
            )
            .await;
            let missing = patch(
                &other.client,
                "/api/tasks/missing-task",
                json!({ "title": "Hijack", "expected_revision": 2 }),
            )
            .await;
            assert_hidden(&foreign, &tid, &missing, "missing-task");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_140_task_transitions_complete_and_reject_stale_revision() {
    case(
        &["CAP-HTTP-140"],
        "cap_http_140_task_transitions_complete_and_reject_stale_revision",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let tid =
                id_of(&new_task(&o.client, json!({ "title": "Finish me", "state": "next" })).await);
            let path = format!("/api/tasks/{tid}/transitions");

            let done = expect_status(
                &post(
                    &o.client,
                    &path,
                    json!({ "action": "complete", "expected_revision": 1 }),
                )
                .await,
                200,
            );
            assert_eq!(done["state"], "completed");
            assert!(done["completed_at"].is_string(), "completed_at set: {done}");
            assert_eq!(done["revision"], 2);

            let stale = post(
                &o.client,
                &path,
                json!({ "action": "reopen", "expected_revision": 1 }),
            )
            .await;
            assert_eq!(stale.status, 409, "{}", stale.body);

            let foreign = post(
                &other.client,
                &path,
                json!({ "action": "reopen", "expected_revision": 2 }),
            )
            .await;
            let missing = post(
                &other.client,
                "/api/tasks/missing-task/transitions",
                json!({ "action": "reopen", "expected_revision": 2 }),
            )
            .await;
            assert_hidden(&foreign, &tid, &missing, "missing-task");
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_141_create_task_returns_201_and_hides_foreign_projects() {
    case(
        &["CAP-HTTP-141"],
        "cap_http_141_create_task_returns_201_and_hides_foreign_projects",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let pid = id_of(&new_project(&o.client, "Owned").await);
            let tid = id_of(&new_tag(&o.client, "Owned tag").await);

            let v = expect_status(
                &post(
                    &o.client,
                    "/api/tasks",
                    json!({
                        "title": "Plan trip",
                        "state": "next",
                        "project_id": pid,
                        "tag_ids": [tid],
                        "due_date": "2026-11-01",
                    }),
                )
                .await,
                201,
            );
            assert_eq!(v["title"], "Plan trip");
            assert_eq!(v["state"], "next");
            assert_eq!(v["project_id"], pid);
            assert_eq!(v["tag_ids"][0], tid);
            assert_eq!(v["revision"], 1);

            let defaults = expect_status(
                &post(&o.client, "/api/tasks", json!({ "title": "Plain" })).await,
                201,
            );
            assert_eq!(defaults["state"], "inbox");
            assert!(
                defaults.get("priority").is_none(),
                "no priority field: {defaults}"
            );

            let foreign = post(
                &other.client,
                "/api/tasks",
                json!({ "title": "Borrow", "project_id": pid }),
            )
            .await;
            assert_eq!(foreign.status, 404, "foreign project: {}", foreign.body);
        },
    )
    .await;
}

#[tokio::test]
async fn cap_http_142_list_tasks_filters_pages_and_scopes_to_owner() {
    case(
        &["CAP-HTTP-142"],
        "cap_http_142_list_tasks_filters_pages_and_scopes_to_owner",
        async {
            let e = env();
            let o = owner(&e).await;
            let other = owner(&e).await;
            let pid = id_of(&new_project(&o.client, "Listed").await);
            let tag = id_of(&new_tag(&o.client, "Listed tag").await);
            for title in ["Alpha", "Beta", "Gamma"] {
                new_task(
                    &o.client,
                    json!({ "title": title, "project_id": pid, "tag_ids": [tag] }),
                )
                .await;
            }
            let done = new_task(&o.client, json!({ "title": "Finished", "project_id": pid })).await;
            expect_status(
                &post(
                    &o.client,
                    &format!("/api/tasks/{}/transitions", id_of(&done)),
                    json!({ "action": "complete", "expected_revision": 1 }),
                )
                .await,
                200,
            );

            let page1 = expect_status(
                &read(
                    &o.client,
                    &format!("/api/tasks?project_id={pid}&sort=title&limit=2"),
                )
                .await,
                200,
            );
            assert_eq!(page1["items"].as_array().map(Vec::len), Some(2));
            assert_eq!(page1["has_more"], true);
            let cursor = page1["next_cursor"]
                .as_str()
                .expect("next_cursor")
                .to_string();
            let page2 = expect_status(
                &read(
                    &o.client,
                    &format!("/api/tasks?project_id={pid}&sort=title&limit=2&cursor={cursor}"),
                )
                .await,
                200,
            );
            assert_eq!(page2["items"].as_array().map(Vec::len), Some(1));
            assert_eq!(page2["has_more"], false);
            assert!(
                page1["counts_by_state"]["inbox"].is_number(),
                "counts present: {page1}"
            );

            let with_done = expect_status(
                &read(
                    &o.client,
                    &format!("/api/tasks?project_id={pid}&include_completed=true&limit=200"),
                )
                .await,
                200,
            );
            assert_eq!(with_done["items"].as_array().map(Vec::len), Some(4));

            let by_tag = expect_status(
                &read(&o.client, &format!("/api/tasks?tag_id={tag}")).await,
                200,
            );
            assert_eq!(by_tag["items"].as_array().map(Vec::len), Some(3));

            let by_query = expect_status(&read(&o.client, "/api/tasks?q=Gamma").await, 200);
            assert_eq!(by_query["items"].as_array().map(Vec::len), Some(1));

            let foreign_view = expect_status(&read(&other.client, "/api/tasks").await, 200);
            assert_eq!(foreign_view["items"].as_array().map(Vec::len), Some(0));

            let bad_limit = read(&o.client, "/api/tasks?limit=0").await;
            assert_eq!(bad_limit.status, 422, "{}", bad_limit.body);
            let bad_state = read(&o.client, "/api/tasks?state=bogus").await;
            assert_eq!(bad_state.status, 422, "{}", bad_state.body);
        },
    )
    .await;
}

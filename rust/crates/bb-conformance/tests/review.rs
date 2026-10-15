#![cfg(feature = "live")]
//! Conformance for the weekly review routes (contracts/capability-inventory.md
//! §1.10 and §5): CAP-HTTP-150..156, CAP-HTTP-161..167 and CAP-MW-009.
//!
//! Each test encodes what the frozen Python server does today (027-FR-001,
//! 027_FR_003). Owner scope is probed with a second synthetic owner: a foreign
//! id answers the same 404 as a missing one (027_FR_008). Seeding goes through
//! the test control API (aged tasks, the `weekly_review` flag, the clock);
//! ordinary product writes use the public routes. Run with
//! `BB_CONFORMANCE_BASE_URL` and `BRAIN_BUDDY_TEST_CONTROL_TOKEN` set.

use bb_conformance::{Client, Config, Owner, Reply, TestControl, case};
use reqwest::Method;
use serde_json::{Value, json};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::Mutex;

/// The `weekly_review` flag is process-global on the server, so every test
/// holds this lock while it runs and sets the flag it needs first.
static FLAG_LOCK: Mutex<()> = Mutex::const_new(());

const FLAG: &str = "weekly_review";
const PASSWORD: &str = "Conformance-pass-1!";

fn env() -> (Config, TestControl) {
    let cfg = Config::from_env().expect("BB_CONFORMANCE_BASE_URL is set");
    let tc = TestControl::new(&cfg).expect("test control client");
    (cfg, tc)
}

/// A lowercase RFC 4122-shaped id: unique within and across test processes.
fn uuid() -> String {
    static N: AtomicU64 = AtomicU64::new(1);
    let n = N.fetch_add(1, Ordering::Relaxed);
    let t = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_nanos()) as u64;
    let b = n ^ (u64::from(std::process::id()) << 40);
    let mix = t ^ b.rotate_left(17);
    format!(
        "{:08x}-{:04x}-4{:03x}-a{:03x}-{:012x}",
        (t >> 32) as u32,
        (t >> 16) & 0xffff,
        t & 0xfff,
        b & 0xfff,
        mix & 0xffff_ffff_ffff
    )
}

/// A synthetic owner: invite, then signup. The domain is one the server's
/// email validator accepts (`.invalid` is a reserved name it refuses).
async fn owner(cfg: &Config, tc: &TestControl) -> Owner {
    let mut client = Client::new(cfg).expect("client");
    let invites = tc.invites(1).await.expect("invite");
    let code = invites["codes"][0]
        .as_str()
        .expect("invite code")
        .to_owned();
    let email = format!("review-{}@synthetic.example", uuid());
    let body = json!({ "email": email, "password": PASSWORD, "invite_code": code });
    let reply = client
        .post("/api/auth/signup", &body)
        .await
        .expect("signup");
    assert_eq!(reply.status, 201, "signup: {}", reply.body);
    Owner { email, client }
}

/// An owner who has acknowledged the explainer, so the review is activated.
async fn activated(cfg: &Config, tc: &TestControl) -> Owner {
    set_flag(tc, "on").await;
    let me = owner(cfg, tc).await;
    let reply = call(
        &me,
        Method::POST,
        "/api/review/explainer/acknowledge",
        Some(json!({ "time_zone": "UTC" })),
    )
    .await;
    assert_eq!(reply.status, 200, "explainer: {}", reply.body);
    me
}

async fn set_flag(tc: &TestControl, mode: &str) {
    tc.flag(FLAG, mode, &[]).await.expect("flag");
}

/// One request as `owner`; writes carry a fresh `Idempotency-Key`.
async fn call(owner: &Owner, method: Method, path: &str, body: Option<Value>) -> Reply {
    let mut client = owner.client.clone();
    if method != Method::GET {
        client = client.with_header("Idempotency-Key", &format!("cap-{}", uuid()));
    }
    client
        .send(method, path, body.as_ref())
        .await
        .expect("request")
}

fn parsed(reply: &Reply) -> Value {
    reply
        .json()
        .unwrap_or_else(|e| panic!("json body ({e}): {}", reply.body))
}

async fn task(owner: &Owner, title: &str) -> Value {
    let reply = call(
        owner,
        Method::POST,
        "/api/tasks",
        Some(json!({ "title": title })),
    )
    .await;
    assert_eq!(reply.status, 201, "create task: {}", reply.body);
    parsed(&reply)
}

/// A Next task whose formulation is 30 days old, seeded through test control.
async fn aged_task(tc: &TestControl, owner: &Owner) -> (String, Value) {
    let seeded = tc.aged_task(&owner.email, 30).await.expect("aged task");
    let id = seeded["task_id"].as_str().expect("task id").to_owned();
    let reply = call(owner, Method::GET, &format!("/api/tasks/{id}"), None).await;
    assert_eq!(reply.status, 200, "get aged task: {}", reply.body);
    (id, parsed(&reply))
}

async fn state(owner: &Owner) -> Value {
    let reply = call(owner, Method::GET, "/api/review/state", None).await;
    assert_eq!(reply.status, 200, "review state: {}", reply.body);
    parsed(&reply)
}

async fn start_session(owner: &Owner) -> String {
    let reply = call(
        owner,
        Method::POST,
        "/api/review/sessions",
        Some(json!({
            "mode": "quick",
            "entry": "list",
            "origin": "web",
            "skip_steps": [],
            "replace_open": false
        })),
    )
    .await;
    assert_eq!(reply.status, 201, "start session: {}", reply.body);
    parsed(&reply)["id"]
        .as_str()
        .expect("session id")
        .to_owned()
}

/// The same refusal a missing id gets: 404 naming the resource.
fn assert_not_found(reply: &Reply, resource: &str) {
    assert_eq!(reply.status, 404, "{}", reply.body);
    assert_eq!(
        parsed(reply)["detail"]["resource"],
        resource,
        "{}",
        reply.body
    );
}

/// The flag-off refusal of a gated read (dependencies.py `require_weekly_review_enabled`).
fn assert_gated(reply: &Reply) {
    assert_eq!(reply.status, 404, "{}", reply.body);
    assert_eq!(
        parsed(reply)["detail"]["reason"],
        "weekly_review_disabled",
        "{}",
        reply.body
    );
}

// --------------------------------------------------------------- CAP-HTTP-150
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_150_decision_card_choice() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-HTTP-150"],
        "cap_http_150_decision_card_choice",
        async move {
            let (cfg, tc) = env();
            let me = activated(&cfg, &tc).await;
            let created = task(&me, "Renovate the bathroom").await;
            let id = created["id"].as_str().expect("id").to_owned();
            let path = format!("/api/tasks/{id}/decisions");

            let reply = call(
                &me,
                Method::POST,
                &path,
                Some(json!({ "type": "complete", "expected_revision": 1 })),
            )
            .await;
            assert_eq!(reply.status, 200, "{}", reply.body);
            let decided = parsed(&reply);
            assert!(
                decided["decision"]["id"]
                    .as_str()
                    .is_some_and(|d| d.starts_with("decision_"))
            );
            assert_eq!(decided["decision"]["type"], "complete");
            assert_eq!(decided["decision"]["task_id"], id.as_str());
            assert_eq!(decided["task"]["state"], "completed");
            assert_eq!(decided["task"]["revision"], 2);

            let stranger = owner(&cfg, &tc).await;
            let foreign = call(
                &stranger,
                Method::POST,
                &path,
                Some(json!({ "type": "complete", "expected_revision": 2 })),
            )
            .await;
            assert_not_found(&foreign, "Task");
            let missing = call(
                &stranger,
                Method::POST,
                &format!("/api/tasks/task_{}/decisions", uuid()),
                Some(json!({ "type": "complete", "expected_revision": 1 })),
            )
            .await;
            assert_not_found(&missing, "Task");
        },
    )
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-151
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_151_undo_decision() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-HTTP-151"],
        "cap_http_151_undo_decision",
        async move {
            let (cfg, tc) = env();
            let me = activated(&cfg, &tc).await;
            let created = task(&me, "File the receipts").await;
            let id = created["id"].as_str().expect("id").to_owned();
            let decided = call(
                &me,
                Method::POST,
                &format!("/api/tasks/{id}/decisions"),
                Some(json!({ "type": "complete", "expected_revision": 1 })),
            )
            .await;
            assert_eq!(decided.status, 200, "{}", decided.body);
            let decided = parsed(&decided);
            let decision_id = decided["decision"]["id"]
                .as_str()
                .expect("decision")
                .to_owned();
            let revision = decided["task"]["revision"].as_u64().expect("revision");

            let undo = call(
                &me,
                Method::POST,
                &format!("/api/review/decisions/{decision_id}/undo"),
                Some(json!({ "expected_task_revision": revision })),
            )
            .await;
            assert_eq!(undo.status, 200, "{}", undo.body);
            let undone = parsed(&undo);
            assert_eq!(undone["undone_decision_id"], decision_id.as_str());
            assert_eq!(undone["task"]["state"], "inbox");

            let stranger = owner(&cfg, &tc).await;
            let foreign = call(
                &stranger,
                Method::POST,
                &format!("/api/review/decisions/{decision_id}/undo"),
                Some(json!({ "expected_task_revision": revision })),
            )
            .await;
            assert_not_found(&foreign, "Review decision");
            let missing = call(
                &stranger,
                Method::POST,
                &format!("/api/review/decisions/decision_{}/undo", uuid()),
                Some(json!({ "expected_task_revision": revision })),
            )
            .await;
            assert_not_found(&missing, "Review decision");
        },
    )
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-152
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_152_auto_park() {
    let _flag = FLAG_LOCK.lock().await;
    case(&["CAP-HTTP-152"], "cap_http_152_auto_park", async move {
        let (cfg, tc) = env();
        let me = activated(&cfg, &tc).await;
        let (id, aged) = aged_task(&tc, &me).await;
        let formulation = aged["formulation"]["id"]
            .as_str()
            .expect("formulation")
            .to_owned();
        let path = format!("/api/tasks/{id}/auto-park");

        let parked = call(
            &me,
            Method::POST,
            &path,
            Some(json!({ "formulation_id": formulation })),
        )
        .await;
        assert_eq!(parked.status, 200, "{}", parked.body);
        let parked = parsed(&parked);
        assert_eq!(parked["applied"], true);
        assert_eq!(parked["task"]["state"], "someday");
        assert_eq!(
            parked["task"]["parked"]["formulation_id"],
            formulation.as_str()
        );

        let stranger = owner(&cfg, &tc).await;
        let (other_id, _) = aged_task(&tc, &me).await;
        let foreign = call(
            &stranger,
            Method::POST,
            &format!("/api/tasks/{other_id}/auto-park"),
            Some(json!({ "formulation_id": formulation })),
        )
        .await;
        assert_not_found(&foreign, "Task");

        // With weekly_review off the route is ungated but parks nothing.
        set_flag(&tc, "off").await;
        let (quiet_id, quiet) = aged_task(&tc, &me).await;
        let quiet_form = quiet["formulation"]["id"]
            .as_str()
            .expect("formulation")
            .to_owned();
        let refused = call(
            &me,
            Method::POST,
            &format!("/api/tasks/{quiet_id}/auto-park"),
            Some(json!({ "formulation_id": quiet_form })),
        )
        .await;
        assert_eq!(refused.status, 200, "{}", refused.body);
        let refused = parsed(&refused);
        assert_eq!(refused["applied"], false);
        assert_eq!(refused["task"]["state"], "next");
        set_flag(&tc, "on").await;
    })
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-153
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_153_acknowledge_parks() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-HTTP-153"],
        "cap_http_153_acknowledge_parks",
        async move {
            let (cfg, tc) = env();
            let me = activated(&cfg, &tc).await;
            let (id, aged) = aged_task(&tc, &me).await;
            let formulation = aged["formulation"]["id"]
                .as_str()
                .expect("formulation")
                .to_owned();
            let parked = call(
                &me,
                Method::POST,
                &format!("/api/tasks/{id}/auto-park"),
                Some(json!({ "formulation_id": formulation })),
            )
            .await;
            assert_eq!(parked.status, 200, "{}", parked.body);

            let before = state(&me).await;
            let parks = before["unseen_parks"].as_array().expect("unseen parks");
            assert_eq!(parks.len(), 1);
            assert_eq!(parks[0]["task_id"], id.as_str());

            let ack = call(
                &me,
                Method::POST,
                "/api/review/parks/acknowledge",
                Some(json!({
                    "items": [{ "task_id": id, "formulation_id": formulation }]
                })),
            )
            .await;
            assert_eq!(ack.status, 204, "{}", ack.body);
            assert!(ack.body.is_empty());

            let after = state(&me).await;
            assert_eq!(after["unseen_parks"], json!([]));
        },
    )
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-154
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_154_review_settings() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-HTTP-154"],
        "cap_http_154_review_settings",
        async move {
            let (cfg, tc) = env();
            let me = activated(&cfg, &tc).await;
            let revision = state(&me).await["settings"]["revision"]
                .as_u64()
                .expect("revision");

            let saved = call(
                &me,
                Method::PUT,
                "/api/review/settings",
                Some(json!({ "threshold_days": 21, "expected_revision": revision })),
            )
            .await;
            assert_eq!(saved.status, 200, "{}", saved.body);
            let saved = parsed(&saved);
            assert_eq!(saved["threshold_days"], 21);
            assert_eq!(saved["revision"], revision + 1);

            let stale = call(
                &me,
                Method::PUT,
                "/api/review/settings",
                Some(json!({ "threshold_days": 7, "expected_revision": revision })),
            )
            .await;
            assert_eq!(stale.status, 409, "{}", stale.body);
            assert_eq!(parsed(&stale)["detail"]["resource"], "Review settings");

            // Settings are per owner: a second owner keeps the default threshold.
            let stranger = activated(&cfg, &tc).await;
            let theirs = state(&stranger).await;
            assert_eq!(theirs["settings"]["threshold_days"], 14);
        },
    )
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-155
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_155_explainer_acknowledge() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-HTTP-155"],
        "cap_http_155_explainer_acknowledge",
        async move {
            let (cfg, tc) = env();
            set_flag(&tc, "on").await;
            let me = owner(&cfg, &tc).await;
            let before = state(&me).await;
            assert_eq!(before["explainer_seen"], false);
            assert!(before["settings"]["activated_at"].is_null());

            let acked = call(
                &me,
                Method::POST,
                "/api/review/explainer/acknowledge",
                Some(json!({ "time_zone": "Europe/Berlin" })),
            )
            .await;
            assert_eq!(acked.status, 200, "{}", acked.body);
            let acked = parsed(&acked);
            assert_eq!(acked["explainer_seen"], true);
            assert!(acked["settings"]["activated_at"].is_string());
            assert_eq!(acked["settings"]["time_zone"], "Europe/Berlin");

            let mut anonymous = Client::new(&cfg).expect("client");
            let refused = anonymous
                .send(
                    Method::POST,
                    "/api/review/explainer/acknowledge",
                    Some(&json!({ "time_zone": "UTC" })),
                )
                .await
                .expect("request");
            assert_eq!(refused.status, 401, "{}", refused.body);
        },
    )
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-156
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_156_review_state() {
    let _flag = FLAG_LOCK.lock().await;
    case(&["CAP-HTTP-156"], "cap_http_156_review_state", async move {
        let (cfg, tc) = env();
        let me = activated(&cfg, &tc).await;
        let view = state(&me).await;
        assert_eq!(view["explainer_seen"], true);
        assert!(view["unseen_parks"].is_array());
        assert!(view["counts"]["asks_for_decision"].is_u64());
        assert!(view["next_review_at"].is_string());

        set_flag(&tc, "off").await;
        let gated = call(&me, Method::GET, "/api/review/state", None).await;
        assert_gated(&gated);
        set_flag(&tc, "on").await;

        let mut anonymous = Client::new(&cfg).expect("client");
        let refused = anonymous
            .send(Method::GET, "/api/review/state", None)
            .await
            .expect("request");
        assert_eq!(refused.status, 401, "{}", refused.body);
    })
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-161
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_161_start_session() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-HTTP-161"],
        "cap_http_161_start_session",
        async move {
            let (cfg, tc) = env();
            let me = activated(&cfg, &tc).await;
            let session = call(
                &me,
                Method::POST,
                "/api/review/sessions",
                Some(json!({
                    "mode": "quick",
                    "entry": "list",
                    "origin": "web",
                    "skip_steps": [],
                    "replace_open": false
                })),
            )
            .await;
            assert_eq!(session.status, 201, "{}", session.body);
            let session = parsed(&session);
            let id = session["id"].as_str().expect("session id").to_owned();
            assert!(id.starts_with("review_"));
            assert_eq!(session["status"], "open");
            assert_eq!(session["mode"], "quick");

            let second = call(
                &me,
                Method::POST,
                "/api/review/sessions",
                Some(json!({
                    "mode": "full",
                    "entry": "list",
                    "origin": "web",
                    "skip_steps": [],
                    "replace_open": false
                })),
            )
            .await;
            assert_eq!(second.status, 409, "{}", second.body);
            let second = parsed(&second);
            assert_eq!(second["detail"]["reason"], "open_session_exists");
            assert_eq!(second["detail"]["session_id"], id.as_str());

            // Starting is not gated: a device's queued review starts with the flag off.
            let late = owner(&cfg, &tc).await;
            set_flag(&tc, "off").await;
            let ungated = call(
                &late,
                Method::POST,
                "/api/review/sessions",
                Some(json!({
                    "mode": "quick",
                    "entry": "list",
                    "origin": "web",
                    "skip_steps": [],
                    "replace_open": false
                })),
            )
            .await;
            assert_eq!(ungated.status, 201, "{}", ungated.body);
            set_flag(&tc, "on").await;
        },
    )
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-162
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_162_get_session() {
    let _flag = FLAG_LOCK.lock().await;
    case(&["CAP-HTTP-162"], "cap_http_162_get_session", async move {
        let (cfg, tc) = env();
        let me = activated(&cfg, &tc).await;
        let id = start_session(&me).await;
        let path = format!("/api/review/sessions/{id}");

        let got = call(&me, Method::GET, &path, None).await;
        assert_eq!(got.status, 200, "{}", got.body);
        assert_eq!(parsed(&got)["id"], id.as_str());

        let stranger = owner(&cfg, &tc).await;
        let foreign = call(&stranger, Method::GET, &path, None).await;
        assert_not_found(&foreign, "Review session");
        let missing = call(
            &stranger,
            Method::GET,
            &format!("/api/review/sessions/review_{}", uuid()),
            None,
        )
        .await;
        assert_not_found(&missing, "Review session");

        set_flag(&tc, "off").await;
        let gated = call(&me, Method::GET, &path, None).await;
        assert_gated(&gated);
        set_flag(&tc, "on").await;
    })
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-163
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_163_progress_session() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-HTTP-163"],
        "cap_http_163_progress_session",
        async move {
            let (cfg, tc) = env();
            let me = activated(&cfg, &tc).await;
            let id = start_session(&me).await;
            let path = format!("/api/review/sessions/{id}");
            let body = json!({
                "progress_id": format!("progress_{}", uuid()),
                "current_step": "inbox"
            });

            let moved = call(&me, Method::PATCH, &path, Some(body.clone())).await;
            assert_eq!(moved.status, 200, "{}", moved.body);
            let moved = parsed(&moved);
            assert_eq!(moved["current_step"], "inbox");
            assert_eq!(moved["revision"], 2);

            // The same progress_id replays the stored result, not a second change.
            let replay = call(&me, Method::PATCH, &path, Some(body)).await;
            assert_eq!(replay.status, 200, "{}", replay.body);
            assert_eq!(parsed(&replay)["revision"], 2);

            let stranger = owner(&cfg, &tc).await;
            let foreign = call(
                &stranger,
                Method::PATCH,
                &path,
                Some(json!({
                    "progress_id": format!("progress_{}", uuid()),
                    "current_step": "inbox"
                })),
            )
            .await;
            assert_not_found(&foreign, "Review session");
        },
    )
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-164
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_164_finish_session() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-HTTP-164"],
        "cap_http_164_finish_session",
        async move {
            let (cfg, tc) = env();
            let me = activated(&cfg, &tc).await;
            let id = start_session(&me).await;
            let path = format!("/api/review/sessions/{id}/finish");

            let finished = call(&me, Method::POST, &path, Some(json!({}))).await;
            assert_eq!(finished.status, 200, "{}", finished.body);
            let finished = parsed(&finished);
            assert_eq!(finished["status"], "completed_empty");
            assert!(finished["ended_at"].is_string());
            let revision = finished["revision"].clone();

            // Finishing again is idempotent: the same summary, no new revision.
            let again = call(&me, Method::POST, &path, Some(json!({}))).await;
            assert_eq!(again.status, 200, "{}", again.body);
            assert_eq!(parsed(&again)["revision"], revision);

            let stranger = owner(&cfg, &tc).await;
            let foreign = call(
                &stranger,
                Method::POST,
                &format!("/api/review/sessions/{id}/finish"),
                Some(json!({})),
            )
            .await;
            assert_not_found(&foreign, "Review session");
        },
    )
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-165
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_165_review_queues() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-HTTP-165"],
        "cap_http_165_review_queues",
        async move {
            let (cfg, tc) = env();
            let me = activated(&cfg, &tc).await;
            let created = task(&me, "Queue probe").await;
            let id = created["id"].as_str().expect("id").to_owned();

            let inbox = call(&me, Method::GET, "/api/review/queues/inbox", None).await;
            assert_eq!(inbox.status, 200, "{}", inbox.body);
            let inbox = parsed(&inbox);
            let ids: Vec<&str> = inbox["items"]
                .as_array()
                .expect("items")
                .iter()
                .filter_map(|item| item["id"].as_str())
                .collect();
            assert!(ids.contains(&id.as_str()));
            assert!(inbox["meta"].as_object().is_some_and(|m| m.is_empty()));

            let wins = call(&me, Method::GET, "/api/review/queues/wins", None).await;
            assert_eq!(wins.status, 200, "{}", wins.body);
            assert!(parsed(&wins)["meta"]["count"].is_u64());

            // An owner's queue never lists another owner's tasks.
            let stranger = owner(&cfg, &tc).await;
            let theirs = call(&stranger, Method::GET, "/api/review/queues/inbox", None).await;
            assert_eq!(theirs.status, 200, "{}", theirs.body);
            let theirs = parsed(&theirs);
            let leaked = theirs["items"]
                .as_array()
                .expect("items")
                .iter()
                .any(|item| item["id"] == id.as_str());
            assert!(!leaked);

            set_flag(&tc, "off").await;
            let gated = call(&me, Method::GET, "/api/review/queues/inbox", None).await;
            assert_gated(&gated);
            set_flag(&tc, "on").await;
        },
    )
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-166
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_166_bulk_release() {
    let _flag = FLAG_LOCK.lock().await;
    case(&["CAP-HTTP-166"], "cap_http_166_bulk_release", async move {
        let (cfg, tc) = env();
        let me = activated(&cfg, &tc).await;
        let (fresh, _) = aged_task(&tc, &me).await;
        let (stale, _) = aged_task(&tc, &me).await;

        // A partial result is still 200: one released, one stale and skipped.
        let release = call(
            &me,
            Method::POST,
            "/api/review/bulk-releases",
            Some(json!({
                "id": format!("bulk_{}", uuid()),
                "kind": "restart",
                "items": [
                    { "task_id": fresh, "expected_revision": 1 },
                    { "task_id": stale, "expected_revision": 99 }
                ]
            })),
        )
        .await;
        assert_eq!(release.status, 200, "{}", release.body);
        let release = parsed(&release);
        assert!(
            release["id"]
                .as_str()
                .is_some_and(|i| i.starts_with("bulk_"))
        );
        let released = release["released"].as_array().expect("released");
        assert_eq!(released.len(), 1);
        assert_eq!(released[0]["task_id"], fresh.as_str());
        assert_eq!(released[0]["revision_after"], 2);
        let skipped = release["skipped"].as_array().expect("skipped");
        assert_eq!(skipped.len(), 1);
        assert_eq!(skipped[0]["task_id"], stale.as_str());
        assert_eq!(skipped[0]["reason"], "stale");
    })
    .await;
}

// --------------------------------------------------------------- CAP-HTTP-167
/// 027_FR_001 027_FR_003 027_FR_008
#[tokio::test]
async fn cap_http_167_undo_bulk_release() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-HTTP-167"],
        "cap_http_167_undo_bulk_release",
        async move {
            let (cfg, tc) = env();
            let me = activated(&cfg, &tc).await;
            let (task_id, _) = aged_task(&tc, &me).await;
            let bulk_id = format!("bulk_{}", uuid());
            let release = call(
                &me,
                Method::POST,
                "/api/review/bulk-releases",
                Some(json!({
                    "id": bulk_id,
                    "kind": "restart",
                    "items": [{ "task_id": task_id, "expected_revision": 1 }]
                })),
            )
            .await;
            assert_eq!(release.status, 200, "{}", release.body);
            assert_eq!(
                parsed(&release)["released"].as_array().map(Vec::len),
                Some(1)
            );

            let path = format!("/api/review/bulk-releases/{bulk_id}/undo");
            let undone = call(&me, Method::POST, &path, Some(json!({}))).await;
            assert_eq!(undone.status, 200, "{}", undone.body);
            let undone = parsed(&undone);
            assert_eq!(undone["restored"], json!([task_id]));
            assert_eq!(undone["skipped"], json!([]));

            // An already undone release answers its stored result.
            let again = call(&me, Method::POST, &path, Some(json!({}))).await;
            assert_eq!(again.status, 200, "{}", again.body);
            assert_eq!(parsed(&again)["restored"], json!([task_id]));

            let stranger = owner(&cfg, &tc).await;
            let foreign = call(&stranger, Method::POST, &path, Some(json!({}))).await;
            assert_not_found(&foreign, "Review bulk release");
            let missing = call(
                &stranger,
                Method::POST,
                &format!("/api/review/bulk-releases/bulk_{}/undo", uuid()),
                Some(json!({})),
            )
            .await;
            assert_not_found(&missing, "Review bulk release");
        },
    )
    .await;
}

// -------------------------------------------------------------- CAP-MW-009
/// Review refusals render `{message, detail:{reason}, reference_id}` and echo
/// the correlation id (027_FR_001 027_FR_003).
#[tokio::test]
async fn cap_mw_009_review_error_envelope() {
    let _flag = FLAG_LOCK.lock().await;
    case(
        &["CAP-MW-009"],
        "cap_mw_009_review_error_envelope",
        async move {
            let (cfg, tc) = env();
            let me = activated(&cfg, &tc).await;
            let created = task(&me, "Envelope probe").await;
            let id = created["id"].as_str().expect("id").to_owned();

            // keep_someday is allowed only on a someday task: an inbox task refuses it.
            let correlation = format!("cap-mw-009-{}", uuid());
            let mut traced = me
                .client
                .clone()
                .with_header("X-Correlation-ID", &correlation)
                .with_header("Idempotency-Key", &format!("cap-{}", uuid()));
            let refused = traced
                .send(
                    Method::POST,
                    &format!("/api/tasks/{id}/decisions"),
                    Some(&json!({ "type": "keep_someday", "expected_revision": 1 })),
                )
                .await
                .expect("request");
            assert_eq!(refused.status, 400, "{}", refused.body);
            assert_eq!(
                refused.header("x-correlation-id"),
                Some(correlation.as_str())
            );
            let envelope = parsed(&refused);
            assert_eq!(envelope["detail"]["reason"], "decision_not_allowed");
            assert!(envelope["message"].is_string());
            assert_eq!(envelope["reference_id"], correlation.as_str());

            // The settings refusal has the same envelope.
            let revision = state(&me).await["settings"]["revision"]
                .as_u64()
                .expect("revision");
            let zone = call(
                &me,
                Method::PUT,
                "/api/review/settings",
                Some(json!({ "time_zone": "Not/AZone", "expected_revision": revision })),
            )
            .await;
            assert_eq!(zone.status, 400, "{}", zone.body);
            assert_eq!(parsed(&zone)["detail"]["reason"], "invalid_time_zone");
        },
    )
    .await;
}

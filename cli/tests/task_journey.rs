mod common;
use serde_json::Value;
use std::{
    io::{BufRead, BufReader},
    process::{Child, Command, Stdio},
};

struct Backend(Child);
impl Drop for Backend {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

#[test]
#[ignore = "Requires installed real backend; required Linux integration job runs explicitly"]
fn real_capture_replay_search_edit_conflict_complete_024_fr_001_024_fr_005_024_fr_006_024_fr_012_024_sc_001_024_sc_003()
 {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap();
    let python = std::env::var("BB_TEST_BACKEND_PYTHON")
        .expect("Set BB_TEST_BACKEND_PYTHON to the backend virtualenv interpreter");
    let dir = tempfile::tempdir().unwrap();
    let mut backend = Backend(
        Command::new(python)
            .arg(root.join("cli/tests/backend_fixture.py"))
            .current_dir(root.join("backend"))
            .env("PYTHONPATH", root.join("backend"))
            .env("BRAIN_BUDDY_DATA_DIR", dir.path().join("data"))
            .env("BRAIN_BUDDY_ENV", "test")
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap(),
    );
    let mut line = String::new();
    BufReader::new(backend.0.stdout.take().unwrap())
        .read_line(&mut line)
        .unwrap();
    let context: Value =
        serde_json::from_str(&line).expect("Backend fixture must start successfully");
    let invoke = |args: &[&str], exit: i32| {
        let output = Command::new(common::binary())
            .args(args)
            .env("BB_SERVER", context["server"].as_str().unwrap())
            .env("BB_SESSION_TOKEN", context["token"].as_str().unwrap())
            .env("BB_CONFIG_DIR", dir.path().join("config"))
            .output()
            .unwrap();
        assert_eq!(
            output.status.code(),
            Some(exit),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        serde_json::from_slice::<Value>(if exit == 0 {
            &output.stdout
        } else {
            &output.stderr
        })
        .unwrap()
    };
    let schema = invoke(&["schema", "POST", "/tasks"], 0);
    assert_eq!(schema["data"]["path"], "/tasks");
    assert_eq!(schema["data"]["method"], "POST");
    assert!(schema["data"]["schemas"].get("TaskCreateRequest").is_some());
    let created = invoke(
        &[
            "task",
            "add",
            "--title",
            "CLI fixture capture",
            "--key",
            "fixture-capture",
        ],
        0,
    );
    let id = created["data"]["id"].as_str().unwrap();
    let replay = invoke(
        &[
            "task",
            "add",
            "--title",
            "CLI fixture capture",
            "--key",
            "fixture-capture",
        ],
        0,
    );
    assert_eq!(replay["data"]["id"], id);
    let found = invoke(&["task", "list", "--q", "CLI fixture capture"], 0);
    assert_eq!(found["data"].as_array().unwrap().len(), 1);
    let revision = created["data"]["revision"].to_string();
    let edited = invoke(
        &[
            "task",
            "update",
            id,
            "--title",
            "CLI fixture edited",
            "--revision",
            &revision,
            "--key",
            "fixture-edit",
        ],
        0,
    );
    let conflict = invoke(
        &[
            "task",
            "update",
            id,
            "--title",
            "Stale overwrite",
            "--revision",
            &revision,
            "--key",
            "fixture-stale",
        ],
        6,
    );
    assert_eq!(conflict["error"]["code"], "conflict");
    let revision = edited["data"]["revision"].to_string();
    let done = invoke(
        &[
            "task",
            "transition",
            id,
            "complete",
            "--revision",
            &revision,
            "--key",
            "fixture-complete",
        ],
        0,
    );
    assert_eq!(done["data"]["state"], "completed");
    let read = invoke(&["task", "get", id], 0);
    assert_eq!(read["data"]["title"], "CLI fixture edited");
    assert_eq!(read["data"]["state"], "completed");
}

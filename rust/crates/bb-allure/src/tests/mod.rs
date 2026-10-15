use super::*;

fn temp_dir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("bb-allure-{tag}-{}", uuid()));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

#[test]
fn writes_result_the_taxonomy_validator_accepts_027_fr_001() {
    let dir = temp_dir("ok");
    let mut t = Recorder::new(
        "Rust server",
        "Allure",
        "Writer",
        "Writer emits taxonomy",
        "m",
    );
    t.step("do work \"quoted\"", || ());
    t.write_to(&dir, true).unwrap();
    let script =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../scripts/validate_allure_taxonomy.py");
    let Ok(out) = std::process::Command::new("python3")
        .arg(script)
        .args(["--label", "rust", "--path"])
        .arg(&dir)
        .output()
    else {
        return; // python3 absent: the CI taxonomy job validates instead
    };
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
}

#[test]
fn failing_step_is_recorded_and_reraised_027_sc_003() {
    let dir = temp_dir("fail");
    let mut t = Recorder::new("e", "f", "s", "Failing run", "m");
    let caught = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        t.step("boom", || panic!("x"));
    }));
    assert!(caught.is_err());
    let text = std::fs::read_to_string(t.write_to(&dir, false).unwrap()).unwrap();
    assert!(text.contains("\"status\":\"failed\""));
}

//! Run report keyed by capability id: `target/conformance/<server>.json`.
//!
//! Shape: `{"server", "results": {CAP: {"status": "passed"|"failed", "tests": [..]}}}`.

use crate::{Config, Result, control::unique};
use serde_json::{Map, Value, json};
use std::{future::Future, path::PathBuf};

pub struct Report {
    server: String,
    results: Map<String, Value>,
}

impl Report {
    pub fn new(server: &str) -> Self {
        let results = Map::new();
        Self {
            server: server.into(),
            results,
        }
    }

    pub fn path(server: &str) -> PathBuf {
        let target = std::env::var_os("CARGO_TARGET_DIR").unwrap_or_else(|| "target".into());
        PathBuf::from(target)
            .join("conformance")
            .join(format!("{server}.json"))
    }

    /// Tags `test` with each capability id and its outcome.
    pub fn record(&mut self, caps: &[&str], test: &str, passed: bool) {
        for cap in caps {
            let new = json!({"status": "passed", "tests": []});
            let entry = self.results.entry(cap.to_string()).or_insert(new);
            if !passed {
                entry["status"] = json!("failed");
            }
            if let Some(tests) = entry["tests"].as_array_mut()
                && !tests.iter().any(|t| t == test)
            {
                tests.push(json!(test));
            }
        }
    }

    pub fn to_json(&self) -> Value {
        json!({ "server": self.server, "results": self.results })
    }

    /// Merges into the existing report (several test binaries share one file).
    pub fn write(&self) -> Result<PathBuf> {
        let path = Self::path(&self.server);
        let mut merged = Report::new(&self.server);
        if let Ok(old) = std::fs::read_to_string(&path)
            && let Ok(Value::Object(prev)) =
                serde_json::from_str::<Value>(&old).map(|v| v["results"].clone())
        {
            merged.results = prev;
        }
        for (cap, v) in &self.results {
            let tests = v["tests"].as_array().into_iter().flatten();
            for t in tests.filter_map(Value::as_str) {
                merged.record(&[cap], t, v["status"] == "passed");
            }
        }
        std::fs::create_dir_all(path.parent().unwrap_or(&path))?;
        std::fs::write(&path, serde_json::to_string_pretty(&merged.to_json())?)?;
        Ok(path)
    }
}

/// Collects seeded user text and fails the run when a server log line holds it.
#[derive(Default)]
pub struct LogCollector {
    seeds: Vec<String>,
}

impl LogCollector {
    /// A unique synthetic string for a test to submit as user content.
    pub fn seed(&mut self) -> String {
        self.seeds.push(format!("seedtext-{}", unique()));
        self.seeds[self.seeds.len() - 1].clone()
    }

    /// Scans log text; the error names line numbers only, never the line.
    pub fn check(&self, log: &str) -> Result<()> {
        let hits: Vec<usize> = (1..)
            .zip(log.lines())
            .filter(|(_, l)| self.seeds.iter().any(|s| l.contains(s.as_str())))
            .map(|(i, _)| i)
            .collect();
        if hits.is_empty() {
            return Ok(());
        }
        Err(format!("seeded user text found in server log lines {hits:?}").into())
    }

    /// Scans the log file named by `BB_CONFORMANCE_SERVER_LOG`, if set.
    pub fn check_env_file(&self) -> Result<()> {
        match std::env::var_os("BB_CONFORMANCE_SERVER_LOG") {
            Some(p) => self.check(&std::fs::read_to_string(p)?),
            None => Ok(()),
        }
    }
}

/// Runs `body`, records the outcome for every id in `caps` (report and
/// Allure story) and re-raises a failure so the test still fails.
pub async fn case<F: Future<Output = ()> + Send + 'static>(caps: &[&str], title: &str, body: F) {
    let story = format!("027-FR-001 {}", caps.join(" "));
    let mut t =
        bb_allure::Recorder::new("Rust server", "Conformance", &story, title, module_path!());
    let outcome = tokio::spawn(body).await;
    let passed = outcome.is_ok();
    let server = Config::from_env().map_or_else(|_| "python".into(), |c| c.server);
    let mut report = Report::new(&server);
    report.record(caps, title, passed);
    report.write().expect("write conformance report");
    let stepped = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        t.step(title, || {
            if let Err(e) = outcome {
                std::panic::resume_unwind(e.into_panic());
            }
        });
    }));
    t.write(passed).expect("write allure result");
    if let Err(panic) = stepped {
        std::panic::resume_unwind(panic);
    }
}

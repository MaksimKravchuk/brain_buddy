//! Dev-only Allure result writer for Rust tests.
//!
//! Writes `<uuid>-result.json` files that satisfy
//! `scripts/validate_allure_taxonomy.py` unchanged: non-empty `epic`,
//! `feature` and `story` labels, a human-readable `name` and at least one
//! named, non-zero-duration step. The directory comes from
//! `ALLURE_RESULTS_DIR` (default `allure-results`).

mod json;

use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::io;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use json::quote;

/// Environment variable naming the result directory.
pub const RESULTS_DIR_ENV: &str = "ALLURE_RESULTS_DIR";

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_millis())
}

fn uuid() -> String {
    let mut b = [0u8; 16];
    for chunk in b.chunks_mut(8) {
        let mut h = RandomState::new().build_hasher();
        h.write_u128(now_ms());
        chunk.copy_from_slice(&h.finish().to_le_bytes());
    }
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    let hex: String = b.iter().map(|x| format!("{x:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &hex[..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..]
    )
}

struct Step {
    name: String,
    passed: bool,
    start: u128,
    stop: u128,
}

/// Collects the taxonomy labels and steps of one test run.
pub struct Recorder {
    epic: String,
    feature: String,
    story: String,
    title: String,
    full_name: String,
    start: u128,
    steps: Vec<Step>,
}

fn status(ok: bool) -> &'static str {
    if ok { "passed" } else { "failed" }
}

fn label(name: &str, value: &str) -> String {
    format!("{{\"name\":{},\"value\":{}}}", quote(name), quote(value))
}

impl Recorder {
    pub fn new(epic: &str, feature: &str, story: &str, title: &str, full_name: &str) -> Self {
        Self {
            epic: epic.into(),
            feature: feature.into(),
            story: story.into(),
            title: title.into(),
            full_name: full_name.into(),
            start: now_ms(),
            steps: Vec::new(),
        }
    }

    /// Runs `body` as a named step; a panic marks the step failed and resumes.
    pub fn step<T>(&mut self, name: &str, body: impl FnOnce() -> T) -> T {
        let start = now_ms();
        let outcome = std::panic::catch_unwind(std::panic::AssertUnwindSafe(body));
        // The validator rejects zero-duration steps without evidence.
        let stop = now_ms().max(start + 1);
        self.steps.push(Step {
            name: name.into(),
            passed: outcome.is_ok(),
            start,
            stop,
        });
        match outcome {
            Ok(value) => value,
            Err(panic) => std::panic::resume_unwind(panic),
        }
    }

    /// Renders the Allure result JSON.
    pub fn render(&self, passed: bool) -> String {
        let labels = [
            label("epic", &self.epic),
            label("feature", &self.feature),
            label("story", &self.story),
            label("language", "rust"),
        ]
        .join(",");
        let steps: Vec<String> = self
            .steps
            .iter()
            .map(|s| {
                format!(
                    "{{\"name\":{},\"status\":\"{}\",\"stage\":\"finished\",\"start\":{},\"stop\":{}}}",
                    quote(&s.name),
                    status(s.passed),
                    s.start,
                    s.stop
                )
            })
            .collect();
        let stop = self.steps.last().map_or(self.start + 1, |s| s.stop);
        format!(
            "{{\"uuid\":{},\"name\":{},\"fullName\":{},\"status\":\"{}\",\"stage\":\"finished\",\"start\":{},\"stop\":{},\"labels\":[{}],\"steps\":[{}]}}",
            quote(&uuid()),
            quote(&self.title),
            quote(&self.full_name),
            status(passed),
            self.start,
            stop,
            labels,
            steps.join(",")
        )
    }

    /// Writes the result into `dir`, returning the file path.
    pub fn write_to(&self, dir: &Path, passed: bool) -> io::Result<PathBuf> {
        std::fs::create_dir_all(dir)?;
        let path = dir.join(format!("{}-result.json", uuid()));
        std::fs::write(&path, self.render(passed))?;
        Ok(path)
    }

    /// Writes the result into `ALLURE_RESULTS_DIR` (default `allure-results`).
    pub fn write(&self, passed: bool) -> io::Result<PathBuf> {
        let dir = std::env::var_os(RESULTS_DIR_ENV).unwrap_or_else(|| "allure-results".into());
        self.write_to(Path::new(&dir), passed)
    }
}

/// Runs a test body with a [`Recorder`], writes the result, then re-raises
/// any panic so the test still fails.
///
/// ```ignore
/// allure_test!("Rust server", "Health", "Liveness", "Health answers ok", |t| {
///     t.step("call the endpoint", || assert!(true));
/// });
/// ```
#[macro_export]
macro_rules! allure_test {
    ($epic:expr, $feature:expr, $story:expr, $title:expr, |$t:ident| $body:block) => {{
        let mut $t = $crate::Recorder::new($epic, $feature, $story, $title, module_path!());
        let outcome = ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(|| $body));
        $t.write(outcome.is_ok()).expect("write allure result");
        if let Err(panic) = outcome {
            ::std::panic::resume_unwind(panic);
        }
    }};
}

#[cfg(test)]
mod tests;

//! The inter-process migration lock.
//!
//! Ordinary writes need no lock of ours: SQLite's WAL write lock, taken by
//! `BEGIN IMMEDIATE`, serializes them across processes. A schema migration is
//! different, because a future one (the JSON import) spans more than one
//! SQLite transaction. It holds an exclusive `flock` on a sibling
//! `.<db>.migrate.lock` file; every open holds the same lock shared while it
//! reads the schema version, so no process opens a store mid-migration.
//!
//! `flock` belongs to the open file description, exactly like the existing
//! Swift `DocumentFile` lock: two handles in one process exclude each other
//! the way two processes do, and the kernel drops the lock when its holder
//! dies, so a crashed migrator never wedges the store.

use std::fs::{File, OpenOptions, TryLockError};
use std::io;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};
use std::thread::sleep;
use std::time::{Duration, Instant};

const POLL_INTERVAL: Duration = Duration::from_millis(5);

/// How a `MigrationLock` is held.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LockMode {
    /// Held while opening: excludes migrators, not other openers.
    Shared,
    /// Held while migrating: excludes everyone.
    Exclusive,
}

/// A held migration lock. Dropping it closes the file, which releases it.
#[derive(Debug)]
pub struct MigrationLock {
    _file: File,
}

impl MigrationLock {
    /// The lock file next to the database at `db`.
    pub fn path_for(db: &Path) -> PathBuf {
        let name = db
            .file_name()
            .map(|n| n.to_string_lossy())
            .unwrap_or_default();
        db.with_file_name(format!(".{name}.migrate.lock"))
    }

    /// Waits at most `timeout` for the lock. `Ok(None)` means the wait ran
    /// out; the caller reports a retryable busy store, never success.
    pub fn acquire(db: &Path, mode: LockMode, timeout: Duration) -> io::Result<Option<Self>> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .open(Self::path_for(db))?;
        let deadline = Instant::now() + timeout;
        loop {
            let attempt = match mode {
                LockMode::Shared => file.try_lock_shared(),
                LockMode::Exclusive => file.try_lock(),
            };
            match attempt {
                Ok(()) => return Ok(Some(Self { _file: file })),
                Err(TryLockError::WouldBlock) if Instant::now() < deadline => sleep(POLL_INTERVAL),
                Err(TryLockError::WouldBlock) => return Ok(None),
                Err(TryLockError::Error(error)) => return Err(error),
            }
        }
    }
}

use crate::error::{Error, Result};
use std::{
    fs::{self, OpenOptions},
    io::{Read, Write},
    path::Path,
};

fn unavailable() -> Error {
    Error::store("Protected configuration or credential file is unavailable.")
}

pub fn directory(path: &Path, create: bool) -> Result<()> {
    if create && !path.exists() {
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            let mut builder = fs::DirBuilder::new();
            builder.recursive(true).mode(0o700);
            builder.create(path).map_err(|_| unavailable())?;
        }
        #[cfg(not(unix))]
        fs::create_dir_all(path).map_err(|_| unavailable())?;
    }
    let metadata = fs::symlink_metadata(path).map_err(|_| unavailable())?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(unavailable());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.uid() != unsafe { libc::geteuid() } || metadata.mode() & 0o777 != 0o700 {
            return Err(unavailable());
        }
    }
    Ok(())
}

#[cfg(unix)]
fn options() -> OpenOptions {
    let mut options = OpenOptions::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
    }
    options
}

#[cfg(not(unix))]
fn options() -> OpenOptions {
    OpenOptions::new()
}

pub fn read(path: &Path, limit: usize) -> Result<Vec<u8>> {
    directory(path.parent().ok_or_else(unavailable)?, false)?;
    let mut file = options().read(true).open(path).map_err(|_| unavailable())?;
    let metadata = file.metadata().map_err(|_| unavailable())?;
    if !metadata.is_file() || metadata.len() > limit as u64 {
        return Err(unavailable());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.uid() != unsafe { libc::geteuid() } || metadata.mode() & 0o777 != 0o600 {
            return Err(unavailable());
        }
    }
    let mut bytes = Vec::new();
    Read::take(&mut file, (limit + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| unavailable())?;
    if bytes.len() > limit {
        return Err(unavailable());
    }
    Ok(bytes)
}

pub fn random_locator() -> Result<String> {
    let mut bytes = [0u8; 24];
    getrandom::fill(&mut bytes).map_err(|_| unavailable())?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}
pub fn valid_locator(locator: &str) -> Result<()> {
    if locator.len() != 48 || !locator.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(unavailable());
    }
    Ok(())
}

pub fn write(path: &Path, bytes: &[u8]) -> Result<()> {
    write_with_sync(path, bytes, |parent| {
        #[cfg(unix)]
        return fs::File::open(parent).and_then(|dir| dir.sync_all());
        #[cfg(not(unix))]
        {
            let _ = parent;
            Ok(())
        }
    })
}

fn write_with_sync(
    path: &Path,
    bytes: &[u8],
    sync: impl FnOnce(&Path) -> std::io::Result<()>,
) -> Result<()> {
    let parent = path.parent().ok_or_else(unavailable)?;
    directory(parent, true)?;
    if path.symlink_metadata().is_ok() {
        let _ = read(path, 65536)?;
    }
    let temp = parent.join(format!(".{}.tmp", random_locator()?));
    let result = (|| {
        let mut file = options()
            .write(true)
            .create_new(true)
            .open(&temp)
            .map_err(|_| unavailable())?;
        file.write_all(bytes).map_err(|_| unavailable())?;
        file.sync_all().map_err(|_| unavailable())?;
        fs::rename(&temp, path).map_err(|_| unavailable())?;
        sync(parent).map_err(|_| {
            let mut error = unavailable();
            error.detail = Some(Box::new(
                serde_json::json!({"write_committed":true,"durability_uncertain":true}),
            ));
            error
        })?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(temp);
    }
    result
}

pub struct Lock(std::path::PathBuf);

impl Lock {
    pub fn acquire(dir: &Path) -> Result<Self> {
        directory(dir, true)?;
        let path = dir.join("config.lock");
        options()
            .write(true)
            .create_new(true)
            .open(&path)
            .map_err(|_| {
                Error::store("Configuration is busy; inspect config.lock after a terminated login.")
            })?;
        Ok(Self(path))
    }
}
impl Drop for Lock {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn post_rename_sync_failure_keeps_committed_bytes_024_fr_013() {
        let dir = tempfile::tempdir().unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        let path = dir.path().join("config.json");
        let error = match super::write_with_sync(&path, b"new-config", |_| {
            Err(std::io::Error::other("Synthetic directory sync failure"))
        }) {
            Ok(_) => panic!("Expected uncertain durability"),
            Err(error) => error,
        };
        assert_eq!(std::fs::read(&path).unwrap(), b"new-config");
        assert_eq!(error.detail.as_ref().unwrap()["write_committed"], true);
        assert_eq!(error.detail.as_ref().unwrap()["durability_uncertain"], true);
    }
}

use crate::error::{Error, Result};
use std::{
    fs::{self, File, OpenOptions},
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
        #[cfg(unix)]
        File::open(parent)
            .and_then(|dir| dir.sync_all())
            .map_err(|_| unavailable())?;
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

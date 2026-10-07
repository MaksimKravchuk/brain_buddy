use crate::{
    config::Config,
    error::{Error, Result},
};
use std::env;
use zeroize::Zeroizing;

pub struct Credential {
    pub token: Zeroizing<String>,
    pub cookie_name: String,
    pub external: bool,
}
pub fn cookie_name(name: &str) -> Result<()> {
    if name.is_empty()
        || name.len() > 128
        || !name
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&b))
    {
        return Err(Error::invalid("Invalid session cookie name."));
    }
    Ok(())
}
pub fn token_value(token: &str) -> Result<()> {
    if token.is_empty()
        || token.len() > 4096
        || !token
            .bytes()
            .all(|b| matches!(b,0x21|0x23..=0x2b|0x2d..=0x3a|0x3c..=0x5b|0x5d..=0x7e))
    {
        return Err(Error::auth());
    }
    Ok(())
}
pub fn load(config: &Config) -> Result<Credential> {
    if let Ok(token) = env::var("BB_SESSION_TOKEN") {
        token_value(&token)?;
        let name =
            env::var("BB_SESSION_COOKIE_NAME").unwrap_or_else(|_| "brainbuddy_session".into());
        cookie_name(&name)?;
        return Ok(Credential {
            token: Zeroizing::new(token),
            cookie_name: name,
            external: true,
        });
    }
    let connection = config.connection.as_ref().ok_or_else(Error::auth)?;
    cookie_name(&connection.cookie_name)?;
    let token = read(config, &connection.store, &connection.locator)?;
    token_value(&token)?;
    Ok(Credential {
        token,
        cookie_name: connection.cookie_name.clone(),
        external: false,
    })
}

const SERVICE: &str = "BrainBuddy CLI";
fn entry(config: &Config, locator: &str) -> Result<keyring::Entry> {
    crate::storage::valid_locator(locator)?;
    keyring::Entry::new(
        SERVICE,
        &format!(
            "{}:{locator}",
            crate::config::namespace(&config.server, &config.api_prefix)
        ),
    )
    .map_err(|_| Error::store("Native credential store is unavailable."))
}

#[cfg(target_os = "linux")]
fn native_read(entry: &keyring::Entry) -> Result<Zeroizing<String>> {
    use dbus_secret_service::{EncryptionType, SecretService};
    let credential = entry
        .get_credential()
        .downcast_ref::<keyring::secret_service::SsCredential>()
        .ok_or_else(|| Error::store("Unexpected native credential adapter."))?;
    let service =
        SecretService::connect_with_max_prompt_timeout(EncryptionType::Dh, 0).map_err(|_| {
            Error::store("Secret Service is unavailable; business commands never unlock it.")
        })?;
    let attributes = credential
        .attributes
        .iter()
        .map(|(k, v)| (k.as_str(), v.as_str()))
        .collect();
    let items = service
        .search_items(attributes)
        .map_err(|_| Error::store("Cannot inspect the native credential."))?;
    if !items.locked.is_empty() || items.unlocked.len() != 1 {
        return Err(Error::store(
            "Credential is missing, locked or ambiguous; unlock your store explicitly.",
        ));
    }
    let item = &items.unlocked[0];
    if item
        .is_locked()
        .map_err(|_| Error::store("Cannot inspect native lock state."))?
    {
        return Err(Error::store("Credential is locked."));
    }
    let bytes = Zeroizing::new(
        item.get_secret()
            .map_err(|_| Error::store("Cannot read native credential without interaction."))?,
    );
    String::from_utf8(bytes.to_vec())
        .map(Zeroizing::new)
        .map_err(|_| Error::store("Native credential encoding is invalid."))
}

#[cfg(target_os = "macos")]
fn native_read(entry: &keyring::Entry) -> Result<Zeroizing<String>> {
    use security_framework::os::macos::keychain::SecKeychain;
    let _interaction = SecKeychain::disable_user_interaction()
        .map_err(|_| Error::store("Cannot disable Keychain interaction."))?;
    entry
        .get_password()
        .map(Zeroizing::new)
        .map_err(|_| Error::store("Keychain credential cannot be read without interaction."))
}

#[cfg(target_os = "windows")]
fn native_read(entry: &keyring::Entry) -> Result<Zeroizing<String>> {
    entry
        .get_password()
        .map(Zeroizing::new)
        .map_err(|_| Error::store("Credential Manager entry is unavailable."))
}

#[cfg(unix)]
fn file_path(config: &Config, locator: &str) -> Result<std::path::PathBuf> {
    crate::storage::valid_locator(locator)?;
    Ok(config.dir.join(format!("{locator}.credential")))
}
pub fn read(config: &Config, store: &str, locator: &str) -> Result<Zeroizing<String>> {
    match store {
        "native" => native_read(&entry(config, locator)?),
        #[cfg(unix)]
        "file" => String::from_utf8(crate::storage::read(&file_path(config, locator)?, 4096)?)
            .map(Zeroizing::new)
            .map_err(|_| Error::store("Credential file is invalid.")),
        _ => Err(Error::store(
            "This credential store is unsupported on this platform.",
        )),
    }
}
pub fn write(config: &Config, store: &str, locator: &str, token: &str) -> Result<()> {
    match store {
        "native" => entry(config, locator)?
            .set_password(token)
            .map_err(|_| Error::store("Cannot save native credential.")),
        #[cfg(unix)]
        "file" => crate::storage::write(&file_path(config, locator)?, token.as_bytes()),
        _ => Err(Error::store(
            "File credentials are unsupported on Windows; use Credential Manager.",
        )),
    }
}
pub fn remove(config: &Config, store: &str, locator: &str) -> Result<()> {
    match store {
        "native" => native_remove(&entry(config, locator)?),
        #[cfg(unix)]
        "file" => {
            let path = file_path(config, locator)?;
            if path
                .symlink_metadata()
                .is_err_and(|e| e.kind() == std::io::ErrorKind::NotFound)
            {
                return Ok(());
            }
            let _ = crate::storage::read(&path, 4096)?;
            std::fs::remove_file(path).map_err(|_| Error::store("Cannot remove credential file."))
        }
        _ => Err(Error::store("Unsupported credential store.")),
    }
}

fn native_remove(entry: &keyring::Entry) -> Result<()> {
    #[cfg(target_os = "linux")]
    {
        use dbus_secret_service::{EncryptionType, SecretService};
        let credential = entry
            .get_credential()
            .downcast_ref::<keyring::secret_service::SsCredential>()
            .ok_or_else(|| Error::store("Unexpected native credential adapter."))?;
        let service = SecretService::connect_with_max_prompt_timeout(EncryptionType::Dh, 0)
            .map_err(|_| Error::store("Secret Service is unavailable."))?;
        let attributes = credential
            .attributes
            .iter()
            .map(|(k, v)| (k.as_str(), v.as_str()))
            .collect();
        let items = service
            .search_items(attributes)
            .map_err(|_| Error::store("Cannot inspect native credential."))?;
        if !items.locked.is_empty() || items.unlocked.len() > 1 {
            return Err(Error::store("Native credential is locked or ambiguous."));
        }
        for item in items.unlocked {
            item.delete().map_err(|_| {
                Error::store("Cannot remove native credential without interaction.")
            })?;
        }
        Ok(())
    }
    #[cfg(not(target_os = "linux"))]
    {
        #[cfg(target_os = "macos")]
        let _interaction =
            security_framework::os::macos::keychain::SecKeychain::disable_user_interaction()
                .map_err(|_| Error::store("Cannot disable Keychain interaction."))?;
        match entry.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
            Err(_) => Err(Error::store(
                "Cannot remove native credential without interaction.",
            )),
        }
    }
}
pub fn preflight(config: &Config, store: &str) -> Result<()> {
    crate::storage::directory(&config.dir, true)?;
    let locator = crate::storage::random_locator()?;
    let probe = Zeroizing::new(crate::storage::random_locator()?);
    write(config, store, &locator, &probe)?;
    let result = read(config, store, &locator).and_then(|value| {
        if *value == *probe {
            Ok(())
        } else {
            Err(Error::store("Credential read-back failed."))
        }
    });
    let cleanup = remove(config, store, &locator);
    result.and(cleanup)
}

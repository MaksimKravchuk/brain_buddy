use crate::{
    command::{Cli, validate_path},
    error::{Error, Result},
};
use directories::ProjectDirs;
use reqwest::Url;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, env, net::IpAddr, path::PathBuf};

#[derive(Clone, Deserialize, Serialize)]
pub struct Connection {
    pub server: String,
    pub api_prefix: String,
    pub account_id: String,
    pub store: String,
    pub locator: String,
    pub cookie_name: String,
    pub expires_at: String,
}
#[derive(Clone, Default, Deserialize, Serialize)]
pub struct Saved {
    pub default: Option<String>,
    pub connections: BTreeMap<String, Connection>,
}
pub struct Config {
    pub server: String,
    pub api_prefix: String,
    pub dir: PathBuf,
    pub saved: Saved,
    pub connection: Option<Connection>,
}

pub fn canonical_server(server: &str) -> Result<String> {
    let url = Url::parse(server).map_err(|_| Error::invalid("Server must be an HTTPS origin."))?;
    let loopback = url.host_str().is_some_and(|h| {
        h == "localhost"
            || h.trim_matches(['[', ']'])
                .parse::<IpAddr>()
                .is_ok_and(|ip| ip.is_loopback())
    });
    if !(url.scheme() == "https" || (url.scheme() == "http" && loopback))
        || !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
        || url.path() != "/"
        || url.host_str().is_none()
    {
        return Err(Error::invalid(
            "Use an HTTPS server origin without credentials, path, query or fragment; HTTP is loopback-only.",
        ));
    }
    Ok(url.origin().ascii_serialization())
}
pub fn prefix(value: &str) -> Result<String> {
    validate_path(value)?;
    if value == "/" {
        Ok(String::new())
    } else {
        Ok(value.trim_end_matches('/').to_owned())
    }
}
pub fn namespace(server: &str, prefix: &str) -> String {
    format!(
        "{:x}",
        Sha256::digest(format!("{server}\n{prefix}").as_bytes())
    )
}

impl Config {
    pub fn load(cli: &Cli) -> Result<Self> {
        let dir = env::var_os("BB_CONFIG_DIR")
            .map(PathBuf::from)
            .or_else(|| {
                ProjectDirs::from("dev", "BrainBuddy", "bb").map(|d| d.config_dir().to_owned())
            })
            .ok_or_else(|| Error::store("Cannot locate a user configuration directory."))?;
        let path = dir.join("config.json");
        let saved = if path.symlink_metadata().is_ok() {
            serde_json::from_slice::<Saved>(&crate::storage::read(&path, 65536)?)
                .map_err(|_| Error::store("CLI configuration is invalid."))?
        } else {
            Saved::default()
        };
        let default = saved
            .default
            .as_ref()
            .and_then(|key| saved.connections.get(key));
        let server = cli
            .server
            .clone()
            .or_else(|| env::var("BB_SERVER").ok())
            .or_else(|| default.map(|c| c.server.clone()))
            .ok_or_else(|| {
                Error::invalid(
                    "Provide --server, BB_SERVER, or first run bb auth login --server ORIGIN.",
                )
            })?;
        let server = canonical_server(&server)?;
        let api_prefix = prefix(
            &cli.api_prefix
                .clone()
                .or_else(|| env::var("BB_API_PREFIX").ok())
                .or_else(|| {
                    default
                        .filter(|c| c.server == server)
                        .map(|c| c.api_prefix.clone())
                })
                .unwrap_or_else(|| "/api".into()),
        )?;
        let connection = saved
            .connections
            .get(&namespace(&server, &api_prefix))
            .cloned();
        Ok(Self {
            server,
            api_prefix,
            dir,
            saved,
            connection,
        })
    }
    pub fn url(&self, path: &str) -> Result<Url> {
        validate_path(path)?;
        Url::parse(&format!("{}{}{}", self.server, self.api_prefix, path))
            .map_err(|_| Error::invalid("Invalid API destination."))
    }
    pub fn save(&mut self, connection: Option<Connection>) -> Result<()> {
        let _lock = crate::storage::Lock::acquire(&self.dir)?;
        let path = self.dir.join("config.json");
        if path.symlink_metadata().is_ok() {
            let current: Saved = serde_json::from_slice(&crate::storage::read(&path, 65536)?)
                .map_err(|_| Error::store("CLI configuration is invalid."))?;
            if serde_json::to_value(&current).ok() != serde_json::to_value(&self.saved).ok() {
                return Err(Error::store(
                    "Configuration changed during this operation; reconnect explicitly.",
                ));
            }
        } else if !self.saved.connections.is_empty() {
            return Err(Error::store("Configuration changed during this operation."));
        }
        let key = namespace(&self.server, &self.api_prefix);
        let mut saved = self.saved.clone();
        if let Some(value) = &connection {
            saved.connections.insert(key.clone(), value.clone());
            saved.default = Some(key);
        } else {
            saved.connections.remove(&key);
            if saved.default.as_ref() == Some(&key) {
                saved.default = saved.connections.keys().next().cloned();
            }
        }
        let bytes =
            serde_json::to_vec(&saved).map_err(|_| Error::store("Cannot encode configuration."))?;
        if bytes.len() > 65536 {
            return Err(Error::store("Too many saved connections."));
        }
        crate::storage::write(&path, &bytes)?;
        self.saved = saved;
        self.connection = connection;
        Ok(())
    }
}

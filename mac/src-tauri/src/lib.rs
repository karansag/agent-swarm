//! Portable URL, persistence, and attention logic; native shell lives in app.rs.
use serde::{Deserialize, Serialize};
use std::{collections::BTreeSet, fs, io::Write, path::Path};
use url::{Host, Url};

#[cfg(all(feature = "desktop", target_os = "macos"))]
pub mod app;

#[derive(Clone, Debug)]
pub struct HubUrl(Url);

impl HubUrl {
    pub fn parse(input: &str) -> Result<Self, String> {
        let url = Url::parse(input.trim()).map_err(|_| "Enter a full https:// dashboard URL.")?;
        let loopback = match url.host() {
            Some(Host::Domain("localhost")) => true,
            Some(Host::Ipv4(ip)) => ip.is_loopback(),
            Some(Host::Ipv6(ip)) => ip.is_loopback(),
            _ => false,
        };
        if url.host().is_none()
            || (url.scheme() != "https" && !(url.scheme() == "http" && loopback))
        {
            return Err("Use HTTPS, or HTTP on localhost for a local test hub.".into());
        }
        if !url.username().is_empty() || url.password().is_some() || url.query().is_some() {
            return Err("Use the dashboard URL without credentials or query parameters.".into());
        }
        Ok(Self(url))
    }

    pub fn url(&self) -> &Url {
        &self.0
    }
    pub fn origin_pattern(&self) -> String {
        format!("{}/*", self.0.origin().ascii_serialization())
    }
    pub fn allows(&self, url: &Url) -> bool {
        self.0.origin() == url.origin()
    }
}

#[derive(Default, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    pub hub_url: Option<String>,
}

impl Settings {
    pub fn load(path: &Path) -> Result<Self, String> {
        match fs::read(path) {
            Ok(bytes) => serde_json::from_slice(&bytes)
                .map_err(|e| format!("Could not read saved hub settings: {e}")),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Self::default()),
            Err(e) => Err(format!("Could not read saved hub settings: {e}")),
        }
    }

    pub fn save(path: &Path, hub: &HubUrl) -> Result<(), String> {
        let parent = path.parent().ok_or("Missing settings directory")?;
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        let mut file = tempfile::NamedTempFile::new_in(parent).map_err(|e| e.to_string())?;
        let settings = Self {
            hub_url: Some(hub.url().to_string()),
        };
        file.write_all(&serde_json::to_vec_pretty(&settings).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
        file.as_file().sync_all().map_err(|e| e.to_string())?;
        file.persist(path).map_err(|e| e.to_string())?;
        Ok(())
    }
}

#[derive(Clone, Default)]
pub struct Attention {
    names: BTreeSet<String>,
}

impl Attention {
    pub fn update(&mut self, agents: Vec<String>) -> Result<(usize, Vec<String>), String> {
        if agents.len() > 512
            || agents
                .iter()
                .any(|s| s.is_empty() || s.len() > 128 || s.chars().any(char::is_control))
        {
            return Err("Invalid attention list".into());
        }
        let current: BTreeSet<_> = agents.into_iter().collect();
        let added = current.difference(&self.names).cloned().collect();
        let count = current.len();
        self.names = current;
        Ok((count, added))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hub_origin_includes_scheme_and_port() {
        let hub = HubUrl::parse(" https://linux.example.ts.net:8445/#/ ").unwrap();
        assert_eq!(hub.origin_pattern(), "https://linux.example.ts.net:8445/*");
        assert!(hub
            .allows(&Url::parse("https://linux.example.ts.net:8445/other#/agent/otter").unwrap()));
        for other in [
            "https://linux.example.ts.net/",
            "https://evil.example/",
            "http://linux.example.ts.net:8445/",
        ] {
            assert!(!hub.allows(&Url::parse(other).unwrap()));
        }
    }

    #[test]
    fn rejects_unsafe_hubs_and_accepts_loopback_test_hubs() {
        for bad in [
            "file:///tmp/a",
            "javascript:alert(1)",
            "http://tailnet.example/",
            "https://user:secret@example.com/",
            "https://example.com/?token=secret",
            "example.com",
        ] {
            assert!(HubUrl::parse(bad).is_err(), "{bad}");
        }
        for good in [
            "http://127.0.0.1:8798/",
            "http://[::1]:8798/",
            "http://localhost:8798/",
            "https://example.com/dashboard/#/",
        ] {
            assert!(HubUrl::parse(good).is_ok(), "{good}");
        }
    }

    #[test]
    fn attention_deduplicates_and_only_notifies_on_entry() {
        let mut attention = Attention::default();
        assert_eq!(
            attention
                .update(vec!["otter".into(), "otter".into()])
                .unwrap(),
            (1, vec!["otter".into()])
        );
        assert_eq!(attention.update(vec!["otter".into()]).unwrap(), (1, vec![]));
        assert_eq!(
            attention
                .update(vec!["stoat".into(), "otter".into()])
                .unwrap(),
            (2, vec!["stoat".into()])
        );
        assert_eq!(attention.update(vec![]).unwrap(), (0, vec![]));
        assert_eq!(
            attention.update(vec!["otter".into()]).unwrap(),
            (1, vec!["otter".into()])
        );
    }

    #[test]
    fn invalid_attention_does_not_replace_the_previous_list() {
        let mut attention = Attention::default();
        attention.update(vec!["otter".into()]).unwrap();
        assert!(attention.update(vec!["\n".into()]).is_err());
        assert_eq!(attention.update(vec!["otter".into()]).unwrap(), (1, vec![]));
    }

    #[test]
    fn settings_are_atomic_and_survive_replacement() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("settings.json");
        assert!(Settings::load(&path).unwrap().hub_url.is_none());
        let first = HubUrl::parse("https://one.example:8445/").unwrap();
        Settings::save(&path, &first).unwrap();
        assert_eq!(
            Settings::load(&path).unwrap().hub_url.unwrap(),
            first.url().as_str()
        );
        let second = HubUrl::parse("https://two.example:8445/").unwrap();
        Settings::save(&path, &second).unwrap();
        assert_eq!(
            Settings::load(&path).unwrap().hub_url.unwrap(),
            second.url().as_str()
        );
        fs::write(&path, b"bad json").unwrap();
        assert!(Settings::load(&path).is_err());
    }
}

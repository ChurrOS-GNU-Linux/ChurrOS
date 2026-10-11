// ==========================================
// IconsService — temas de iconos (equivalente a services/icons.py)
// ==========================================

use std::fs;
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde_json::json;

use crate::services::settings;

fn home() -> String {
    churros_services::home_dir()
}

fn uid() -> u32 {
    // getuid sin crate libc: leer /proc/self/status (mismo truco que services/theme.rs)
    if let Ok(content) = fs::read_to_string("/proc/self/status") {
        for line in content.lines() {
            if let Some(rest) = line.strip_prefix("Uid:") {
                if let Some(first) = rest.split_whitespace().next() {
                    if let Ok(uid) = first.parse::<u32>() {
                        return uid;
                    }
                }
            }
        }
    }
    1000
}

/// Socket wayland real del runtime dir (wayland-0, wayland-1, ...).
/// Fallback al valor de la variable de entorno si existe.
fn detect_wayland_display() -> Option<String> {
    if let Ok(v) = std::env::var("WAYLAND_DISPLAY") {
        if !v.is_empty() {
            return Some(v);
        }
    }
    let xrd = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| format!("/run/user/{}", uid()));
    let dir = PathBuf::from(&xrd);
    if !dir.is_dir() {
        return None;
    }
    let Ok(entries) = fs::read_dir(&dir) else {
        return None;
    };
    let mut socks: Vec<String> = entries
        .flatten()
        .filter_map(|e| e.file_name().into_string().ok())
        .filter(|n| n.starts_with("wayland-"))
        .collect();
    socks.sort();
    socks.first().cloned()
}

/// Escribe/actualiza una clave en ~/.config/gtk-{3.0,4.0}/settings.ini
/// (equivalente al bucle de ver/dir en IconsService.set del Python)
fn write_gtk_ini(key: &str, value: &str) {
    for ver in ["3.0", "4.0"] {
        let dir = PathBuf::from(home()).join(".config").join(format!("gtk-{ver}"));
        let _ = fs::create_dir_all(&dir);
        let ini = dir.join("settings.ini");

        let existing = fs::read_to_string(&ini).unwrap_or_default();
        let mut lines: Vec<String> = existing.lines().map(|s| s.to_string()).collect();

        let mut seen = false;
        for line in lines.iter_mut() {
            if line.trim_start().starts_with(&format!("{key}=")) {
                *line = format!("{key}={value}");
                seen = true;
            }
        }
        if !seen {
            lines.push(format!("{key}={value}"));
        }

        let joined = lines.join("\n");
        if !joined.contains("[Settings]") {
            lines.insert(0, "[Settings]".to_string());
        }

        let _ = fs::write(ini, lines.join("\n") + "\n");
    }
}

/// gsettings set icon-theme en vivo (equivalente a _apply_live_icon_theme)
fn apply_live_icon_theme(theme: &str) {
    let mut env: Vec<(String, String)> = std::env::vars().collect();
    if !env.iter().any(|(k, _)| k == "WAYLAND_DISPLAY") {
        if let Some(sock) = detect_wayland_display() {
            env.push(("WAYLAND_DISPLAY".to_string(), sock));
        }
    }
    if !env.iter().any(|(k, _)| k == "XDG_RUNTIME_DIR") {
        env.push(("XDG_RUNTIME_DIR".to_string(), format!("/run/user/{}", uid())));
    }
    let env_refs: Vec<(&str, &str)> = env
        .iter()
        .map(|(k, v)| (k.as_str(), v.as_str()))
        .collect();

    let _ = Command::new("gsettings")
        .args(["set", "org.gnome.desktop.interface", "icon-theme", theme])
        .envs(env_refs.iter().map(|(k, v)| (*k, *v)))
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

pub struct IconsService;

impl IconsService {
    /// Directorios donde se buscan temas de iconos (ICON_DIRS del Python)
    pub fn icon_dirs() -> Vec<PathBuf> {
        let h = home();
        vec![
            PathBuf::from("/usr/share/icons"),
            PathBuf::from(&h).join(".icons"),
            PathBuf::from(&h).join(".local/share/icons"),
        ]
    }

    /// Tema actual: settings.json "icons.theme", fallback a gtk-3.0/settings.ini, luego "Adwaita"
    pub fn current() -> String {
        let cached = settings::get_string("icons.theme", "");
        if !cached.is_empty() {
            return cached;
        }

        let ini3 = PathBuf::from(home()).join(".config/gtk-3.0/settings.ini");
        if ini3.is_file() {
            if let Ok(content) = fs::read_to_string(&ini3) {
                for line in content.lines() {
                    if line.trim_start().starts_with("gtk-icon-theme-name=") {
                        if let Some((_, value)) = line.split_once('=') {
                            return value.trim().to_string();
                        }
                    }
                }
            }
        }

        "Adwaita".to_string()
    }

    pub fn set(theme: &str) {
        settings::set("icons.theme", json!(theme));

        write_gtk_ini("gtk-icon-theme-name", theme);
        apply_live_icon_theme(theme);

        let _ = Command::new("xfconf-query")
            .args(["-c", "xsettings", "-p", "/Net/IconThemeName", "-s", theme])
            .output();

        if churros_services::version::edition().contains("kde")
            || churros_services::which("kwriteconfig6")
        {
            let _ = Command::new("kwriteconfig6")
                .args(["--file", "kdeglobals", "--group", "Icons", "--key", "Theme", theme])
                .output();
        }
    }

    /// Temas disponibles: carpetas con index.theme en ICON_DIRS (sorted set)
    pub fn available() -> Vec<String> {
        let mut themes: Vec<String> = Vec::new();
        for directory in Self::icon_dirs() {
            if !directory.is_dir() {
                continue;
            }
            if let Ok(entries) = fs::read_dir(&directory) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if !path.is_dir() {
                        continue;
                    }
                    if path.join("index.theme").is_file() {
                        if let Some(name) = entry.file_name().to_str() {
                            if !themes.contains(&name.to_string()) {
                                themes.push(name.to_string());
                            }
                        }
                    }
                }
            }
        }
        themes.sort();
        themes
    }
}

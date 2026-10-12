// ==========================================
// CursorService — tema y tamaño del cursor (equivalente a services/cursor.py)
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

fn niri_config_path() -> PathBuf {
    PathBuf::from(home()).join(".config").join("niri").join("config.kdl")
}

/// Escribe/actualiza una clave en ~/.config/gtk-{3.0,4.0}/settings.ini
/// (equivalente a CursorService._write_gtk del Python)
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

/// Señales en vivo a gnome-shell + gsettings cursor-theme/cursor-size
/// (equivalente a _apply_live_cursor_theme del Python)
fn apply_live_cursor_theme(theme_name: &str, size: i64) {
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

    // sh -c 'for pid in $(pgrep -x gnome-shell); do kill -USR1 $pid 2>/dev/null; done; exit 0'
    let _ = Command::new("sh")
        .args([
            "-c",
            "for pid in $(pgrep -x gnome-shell); do kill -USR1 $pid 2>/dev/null; done; exit 0",
        ])
        .envs(env_refs.iter().map(|(k, v)| (*k, *v)))
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();

    let _ = Command::new("gsettings")
        .args(["set", "org.gnome.desktop.interface", "cursor-theme", theme_name])
        .envs(env_refs.iter().map(|(k, v)| (*k, *v)))
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();

    let _ = Command::new("gsettings")
        .args(["set", "org.gnome.desktop.interface", "cursor-size", &size.to_string()])
        .envs(env_refs.iter().map(|(k, v)| (*k, *v)))
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

/// Reescritura del interior del bloque "cursor { ... }" en config.kdl:
/// sustituye "xcursor-size <dígitos>" por el nuevo tamaño; si el token no
/// existe, lo añade como última línea del bloque.
/// (equivalente a la parte de re.sub de NiriConfig.set_cursor_size)
fn rewrite_cursor_block(block: &str, size: i64) -> String {
    // Primera ocurrencia de "xcursor-size" + whitespace + dígitos
    if let Some(pos) = block.find("xcursor-size") {
        let after = &block[pos + "xcursor-size".len()..];
        let ws_len = after.len() - after.trim_start_matches([' ', '\t']).len();
        let rest = &after[ws_len..];
        let digits_len = rest.len() - rest.trim_start_matches(|c: char| c.is_ascii_digit()).len();
        if digits_len > 0 {
            let start = pos + "xcursor-size".len() + ws_len;
            return format!(
                "{}{}{}",
                &block[..pos],
                format!("xcursor-size {size}"),
                &block[start + digits_len..]
            );
        }
    }

    if block.contains("xcursor-size") {
        // Existe el token pero sin el formato esperado: reemplazar todas las ocurrencias
        let mut out = String::new();
        let mut rest = block;
        while let Some(pos) = rest.find("xcursor-size") {
            out.push_str(&rest[..pos]);
            let after = &rest[pos + "xcursor-size".len()..];
            let ws_len = after.len() - after.trim_start_matches([' ', '\t']).len();
            let rest2 = &after[ws_len..];
            let digits_len = rest2
                .len()
                - rest2.trim_start_matches(|c: char| c.is_ascii_digit()).len();
            out.push_str(&format!("xcursor-size {size}"));
            rest = &rest2[digits_len..];
        }
        out.push_str(rest);
        out
    } else {
        // No existe: añadir al final del bloque
        format!("{block}    xcursor-size {size}\n")
    }
}

/// Port de NiriConfig.set_cursor_size (services/dotfiles/niri_config.py).
/// Se implementa aquí (y no en services/niri_config.rs) porque el port Rust de
/// NiriConfig solo cubre animations/prefer-no-csd. La página cursor.py lo llama
/// dentro de un try/except que ignora errores: aquí los fallos se silencian.
fn set_niri_cursor_size(size: f64) {
    let size_i = size as i64;
    let path = niri_config_path();
    let Ok(content) = fs::read_to_string(&path) else {
        return;
    };

    // Buscar un bloque "cursor {" al inicio de línea (regex ^cursor\s*\{ del Python)
    let mut new_content: Option<String> = None;
    let mut search_from = 0usize;

    while let Some(rel) = content[search_from..].find("cursor") {
        let abs = search_from + rel;
        let line_start = content[..abs].rfind('\n').map(|i| i + 1).unwrap_or(0);
        let prefix = &content[line_start..abs];
        if !prefix.is_empty() {
            search_from = abs + "cursor".len();
            continue;
        }

        let after = &content[abs + "cursor".len()..];
        let after_trimmed = after.trim_start();
        if !after_trimmed.starts_with('{') {
            search_from = abs + "cursor".len();
            continue;
        }

        let brace_open = abs + "cursor".len() + (after.len() - after_trimmed.len());

        // Primer '}' tras la apertura ([^}]* del Python: sin anidar)
        let Some(close_rel) = content[brace_open + 1..].find('}') else {
            search_from = abs + "cursor".len();
            continue;
        };
        let close = brace_open + 1 + close_rel;

        let block = &content[brace_open + 1..close];
        let new_block = rewrite_cursor_block(block, size_i);
        new_content = Some(format!(
            "{}{}{}",
            &content[line_start..=brace_open],
            new_block,
            &content[close..]
        ));
        break;
    }

    let new_content = new_content.unwrap_or_else(|| {
        // No había bloque: añadirlo al final (equivalente a _append)
        let mut c = content;
        if !c.ends_with('\n') {
            c.push('\n');
        }
        c.push_str(&format!("cursor {{\n    xcursor-size {size_i}\n}}\n"));
        c
    });

    // Escritura atómica tmp + rename (como _write_atomic del Python)
    let tmp = path.with_extension("kdl.tmp");
    if fs::write(&tmp, &new_content).is_ok() {
        let _ = fs::rename(&tmp, &path);
    }
}

pub struct CursorService;

impl CursorService {
    /// Directorios donde se buscan temas de cursor (CURSOR_DIRS del Python)
    pub fn cursor_dirs() -> Vec<PathBuf> {
        let h = home();
        vec![
            PathBuf::from("/usr/share/icons"),
            PathBuf::from(&h).join(".icons"),
            PathBuf::from(&h).join(".local/share/icons"),
        ]
    }

    /// Tema actual: settings.json "cursor.theme", fallback a gtk-3.0/settings.ini, luego "default"
    pub fn current() -> String {
        let cached = settings::get_string("cursor.theme", "");
        if !cached.is_empty() {
            return cached;
        }

        let ini3 = PathBuf::from(home()).join(".config/gtk-3.0/settings.ini");
        if ini3.is_file() {
            if let Ok(content) = fs::read_to_string(&ini3) {
                for line in content.lines() {
                    if line.trim_start().starts_with("gtk-cursor-theme-name=") {
                        if let Some((_, value)) = line.split_once('=') {
                            return value.trim().to_string();
                        }
                    }
                }
            }
        }

        "default".to_string()
    }

    pub fn set(theme: &str) {
        settings::set("cursor.theme", json!(theme));

        let size = Self::size();
        write_gtk_ini("gtk-cursor-theme-name", theme);
        write_gtk_ini("gtk-cursor-theme-size", &(size as i64).to_string());
        apply_live_cursor_theme(theme, size as i64);

        let _ = Command::new("xfconf-query")
            .args(["-c", "xsettings", "-p", "/Gtk/CursorThemeName", "-s", theme])
            .output();

        if churros_services::version::edition().contains("kde")
            || churros_services::which("kwriteconfig6")
        {
            let _ = Command::new("kwriteconfig6")
                .args(["--file", "kcminputrc", "--group", "Mouse", "--key", "cursorTheme", theme])
                .output();
            let _ = Command::new("plasma-apply-cursortheme")
                .arg(theme)
                .output();
        }
    }

    /// Temas disponibles: carpetas con subdirectorio "cursors" en CURSOR_DIRS (sorted set)
    pub fn available() -> Vec<String> {
        let mut cursors: Vec<String> = Vec::new();
        for directory in Self::cursor_dirs() {
            if !directory.is_dir() {
                continue;
            }
            if let Ok(entries) = fs::read_dir(&directory) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if !path.is_dir() {
                        continue;
                    }
                    if path.join("cursors").is_dir() {
                        if let Some(name) = entry.file_name().to_str() {
                            if !cursors.contains(&name.to_string()) {
                                cursors.push(name.to_string());
                            }
                        }
                    }
                }
            }
        }
        cursors.sort();
        cursors
    }

    /// Tamaño del cursor desde settings.json ("cursor.size", default 24)
    pub fn size() -> f64 {
        settings::get("cursor.size", json!(24)).as_f64().unwrap_or(24.0)
    }

    pub fn set_size(size: f64) {
        let size_i = size as i64;
        settings::set("cursor.size", json!(size_i));

        let theme = Self::current();
        write_gtk_ini("gtk-cursor-theme-size", &size_i.to_string());
        apply_live_cursor_theme(&theme, size_i);

        let _ = Command::new("xfconf-query")
            .args(["-c", "xsettings", "-p", "/Gtk/CursorThemeSize", "-s", &size_i.to_string()])
            .output();

        if churros_services::version::edition().contains("kde")
            || churros_services::which("kwriteconfig6")
        {
            let _ = Command::new("kwriteconfig6")
                .args(["--file", "kcminputrc", "--group", "Mouse", "--key", "cursorSize", &size_i.to_string()])
                .output();
        }

        // Equivalente a: NiriConfig.set_cursor_size(size) dentro de try/except
        set_niri_cursor_size(size);
    }
}

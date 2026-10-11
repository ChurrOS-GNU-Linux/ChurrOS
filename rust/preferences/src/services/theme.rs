// ==========================================
// ThemeService — dark/light + gtk settings + señales a foot
// (equivalente a services/theme.py)
// ==========================================

use std::cell::{Cell, RefCell};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use serde_json::json;

use crate::services::settings;

// Listeners de cambio de tema (dark/light). Los registra la ventana y
// ThemeService::set los invoca para refrescar la clase CSS y GtkSettings
// sin depender de gsettings/dconf. Todo corre en el hilo principal de GTK.
thread_local! {
    static THEME_LISTENERS: RefCell<Vec<Box<dyn Fn(bool)>>> = RefCell::new(Vec::new());
    static APPLYING: Cell<bool> = const { Cell::new(false) };
}

fn cache_dir() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home).join(".cache").join("churros-theme")
}

fn dark_flag() -> PathBuf {
    cache_dir().join("dark-flag")
}

fn gtk_ini(dir: &str) -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home).join(".config").join(dir).join("settings.ini")
}

fn build_env() -> Vec<(String, String)> {
    let mut env: Vec<(String, String)> = std::env::vars().collect();
    let uid = libc_getuid();
    let xrd = format!("/run/user/{uid}");

    if env.iter().all(|(k, _)| k != "XDG_RUNTIME_DIR") {
        env.push(("XDG_RUNTIME_DIR".to_string(), xrd.clone()));
    }

    if env.iter().all(|(k, _)| k != "WAYLAND_DISPLAY") {
        if std::path::Path::new(&xrd).is_dir() {
            if let Ok(entries) = fs::read_dir(&xrd) {
                let mut valid_socks: Vec<(std::time::SystemTime, String)> = entries
                    .flatten()
                    .filter_map(|e| {
                        let name = e.file_name().to_string_lossy().to_string();
                        if name.starts_with("wayland-") && !name.ends_with(".lock") {
                            let mtime = e
                                .metadata()
                                .and_then(|m| m.modified())
                                .unwrap_or(std::time::SystemTime::UNIX_EPOCH);
                            Some((mtime, name))
                        } else {
                            None
                        }
                    })
                    .collect();
                valid_socks.sort_by(|a, b| b.0.cmp(&a.0));
                if let Some((_, name)) = valid_socks.first() {
                    env.push(("WAYLAND_DISPLAY".to_string(), name.clone()));
                }
            }
        }
    }

    env
}

fn libc_getuid() -> u32 {
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

/// Actualiza una clave del ini preservando el resto (cursor, fuente, …).
fn update_ini_key(ini: &Path, key: &str, value: &str) {
    if let Some(parent) = ini.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let existing = fs::read_to_string(ini).unwrap_or_default();
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
    let content = if joined.contains("[Settings]") {
        joined
    } else {
        format!("[Settings]\n{joined}")
    };
    let _ = fs::write(ini, content + "\n");
}

fn migrate_adwaita_dark_ini(ini: &Path) {
    let Ok(content) = fs::read_to_string(ini) else {
        return;
    };
    if !content
        .lines()
        .any(|line| line.trim() == "gtk-theme-name=Adwaita-dark")
    {
        return;
    }
    let updated = content.replace("gtk-theme-name=Adwaita-dark", "gtk-theme-name=Adwaita");
    let _ = fs::write(ini, updated);
}

fn noctalia_prefers_dark() -> Option<bool> {
    let home = PathBuf::from(churros_services::home_dir());
    let state = fs::read_to_string(home.join(".local/state/noctalia/settings.toml")).ok();
    let config = fs::read_to_string(home.join(".config/noctalia/config.toml")).ok();
    churros_services::noctalia::preferred_dark(state.as_deref(), config.as_deref())
}

fn write_dark_flag(dark: bool) {
    if let Some(parent) = dark_flag().parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(dark_flag(), if dark { "1" } else { "0" });
}

/// Limpia claves obsoletas de GTK3 de settings.ini de GTK4
fn clean_gtk4_ini(ini: &Path) {
    let Ok(content) = fs::read_to_string(ini) else {
        return;
    };
    if !content
        .lines()
        .any(|l| l.trim_start().starts_with("gtk-application-prefer-dark-theme"))
    {
        return;
    }
    let lines: Vec<&str> = content
        .lines()
        .filter(|l| !l.trim_start().starts_with("gtk-application-prefer-dark-theme"))
        .collect();
    let _ = fs::write(ini, lines.join("\n") + "\n");
}

/// Persistencia para otras apps. No toca gtk-theme-name en GTK4: Adwaita-dark
/// no existe como tema GTK4 (Adwaita va integrado) y cambiar gtk-theme en
/// caliente recarga el CSS de esta misma app y la termina cerrando.
fn persist_desktop(dark: bool) {
    update_ini_key(
        &gtk_ini("gtk-3.0"),
        "gtk-application-prefer-dark-theme",
        if dark { "1" } else { "0" },
    );
    update_ini_key(&gtk_ini("gtk-3.0"), "gtk-theme-name", "Adwaita");
    // NO tocar archivos de gtk-4.0 en caliente: cualquier modificación de settings.ini
    // a runtime dispara recarga inotify de hojas de estilo y cierra las ventanas.
    // La migración de claves obsoletas se realiza antes de gtk_init en migrate_before_gtk.

    let _ = Command::new("gsettings")
        .args([
            "set",
            "org.gnome.desktop.interface",
            "color-scheme",
            if dark { "prefer-dark" } else { "prefer-light" },
        ])
        .output();

    // Noctalia (sesión Niri) vuelve a escribir color-scheme desde su
    // [theme].mode al arrancar. shell_mode = "follow" en config.toml hace
    // que la barra y los paneles usen esa misma variante. El modo se guarda
    // en settings.toml. Sin Noctalia corriendo no hace nada.
    if churros_services::which("noctalia") {
        let _ = Command::new("noctalia")
            .args(["msg", "theme-mode-set", if dark { "dark" } else { "light" }])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();
    }

    // Sincronizar tema con XFCE (xsettings) solo en sesión XFCE
    if churros_services::version::edition().contains("xfce")
        || churros_services::which("xfce4-session")
    {
        let _ = Command::new("xfconf-query")
            .args([
                "-c",
                "xsettings",
                "-p",
                "/Net/ThemeName",
                "-s",
                if dark { "Adwaita-dark" } else { "Adwaita" },
            ])
            .output();
    }

    // Sincronizar tema con KDE Plasma (color-scheme)
    if churros_services::version::edition().contains("kde")
        || churros_services::which("startplasma-wayland")
        || churros_services::which("plasma-apply-colorscheme")
    {
        let scheme = if dark { "ChurroOSDark" } else { "BreezeLight" };
        let _ = Command::new("plasma-apply-colorscheme")
            .arg(scheme)
            .output();
        let _ = Command::new("kwriteconfig6")
            .args(["--file", "kdeglobals", "--group", "General", "--key", "ColorScheme", scheme])
            .output();
    }

    let env = build_env();
    let env_refs: Vec<(&str, &str)> = env
        .iter()
        .map(|(k, v)| (k.as_str(), v.as_str()))
        .collect();
    // Waybar no usa el tema GTK: recargarla aquí solo resetea la barra.
    // foot: SIGUSR1 = colors-dark, SIGUSR2 = colors-light (foot(1)).
    // Se usa --signal y -x para concordancia exacta y segura.
    let _ = Command::new("pkill")
        .args([
            "--signal",
            if dark { "USR1" } else { "USR2" },
            "-x",
            "foot",
        ])
        .envs(env_refs.iter().map(|(k, v)| (*k, *v)))
        .output();
}

pub struct ThemeService;

impl ThemeService {
    /// Corregir leftovers de Adwaita-dark y claves obsoletas *antes* de gtk_init.
    pub fn migrate_before_gtk() {
        let stamp = cache_dir().join("migrated-adwaita");
        if stamp.exists() {
            return;
        }

        migrate_adwaita_dark_ini(&gtk_ini("gtk-3.0"));
        migrate_adwaita_dark_ini(&gtk_ini("gtk-4.0"));
        clean_gtk4_ini(&gtk_ini("gtk-4.0"));

        let output = Command::new("gsettings")
            .args(["get", "org.gnome.desktop.interface", "gtk-theme"])
            .output();
        if let Ok(output) = output {
            let value = String::from_utf8_lossy(&output.stdout);
            if value.contains("Adwaita-dark") {
                let _ = Command::new("gsettings")
                    .args(["set", "org.gnome.desktop.interface", "gtk-theme", "Adwaita"])
                    .output();
            }
        }

        let _ = fs::create_dir_all(cache_dir());
        let _ = fs::write(&stamp, "1");
    }

    pub fn is_dark() -> bool {
        // Con Noctalia el modo real es [theme].mode: settings.toml si hay
        // override, y si no el config.toml de fábrica (oscuro).
        if churros_services::noctalia::shell_active() {
            if let Some(dark) = noctalia_prefers_dark() {
                return dark;
            }
        }
        if let Ok(content) = fs::read_to_string(dark_flag()) {
            return content.trim() == "1";
        }
        if let Some(cached) = settings::get("theme.dark", json!(null)).as_bool() {
            return cached;
        }
        true
    }

    pub fn set(dark: bool) {
        if APPLYING.with(Cell::get) || Self::is_dark() == dark {
            return;
        }
        Self::apply(dark);
    }

    /// Escribe el modo aunque `is_dark()` ya coincida. Tras restablecer,
    /// el config de Noctalia vuelve a `mode = "dark"` y `set(true)` saldría
    /// sin `theme-mode-set` ni el prefer-dark de GTK.
    pub fn apply(dark: bool) {
        if APPLYING.with(Cell::get) {
            return;
        }
        APPLYING.with(|flag| flag.set(true));

        settings::set("theme.dark", json!(dark));
        write_dark_flag(dark);
        crate::logging::log(&format!("theme set dark={dark}"));

        // En vivo en ESTE proceso: clase CSS + prefer-dark. No tocar
        // gtk-theme-name ni gsettings gtk-theme (eso cierra la ventana).
        Self::notify(dark);

        glib::idle_add_local_once(move || persist_desktop(dark));
        APPLYING.with(|flag| flag.set(false));
    }

    /// Registra un callback que se invoca en cada cambio de tema.
    pub fn on_change(cb: impl Fn(bool) + 'static) {
        THEME_LISTENERS.with(|l| l.borrow_mut().push(Box::new(cb)));
    }

    fn notify(dark: bool) {
        THEME_LISTENERS.with(|l| {
            for cb in l.borrow().iter() {
                cb(dark);
            }
        });
    }

    pub fn toggle() {
        Self::set(!Self::is_dark());
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    use std::rc::Rc;

    #[test]
    fn on_change_notifies_listeners() {
        let received = Rc::new(RefCell::new(Vec::new()));
        let r1 = received.clone();
        ThemeService::on_change(move |dark| r1.borrow_mut().push(dark));
        let r2 = received.clone();
        ThemeService::on_change(move |dark| r2.borrow_mut().push(dark));

        ThemeService::notify(true);
        ThemeService::notify(false);

        assert_eq!(*received.borrow(), vec![true, true, false, false]);
    }

    #[test]
    fn migrate_rewrites_adwaita_dark() {
        let dir = std::env::temp_dir().join(format!("churros-theme-test-{}", std::process::id()));
        let _ = fs::create_dir_all(&dir);
        let ini = dir.join("settings.ini");
        fs::write(&ini, "[Settings]\ngtk-theme-name=Adwaita-dark\ngtk-font-name=Inter 11\n")
            .unwrap();
        migrate_adwaita_dark_ini(&ini);
        let content = fs::read_to_string(&ini).unwrap();
        assert!(content.contains("gtk-theme-name=Adwaita\n"));
        assert!(!content.contains("Adwaita-dark"));
        assert!(content.contains("gtk-font-name=Inter 11"));
        let _ = fs::remove_dir_all(dir);
    }
}

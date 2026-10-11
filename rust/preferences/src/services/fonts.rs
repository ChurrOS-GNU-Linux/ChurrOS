use gtk::prelude::*;

// ==========================================
// FontService — fuentes del sistema (equivalente a services/fonts.py)
// ==========================================

use std::process::Command;

use serde_json::json;

use crate::services::settings;

pub struct FontService;

impl FontService {
    pub const DEFAULT: &'static str = "Inter";

    /// Fuentes instaladas vía `fc-list : family` (timeout 2s en el Python;
    /// en Rust el .output() bloquea pero fc-list termina al instante).
    /// Fallback a una lista fija si no se puede ejecutar fc-list.
    pub fn available() -> Vec<String> {
        let output = Command::new("fc-list").args([":", "family"]).output();

        let Ok(output) = output else {
            return Self::fallback_fonts();
        };

        // Paridad con Python: no se comprueba el returncode, solo se parsea stdout
        let mut fonts: Vec<String> = Vec::new();
        let stdout = String::from_utf8_lossy(&output.stdout);
        for line in stdout.lines() {
            for family in line.split(',') {
                let family = family.trim();
                if !family.is_empty() && !fonts.contains(&family.to_string()) {
                    fonts.push(family.to_string());
                }
            }
        }

        fonts.sort();
        fonts
    }

    fn fallback_fonts() -> Vec<String> {
        vec![
            Self::DEFAULT.to_string(),
            "Cantarell".to_string(),
            "Roboto".to_string(),
            "Sans".to_string(),
        ]
    }

    /// Fuente actual desde settings.json ("fonts.family", default "Inter")
    pub fn current() -> String {
        settings::get_string("fonts.family", Self::DEFAULT)
    }

    pub fn set(family: &str) {
        settings::set("fonts.family", json!(family));

        // gsettings set ... font-name "Familia 11" (bloqueante, errores ignorados)
        let _ = Command::new("gsettings")
            .args([
                "set",
                "org.gnome.desktop.interface",
                "font-name",
                &format!("{family} 11"),
            ])
            .output();
        let _ = Command::new("gsettings")
            .args([
                "set",
                "org.gnome.desktop.interface",
                "document-font-name",
                &format!("{family} 11"),
            ])
            .output();
        let _ = Command::new("gsettings")
            .args([
                "set",
                "org.gnome.desktop.interface",
                "monospace-font-name",
                &format!("{family} Mono 10"),
            ])
            .output();

        let _ = Command::new("xfconf-query")
            .args([
                "-c",
                "xsettings",
                "-p",
                "/Gtk/FontName",
                "-s",
                &format!("{family} 10"),
            ])
            .output();
        let _ = Command::new("xfconf-query")
            .args([
                "-c",
                "xsettings",
                "-p",
                "/Gtk/MonospaceFontName",
                "-s",
                &format!("{family} Mono 10"),
            ])
            .output();

        if churros_services::version::edition().contains("kde")
            || churros_services::which("kwriteconfig6")
        {
            let _ = Command::new("kwriteconfig6")
                .args(["--file", "kdeglobals", "--group", "General", "--key", "font", &format!("{family},10,-1,5,50,0,0,0,0,0")])
                .output();
            let _ = Command::new("kwriteconfig6")
                .args(["--file", "kdeglobals", "--group", "General", "--key", "fixed", &format!("{family} Mono,10,-1,5,50,0,0,0,0,0")])
                .output();
        }
    }

    /// Escala de fuentes desde settings.json ("fonts.scale", default 1.0)
    pub fn scale() -> f64 {
        settings::get("fonts.scale", json!(1.0)).as_f64().unwrap_or(1.0)
    }

    pub fn set_scale(scale: f64) {
        settings::set("fonts.scale", json!(scale));

        let _ = Command::new("gsettings")
            .args([
                "set",
                "org.gnome.desktop.interface",
                "text-scaling-factor",
                &scale.to_string(),
            ])
            .output();

        // gtk-xft-dpi = int(1024 * scale), como el Python
        if let Some(settings) = gtk::Settings::default() {
            let _ = settings.set_property("gtk-xft-dpi", (1024.0 * scale) as i32);
        }
    }
}

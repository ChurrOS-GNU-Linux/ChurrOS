// ==========================================
// PywalService — colores dinámicos desde el wallpaper
// (equivalente a services/pywal_service.py)
// ==========================================

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use serde_json::{json, Value};

use crate::services::accent::AccentService;
use crate::services::settings;
use crate::services::wallpaper::WallpaperService;
use crate::services::waybar::WaybarService;
use crate::services::foot_config::FootConfig;
use crate::services::fuzzel_config::FuzzelConfig;
use crate::services::mako_config::MakoConfig;

pub struct PywalService;

fn home() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home)
}

fn cache_file() -> PathBuf {
    home().join(".cache").join("wal").join("colors.json")
}

fn which(name: &str) -> bool {
    let path_var = std::env::var("PATH").unwrap_or_default();
    path_var
        .split(':')
        .any(|dir| Path::new(dir).join(name).is_file())
}

impl PywalService {
    pub fn available() -> bool {
        which("wal")
    }

    pub fn enabled() -> bool {
        settings::get_bool("theme.dynamic_colors", false)
    }

    fn current_wallpaper() -> Option<String> {
        let path = WallpaperService::current();
        if !path.is_empty() && Path::new(&path).is_file() {
            return Some(path);
        }
        let default = "/usr/share/churros/wallpapers/default.png";
        if Path::new(default).is_file() {
            return Some(default.to_string());
        }
        None
    }

    /// Corre `wal -i <wallpaper>` para una ruta dada y devuelve la paleta o None.
    pub fn generate_for(wallpaper: &str) -> Option<Value> {
        if !Self::available() || wallpaper.is_empty() || !Path::new(wallpaper).is_file() {
            return None;
        }
        let _ = Command::new("wal")
            .args(["-i", wallpaper, "-q", "-n", "-e", "-s", "-t"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        Self::read_cache()
    }

    /// Corre `wal -i <wallpaper>` del wallpaper actual y devuelve la paleta (colors.json) o None.
    pub fn generate() -> Option<Value> {
        let wallpaper = Self::current_wallpaper()?;
        Self::generate_for(&wallpaper)
    }

    fn read_cache() -> Option<Value> {
        let raw = fs::read_to_string(cache_file()).ok()?;
        serde_json::from_str(&raw).ok()
    }

    /// Aplica la paleta: accent GTK (accent.css) + colores de waybar.
    pub fn apply_accent(palette: &Value) -> bool {
        let colors = palette.get("colors").and_then(|c| c.as_object());
        let specials = palette.get("special").and_then(|c| c.as_object());

        let get_color = |name: &str| -> Option<&str> {
            colors
                .and_then(|c| c.get(name))
                .and_then(|v| v.as_str())
        };
        let get_special = |name: &str| -> Option<&str> {
            specials
                .and_then(|s| s.get(name))
                .and_then(|v| v.as_str())
        };

        // Acento: color vivo de la paleta (color1 -> color4 -> foreground)
        let accent = get_color("color1")
            .or_else(|| get_color("color4"))
            .or_else(|| get_special("foreground"))
            .unwrap_or("#DE8636");
        let bg = get_special("background").unwrap_or("#111827");
        let fg = get_special("foreground").unwrap_or("#F8FAFC");

        // Acento GTK (accent.css)
        crate::logging::log(&format!("[pywal] aplicando acento hex: {accent}, bg: {bg}, fg: {fg}"));
        AccentService::set_hex(accent);

        // Waybar y Mako no corren con Noctalia. Escribir sus configs y
        // lanzar makoctl deja procesos zombi y, en Waybar, una segunda barra.
        if churros_services::noctalia::uses_waybar() {
            WaybarService::apply_pywal_colors(bg, fg, accent);
        }

        if let (Some(colors_map), Some(special_map)) = (colors, specials) {
            FootConfig::apply_pywal(colors_map, special_map);
            FuzzelConfig::apply_pywal(colors_map, special_map);
            if churros_services::noctalia::uses_mako() {
                MakoConfig::apply_pywal(colors_map, special_map);
            }
        }

        crate::logging::log("[pywal] apply_accent completado OK");
        true
    }

    /// Habilita/deshabilita los colores dinámicos.
    pub fn toggle(value: bool) -> bool {
        if value {
            Self::enable()
        } else {
            settings::set("theme.dynamic_colors", json!(false));
            // Volver al color guardado por nombre
            AccentService::set(&AccentService::current());
            true
        }
    }

    fn enable() -> bool {
        settings::set("theme.dynamic_colors", json!(true));
        let Some(palette) = Self::generate() else {
            return false;
        };
        Self::apply_accent(&palette)
    }

    /// Hook de WallpaperService.set: si los colores dinámicos están activos,
    /// regenera la paleta desde el wallpaper y la aplica.
    pub fn regenerate_if_enabled() -> bool {
        if !Self::enabled() {
            return false;
        }
        let Some(palette) = Self::generate() else {
            return false;
        };
        Self::apply_accent(&palette)
    }

    pub fn regenerate_for_wallpaper(path: &str) -> bool {
        if !Self::enabled() {
            crate::logging::log("[pywal] no habilitado, skip");
            return false;
        }
        crate::logging::log(&format!("[pywal] ejecutando wal para {path}..."));
        let Some(palette) = Self::generate_for(path) else {
            crate::logging::log("[pywal] wal fallo o no devolvio paleta");
            return false;
        };
        crate::logging::log("[pywal] paleta obtenida, aplicando...");
        Self::apply_accent(&palette)
    }
}

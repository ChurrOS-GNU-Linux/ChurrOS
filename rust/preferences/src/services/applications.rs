// ==========================================
// ApplicationsService (equivalente a services/applications.py)
// ==========================================

use std::process::Command;

use crate::services::settings;

pub struct ApplicationsService;

impl ApplicationsService {
    /// Número de paquetes instalados, como string.
    /// Lee directamente `/var/lib/pacman/local` (<1ms) en lugar de invocar `pacman -Q` (~130ms),
    /// con fallback a `pacman -Q` si la ruta no fuera legible.
    pub fn count() -> String {
        if let Ok(entries) = std::fs::read_dir("/var/lib/pacman/local") {
            let count = entries
                .flatten()
                .filter(|entry| {
                    if let Ok(file_type) = entry.file_type() {
                        file_type.is_dir() && entry.file_name() != "ALPM_DB_VERSION"
                    } else {
                        false
                    }
                })
                .count();
            if count > 0 {
                return count.to_string();
            }
        }

        match Command::new("pacman").arg("-Q").output() {
            Ok(out) => {
                let text = String::from_utf8_lossy(&out.stdout);
                text.lines().count().to_string()
            }
            Err(_) => "0".to_string(),
        }
    }

    pub fn store() -> &'static str {
        "Pacman"
    }

    pub fn auto_updates() -> bool {
        settings::get_bool("applications.auto_updates", true)
    }

    pub fn set_auto_updates(value: bool) {
        settings::set("applications.auto_updates", serde_json::json!(value));
    }

    pub fn auto_install() -> bool {
        settings::get_bool("applications.auto_install", false)
    }

    pub fn set_auto_install(value: bool) {
        settings::set("applications.auto_install", serde_json::json!(value));
    }

    #[allow(dead_code)] // por paridad con services/applications.py (package_manager)
    pub fn package_manager() -> &'static str {
        "pacman"
    }

    #[allow(dead_code)] // por paridad con services/applications.py (repositories)
    pub fn repositories() -> &'static str {
        "Arch Linux"
    }

    #[allow(dead_code)] // por paridad con services/applications.py (flatpak_enabled)
    pub fn flatpak_enabled() -> bool {
        churros_services::which("flatpak")
    }

    #[allow(dead_code)] // por paridad con services/applications.py (snap_enabled)
    pub fn snap_enabled() -> bool {
        churros_services::which("snap")
    }
}

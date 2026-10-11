// ==========================================
// theme.rs — servicio compartido de tema (dark/light)
// ==========================================

use std::fs;
use std::path::PathBuf;

pub fn cache_dir() -> PathBuf {
    let home = crate::home_dir();
    PathBuf::from(home).join(".cache").join("churros-theme")
}

pub fn dark_flag() -> PathBuf {
    cache_dir().join("dark-flag")
}

/// Comprueba si el tema actual del sistema es oscuro.
/// 1. Lee ~/.cache/churros-theme/dark-flag (escrito por churros-settings).
/// 2. Si no existe, consulta gsettings org.gnome.desktop.interface color-scheme.
/// 3. Por defecto devuelve true (modo oscuro predeterminado de ChurrOS).
pub fn is_dark() -> bool {
    if let Ok(content) = fs::read_to_string(dark_flag()) {
        return content.trim() == "1";
    }

    if let Some((code, stdout, _)) = crate::run(
        &["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
        500,
    ) {
        if code == 0 && stdout.contains("prefer-light") {
            return false;
        }
    }

    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dark_flag_path() {
        let path = dark_flag();
        assert!(path.ends_with(".cache/churros-theme/dark-flag"));
    }
}

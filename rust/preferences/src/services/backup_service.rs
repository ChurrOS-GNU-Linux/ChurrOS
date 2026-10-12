// ==========================================
// BackupService — exportar/importar/restablecer config de ChurrOS
// (equivalente a services/backup_service.py)
// ==========================================

use serde_json::Value;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::Command;

pub struct BackupService;

fn home() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home)
}

fn churros_dir() -> PathBuf {
    home().join(".config").join("churros")
}

fn settings_file() -> PathBuf {
    churros_dir().join("settings.json")
}

/// Dotfiles incluidos en el backup: (nombre, ruta)
fn dotfiles() -> Vec<(&'static str, PathBuf)> {
    vec![
        ("niri", home().join(".config").join("niri")),
        ("foot", home().join(".config").join("foot")),
        ("fuzzel", home().join(".config").join("fuzzel")),
        ("mako", home().join(".config").join("mako")),
        ("waybar", home().join(".config").join("waybar")),
        ("noctalia", home().join(".config").join("noctalia")),
        ("fastfetch", home().join(".config").join("fastfetch")),
        // Estado real que Noctalia persiste en la UI (settings.toml) — sin
        // esto el backup ignora lo que la persona cambió en Noctalia.
        ("noctalia-state", home().join(".local").join("state").join("noctalia")),
    ]
}

const DEFAULTS_DIR: &str = "/usr/share/churros/defaults";

/// Une `base` + `rel` rechazando rutas absolutas y componentes ".."
/// (protección contra path traversal en backups maliciosos).
fn safe_join(base: &Path, rel: &str) -> Option<PathBuf> {
    let rel_path = Path::new(rel);
    if rel_path.is_absolute() {
        return None;
    }
    if rel_path.components().any(|c| {
        matches!(
            c,
            std::path::Component::ParentDir
                | std::path::Component::RootDir
                | std::path::Component::Prefix(_)
        )
    }) {
        return None;
    }
    Some(base.join(rel_path))
}

/// Copia recursiva de directorio (como shutil.copytree).
fn copy_dir_all(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let target = dst.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir_all(&entry.path(), &target)?;
        } else {
            fs::copy(entry.path(), target)?;
        }
    }
    Ok(())
}

/// Noctalia vigila ~/.config/noctalia: si se borra la carpeta deja de ver
/// cambios hasta reiniciarse. Se restauran los archivos en su sitio, se quitan
/// los *.toml que no trae la configuración por defecto y se conserva
/// live.toml, que solo existe en el Live (archiso/airootfs/root/scripts/desktop.sh).
fn restore_noctalia_config(src: &Path, dst: &Path) {
    let _ = fs::create_dir_all(dst);
    if let Ok(entries) = fs::read_dir(dst) {
        for entry in entries.flatten() {
            let name = entry.file_name();
            let path = entry.path();
            let is_toml = path.extension().is_some_and(|ext| ext == "toml");
            if is_toml && name != "live.toml" && !src.join(&name).exists() {
                let _ = fs::remove_file(&path);
            }
        }
    }
    let _ = copy_dir_all(src, dst);
}

impl BackupService {
    /// Exporta settings.json + dotfiles a un .tar (equivalente a export_to).
    pub fn export_to(dest_path: &str) -> Result<String, String> {
        let any_dotfile = dotfiles().iter().any(|(_, p)| p.exists());
        if !churros_dir().is_dir() && !any_dotfile {
            return Err("No hay configuracion que exportar".to_string());
        }

        let dest = PathBuf::from(dest_path);
        let directory = dest
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_else(|| PathBuf::from("."));
        fs::create_dir_all(&directory).map_err(|e| e.to_string())?;

        // Archivo temporal en el mismo directorio (como mkstemp)
        let tmp = directory.join(format!(
            "churros-backup-{}-{}.tar.zst",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));

        let result = (|| -> std::io::Result<()> {
            let file = fs::File::create(&tmp)?;
            // Compresión zstd real (la extensión es .tar.zst).
            let encoder = zstd::stream::Encoder::new(file, 3)?;
            let mut tar = tar::Builder::new(encoder);

            if settings_file().exists() {
                tar.append_path_with_name(&settings_file(), "churros/settings.json")?;
            }

            for (name, path) in dotfiles() {
                if path.exists() {
                    tar.append_dir_all(&format!("dotfiles/{name}"), &path)?;
                }
            }

            let encoder = tar.into_inner()?;
            encoder.finish()?;
            Ok(())
        })();

        match result {
            Ok(()) => {
                fs::rename(&tmp, &dest).map_err(|e| e.to_string())?;
                Ok(dest_path.to_string())
            }
            Err(e) => {
                let _ = fs::remove_file(&tmp);
                Err(e.to_string())
            }
        }
    }

    /// Importa un backup de ChurrOS (equivalente a import_from).
    pub fn import_from(src_path: &str) -> Result<bool, String> {
        let src = PathBuf::from(src_path);
        if !src.is_file() {
            return Err(format!("El archivo no existe: {src_path}"));
        }

        // Leer todos los miembros del tar (path, is_dir, contenido)
        let mut items: Vec<(String, bool, Vec<u8>)> = Vec::new();
        let mut has_churros = false;
        let mut has_dotfiles = false;

        let file = fs::File::open(&src).map_err(|e| format!("Archivo invalido: {e}"))?;
        let raw = std::io::Read::bytes(file)
            .collect::<Result<Vec<u8>, _>>()
            .map_err(|e| format!("Archivo invalido: {e}"))?;

        // Backup comprimido con zstd (magic 28 B5 2F FD) o tar plano (legacy).
        let reader: Box<dyn Read> = if raw.starts_with(&[0x28, 0xB5, 0x2F, 0xFD]) {
            Box::new(
                zstd::stream::read::Decoder::new(&raw[..])
                    .map_err(|e| format!("Archivo invalido: {e}"))?,
            )
        } else {
            Box::new(&raw[..])
        };
        let mut archive = tar::Archive::new(reader);

        let entries = archive
            .entries()
            .map_err(|e| format!("Archivo invalido: {e}"))?;

        for entry in entries {
            let mut entry = entry.map_err(|e| format!("Archivo invalido: {e}"))?;
            let name = entry
                .path()
                .map(|p| p.to_string_lossy().to_string())
                .unwrap_or_default();
            let is_dir = entry.header().entry_type().is_dir();

            if name.starts_with("churros/") || name == "churros" {
                has_churros = true;
            }
            if name.starts_with("dotfiles/") || name == "dotfiles" {
                has_dotfiles = true;
            }

            let mut data = Vec::new();
            if !is_dir {
                let _ = entry.read_to_end(&mut data);
            }
            items.push((name, is_dir, data));
        }

        if !has_churros && !has_dotfiles {
            return Err("El archivo no es un backup de ChurrOS".to_string());
        }

        // Sanitizar rutas: rechazar absolutas y ".." (path traversal).
        for (name, is_dir, data) in items {
            if name.starts_with("churros/") {
                if is_dir {
                    continue;
                }
                let rel = name.trim_start_matches("churros/");
                let Some(target) = safe_join(&churros_dir(), rel) else {
                    continue;
                };
                if let Some(parent) = target.parent() {
                    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
                }
                fs::write(&target, data).map_err(|e| e.to_string())?;
            } else if name.starts_with("dotfiles/") {
                let mut parts = name.splitn(3, '/');
                let _ = parts.next(); // "dotfiles"
                let Some(df_name) = parts.next() else { continue };
                let rest = parts.next().unwrap_or("");

                // Solo dotfiles conocidos (evita escribir dirs arbitrarios).
                if !dotfiles().iter().any(|(n, _)| *n == df_name) {
                    continue;
                }

                // El directorio destino viene del propio dotfiles(): los de
                // estado (noctalia-state) no viven en ~/.config.
                let Some(target_dir) = dotfiles()
                    .into_iter()
                    .find(|(n, _)| *n == df_name)
                    .map(|(_, p)| p)
                else {
                    continue;
                };

                if is_dir {
                    fs::create_dir_all(&target_dir).map_err(|e| e.to_string())?;
                    continue;
                }
                if rest.is_empty() {
                    continue;
                }

                let Some(target) = safe_join(&target_dir, rest) else {
                    continue;
                };
                if let Some(parent) = target.parent() {
                    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
                }
                fs::write(&target, data).map_err(|e| e.to_string())?;
            }
        }

        Self::reload_services();
        Ok(true)
    }

    /// Restablece settings.json y los dotfiles desde /usr/share/churros/defaults.
    pub fn reset_to_defaults() -> Result<bool, String> {
        let defaults_dir = PathBuf::from(DEFAULTS_DIR);
        if !defaults_dir.is_dir() {
            return Err(format!("Defaults no encontrados: {DEFAULTS_DIR}"));
        }

        Self::restore_settings();
        Self::restore_dotfiles();
        // El config restaurado ya dice oscuro, así que ThemeService::set
        // no haría nada y GTK / `[theme].mode` se quedarían en claro.
        // apply() recorre el mismo camino que el interruptor de Apariencia.
        crate::services::theme::ThemeService::apply(true);
        Self::reload_services();
        // settings.json vuelve a Orange, pero accent.css (y el acento de KDE)
        // se quedan con el hex de pywal. El selector de color reescribe ambos.
        crate::services::accent::AccentService::set(
            &crate::services::accent::AccentService::current(),
        );
        Ok(true)
    }

    fn restore_settings() {
        let defaults = serde_json::json!({
            "theme": { "dark": true, "dynamic_colors": false },
            "accent": { "color": "Orange" },
            "wallpaper": { "path": "" },
            "icons": { "theme": "Papirus" },
            "cursor": { "theme": "Adwaita" },
            "fonts": { "family": "Inter", "scale": 1.0 }
        });
        crate::services::settings::save(&defaults);
    }

    fn restore_dotfiles() {
        // Lo que se cambia desde la UI de Noctalia (~/.local/state/noctalia/
        // settings.toml) se aplica encima del config.toml restaurado. Se vacía
        // en vez de borrarlo: Noctalia solo lo relee cuando se escribe y, si
        // desaparece, vuelve a guardar los ajustes que tiene en memoria.
        let noctalia_state = home()
            .join(".local")
            .join("state")
            .join("noctalia")
            .join("settings.toml");
        if noctalia_state.exists() {
            let _ = fs::write(&noctalia_state, "");
        }

        let defaults_dir = PathBuf::from(DEFAULTS_DIR);
        let Ok(entries) = fs::read_dir(&defaults_dir) else {
            return;
        };
        for entry in entries.flatten() {
            let src = entry.path();
            if !src.is_dir() {
                continue;
            }
            let dst = home().join(".config").join(entry.file_name());
            if entry.file_name() == "noctalia" {
                restore_noctalia_config(&src, &dst);
                continue;
            }
            if dst.exists() {
                let _ = fs::remove_dir_all(&dst);
            }
            let _ = copy_dir_all(&src, &dst);
        }
    }

    /// Recarga waybar/mako/fuzzel (equivalente a _reload_services).
    /// Waybar y Mako solo si esa sesión los usa: si no, `reload(true)`
    /// arranca Waybar y `makoctl` queda zombi.
    pub fn reload_services() {
        if churros_services::noctalia::uses_waybar() {
            crate::services::waybar::WaybarService::reload(true);
        }
        if churros_services::noctalia::uses_mako() {
            crate::services::mako_config::MakoConfig::reload();
        }
        let _ = Command::new("pkill")
            .args(["-x", "fuzzel"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();
    }

    /// Settings defaults (paridad con SettingsService.DEFAULTS de Python).
    #[allow(dead_code)]
    pub fn defaults() -> Value {
        serde_json::json!({
            "theme": { "dark": true, "dynamic_colors": false },
            "accent": { "color": "Orange" },
            "wallpaper": { "path": "" },
            "icons": { "theme": "Papirus" },
            "cursor": { "theme": "Adwaita" },
            "fonts": { "family": "Inter", "scale": 1.0 }
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn restore_noctalia_keeps_live_toml_and_drops_extra_toml() {
        let tmp =
            std::env::temp_dir().join(format!("churros-noctalia-test-{}", std::process::id()));
        let src = tmp.join("defaults");
        let dst = tmp.join("config");
        fs::create_dir_all(&src).unwrap();
        fs::create_dir_all(&dst).unwrap();
        fs::write(src.join("config.toml"), "[bar.default]\n").unwrap();
        fs::write(dst.join("config.toml"), "editado").unwrap();
        fs::write(dst.join("live.toml"), "[lockscreen]\n").unwrap();
        fs::write(dst.join("extra.toml"), "[dock]\n").unwrap();

        restore_noctalia_config(&src, &dst);

        assert_eq!(
            fs::read_to_string(dst.join("config.toml")).unwrap(),
            "[bar.default]\n"
        );
        assert!(dst.join("live.toml").exists());
        assert!(!dst.join("extra.toml").exists());
        let _ = fs::remove_dir_all(&tmp);
    }
}

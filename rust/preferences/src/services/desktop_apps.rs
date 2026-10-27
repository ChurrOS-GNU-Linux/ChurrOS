// ==========================================
// DesktopApps — apps instaladas (.desktop) y su desinstalación
// (Pacman o Flatpak)
// ==========================================

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

/// Paquetes (o IDs de .desktop) que la página nunca ofrece desinstalar.
pub const PROTECTED_PACKAGES: &[&str] = &[
    "churros-settings",
    "churros-welcome",
    "calamares",
    "niri",
    "greetd",
    "foot",
    "noctalia",
];

#[derive(Debug, Clone)]
pub struct AppInfo {
    /// Flatpak: ID de la app (org.foo.Bar). Pacman: ID del .desktop.
    pub id: String,
    pub name: String,
    pub comment: String,
    /// Nombre de icono del tema o ruta absoluta.
    pub icon_name: String,
    /// Paquete pacman propietario del .desktop (vacío si no hay ninguno).
    pub package_name: String,
    pub is_flatpak: bool,
    /// Componente esencial de ChurrOS: no se puede desinstalar desde aquí.
    pub is_protected: bool,
}

fn is_protected(id: &str, package_name: &str) -> bool {
    PROTECTED_PACKAGES
        .iter()
        .any(|p| *p == package_name || *p == id)
}

struct Entry {
    path: PathBuf,
    name: String,
    comment: String,
    icon: String,
    flatpak_id: Option<String>,
}

/// Directorios en orden de prioridad creciente: un .desktop con el mismo
/// ID en un directorio posterior sustituye al anterior (como en XDG).
fn application_dirs() -> Vec<PathBuf> {
    let home = PathBuf::from(churros_services::home_dir());
    vec![
        PathBuf::from("/usr/share/applications"),
        PathBuf::from("/var/lib/flatpak/exports/share/applications"),
        home.join(".local/share/flatpak/exports/share/applications"),
        home.join(".local/share/applications"),
    ]
}

/// Parsea la sección [Desktop Entry]. None si no debe listarse.
fn parse_desktop(path: &Path) -> Option<Entry> {
    let text = fs::read_to_string(path).ok()?;

    let mut in_entry = false;
    let mut fields: HashMap<&str, &str> = HashMap::new();
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            in_entry = line == "[Desktop Entry]";
            continue;
        }
        if !in_entry || line.starts_with('#') {
            continue;
        }
        if let Some((k, v)) = line.split_once('=') {
            fields.entry(k.trim()).or_insert(v.trim());
        }
    }

    let is_true = |k: &str| fields.get(k).is_some_and(|v| v.eq_ignore_ascii_case("true"));
    if is_true("NoDisplay") || is_true("Hidden") {
        return None;
    }
    if fields.get("Type").is_some_and(|t| *t != "Application") {
        return None;
    }
    if fields.get("Exec").is_none_or(|e| e.is_empty()) {
        return None;
    }

    let localized = |k: &str| -> String {
        ["es_ES", "es"]
            .iter()
            .find_map(|l| fields.get(format!("{k}[{l}]").as_str()).copied())
            .or_else(|| fields.get(k).copied())
            .unwrap_or("")
            .to_string()
    };

    let name = localized("Name");
    if name.is_empty() {
        return None;
    }

    let exec = fields.get("Exec").copied().unwrap_or("");
    let path_str = path.to_string_lossy();
    let flatpak_id = fields
        .get("X-Flatpak")
        .map(|s| s.to_string())
        .or_else(|| {
            let in_exports = path_str.contains("/flatpak/exports/");
            (in_exports || exec.contains("flatpak run") || exec.contains("/flatpak run"))
                .then(|| desktop_id(path))
        })
        .filter(|s| !s.is_empty());

    Some(Entry {
        path: path.to_path_buf(),
        name,
        comment: localized("Comment"),
        icon: fields.get("Icon").copied().unwrap_or("").to_string(),
        flatpak_id,
    })
}

fn desktop_id(path: &Path) -> String {
    path.file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default()
}

/// Mapea cada ruta a su paquete pacman con una sola llamada a `pacman -Qo`.
fn pacman_owners(paths: &[&Path]) -> HashMap<PathBuf, String> {
    let mut owners = HashMap::new();
    if paths.is_empty() {
        return owners;
    }
    let Ok(out) = Command::new("pacman")
        .env("LC_ALL", "C")
        .arg("-Qo")
        .args(paths)
        .output()
    else {
        return owners;
    };
    // "<ruta> is owned by <paquete> <versión>"
    for line in String::from_utf8_lossy(&out.stdout).lines() {
        if let Some((file, rest)) = line.split_once(" is owned by ")
            && let Some(pkg) = rest.split_whitespace().next()
        {
            owners.insert(PathBuf::from(file), pkg.to_string());
        }
    }
    owners
}

pub fn list_installed_apps() -> Vec<AppInfo> {
    // ID del .desktop -> ruta (el último directorio gana)
    let mut by_id: HashMap<String, PathBuf> = HashMap::new();
    for dir in application_dirs() {
        let Ok(read) = fs::read_dir(&dir) else { continue };
        for entry in read.flatten() {
            let path = entry.path();
            if path.extension().is_some_and(|e| e == "desktop") {
                by_id.insert(desktop_id(&path), path);
            }
        }
    }

    let entries: Vec<Entry> = by_id.values().filter_map(|p| parse_desktop(p)).collect();

    let pacman_paths: Vec<&Path> = entries
        .iter()
        .filter(|e| e.flatpak_id.is_none())
        .map(|e| e.path.as_path())
        .collect();
    let owners = pacman_owners(&pacman_paths);

    let mut apps: Vec<AppInfo> = entries
        .into_iter()
        .map(|e| match e.flatpak_id {
            Some(fid) => AppInfo {
                id: fid.clone(),
                name: e.name,
                comment: e.comment,
                icon_name: e.icon,
                is_protected: is_protected(&fid, &fid),
                package_name: fid,
                is_flatpak: true,
            },
            None => {
                let id = desktop_id(&e.path);
                let package_name = owners.get(&e.path).cloned().unwrap_or_default();
                AppInfo {
                    is_protected: is_protected(&id, &package_name),
                    id,
                    package_name,
                    name: e.name,
                    comment: e.comment,
                    icon_name: e.icon,
                    is_flatpak: false,
                }
            }
        })
        .collect();

    apps.sort_by(|a, b| {
        a.name
            .to_lowercase()
            .cmp(&b.name.to_lowercase())
            .then_with(|| a.id.cmp(&b.id))
    });
    apps
}

/// Paquetes que impiden quitar `output` de pacman ("... required by <pkg>").
fn dependents_from_pacman(output: &str) -> Option<Vec<String>> {
    if !output.contains("could not satisfy dependencies") {
        return None;
    }
    let mut pkgs: Vec<String> = output
        .lines()
        .filter_map(|l| l.rsplit_once(" required by ").map(|(_, p)| p.trim().to_string()))
        .collect();
    pkgs.sort();
    pkgs.dedup();
    Some(pkgs)
}

fn dependents_error(pkgs: &[String]) -> String {
    const MAX: usize = 5;
    let mut msg = String::from("Otras aplicaciones instaladas dependen de este paquete");
    if !pkgs.is_empty() {
        msg.push_str(": ");
        msg.push_str(&pkgs.iter().take(MAX).cloned().collect::<Vec<_>>().join(", "));
        if pkgs.len() > MAX {
            msg.push_str(&format!(" y {} más", pkgs.len() - MAX));
        }
    }
    msg.push('.');
    msg
}

/// Simula la eliminación sin root (`pacman -Rsp`) para detectar
/// dependencias rotas antes de pedir la contraseña.
fn check_pacman_removal(package: &str) -> Result<(), String> {
    let Ok(out) = Command::new("pacman")
        .env("LC_ALL", "C")
        .args(["-Rsp", package])
        .output()
    else {
        return Ok(()); // sin simulación, decide la eliminación real
    };
    if out.status.success() {
        return Ok(());
    }
    let text = String::from_utf8_lossy(&out.stderr);
    match dependents_from_pacman(&text) {
        Some(pkgs) => Err(dependents_error(&pkgs)),
        None => Ok(()),
    }
}

pub fn uninstall_app(app: &AppInfo) -> Result<(), String> {
    if app.is_protected {
        return Err("Es un componente esencial del sistema".into());
    }
    let output = if app.is_flatpak {
        if app.id.is_empty() {
            return Err("ID de Flatpak vacío".into());
        }
        Command::new("flatpak")
            .args(["uninstall", "-y", &app.id])
            .output()
    } else {
        if app.package_name.is_empty() {
            return Err("La aplicación no pertenece a ningún paquete de pacman".into());
        }
        check_pacman_removal(&app.package_name)?;
        // pkexec conserva LC_ALL: los mensajes de pacman llegan en inglés
        // y se pueden interpretar.
        Command::new("pkexec")
            .env("LC_ALL", "C")
            .args(["/usr/bin/pacman", "-Rns", "--noconfirm", &app.package_name])
            .output()
    }
    .map_err(|e| format!("No se pudo ejecutar el comando: {e}"))?;

    if output.status.success() {
        return Ok(());
    }
    // pkexec: 126 = autenticación cancelada/denegada, 127 = no autorizado
    if !app.is_flatpak && matches!(output.status.code(), Some(126 | 127)) {
        return Err("Autenticación cancelada o denegada".into());
    }
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if !app.is_flatpak
        && let Some(pkgs) = dependents_from_pacman(&format!("{stderr}\n{stdout}"))
    {
        return Err(dependents_error(&pkgs));
    }
    let msg = if !stderr.is_empty() { stderr } else { stdout };
    Err(if msg.is_empty() {
        format!("El comando terminó con {}", output.status)
    } else {
        msg
    })
}

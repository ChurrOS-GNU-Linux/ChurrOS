// ==========================================
// UpdateService — actualizaciones de pacman + flatpak
// (timer de systemd + notificaciones vía mako)
// ==========================================

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use serde_json::json;

use crate::services::settings;

pub struct UpdateService;

/// Release de utilidades de ChurrOS (del updates.json del servidor).
#[derive(Debug, Clone, PartialEq)]
pub struct ChurrosUpdate {
    pub version: String,
    pub file: String,
    pub sha256: String,
}

/// La comprobación no pudo completarse: sin red, comando ausente, timeout...
///
/// Es distinto de "no hay actualizaciones": la página no puede decir "al día"
/// ni "0" cuando en realidad no sabe nada (#137).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CheckFailed;

/// Snapshot btrfs del sistema (rollback). Campos de `churros-snapshot list --json`.
#[derive(Debug, Clone, PartialEq)]
pub struct Snapshot {
    pub stamp: String,
    pub reason: String,
    pub date: String,
}

/// Parsea el updates.json del servidor de releases, seleccionando la edición correspondiente
/// (niri, xfce, kde o server) si está definida en el mapa "editions", o usando los campos globales como fallback.
fn parse_updates_json(raw: &str) -> Option<ChurrosUpdate> {
    let v: serde_json::Value = serde_json::from_str(raw).ok()?;
    let version = v.get("version")?.as_str()?.to_string();

    let edition = churros_services::version::edition();
    if let Some(editions) = v.get("editions").and_then(|e| e.as_object()) {
        if let Some(ed_info) = editions.get(&edition).or_else(|| editions.get("niri")) {
            if let (Some(file), Some(sha256)) = (
                ed_info.get("file").and_then(|f| f.as_str()),
                ed_info.get("sha256").and_then(|s| s.as_str()),
            ) {
                return Some(ChurrosUpdate {
                    version,
                    file: file.to_string(),
                    sha256: sha256.to_string(),
                });
            }
        }
    }

    Some(ChurrosUpdate {
        version,
        file: v.get("file")?.as_str()?.to_string(),
        sha256: v.get("sha256")?.as_str()?.to_string(),
    })
}

fn home() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home)
}

fn user_systemd_dir() -> PathBuf {
    home().join(".config").join("systemd").join("user")
}

/// Ejecuta un comando con timeout y captura stdout (salida pequeña).
fn run_capture(args: &[&str], timeout_secs: u64) -> Option<String> {
    let mut child = Command::new(args[0])
        .args(&args[1..])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;

    // Drenar stdout en un thread mientras esperamos: evita el deadlock por
    // pipe lleno en comandos con mucha salida.
    let mut out_pipe = child.stdout.take();
    let reader = std::thread::spawn(move || {
        use std::io::Read;
        let mut buf = String::new();
        if let Some(mut out) = out_pipe.take() {
            let _ = out.read_to_string(&mut buf);
        }
        buf
    });

    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break st,
            Ok(None) => {
                if Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    return None;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(_) => return None,
        }
    };

    let _ = child.wait();
    let buf = reader.join().unwrap_or_default();
    if !status.success() {
        return None;
    }
    Some(buf.trim().to_string())
}

/// Líneas no vacías de una salida.
fn lines(out: &str) -> Vec<String> {
    out.lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .map(String::from)
        .collect()
}

/// Interpreta `checkupdates`: sale con 0 y la lista, con 2 si no hay nada que
/// actualizar y con cualquier otro código si falla (sin red, sin fakeroot...).
fn parse_checkupdates(
    result: Option<churros_services::RunOut>,
) -> Result<Vec<String>, CheckFailed> {
    match result {
        Some((0, out, _)) => Ok(lines(&out)),
        Some((2, _, _)) => Ok(Vec::new()),
        _ => Err(CheckFailed),
    }
}

/// Interpreta `pacman -Qu`: sale con 1 tanto si no hay nada que actualizar
/// como si falla; solo stderr los distingue.
fn parse_pacman_qu(result: Option<churros_services::RunOut>) -> Result<Vec<String>, CheckFailed> {
    match result {
        Some((0, out, _)) => Ok(lines(&out)),
        Some((1, out, err)) if out.trim().is_empty() && err.trim().is_empty() => Ok(Vec::new()),
        _ => Err(CheckFailed),
    }
}

/// Ejecuta un comando con streaming: llama `cb` con cada línea de salida
/// (stdout+stderr combinados) según se produce. Evita el deadlock del pipe
/// leyendo ambos en threads mientras el proceso corre.
fn run_streaming(args: &[&str], cb: &dyn Fn(&str)) -> bool {
    let mut child = match Command::new(args[0])
        .args(&args[1..])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(_) => return false,
    };

    fn spawn_reader<R: std::io::Read + Send + 'static>(stream: R, tx: mpsc::Sender<String>) {
        std::thread::spawn(move || {
            let reader = BufReader::new(stream);
            for line in reader.lines().map_while(Result::ok) {
                if tx.send(line).is_err() {
                    break;
                }
            }
        });
    }

    let (tx, rx) = mpsc::channel::<String>();
    if let Some(s) = child.stdout.take() {
        spawn_reader(s, tx.clone());
    }
    if let Some(e) = child.stderr.take() {
        spawn_reader(e, tx.clone());
    }
    drop(tx);

    while let Ok(line) = rx.recv() {
        cb(&line);
    }

    child.wait().map(|s| s.success()).unwrap_or(false)
}

impl UpdateService {
    // -------------------------------------------------------- settings

    pub fn enabled() -> bool {
        settings::get_bool("updates.enabled", true)
    }

    pub fn set_enabled(enabled: bool) {
        settings::set("updates.enabled", json!(enabled));
    }

    pub fn interval() -> String {
        settings::get_string("updates.interval", "daily")
    }

    pub fn set_interval(interval: &str) {
        settings::set("updates.interval", json!(interval));
    }

    fn on_calendar(interval: &str) -> &'static str {
        match interval {
            "weekly" => "Mon *-*-* 04:00:00",
            "monthly" => "*-*-01 04:00:00",
            _ => "*-*-* 04:00:00",
        }
    }

    // -------------------------------------------------------- checks

    /// Paquetes de pacman con actualización pendiente.
    ///
    /// Usa `checkupdates` (pacman-contrib): sincroniza una copia temporal de
    /// las bases sin root. Antes se hacía `pacman -Sy` como root solo para
    /// refrescar, que deja el sistema expuesto a una actualización parcial y
    /// necesitaba pkexec (#137). Sin pacman-contrib (instalaciones previas) se
    /// recurre a `pacman -Qu`, que compara con la última sincronización.
    pub fn check_pacman() -> Result<Vec<String>, CheckFailed> {
        if churros_services::which("checkupdates") {
            parse_checkupdates(churros_services::run(&["checkupdates"], 120_000))
        } else {
            parse_pacman_qu(churros_services::run(&["pacman", "-Qu"], 30_000))
        }
    }

    /// Actualizaciones de flatpak (`flatpak remote-ls --updates`).
    pub fn check_flatpak() -> Result<Vec<String>, CheckFailed> {
        run_capture(&["flatpak", "remote-ls", "--updates"], 30)
            .map(|out| lines(&out))
            .ok_or(CheckFailed)
    }

    // -------------------------------------------------------- updates
    //
    // Lo que pasa por churros-pkexec va con ruta absoluta y el argv exacto que
    // autoriza la regla polkit (50-churros-store.rules). Si cambias un argv,
    // cambia también la regla y scripts/test-polkit-rules.js.

    pub fn update_pacman(cb: &dyn Fn(&str)) -> bool {
        run_streaming(
            &["churros-pkexec", "/usr/bin/pacman", "-Syu", "--noconfirm"],
            cb,
        )
    }

    pub fn update_flatpak(cb: &dyn Fn(&str)) -> bool {
        run_streaming(&["churros-pkexec", "/usr/bin/flatpak", "update", "-y"], cb)
    }

    // ------------------------------------------- utilidades de ChurrOS

    /// URL base del servidor de releases de utilidades de ChurrOS.
    ///
    /// El origen está fijado en el binario a propósito. Antes se leía de
    /// `~/.config/churros/settings.json` (`updates.churros_url`), un fichero
    /// que escribe el usuario, y esa URL se pasaba tal cual al helper root
    /// `churros-update-utils`, que descarga y extrae sobre `/`: cualquiera
    /// podía lograr que root instalara un tarball arbitrario desde un host
    /// propio (y el sha256 del manifiesto venía del mismo origen no
    /// autenticado, así que no compensaba nada).
    ///
    /// Para mirrors corporativos o de test existe `CHURROS_UPDATE_BASE_URL`,
    /// que solo se aplica si `CHURROS_UPDATE_ALLOW_MIRROR=1` está en el
    /// entorno; pkexec y sudo limpian el entorno, así que un usuario no
    /// puede influir en ella desde la sesión gráfica.
    pub fn churros_url() -> String {
        const PINNED: &str = "https://download.churroslinux.org/churros/";
        match std::env::var("CHURROS_UPDATE_BASE_URL") {
            Ok(base)
                if std::env::var("CHURROS_UPDATE_ALLOW_MIRROR")
                    .ok()
                    .as_deref()
                    == Some("1") =>
            {
                let trimmed = base.trim();
                if trimmed.starts_with("https://") {
                    return format!("{}/", trimmed.trim_end_matches('/'));
                }
                PINNED.to_string()
            }
            _ => PINNED.to_string(),
        }
    }

    /// Versión instalada de las utilidades (lee /etc/churros-version).
    pub fn installed_churros_version() -> String {
        std::fs::read_to_string("/etc/churros-version")
            .map(|s| s.trim().to_string())
            .unwrap_or_else(|_| "?".to_string())
    }

    /// Comprueba si hay una versión nueva de las utilidades de ChurrOS.
    /// `Ok(Some)`: hay actualización (versión != instalada); `Ok(None)`: al
    /// día; `Err`: no se pudo descargar o leer el manifiesto.
    pub fn check_churros() -> Result<Option<ChurrosUpdate>, CheckFailed> {
        let base = Self::churros_url();
        let url = format!("{base}updates.json");
        let out = run_capture(
            &[
                "curl",
                "-fsSL",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--connect-timeout",
                "10",
                url.as_str(),
            ],
            15,
        )
        .ok_or(CheckFailed)?;
        let update = parse_updates_json(&out).ok_or(CheckFailed)?;
        if update.version == Self::installed_churros_version() {
            Ok(None)
        } else {
            Ok(Some(update))
        }
    }

    /// Actualiza las utilidades de ChurrOS vía churros-update-utils (root).
    ///
    /// No se le pasa la URL: `churros-update-utils` la tiene fijada y rechaza
    /// cualquier argumento.
    pub fn update_churros(cb: &dyn Fn(&str)) -> bool {
        run_streaming(&["churros-pkexec", "/usr/bin/churros-update-utils"], cb)
    }

    // ------------------------------------------------ snapshots (rollback)

    /// Lista los snapshots btrfs disponibles (vía churros-snapshot, root).
    pub fn list_snapshots() -> Vec<Snapshot> {
        let Some(out) = run_capture(
            &[
                "churros-pkexec",
                "/usr/local/bin/churros-snapshot",
                "list",
                "--json",
            ],
            30,
        ) else {
            return Vec::new();
        };
        let Ok(value) = serde_json::from_str::<serde_json::Value>(&out) else {
            return Vec::new();
        };
        let Some(items) = value.as_array() else {
            return Vec::new();
        };
        items
            .iter()
            .filter_map(|item| {
                Some(Snapshot {
                    stamp: item.get("stamp")?.as_str()?.to_string(),
                    reason: item
                        .get("reason")
                        .and_then(|r| r.as_str())
                        .unwrap_or_default()
                        .to_string(),
                    date: item
                        .get("date")
                        .and_then(|d| d.as_str())
                        .unwrap_or_default()
                        .to_string(),
                })
            })
            .collect()
    }

    /// Crea un snapshot btrfs manual (razón "manual").
    pub fn create_snapshot() -> bool {
        run_streaming(
            &[
                "churros-pkexec",
                "/usr/local/bin/churros-snapshot",
                "create",
                "manual",
            ],
            &|_| {},
        )
    }

    /// Elimina un snapshot btrfs por su stamp.
    pub fn delete_snapshot(stamp: &str) -> bool {
        run_streaming(
            &[
                "churros-pkexec",
                "/usr/local/bin/churros-snapshot",
                "delete",
                stamp,
            ],
            &|_| {},
        )
    }

    // -------------------------------------------------------- timer

    /// Aplica el estado actual (enabled + intervalo) al timer de systemd.
    /// Escribe el drop-in con el OnCalendar y habilita/deshabilita el timer.
    pub fn apply_timer() {
        let drop_in_dir = user_systemd_dir().join("churros-update.timer.d");
        let _ = std::fs::create_dir_all(&drop_in_dir);
        let oncalendar = Self::on_calendar(&Self::interval());
        let content = format!("[Timer]\nOnCalendar={oncalendar}\n");
        let _ = std::fs::write(drop_in_dir.join("schedule.conf"), content);

        let _ = Command::new("systemctl")
            .args(["--user", "daemon-reload"])
            .status();

        if Self::enabled() {
            let _ = Command::new("systemctl")
                .args(["--user", "enable", "--now", "churros-update.timer"])
                .status();
        } else {
            let _ = Command::new("systemctl")
                .args(["--user", "disable", "--now", "churros-update.timer"])
                .status();
        }
    }

    /// Habilita el timer por primera vez si está activado y aún no enabled.
    pub fn ensure_timer() {
        if !Self::enabled() {
            return;
        }
        let active = Command::new("systemctl")
            .args(["--user", "is-enabled", "churros-update.timer"])
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
        if !active {
            Self::apply_timer();
        }
    }

    // -------------------------------------------------------- notify

    pub fn notify(summary: &str, body: &str) {
        let _ = Command::new("notify-send")
            .args(["-a", "ChurrOS", summary, body])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_updates_json_valid() {
        let raw = r#"{
            "version": "1.0",
            "date": "2026-08-20",
            "file": "churros-utils-1.0.tar.zst",
            "sha256": "abc123"
        }"#;
        let u = parse_updates_json(raw).unwrap();
        assert_eq!(u.version, "1.0");
        assert_eq!(u.file, "churros-utils-1.0.tar.zst");
        assert_eq!(u.sha256, "abc123");
    }

    #[test]
    fn parse_updates_json_invalid() {
        assert!(parse_updates_json("not json").is_none());
        assert!(parse_updates_json(r#"{"version":"1.0"}"#).is_none());
    }

    fn out(code: i32, stdout: &str, stderr: &str) -> Option<churros_services::RunOut> {
        Some((code, stdout.to_string(), stderr.to_string()))
    }

    #[test]
    fn checkupdates_distinguishes_none_from_failure() {
        assert_eq!(
            parse_checkupdates(out(0, "linux 6.1-1 -> 6.2-1\nmesa 1-1 -> 2-1\n", "")),
            Ok(vec![
                "linux 6.1-1 -> 6.2-1".to_string(),
                "mesa 1-1 -> 2-1".to_string()
            ])
        );
        assert_eq!(parse_checkupdates(out(2, "", "")), Ok(Vec::new()));
        assert_eq!(
            parse_checkupdates(out(1, "", "==> ERROR: Cannot fetch updates")),
            Err(CheckFailed)
        );
        assert_eq!(parse_checkupdates(None), Err(CheckFailed));
    }

    #[test]
    fn pacman_qu_distinguishes_none_from_failure() {
        assert_eq!(
            parse_pacman_qu(out(0, "linux 6.1-1 -> 6.2-1\n", "")).map(|v| v.len()),
            Ok(1)
        );
        assert_eq!(parse_pacman_qu(out(1, "", "")), Ok(Vec::new()));
        assert_eq!(
            parse_pacman_qu(out(1, "", "error: failed to init transaction")),
            Err(CheckFailed)
        );
        assert_eq!(parse_pacman_qu(None), Err(CheckFailed));
    }
}

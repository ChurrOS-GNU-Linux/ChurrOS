// ==========================================
// UpdateService — actualizaciones de pacman + flatpak
// (timer de systemd + notificaciones vía mako)
// ==========================================

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::os::unix::process::CommandExt;
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use serde_json::json;

use crate::services::settings;

/// `remote` es una versión estrictamente más nueva que `installed`
/// (1.5.10 > 1.5.9 > 1.5). Igual que churros-update-utils, que ya no
/// instala una versión más antigua: un updates.json viejo no se ofrece.
/// Sin versión instalada legible, cualquier versión válida es nueva.
pub(crate) fn version_is_newer(remote: &str, installed: &str) -> bool {
    fn parts(v: &str) -> Option<Vec<u64>> {
        v.trim().split('.').map(|p| p.parse().ok()).collect()
    }
    match (parts(remote), parts(installed)) {
        (None, _) => false,
        (Some(_), None) => true,
        (Some(mut r), Some(mut i)) => {
            let len = r.len().max(i.len());
            r.resize(len, 0);
            i.resize(len, 0);
            r > i
        }
    }
}

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

/// Resultado de listar snapshots: Ajustes distingue «no hay», «no se pudo
/// leer» y «el sistema no está en btrfs» (#338).
#[derive(Debug, Clone, PartialEq)]
pub enum SnapshotList {
    Ready(Vec<Snapshot>),
    NotBtrfs,
    Failed,
}

/// Como `is_automatic` de churros-snapshot: la retención solo borra estos.
pub fn is_automatic_reason(reason: &str) -> bool {
    reason == "pacman-pre" || reason.starts_with("churros-utils-pre-")
}

/// Tipo del sistema de ficheros montado en `/` según /proc/self/mounts
/// (la última línea gana, como en el kernel).
pub fn root_fstype(mounts: &str) -> Option<String> {
    mounts
        .lines()
        .rev()
        .find_map(|line| {
            let mut f = line.split_whitespace();
            let (_, target, fstype) = (f.next()?, f.next()?, f.next()?);
            (target == "/").then(|| fstype.to_string())
        })
}

fn human_bytes(bytes: u64) -> String {
    let units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let (mut value, mut i) = (bytes as f64, 0);
    while value >= 1024.0 && i < units.len() - 1 {
        value /= 1024.0;
        i += 1;
    }
    if i == 0 { format!("{bytes} B") } else { format!("{value:.1} {}", units[i]).replace('.', ",") }
}

/// Resumen de la lista de snapshots para Ajustes. No suma tamaños: en btrfs
/// los snapshots comparten bloques y no hay un «cuánto ocupan» exacto sin
/// recorrer cada uno (segundos por snapshot); eso lo da
/// `churros-snapshot cleanup --dry-run` (#338).
pub fn snapshot_summary(list: &[Snapshot], space: Option<(u64, u64)>) -> String {
    let auto = list.iter().filter(|s| is_automatic_reason(&s.reason)).count();
    let manual = list.len() - auto;
    let mut text = match list.len() {
        0 => "Ningún snapshot todavía.".to_string(),
        n => {
            let oldest = list.iter().map(|s| s.date.as_str()).filter(|d| !d.is_empty()).min().unwrap_or("?");
            let plural = |k: usize, one: &str, many: &str| format!("{k} {}", if k == 1 { one } else { many });
            format!(
                "{} ({}, {}); el más antiguo es del {oldest}.",
                plural(n, "snapshot", "snapshots"),
                plural(auto, "automático", "automáticos"),
                plural(manual, "manual", "manuales")
            )
        }
    };
    if let Some((avail, total)) = space {
        text.push_str(&format!(" Libre en el disco: {} de {} (aproximado en btrfs).", human_bytes(avail), human_bytes(total)));
        if total > 0 && avail * 10 < total {
            text.push_str(" Queda poco espacio: borra snapshots que no necesites.");
        }
    }
    text.push_str(" Los snapshots comparten datos con el sistema, así que no se puede decir exactamente cuánto ocupan; \
                   para ver cuánto liberaría la limpieza: sudo churros-snapshot cleanup --dry-run");
    text
}

/// Espacio libre y total del sistema de ficheros de `/` (statvfs).
pub fn root_space() -> Option<(u64, u64)> {
    let path = std::ffi::CString::new("/").ok()?;
    let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
    if unsafe { libc::statvfs(path.as_ptr(), &mut st) } != 0 {
        return None;
    }
    let frsize = st.f_frsize as u64;
    Some((st.f_bavail as u64 * frsize, st.f_blocks as u64 * frsize))
}

/// Parsea `churros-snapshot list --json`; None si no es una lista JSON.
pub fn parse_snapshot_list(out: &str) -> Option<Vec<Snapshot>> {
    let value = serde_json::from_str::<serde_json::Value>(out).ok()?;
    Some(
        value
            .as_array()?
            .iter()
            .filter_map(|item| {
                Some(Snapshot {
                    stamp: item.get("stamp")?.as_str()?.to_string(),
                    reason: item.get("reason").and_then(|r| r.as_str()).unwrap_or_default().to_string(),
                    date: item.get("date").and_then(|d| d.as_str()).unwrap_or_default().to_string(),
                })
            })
            .collect(),
    )
}

/// Parsea el updates.json del servidor de releases, seleccionando la edición correspondiente
/// (niri, xfce o server) si está definida en el mapa "editions", o usando los campos globales como fallback.
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
    churros_services::home_path()
}

fn user_systemd_dir() -> PathBuf {
    home().join(".config").join("systemd").join("user")
}

/// Paquetes instalados empaquetados por CachyOS que Arch también tiene
/// (`pacman -Qi` y `pacman -Sl`). Las ISO 1.4 y 1.5 los instalaron con
/// [cachyos] delante de [core] y ya no se actualizan; churros-update-utils
/// los devuelve a Arch (reparación única). Lo que solo tiene CachyOS
/// (linux-cachyos, cachyos-*) no cuenta.
fn repair_candidates(query_info: &str, sync_list: &str) -> Vec<String> {
    let arch: std::collections::HashSet<&str> = sync_list
        .lines()
        .filter_map(|line| {
            let mut fields = line.split_whitespace();
            match (fields.next(), fields.next()) {
                (Some("core" | "extra" | "multilib"), Some(name)) => Some(name),
                _ => None,
            }
        })
        .collect();
    let mut name: Option<&str> = None;
    let mut out = Vec::new();
    for line in query_info.lines() {
        let Some((key, value)) = line.split_once(':') else { continue };
        match key.trim() {
            "Name" => name = Some(value.trim()),
            "Packager" if value.contains("CachyOS") => {
                if let Some(n) = name.take().filter(|n| arch.contains(n)) {
                    out.push(n.to_string());
                }
            }
            _ => {}
        }
    }
    out.sort();
    out
}

/// ¿linux-cachyos instalado sin [cachyos] en pacman.conf? (el kernel no se actualiza)
fn kernel_without_repo(installed_kernel: bool, pacman_conf: &str) -> bool {
    installed_kernel && !pacman_conf.lines().any(|line| line.trim() == "[cachyos]")
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

/// Resumen de paccache: nº de paquetes y espacio ("1.69 GiB").
#[derive(Debug, PartialEq)]
struct PaccacheSummary {
    count: u64,
    size: String,
}

/// "==> finished dry run: 354 candidates (disk space saved: 1.69 GiB)"
/// "==> finished: 354 packages removed (disk space saved: 1.69 GiB)"
/// "==> no candidate packages found for pruning"
fn parse_paccache(output: &str) -> Option<PaccacheSummary> {
    if output.contains("no candidate packages found") {
        return Some(PaccacheSummary { count: 0, size: "0 B".to_string() });
    }
    let line = output.lines().find(|l| l.contains("(disk space saved:"))?;
    let (head, tail) = line.split_once("(disk space saved:")?;
    let size = tail.trim().trim_end_matches(')').trim().to_string();
    let count = head
        .rsplit_once(':')
        .map(|(_, r)| r)
        .unwrap_or(head)
        .split_whitespace()
        .find_map(|w| w.parse::<u64>().ok())?;
    Some(PaccacheSummary { count, size })
}

/// Primera línea útil de un error (sin el prefijo "error:" / "==> ERROR:").
fn first_error_line(stderr: &str, stdout: &str) -> Option<String> {
    [stderr, stdout]
        .iter()
        .flat_map(|s| s.lines())
        .map(str::trim)
        .find(|l| !l.is_empty())
        .map(|l| {
            l.trim_start_matches("==>")
                .trim()
                .trim_start_matches("ERROR:")
                .trim_start_matches("error:")
                .trim()
                .to_string()
        })
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
fn run_streaming(args: &[&str], timeout: Duration, cb: &dyn Fn(&str)) -> bool {
    let Some((program, command_args)) = args.split_first() else {
        return false;
    };
    let mut child = match Command::new(program)
        .args(command_args)
        .process_group(0)
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

    let deadline = Instant::now() + timeout;
    loop {
        match rx.recv_timeout(Duration::from_millis(100)) {
            // lines() quita el salto: sin devolverlo, el registro de Ajustes
            // juntaba todas las líneas en un solo párrafo.
            Ok(line) => cb(&format!("{line}\n")),
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
            Err(mpsc::RecvTimeoutError::Timeout) if Instant::now() >= deadline => {
                unsafe {
                    libc::kill(-(child.id() as i32), libc::SIGKILL);
                }
                let _ = child.wait();
                return false;
            }
            Err(mpsc::RecvTimeoutError::Timeout) => {}
        }
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
            Duration::from_secs(30 * 60),
            cb,
        )
    }

    pub fn update_flatpak(cb: &dyn Fn(&str)) -> bool {
        run_streaming(
            &["churros-pkexec", "/usr/bin/flatpak", "update", "-y"],
            Duration::from_secs(30 * 60),
            cb,
        )
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
        if version_is_newer(&update.version, &Self::installed_churros_version()) {
            Ok(Some(update))
        } else {
            Ok(None)
        }
    }

    /// Actualiza las utilidades de ChurrOS vía churros-update-utils (root).
    ///
    /// No se le pasa la URL: `churros-update-utils` la tiene fijada y rechaza
    /// cualquier argumento.
    pub fn update_churros(cb: &dyn Fn(&str)) -> bool {
        run_streaming(
            &["churros-pkexec", "/usr/bin/churros-update-utils"],
            Duration::from_secs(10 * 60),
            cb,
        )
    }

    /// Reparación pendiente de las ISO 1.4/1.5: paquetes de CachyOS que Arch
    /// tiene (y, si el kernel no tiene repositorio, linux-cachyos). Vacía si
    /// no hay nada que hacer o en el Live.
    ///
    /// Si `pacman -Qi` o `pacman -Sl` fallan (base de datos bloqueada, timeout),
    /// devuelve None en vez de una lista vacía: antes `unwrap_or_default()`
    /// colapsaba el fallo a cadena vacía y una base bloqueada se presentaba
    /// como "no hay nada que reparar" (auditoría V6).
    pub fn repair_pending() -> Option<Vec<String>> {
        if std::path::Path::new("/run/archiso").exists() {
            return Some(Vec::new());
        }
        // El código de salida importa: `run` devuelve None en timeout o error
        // de ejecución, y un pacman que falla no da la lista de paquetes.
        // RunOut es (código, stdout, stderr). La lista sale por stdout; el
        // código de salida distingue «no hay nada» de «pacman no pudo mirar».
        let (query_code, query, _) = churros_services::run(&["pacman", "-Qi"], 30_000)?;
        let (sync_code, sync, _) = churros_services::run(&["pacman", "-Sl"], 30_000)?;
        if query_code != 0 || sync_code != 0 {
            return None;
        }
        let mut pending = repair_candidates(&query, &sync);
        let kernel = churros_services::run(&["pacman", "-Q", "linux-cachyos"], 5_000).is_some_and(|r| r.0 == 0);
        let conf = std::fs::read_to_string("/etc/pacman.conf").unwrap_or_default();
        if kernel_without_repo(kernel, &conf) {
            pending.push("linux-cachyos".to_string());
        }
        Some(pending)
    }

    /// 1.4/1.5 instaladas: se coló el llavero de pacman en memoria del Live
    /// (se regenera en cada arranque). La reparación lo quita.
    pub fn live_keyring_pending() -> bool {
        !std::path::Path::new("/run/archiso").exists()
            && std::path::Path::new("/etc/systemd/system/etc-pacman.d-gnupg.mount").exists()
    }

    // ------------------------------------------------ snapshots (rollback)

    /// Lista los snapshots btrfs disponibles (vía churros-snapshot, root).
    pub fn list_snapshots() -> SnapshotList {
        let mounts = std::fs::read_to_string("/proc/self/mounts").unwrap_or_default();
        if root_fstype(&mounts).is_some_and(|fs| fs != "btrfs") {
            return SnapshotList::NotBtrfs;
        }
        let Some(out) = run_capture(
            &[
                "churros-pkexec",
                "/usr/local/bin/churros-snapshot",
                "list",
                "--json",
            ],
            30,
        ) else {
            return SnapshotList::Failed;
        };
        match parse_snapshot_list(&out) {
            Some(list) => SnapshotList::Ready(list),
            None => SnapshotList::Failed,
        }
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
            Duration::from_secs(5 * 60),
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
            Duration::from_secs(5 * 60),
            &|_| {},
        )
    }

    // -------------------------------------------------------- timer

    // ---------- Limpieza ----------

    /// Espacio que liberaría `clean_cache()`: simulación con la misma
    /// retención (`-k1`). None si paccache no está o falla.
    pub fn check_cache_cleanup() -> Option<String> {
        let (code, out, err) =
            churros_services::run(&["paccache", "-dk1", "--nocolor"], 30_000)?;
        if code != 0 {
            return None;
        }
        let summary = parse_paccache(&format!("{out}\n{err}"))?;
        Some(match summary {
            PaccacheSummary { count: 0, .. } => "Caché al día (0 B recuperables)".to_string(),
            PaccacheSummary { count, size } => {
                format!("{size} recuperables ({count} paquetes antiguos)")
            }
        })
    }

    /// Borra las versiones antiguas de la caché de pacman (conserva la última).
    pub fn clean_cache() -> Result<String, String> {
        let (code, out, err) =
            churros_services::run(&["pkexec", "/usr/bin/paccache", "-rk1"], 0)
                .ok_or("No se pudo ejecutar paccache")?;
        match code {
            0 => Ok(match parse_paccache(&format!("{out}\n{err}")) {
                Some(PaccacheSummary { count: 0, .. }) | None => {
                    "No había versiones antiguas que borrar".to_string()
                }
                Some(PaccacheSummary { count, size }) => {
                    format!("{size} liberados ({count} paquetes eliminados)")
                }
            }),
            126 | 127 => Err("Autenticación cancelada".to_string()),
            _ => Err(first_error_line(&err, &out)
                .unwrap_or_else(|| format!("paccache terminó con código {code}"))),
        }
    }

    /// Quita runtimes y extensiones de Flatpak que ya no usa ninguna app.
    pub fn clean_unused_flatpaks() -> Result<(), String> {
        if !churros_services::which("flatpak") {
            return Err("Flatpak no está instalado".to_string());
        }
        let (code, out, err) =
            churros_services::run(&["flatpak", "uninstall", "--unused", "-y"], 0)
                .ok_or("No se pudo ejecutar flatpak")?;
        if code == 0 {
            Ok(())
        } else {
            Err(first_error_line(&err, &out)
                .unwrap_or_else(|| format!("flatpak terminó con código {code}")))
        }
    }

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

    #[test]
    fn only_a_newer_churros_version_is_offered() {
        // [updates-only-newer] una copia vieja de updates.json no ofrece bajar de versión
        assert!(version_is_newer("1.5.6", "1.5.5"));
        assert!(version_is_newer("1.5.10", "1.5.9"));
        assert!(version_is_newer("1.6", "1.5.9"));
        assert!(version_is_newer("1.5.1", "1.5"));
        assert!(version_is_newer("1.5.5", ""), "sin versión instalada");
        assert!(!version_is_newer("1.5.5", "1.5.6"), "[updates-only-newer] ofrece bajar de versión");
        assert!(!version_is_newer("1.5.6", "1.5.6"));
        assert!(!version_is_newer("1.5", "1.5.0"));
        assert!(!version_is_newer("x", "1.5"));
    }
    use super::*;

    fn snap(stamp: &str, reason: &str, date: &str) -> Snapshot {
        Snapshot { stamp: stamp.into(), reason: reason.into(), date: date.into() }
    }

    #[test]
    fn snapshot_summary_counts_and_never_sums_sizes() {
        let list = vec![
            snap("20261102-000000", "pacman-pre", "2026-11-02 00:00:00"),
            snap("20261101-000000", "manual", "2026-11-01 00:00:00"),
            snap("20261103-000000", "churros-utils-pre-1.5.7", "2026-11-03 00:00:00"),
        ];
        let text = snapshot_summary(&list, Some((50 << 30, 100 << 30)));
        assert!(text.contains("3 snapshots (2 automáticos, 1 manual)"), "[snapshot-summary] {text}");
        let one = snapshot_summary(&list[..1], None);
        assert!(one.starts_with("1 snapshot (1 automático, 0 manuales)"), "[snapshot-summary] {one}");
        assert!(text.contains("el más antiguo es del 2026-11-01"), "[snapshot-summary] {text}");
        assert!(text.contains("Libre en el disco: 50,0 GiB de 100,0 GiB"), "[snapshot-summary] {text}");
        assert!(text.contains("aproximado"), "[snapshot-summary] tiene que rotularse como estimación");
        assert!(text.contains("cleanup --dry-run"), "[snapshot-summary] remite a la vista previa exacta");
        assert!(!text.contains("Queda poco espacio"));
        let low = snapshot_summary(&list, Some((5 << 30, 100 << 30)));
        assert!(low.contains("Queda poco espacio"), "[snapshot-summary] avisa con menos del 10 % libre");
        assert!(snapshot_summary(&[], None).starts_with("Ningún snapshot"), "[snapshot-summary] estado vacío");
    }

    #[test]
    fn automatic_reasons_match_churros_snapshot() {
        assert!(is_automatic_reason("pacman-pre"));
        assert!(is_automatic_reason("churros-utils-pre-1.5.7"));
        assert!(!is_automatic_reason("manual"));
        assert!(!is_automatic_reason("antes-de-probar"));
    }

    #[test]
    fn root_fstype_takes_the_last_mount_of_root() {
        let mounts = "proc /proc proc rw 0 0\n/dev/sda2 / ext4 rw 0 0\n/dev/sda3 / btrfs rw,subvol=/@ 0 0\n";
        assert_eq!(root_fstype(mounts).as_deref(), Some("btrfs"));
        assert_eq!(root_fstype("/dev/sda2 / ext4 rw 0 0\n").as_deref(), Some("ext4"));
        assert_eq!(root_fstype(""), None);
    }

    #[test]
    fn snapshot_list_parse_failure_is_not_an_empty_list() {
        // [snapshot-list-failed] un error (p. ej. pkexec denegado) no se enseña como «sin snapshots»
        assert_eq!(parse_snapshot_list("[]"), Some(vec![]));
        assert_eq!(parse_snapshot_list("no es json"), None, "[snapshot-list-failed]");
        assert_eq!(
            parse_snapshot_list(r#"[{"stamp":"20261101-000000","reason":"manual","date":"2026-11-01 00:00:00"}]"#),
            Some(vec![snap("20261101-000000", "manual", "2026-11-01 00:00:00")])
        );
    }

    #[test]
    fn streamed_lines_keep_their_newline() {
        let out = std::cell::RefCell::new(String::new());
        let ok = run_streaming(
            &["sh", "-c", "printf 'uno\\ndos\\n'"],
            Duration::from_secs(10),
            &|line| out.borrow_mut().push_str(line),
        );
        assert!(ok);
        assert_eq!(out.into_inner(), "uno\ndos\n", "cada línea del registro, en su línea");
    }

    #[test]
    fn repair_finds_cachyos_builds_that_arch_also_ships() {
        let query = "Name            : pacman\nVersion         : 7.1.0.r9.g54d9411-6\nPackager        : CachyOS <admin@cachyos.org>\n\n\
                     Name            : mesa\nPackager        : CachyOS <admin@cachyos.org>\n\n\
                     Name            : linux-cachyos\nPackager        : CachyOS <admin@cachyos.org>\n\n\
                     Name            : firefox\nPackager        : Jan Alexander Steffens (heftig) <heftig@archlinux.org>\n\n\
                     Name            : lib32-mesa\nPackager        : CachyOS <admin@cachyos.org>\n";
        let sync = "core pacman 7.1.0-3\nextra mesa 1:26.2.7-1\nextra firefox 160.0-1\n\
                    multilib lib32-mesa 1:26.2.7-1\ncachyos linux-cachyos 7.3.3-1\ncachyos mesa 3:26.2.6-1\n";
        assert_eq!(repair_candidates(query, sync), ["lib32-mesa", "mesa", "pacman"]);
        // Sistema sano (ISO nueva o ya reparado): nada.
        let healthy = "Name            : pacman\nPackager        : Pierre Schmitz <pierre@archlinux.org>\n";
        assert!(repair_candidates(healthy, sync).is_empty());
        // Sin base de datos sincronizada no se puede saber: nada (no hay falsa alarma).
        assert!(repair_candidates(query, "").is_empty());
        assert!(kernel_without_repo(true, "[core]\nInclude = x\n"));
        assert!(!kernel_without_repo(true, "[core]\n\n[cachyos]\nInclude = /etc/pacman.d/cachyos-mirrorlist\n"));
        assert!(!kernel_without_repo(false, "[core]\n"));
    }

    #[test]
    fn paccache_summaries() {
        assert_eq!(
            parse_paccache("\n==> finished dry run: 354 candidates (disk space saved: 1.69 GiB)\n"),
            Some(PaccacheSummary { count: 354, size: "1.69 GiB".into() })
        );
        assert_eq!(
            parse_paccache("==> finished: 12 packages removed (disk space saved: 80.5 MiB)"),
            Some(PaccacheSummary { count: 12, size: "80.5 MiB".into() })
        );
        assert_eq!(
            parse_paccache("==> no candidate packages found for pruning"),
            Some(PaccacheSummary { count: 0, size: "0 B".into() })
        );
        assert_eq!(parse_paccache("algo raro"), None);
    }

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

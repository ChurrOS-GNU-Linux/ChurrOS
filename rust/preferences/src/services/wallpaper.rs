// ==========================================
// WallpaperService — estado del wallpaper (equivalente a services/wallpaper.py)
// ==========================================

use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;
use std::io::Read;

use crate::services::settings;

pub struct WallpaperService;

fn build_env() -> Vec<(String, String)> {
    let mut env: Vec<(String, String)> = std::env::vars().collect();

    let uid = current_uid();
    let xrd = format!("/run/user/{uid}");

    if !env.iter().any(|(k, _)| k == "XDG_RUNTIME_DIR") {
        env.push(("XDG_RUNTIME_DIR".to_string(), xrd.clone()));
    }

    if !env.iter().any(|(k, _)| k == "WAYLAND_DISPLAY") {
        if Path::new(&xrd).is_dir() {
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
                if let Some((_, sock)) = valid_socks.first() {
                    env.push(("WAYLAND_DISPLAY".to_string(), sock.clone()));
                }
            }
        }
    }

    env
}

fn current_uid() -> u32 {
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

/// shutil.which equivalente: busca el binario en $PATH
fn which(name: &str) -> bool {
    let path_var = std::env::var("PATH").unwrap_or_default();
    path_var.split(':').any(|dir| Path::new(dir).join(name).is_file())
}

/// Ejecuta un comando con timeout y captura stdout/stderr. None si falla/timeout.
fn run_with_timeout(
    args: &[&str],
    timeout: Duration,
    env_refs: &[(&str, &str)],
) -> Option<std::process::Output> {
    let mut child = Command::new(args[0])
        .args(&args[1..])
        .envs(env_refs.iter().map(|(k, v)| (*k, *v)))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;

    // Drenar stdout/stderr en threads mientras el proceso corre: sin esto, un
    // comando que escriba más de ~64 KiB se bloquea en el pipe (deadlock).
    let mut out_pipe = child.stdout.take();
    let mut err_pipe = child.stderr.take();
    let out_thread = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(mut o) = out_pipe.take() {
            let _ = o.read_to_end(&mut buf);
        }
        buf
    });
    let err_thread = std::thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(mut e) = err_pipe.take() {
            let _ = e.read_to_end(&mut buf);
        }
        buf
    });

    let deadline = std::time::Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break st,
            Ok(None) => {
                if std::time::Instant::now() >= deadline {
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
    let stdout = out_thread.join().unwrap_or_default();
    let stderr = err_thread.join().unwrap_or_default();
    Some(std::process::Output {
        status,
        stdout,
        stderr,
    })
}

impl WallpaperService {
    /// Ruta del wallpaper que se está viendo.
    ///
    /// Con Noctalia, el fondo vivo está en `settings.toml` (`[wallpaper.default]`,
    /// si no `[wallpaper.last]` o un monitor) y el de fábrica en `config.toml`.
    /// `settings.json` solo cuenta si Noctalia no es el shell, o como último
    /// recurso: si no, Apariencia se queda en «Sin fondo» tras un cambio hecho
    /// con `noctalia msg wallpaper-set` o con la UI del shell.
    pub fn current() -> String {
        let settings_path = settings::get_string("wallpaper.path", "");
        let home = churros_services::home_dir();
        let home = std::path::PathBuf::from(home);
        let state = fs::read_to_string(home.join(".local/state/noctalia/settings.toml")).ok();
        let config = fs::read_to_string(home.join(".config/noctalia/config.toml")).ok();
        let niri = fs::read_to_string(home.join(".config/niri/config.kdl")).unwrap_or_default();
        let running = churros_services::noctalia::running_shells();
        let noctalia_is_shell = churros_services::noctalia::noctalia_is_shell(running, &niri);
        for path in churros_services::noctalia::wallpaper_candidates(
            &settings_path,
            state.as_deref(),
            config.as_deref(),
            noctalia_is_shell,
        ) {
            if !path.is_empty() && Path::new(&path).is_file() {
                return path;
            }
        }
        String::new()
    }

    pub fn user_dir() -> PathBuf {
        let home = churros_services::home_dir();
        PathBuf::from(home)
            .join(".local/share/churros/wallpapers")
    }

    /// Directorios donde se buscan wallpapers (orden de prioridad)
    pub fn wallpaper_dirs() -> Vec<PathBuf> {
        let home = churros_services::home_dir();
        vec![
            PathBuf::from("/usr/share/churros/wallpapers"),
            PathBuf::from("/usr/share/backgrounds"),
            Self::user_dir(),
            PathBuf::from(&home).join("Pictures/Wallpapers"),
            PathBuf::from(&home).join("Pictures"),
        ]
    }

    /// Escanea los directorios y devuelve wallpapers (ext: jpg jpeg png webp gif)
    pub fn list() -> Vec<PathBuf> {
        let mut found = Vec::new();
        for dir in Self::wallpaper_dirs() {
            if let Ok(entries) = std::fs::read_dir(&dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.is_file() {
                        if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
                            let ext = ext.to_lowercase();
                            if matches!(ext.as_str(), "jpg" | "jpeg" | "png" | "webp" | "gif") {
                                found.push(path);
                            }
                        }
                    }
                }
            }
        }
        found.sort();
        found.dedup();
        found
    }

    /// Guarda el wallpaper en settings.json y lo aplica en vivo.
    /// Devuelve si se aplicó correctamente (equivalente a WallpaperService.set).
    pub fn set(path: &str) -> bool {
        crate::logging::log(&format!("[wallpaper] set inicio: {path}"));
        settings::set("wallpaper.path", serde_json::json!(path));
        let applied = Self::apply(path);
        crate::logging::log(&format!("[wallpaper] apply retorno: {applied}"));
        // Colores dinámicos: regenerar paleta pywal si está activo.
        let dyn_ok = crate::services::pywal::PywalService::regenerate_for_wallpaper(path);
        crate::logging::log(&format!("[wallpaper] pywal retorno: {dyn_ok}"));
        applied
    }

    /// Aplica el wallpaper con churros-apply-wallpaper o swaybg
    /// (equivalente a WallpaperService.apply del Python).
    pub fn apply(path: &str) -> bool {
        if path.is_empty() || !Path::new(path).is_file() {
            println!("[wallpaper] ruta invalida: {path}");
            return false;
        }

        let env = build_env();
        let env_refs: Vec<(&str, &str)> = env
            .iter()
            .map(|(k, v)| (k.as_str(), v.as_str()))
            .collect();

        // Noctalia pinta el fondo. Si el IPC falla o el script pasa de 18 s,
        // no arrancar swaybg: se queda debajo del shell aunque Noctalia
        // haya aplicado la imagen.
        if churros_services::noctalia::running_shells().noctalia {
            return apply_with_noctalia(path, &env_refs);
        }

        // Backend 1: wrapper churros-apply-wallpaper (con timeout: no bloquear
        // la UI si el wrapper se cuelga). swaybg solo si Noctalia no corre.
        if which("churros-apply-wallpaper") {
            let r = run_with_timeout(
                &["churros-apply-wallpaper", path],
                Duration::from_secs(10),
                &env_refs,
            );
            match r {
                Some(out) => {
                    println!(
                        "[wallpaper] wrapper stdout: {}",
                        String::from_utf8_lossy(&out.stdout)
                    );
                    if !out.stderr.is_empty() {
                        println!(
                            "[wallpaper] wrapper stderr: {}",
                            String::from_utf8_lossy(&out.stderr)
                        );
                    }
                    if out.status.success() {
                        return true;
                    }
                    println!("[wallpaper] wrapper fallo rc={:?}", out.status.code());
                    // Ruta vacía o inexistente: el script ya lo dijo. swaybg
                    // arrancaría igual y apply() lo contaría como éxito.
                    if String::from_utf8_lossy(&out.stderr).contains("archivo no existe") {
                        return false;
                    }
                }
                None => println!("[wallpaper] wrapper timeout/ex"),
            }
        }

        // Backend 2: swaybg
        if which("swaybg") {
            let _ = Command::new("pkill")
                .args(["-x", "swaybg"])
                .envs(env_refs.iter().map(|(k, v)| (*k, *v)))
                .status();

            std::thread::sleep(Duration::from_millis(100));

            use std::os::unix::process::CommandExt;
            let mut cmd = Command::new("swaybg");
            cmd.args(["-i", path, "-m", "fill"])
                .envs(env_refs.iter().map(|(k, v)| (*k, *v)))
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .process_group(0);

            if cmd.spawn().is_ok() {
                std::thread::sleep(Duration::from_millis(200));
                println!("[wallpaper] swaybg OK: {path}");
                return true;
            }
        }

        // Backend 3: plasma-apply-wallpaperimage (KDE Plasma)
        if which("plasma-apply-wallpaperimage") {
            let r = run_with_timeout(
                &["plasma-apply-wallpaperimage", path],
                Duration::from_secs(5),
                &env_refs,
            );
            if let Some(out) = r {
                if out.status.success() {
                    println!("[wallpaper] plasma-apply-wallpaperimage OK: {path}");
                    return true;
                }
            }
        }

        println!("[wallpaper] NINGUN backend funciono");
        false
    }

    /// Copia la imagen a ~/.local/share/churros/wallpapers evitando colisiones
    /// de nombre (name_1.ext, name_2.ext...). Devuelve la ruta destino o None.
    /// (equivalente a WallpaperService.import_image del Python)
    pub fn import_image(source_path: &str) -> Option<String> {
        if source_path.is_empty() || !Path::new(source_path).is_file() {
            return None;
        }

        let user_dir = Self::user_dir();
        if fs::create_dir_all(&user_dir).is_err() {
            return None;
        }

        let base = Path::new(source_path)
            .file_name()
            .and_then(|n| n.to_str())
            .unwrap_or("wallpaper")
            .to_string();

        let (name, ext) = match base.rsplit_once('.') {
            Some((n, e)) => (n.to_string(), format!(".{e}")),
            None => (base.clone(), String::new()),
        };

        let mut dest = user_dir.join(&base);
        let mut n = 1u32;
        while dest.exists() {
            dest = user_dir.join(format!("{name}_{n}{ext}"));
            n += 1;
        }

        if fs::copy(source_path, &dest).is_err() {
            return None;
        }

        Some(dest.to_string_lossy().to_string())
    }
}

/// Noctalia está en marcha: el script reintenta el IPC y no llama a swaybg.
/// Si el script no está, el mismo reintento (3 veces, espera corta) se hace aquí.
fn apply_with_noctalia(path: &str, env_refs: &[(&str, &str)]) -> bool {
    if which("churros-apply-wallpaper") {
        let r = run_with_timeout(
            &["churros-apply-wallpaper", path],
            Duration::from_secs(18),
            env_refs,
        );
        return match r {
            Some(out) => {
                if !out.stderr.is_empty() {
                    println!(
                        "[wallpaper] wrapper stderr: {}",
                        String::from_utf8_lossy(&out.stderr)
                    );
                }
                out.status.success()
            }
            None => {
                println!("[wallpaper] wrapper timeout; swaybg no se arranca");
                false
            }
        };
    }

    if !which("noctalia") {
        return false;
    }
    for attempt in 1..=3 {
        println!("[wallpaper] noctalia msg wallpaper-set intento {attempt}");
        let r = run_with_timeout(
            &["noctalia", "msg", "wallpaper-set", path],
            Duration::from_secs(3),
            env_refs,
        );
        if r.as_ref().is_some_and(|out| out.status.success()) {
            return true;
        }
        if attempt < 3 {
            let wait_ms = u64::try_from(attempt).unwrap_or(0);
            std::thread::sleep(Duration::from_millis(200 * wait_ms));
        }
    }
    println!("[wallpaper] noctalia no acepto el fondo; swaybg no se arranca");
    false
}

// ==========================================
// churros-services — capa de servicios de ChurrOS
// (port Rust de usr/share/churros/services/*.py)
// ==========================================

pub mod audio;
pub mod battery;
pub mod bluetooth;
pub mod brightness;
pub mod dev;
pub mod ethernet;
pub mod jsonc;
pub mod noctalia;
pub mod power;
pub mod theme;
pub mod version;
pub mod waybar_style;
pub mod wifi;

use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use wait_timeout::ChildExt;

/// HOME del usuario efectivo; si la variable no existe, se consulta passwd
/// (getent) en vez de asumir "/root" en cualquier caso.
pub fn home_dir() -> String {
    if let Ok(h) = std::env::var("HOME") {
        if !h.is_empty() {
            return h;
        }
    }
    if let Ok(out) = Command::new("getent")
        .args(["passwd", &std::env::var("USER").unwrap_or_default()])
        .output()
    {
        if out.status.success() {
            let line = String::from_utf8_lossy(&out.stdout);
            if let Some(home) = line.split(':').nth(5) {
                let home = home.trim();
                if !home.is_empty() {
                    return home.to_string();
                }
            }
        }
    }
    "/root".to_string()
}

/// Directorio HOME como PathBuf.
pub fn home_path() -> PathBuf {
    PathBuf::from(home_dir())
}

/// UID del usuario efectivo actual (getuid(2)).
pub fn uid() -> u32 {
    unsafe { libc::getuid() }
}

/// Resultado de ejecutar un comando: (returncode, stdout, stderr).
pub type RunOut = (i32, String, String);

/// Ejecuta un comando capturando stdout/stderr, con timeout opcional.
/// Devuelve None si falla el spawn, el timeout se agota o la salida no es UTF-8
/// (equivalente al `try/except` de los módulos Python).
pub fn run(cmd: &[&str], timeout_ms: u64) -> Option<RunOut> {
    if dev::enabled() && dev::is_mutation(cmd) {
        dev::log_blocked(cmd);
        return Some((0, String::new(), String::new()));
    }

    let mut child = Command::new(cmd[0])
        .args(&cmd[1..])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;

    // Drenar stdout/stderr en threads ANTES de esperar: si no, un proceso que
    // escriba más de ~64 KiB se bloquea en el pipe y el padre nunca recoge la
    // salida (deadlock hasta el timeout).
    let mut out_pipe = child.stdout.take();
    let mut err_pipe = child.stderr.take();
    let out_thread = std::thread::spawn(move || {
        let mut buf = String::new();
        if let Some(mut so) = out_pipe.take() {
            let _ = so.read_to_string(&mut buf);
        }
        buf
    });
    let err_thread = std::thread::spawn(move || {
        let mut buf = String::new();
        if let Some(mut se) = err_pipe.take() {
            let _ = se.read_to_string(&mut buf);
        }
        buf
    });

    let timed_out = if timeout_ms > 0 {
        match child
            .wait_timeout(Duration::from_millis(timeout_ms))
            .ok()?
        {
            Some(_) => false,
            None => {
                let _ = child.kill();
                let _ = child.wait();
                true
            }
        }
    } else {
        let _ = child.wait();
        false
    };

    if timed_out {
        return None;
    }

    let code = child.wait().map(|s| s.code().unwrap_or(1)).unwrap_or(1);
    let stdout = out_thread.join().unwrap_or_default();
    let stderr = err_thread.join().unwrap_or_default();

    Some((code, stdout, stderr))
}

/// Ejecuta un comando al vuelo (fire-and-forget, equivale a subprocess.Popen).
pub fn spawn(cmd: &[&str]) {
    if dev::enabled() {
        dev::log_blocked(cmd);
        return;
    }

    if let Err(e) = Command::new(cmd[0])
        .args(&cmd[1..])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        eprintln!("churros-services: no se pudo lanzar {:?}: {}", cmd, e);
    }
}

/// Comprueba si un binario existe en el PATH (equivale a shutil.which).
pub fn which(bin: &str) -> bool {
    std::env::var_os("PATH")
        .map(|paths| {
            std::env::split_paths(&paths).any(|d| d.join(bin).is_file())
        })
        .unwrap_or(false)
}

/// Entorno enriquecido para sesiones gráficas Wayland, garantizando
/// XDG_RUNTIME_DIR y WAYLAND_DISPLAY (si existe socket en tiempo de ejecución).
pub fn session_env() -> Vec<(String, String)> {
    let mut env: Vec<(String, String)> = std::env::vars().collect();
    let u = uid();
    let xrd = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| format!("/run/user/{u}"));

    if !env.iter().any(|(k, _)| k == "XDG_RUNTIME_DIR") {
        env.push(("XDG_RUNTIME_DIR".to_string(), xrd.clone()));
    }

    if !env.iter().any(|(k, _)| k == "WAYLAND_DISPLAY") {
        if Path::new(&xrd).is_dir() {
            if let Ok(entries) = std::fs::read_dir(&xrd) {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_uid_matches_libc() {
        assert_eq!(uid(), unsafe { libc::getuid() });
    }

    #[test]
    fn test_home_path_non_empty() {
        assert!(!home_path().as_os_str().is_empty());
    }

    #[test]
    fn test_which_existing_and_missing() {
        assert!(which("sh"));
        assert!(!which("nonexistent_binary_xyz_123"));
    }

    #[test]
    fn test_session_env_contains_runtime_dir() {
        let env = session_env();
        assert!(env.iter().any(|(k, _)| k == "XDG_RUNTIME_DIR"));
    }
}


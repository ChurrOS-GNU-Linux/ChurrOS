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

// ==========================================
// DatetimeService (equivalente a services/datetime.py)
// ==========================================

use std::io::Read;
use std::process::{Command, Output, Stdio};
use std::time::{Duration, Instant};

/// Ejecuta un comando y devuelve el Output completo (stdout + stderr + status).
/// None si falla el spawn o tarda más de `timeout_secs`.
fn run_output(args: &[&str], timeout_secs: u64) -> Option<Output> {
    let mut child = Command::new(args[0])
        .args(&args[1..])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;

    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break st,
            Ok(None) => {}
            Err(_) => {
                let _ = child.kill();
                return None;
            }
        }
        if start.elapsed() > Duration::from_secs(timeout_secs) {
            let _ = child.kill();
            let _ = child.wait();
            return None;
        }
        std::thread::sleep(Duration::from_millis(20));
    };

    let mut stdout = Vec::new();
    if let Some(mut s) = child.stdout.take() {
        let _ = s.read_to_end(&mut stdout);
    }
    let mut stderr = Vec::new();
    if let Some(mut s) = child.stderr.take() {
        let _ = s.read_to_end(&mut stderr);
    }
    Some(Output {
        status,
        stdout,
        stderr,
    })
}

/// stdout recortado de un comando ("" si falla).
fn run_stdout(args: &[&str], timeout_secs: u64) -> String {
    match run_output(args, timeout_secs) {
        Some(out) => String::from_utf8_lossy(&out.stdout).trim().to_string(),
        None => String::new(),
    }
}

pub struct DatetimeService;

impl DatetimeService {
    /// Zona horaria actual ("Europe/Madrid") o "".
    pub fn get_timezone() -> String {
        run_stdout(
            &["timedatectl", "show", "--property=Timezone", "--value"],
            3,
        )
    }

    /// True si NTP está activo.
    pub fn get_ntp() -> bool {
        run_stdout(&["timedatectl", "show", "--property=NTP", "--value"], 3)
            .eq_ignore_ascii_case("yes")
    }

    /// Hora del RTC ("n/a" -> "").
    pub fn get_rtc_time() -> String {
        let raw = run_stdout(&["timedatectl", "show", "--property=RTCTime", "--value"], 3);
        if raw.is_empty() || raw == "n/a" {
            String::new()
        } else {
            raw
        }
    }

    /// Lista de zonas horarias conocidas.
    pub fn list_timezones() -> Vec<String> {
        let out = run_stdout(&["timedatectl", "list-timezones"], 5);
        out.lines().map(|l| l.trim().to_string()).filter(|l| !l.is_empty()).collect()
    }

    /// Cambia la zona horaria (via churros-pkexec). True si ok.
    ///
    /// La regla polkit autoriza por ruta absoluta y argv exacto: sin
    /// contraseña solo `set-timezone <Zona/Ciudad>` y `set-ntp true|false`.
    pub fn set_timezone(tz: &str) -> bool {
        match run_output(
            &["churros-pkexec", "/usr/bin/timedatectl", "set-timezone", tz],
            10,
        ) {
            Some(out) => out.status.success(),
            None => false,
        }
    }

    /// Activa/desactiva NTP (via churros-pkexec). True si ok.
    pub fn set_ntp(enabled: bool) -> bool {
        let flag = if enabled { "true" } else { "false" };
        match run_output(
            &["churros-pkexec", "/usr/bin/timedatectl", "set-ntp", flag],
            10,
        ) {
            Some(out) => out.status.success(),
            None => false,
        }
    }

    /// Último segmento de la zona ("Europe/Madrid" -> "Madrid").
    pub fn current_zone_short() -> String {
        let tz = Self::get_timezone();
        if tz.is_empty() {
            return String::new();
        }
        let parts: Vec<&str> = tz.split('/').collect();
        if parts.len() >= 2 {
            parts.last().unwrap().replace('_', " ")
        } else {
            tz
        }
    }
}

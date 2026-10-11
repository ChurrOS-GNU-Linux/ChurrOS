// ==========================================
// PowerService (equivalente a services/power.py)
// ==========================================

use std::io::Read;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// Helper seguro: ejecuta un comando con timeout corto y captura de stdout.
/// Nunca lanza. Devuelve stdout sin espacios al final, o "" si falla/tarda.
/// (equivalente a _run() de power.py, timeout=2)
fn run(args: &[&str]) -> String {
    let mut child = match Command::new(args[0])
        .args(&args[1..])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(c) => c,
        Err(_) => return String::new(),
    };

    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break st,
            Ok(None) => {}
            Err(_) => {
                let _ = child.kill();
                return String::new();
            }
        }
        if start.elapsed() > Duration::from_secs(2) {
            let _ = child.kill();
            let _ = child.wait();
            return String::new();
        }
        std::thread::sleep(Duration::from_millis(20));
    };

    // power.py usa subprocess.run sin check: devuelve stdout igualmente
    let _ = status;
    let mut buf = String::new();
    if let Some(mut out) = child.stdout.take() {
        let _ = out.read_to_string(&mut buf);
    }
    buf.trim().to_string()
}

/// Comandos "set": equivalente a subprocess.run(capture_output=False).
/// status() recoge el proceso para no dejar zombis.
fn run_no_output(args: &[&str]) {
    let _ = Command::new(args[0])
        .args(&args[1..])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

pub struct PowerService;

/// Ruta del primer dispositivo de batería de `upower -e`
/// (línea que termina en "battery": BAT0, CMB0, hidpp_battery_*, etc.).
fn battery_device() -> Option<String> {
    let output = run(&["upower", "-e"]);
    output
        .lines()
        .find(|l| l.trim().ends_with("battery"))
        .map(|l| l.trim().to_string())
}

impl PowerService {
    /// True si hay una batería detectada (upower -e termina en "battery").
    pub fn battery_present() -> bool {
        battery_device().is_some()
    }

    /// Porcentaje de carga (0-100); si no hay batería/upower falla -> 100.
    pub fn battery_percentage() -> i64 {
        let Some(device) = battery_device() else {
            return 100;
        };
        let output = run(&["upower", "-i", &device]);
        for line in output.lines() {
            if line.contains("percentage") {
                if let Some((_, v)) = line.split_once(':') {
                    let v = v.trim().trim_end_matches('%');
                    if let Ok(n) = v.parse::<f64>() {
                        return n as i64;
                    }
                }
            }
        }
        100
    }

    /// Estado crudo de upower ("charging", "discharging", "full", ...).
    /// NOTA: el docstring del Python dice 'Cargando'/'Descargando'/'Llena' pero
    /// el codigo devuelve el valor crudo en ingles; se porta el comportamiento real.
    pub fn battery_state() -> String {
        let Some(device) = battery_device() else {
            return "Desconocido".to_string();
        };
        let output = run(&["upower", "-i", &device]);
        for line in output.lines() {
            if line.contains("state") {
                if let Some((_, v)) = line.split_once(':') {
                    return v.trim().to_string();
                }
            }
        }
        "Desconocido".to_string()
    }

    /// Perfil activo ('performance'|'balanced'|'power-saver'); desconocido -> "balanced".
    pub fn power_profile() -> String {
        let output = run(&["powerprofilesctl", "get"]);
        if matches!(output.as_str(), "performance" | "balanced" | "power-saver") {
            output
        } else {
            "balanced".to_string()
        }
    }

    /// Lista de perfiles soportados; fallback ["balanced"] (paridad con Python).
    pub fn power_profiles_available() -> Vec<String> {
        let output = run(&["powerprofilesctl", "list"]);
        let mut profiles = Vec::new();
        for line in output.lines() {
            // `powerprofilesctl list` imprime `  performance:` (con ":") y un
            // `*` en el activo; el match exacto fallaba por los dos puntos.
            let t = line.trim().trim_end_matches(':').trim();
            if matches!(t, "performance" | "balanced" | "power-saver") {
                if !profiles.contains(&t.to_string()) {
                    profiles.push(t.to_string());
                }
            }
        }
        if profiles.is_empty() {
            vec!["balanced".to_string()]
        } else {
            profiles
        }
    }

    /// Timeout de pantalla en segundos (gsettings idle-delay); default 300.
    pub fn screen_timeout() -> i64 {
        let output = run(&[
            "gsettings",
            "get",
            "org.gnome.desktop.session",
            "idle-delay",
        ]);
        if let Some(v) = output.strip_prefix("uint32") {
            if let Ok(n) = v.trim().parse::<i64>() {
                return n;
            }
        }
        if !output.is_empty() && output.chars().all(|c| c.is_ascii_digit()) {
            if let Ok(n) = output.parse::<i64>() {
                return n;
            }
        }
        300
    }

    /// Timeout de suspensión en segundos (sleep-inactive-ac-timeout); default 900.
    pub fn sleep_timeout() -> i64 {
        let output = run(&[
            "gsettings",
            "get",
            "org.gnome.settings-daemon.plugins.power",
            "sleep-inactive-ac-timeout",
        ]);
        if let Some(v) = output.strip_prefix("uint32") {
            if let Ok(n) = v.trim().parse::<i64>() {
                return n;
            }
        }
        if !output.is_empty() && output.chars().all(|c| c.is_ascii_digit()) {
            if let Ok(n) = output.parse::<i64>() {
                return n;
            }
        }
        900
    }

    /// Acción al cerrar la tapa; default "suspend".
    pub fn lid_close_action() -> String {
        let output = run(&[
            "gsettings",
            "get",
            "org.gnome.settings-daemon.plugins.power",
            "lid-close-ac-action",
        ]);
        let value = output.trim().trim_matches(|c| c == '\'' || c == '"');
        if matches!(
            value,
            "suspend" | "hibernate" | "nothing" | "blank" | "logout" | "shutdown"
        ) {
            value.to_string()
        } else {
            "suspend".to_string()
        }
    }

    /// True si el modo ahorro de energía está activo.
    pub fn power_saver_enabled() -> bool {
        Self::power_profile() == "power-saver"
    }

    /// Cambia el perfil activo via powerprofilesctl.
    pub fn set_power_profile(profile: &str) {
        run_no_output(&["powerprofilesctl", "set", profile]);
    }

    /// Establece el tiempo de espera para apagar la pantalla.
    pub fn set_screen_timeout(seconds: i64) {
        let s = seconds.to_string();
        run_no_output(&[
            "gsettings",
            "set",
            "org.gnome.desktop.session",
            "idle-delay",
            &s,
        ]);
    }

    /// Establece el tiempo de espera para suspender.
    pub fn set_sleep_timeout(seconds: i64) {
        let s = seconds.to_string();
        run_no_output(&[
            "gsettings",
            "set",
            "org.gnome.settings-daemon.plugins.power",
            "sleep-inactive-ac-timeout",
            &s,
        ]);
    }

    /// Configura la acción al cerrar la tapa.
    pub fn set_lid_close_action(action: &str) {
        run_no_output(&[
            "gsettings",
            "set",
            "org.gnome.settings-daemon.plugins.power",
            "lid-close-ac-action",
            action,
        ]);
    }
}

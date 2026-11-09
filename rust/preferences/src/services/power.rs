// ==========================================
// PowerService (equivalente a services/power.py)
// ==========================================

use std::io::Read;
use std::path::Path;
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
    /// Governor de cpufreq de cpu0 (performance, schedutil, powersave...).
    pub fn cpu_governor() -> String {
        std::fs::read_to_string("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
            .ok()
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "Desconocido".to_string())
    }

    /// Planificador de CPU del kernel: BORE (kernels CachyOS) o EEVDF de serie.
    pub fn kernel_scheduler() -> String {
        let has_sysctl = ["/proc/sys/kernel/sched_bore", "/proc/sys/kernel/sched_poc_count"]
            .iter()
            .any(|p| std::path::Path::new(p).exists());
        let version = std::fs::read_to_string("/proc/version")
            .unwrap_or_default()
            .to_lowercase();
        if has_sysctl || version.contains("cachyos") || version.contains("bore") {
            "CachyOS BORE (Bajo retardo)".to_string()
        } else {
            "EEVDF / Estándar".to_string()
        }
    }

    /// Estado del demonio de Feral GameMode (`gamemoded -s`, timeout 2 s).
    pub fn gamemode_status() -> String {
        if !churros_services::which("gamemoded") {
            return "No instalado".to_string();
        }
        // "gamemode is active" / "gamemode is inactive"
        if run(&["gamemoded", "-s"]).contains("is active") {
            "En ejecución".to_string()
        } else {
            "Inactivo (listo para juegos)".to_string()
        }
    }

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

    /// Quién aplica la inactividad y la tapa en esta sesión.
    pub fn idle_backend() -> IdleBackend {
        if churros_services::noctalia::running() {
            IdleBackend::Noctalia
        } else if churros_services::which("xfconf-query")
            && Path::new("/usr/bin/xfce4-power-manager").exists()
        {
            IdleBackend::Xfce
        } else {
            IdleBackend::None
        }
    }

    /// Segundos hasta apagar la pantalla; 0 = nunca.
    pub fn screen_timeout() -> i64 {
        match Self::idle_backend() {
            IdleBackend::Noctalia => noctalia_idle("screen-off").unwrap_or(600),
            IdleBackend::Xfce => xfpm_get("dpms-on-ac-off").map(|m| m * 60).unwrap_or(15 * 60),
            IdleBackend::None => 0,
        }
    }

    /// Segundos de inactividad hasta suspender; 0 = nunca.
    pub fn sleep_timeout() -> i64 {
        match Self::idle_backend() {
            IdleBackend::Noctalia => noctalia_idle("lock-and-suspend").unwrap_or(0),
            IdleBackend::Xfce => xfpm_get("inactivity-on-ac").map(|m| m * 60).unwrap_or(0),
            IdleBackend::None => 0,
        }
    }

    /// Acción al cerrar la tapa: una de LID_ACTIONS. Solo XFCE la
    /// configura (xfce4-power-manager); en Niri la decide logind (suspender).
    pub fn lid_close_action() -> String {
        if Self::idle_backend() == IdleBackend::Xfce {
            if let Some(n) = xfpm_get("lid-action-on-ac") {
                if let Some((name, _)) = LID_ACTIONS.iter().find(|(_, v)| *v == n) {
                    return (*name).to_string();
                }
            }
        }
        "suspend".to_string()
    }

    /// ¿Se puede cambiar la acción de la tapa en esta sesión?
    pub fn lid_action_configurable() -> bool {
        Self::idle_backend() == IdleBackend::Xfce
    }

    /// True si el modo ahorro de energía está activo.
    pub fn power_saver_enabled() -> bool {
        Self::power_profile() == "power-saver"
    }

    /// Cambia el perfil activo via powerprofilesctl.
    pub fn set_power_profile(profile: &str) {
        run_no_output(&["powerprofilesctl", "set", profile]);
    }

    /// Apaga la pantalla tras `seconds` de inactividad (0 = nunca).
    pub fn set_screen_timeout(seconds: i64) -> bool {
        match Self::idle_backend() {
            IdleBackend::Noctalia => set_noctalia_idle("screen-off", seconds),
            IdleBackend::Xfce => {
                let minutes = to_minutes(seconds);
                xfpm_set("dpms-on-ac-off", minutes) && xfpm_set("dpms-on-battery-off", minutes)
            }
            IdleBackend::None => false,
        }
    }

    /// Suspende tras `seconds` de inactividad (0 = nunca). En Noctalia la
    /// acción es bloquear y suspender, como en la configuración de ChurrOS.
    pub fn set_sleep_timeout(seconds: i64) -> bool {
        match Self::idle_backend() {
            IdleBackend::Noctalia => set_noctalia_idle("lock-and-suspend", seconds),
            IdleBackend::Xfce => {
                let minutes = to_minutes(seconds);
                xfpm_set("inactivity-on-ac", minutes)
                    && xfpm_set("inactivity-on-battery", minutes)
                    && xfpm_set("inactivity-sleep-mode-on-ac", 1)
                    && xfpm_set("inactivity-sleep-mode-on-battery", 1)
            }
            IdleBackend::None => false,
        }
    }

    /// Acción al cerrar la tapa (solo XFCE).
    pub fn set_lid_close_action(action: &str) -> bool {
        let Some((_, value)) = LID_ACTIONS.iter().find(|(name, _)| *name == action) else {
            return false;
        };
        Self::idle_backend() == IdleBackend::Xfce
            && xfpm_set("lid-action-on-ac", *value)
            && xfpm_set("lid-action-on-battery", *value)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum IdleBackend {
    /// [idle.behavior.*] de Noctalia (Niri).
    Noctalia,
    /// xfce4-power-manager (xfconf).
    Xfce,
    None,
}

/// Acciones de tapa -> XfpmLidTriggerAction (xfpm-enum-glib.h).
pub const LID_ACTIONS: [(&str, i64); 6] = [
    ("suspend", 1),
    ("hibernate", 2),
    ("lock", 3),
    ("blank", 0),
    ("nothing", 4),
    ("shutdown", 6),
];

fn to_minutes(seconds: i64) -> i64 {
    if seconds <= 0 {
        0
    } else {
        (seconds + 59) / 60
    }
}

/// Segundos de [idle.behavior.<name>]; 0 si está desactivado.
fn noctalia_idle(name: &str) -> Option<i64> {
    use churros_services::noctalia::{config_get, parse_bool, parse_number};
    let enabled = parse_bool(&config_get(&format!("idle.behavior.{name}.enabled"))?)?;
    if !enabled {
        return Some(0);
    }
    parse_number(&config_get(&format!("idle.behavior.{name}.timeout"))?)
}

fn set_noctalia_idle(name: &str, seconds: i64) -> bool {
    use churros_services::noctalia::config_set;
    if seconds <= 0 {
        return config_set(&format!("idle.behavior.{name}.enabled"), "false");
    }
    config_set(&format!("idle.behavior.{name}.timeout"), &seconds.to_string())
        && config_set(&format!("idle.behavior.{name}.enabled"), "true")
}

fn xfpm_get(key: &str) -> Option<i64> {
    let property = format!("/xfce4-power-manager/{key}");
    let (code, out, _) =
        churros_services::run(&["xfconf-query", "-c", "xfce4-power-manager", "-p", &property], 3000)?;
    (code == 0).then(|| out.trim().parse().ok()).flatten()
}

/// -n crea la propiedad si no existe (xfpm solo guarda lo que se cambia).
fn xfpm_set(key: &str, value: i64) -> bool {
    let property = format!("/xfce4-power-manager/{key}");
    let value = value.to_string();
    matches!(
        churros_services::run(
            &["xfconf-query", "-c", "xfce4-power-manager", "-p", &property, "-n", "-t", "uint", "-s", &value],
            3000,
        ),
        Some((0, _, _))
    )
}

#[cfg(test)]
mod idle_tests {
    use super::*;

    #[test]
    fn minutes_round_up_and_never_is_zero() {
        assert_eq!(to_minutes(0), 0);
        assert_eq!(to_minutes(60), 1);
        assert_eq!(to_minutes(90), 2);
        assert_eq!(to_minutes(1800), 30);
    }

    #[test]
    fn lid_actions_match_xfpm_enum() {
        // LID_TRIGGER_DPMS, SUSPEND, HIBERNATE, LOCK_SCREEN, NOTHING, HYBRID_SLEEP, SHUTDOWN
        let value = |n: &str| LID_ACTIONS.iter().find(|(name, _)| *name == n).unwrap().1;
        assert_eq!(value("blank"), 0);
        assert_eq!(value("suspend"), 1);
        assert_eq!(value("hibernate"), 2);
        assert_eq!(value("lock"), 3);
        assert_eq!(value("nothing"), 4);
        assert_eq!(value("shutdown"), 6);
    }
}

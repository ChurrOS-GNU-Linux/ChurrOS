// ==========================================
// LockScreenService — ~/.config/churros/lock_screen.json
// swaylock + swayidle
// (equivalente a services/lock_screen.py)
// ==========================================

use serde_json::{Value, json};
use std::fs;
use std::io::{Read, Seek};
use std::path::PathBuf;
use std::process::{Command, Stdio};

use gio::prelude::*;

pub struct LockScreenService;

fn config_file() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home)
        .join(".config")
        .join("churros")
        .join("lock_screen.json")
}

pub fn defaults() -> Value {
    json!({
        "enabled": false,
        "timeout_seconds": 600,
        "indicator": "auto",
        "wallpaper_path": "",
        "font": "JetBrains Mono",
        "font_size": 24,
        "ring_color": "7aa2f7ff",
        "inside_color": "00000088",
        "key_hl_color": "bb9af7ff",
        "bs_color": "f7768eff",
        "separator_color": "00000000",
    })
}

pub const INDICATORS: [&str; 2] = ["none", "auto"];

fn read_data() -> Value {
    let d = defaults();
    match fs::read_to_string(config_file()) {
        Ok(content) => match serde_json::from_str::<Value>(&content) {
            Ok(data) => {
                let mut merged = d.as_object().cloned().unwrap_or_default();
                if let Some(obj) = data.as_object() {
                    for (k, v) in obj {
                        merged.insert(k.clone(), v.clone());
                    }
                }
                Value::Object(merged)
            }
            Err(_) => d,
        },
        Err(_) => d,
    }
}

fn save_data(data: &Value) {
    if let Some(parent) = config_file().parent() {
        let _ = fs::create_dir_all(parent);
    }
    let _ = fs::write(
        config_file(),
        serde_json::to_string_pretty(data).unwrap_or_default(),
    );
}

/// Construye el comando swaylock a partir de la config (equivalente a _build_swaylock_cmd).
fn build_swaylock_cmd(data: &Value) -> Vec<String> {
    let mut cmd = vec!["swaylock".to_string()];

    // Los tipos antiguos (ring/bar/dots) usan el anillo automático de stock.
    let indicator = data
        .get("indicator")
        .and_then(|v| v.as_str())
        .unwrap_or("auto");
    if indicator == "none" {
        cmd.push("--no-unlock-indicator".to_string());
    }

    let wp = data
        .get("wallpaper_path")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if !wp.is_empty() && PathBuf::from(wp).is_file() {
        cmd.push("--image".to_string());
        cmd.push(wp.to_string());
    }

    let font = data.get("font").and_then(|v| v.as_str()).unwrap_or("");
    let font_size = data.get("font_size").and_then(|v| v.as_i64()).unwrap_or(24);

    if !font.is_empty() {
        cmd.push("--font".to_string());
        cmd.push(font.to_string());
    }
    if font_size != 0 {
        cmd.push("--font-size".to_string());
        cmd.push(font_size.to_string());
    }

    for (key, flag) in [
        ("ring_color", "--ring-color"),
        ("inside_color", "--inside-color"),
        ("key_hl_color", "--key-hl-color"),
        ("bs_color", "--bs-hl-color"),
        ("separator_color", "--separator-color"),
    ] {
        let val = data.get(key).and_then(|v| v.as_str()).unwrap_or("");
        if !val.is_empty() {
            cmd.push(flag.to_string());
            cmd.push(val.trim_start_matches('#').to_string());
        }
    }

    cmd
}

fn run_preview(command: &mut Command) -> Result<(), String> {
    let capture_error = |err| format!("No se pudo capturar stderr de swaylock: {err}");
    let (file, _stream) = gio::File::new_tmp(Some("churros-swaylock-XXXXXX"))
        .map_err(|err| capture_error(err.to_string()))?;
    let path = file
        .path()
        .ok_or("No se pudo crear el archivo temporal de swaylock")?;
    let mut stderr = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&path)
        .map_err(|err| capture_error(err.to_string()))?;
    fs::remove_file(&path).map_err(|err| capture_error(err.to_string()))?;

    // El backend PAM puede heredar stderr hasta el desbloqueo. Un archivo
    // anónimo evita esperar al EOF de un pipe incluso tras --daemonize.
    let status = command
        .arg("--daemonize")
        .stdout(Stdio::null())
        .stderr(
            stderr
                .try_clone()
                .map_err(|err| capture_error(err.to_string()))?,
        )
        .status()
        .map_err(|err| format!("No se pudo iniciar swaylock: {err}"))?;
    if status.success() {
        return Ok(());
    }

    stderr
        .rewind()
        .map_err(|err| capture_error(err.to_string()))?;
    let mut detail = Vec::new();
    stderr
        .read_to_end(&mut detail)
        .map_err(|err| capture_error(err.to_string()))?;
    Err(format!(
        "swaylock ({status}): {}",
        String::from_utf8_lossy(&detail).trim()
    ))
}

/// Cita un argumento para sh (swayidle ejecuta el comando con sh -c).
fn sh_quote(arg: &str) -> String {
    if arg
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || "/._-+@%:".contains(c))
    {
        return arg.to_string();
    }
    format!("'{}'", arg.replace('\'', r"'\''"))
}

impl LockScreenService {
    pub fn get(key: &str, default: Value) -> Value {
        read_data().get(key).cloned().unwrap_or(default)
    }

    /// Fusiona los pares clave/valor dados en lock_screen.json (equivalente a set_all).
    pub fn set_all(updates: &Value) {
        let mut data = read_data();
        if let Some(obj) = data.as_object_mut() {
            if let Some(updates) = updates.as_object() {
                for (k, v) in updates {
                    obj.insert(k.clone(), v.clone());
                }
            }
        }
        save_data(&data);
    }

    pub fn is_enabled() -> bool {
        read_data()
            .get("enabled")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
    }

    pub fn is_available() -> bool {
        churros_services::which("swaylock")
    }

    pub fn is_idle_available() -> bool {
        churros_services::which("swayidle")
    }

    pub fn is_running_idle() -> bool {
        Command::new("pgrep")
            .args(["-x", "swayidle"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }

    pub fn is_running_lock() -> bool {
        Command::new("pgrep")
            .args(["-x", "swaylock"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }

    /// Lanza swaylock al instante (solo bloqueo, sin estilos propios).
    pub fn lock_now() {
        let _ = Command::new("swaylock")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn();
    }

    /// Confirma el bloqueo, sin esperar a que el usuario se autentique.
    pub fn preview() -> Result<(), String> {
        let cmd = build_swaylock_cmd(&read_data());
        let mut command = Command::new(&cmd[0]);
        command.args(&cmd[1..]);
        run_preview(&mut command)
    }

    fn stop_idle() {
        let _ = Command::new("pkill")
            .args(["-x", "swayidle"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
    }

    /// Aplica el estado: si enabled, relanza swayidle con el timeout y swaylock.
    pub fn apply() {
        Self::stop_idle();

        let data = read_data();

        if !data
            .get("enabled")
            .and_then(|v| v.as_bool())
            .unwrap_or(false)
        {
            return;
        }
        if !Self::is_idle_available() || !Self::is_available() {
            return;
        }

        let timeout = data
            .get("timeout_seconds")
            .and_then(|v| v.as_i64())
            .unwrap_or(600);

        let swaylock_cmd = build_swaylock_cmd(&data);
        // swayidle ejecuta el comando con sh -c: citar cada argumento
        // (el font por defecto contiene espacios y rompía el comando).
        let joined = swaylock_cmd
            .iter()
            .map(|a| sh_quote(a))
            .collect::<Vec<_>>()
            .join(" ");

        // swayidle -w timeout <segundos> "<comando swaylock>"
        let mut cmd = Command::new("swayidle");
        cmd.args(["-w", "timeout", &timeout.to_string(), &joined]);
        // Conservar diagnósticos de swayidle y del swaylock que lanza.
        cmd.stdout(Stdio::null()).stderr(Stdio::inherit());

        let uid = Command::new("id")
            .arg("-u")
            .output()
            .ok()
            .and_then(|o| {
                String::from_utf8_lossy(&o.stdout)
                    .trim()
                    .parse::<u32>()
                    .ok()
            })
            .unwrap_or(0);
        let xrd = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| format!("/run/user/{uid}"));
        if PathBuf::from(&xrd).is_dir() {
            cmd.env("XDG_RUNTIME_DIR", xrd);
        }

        if let Err(error) = cmd.spawn() {
            eprintln!("[lock-screen] No se pudo iniciar swayidle: {error}");
        }
    }

    /// Wallpapers disponibles (equivalente a get_wallpapers).
    pub fn get_wallpapers() -> Vec<String> {
        crate::services::wallpaper::WallpaperService::list()
            .into_iter()
            .map(|p| p.to_string_lossy().to_string())
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_command_uses_stock_colors() {
        assert_eq!(
            build_swaylock_cmd(&defaults()),
            [
                "swaylock",
                "--font",
                "JetBrains Mono",
                "--font-size",
                "24",
                "--ring-color",
                "7aa2f7ff",
                "--inside-color",
                "00000088",
                "--key-hl-color",
                "bb9af7ff",
                "--bs-hl-color",
                "f7768eff",
                "--separator-color",
                "00000000",
            ]
        );
    }

    #[test]
    fn legacy_effects_are_ignored_and_indicators_fall_back_to_auto() {
        let mut data = defaults();
        data["screenshot"] = json!(true);
        data["fade_in"] = json!(750);
        data["grace"] = json!(5000);
        for indicator in ["auto", "ring", "bar", "dots", "unknown"] {
            data["indicator"] = json!(indicator);
            assert_eq!(build_swaylock_cmd(&data), build_swaylock_cmd(&defaults()));
        }
        data["indicator"] = json!("none");
        assert_eq!(build_swaylock_cmd(&data)[1], "--no-unlock-indicator");
        data["ring_color"] = json!("#12345678");
        assert!(
            build_swaylock_cmd(&data)
                .windows(2)
                .any(|pair| pair == ["--ring-color", "12345678"])
        );
    }

    #[test]
    fn wallpaper_and_shell_arguments_remain_separate() {
        let (file, _stream) = gio::File::new_tmp(Some("churros-lock-screen-XXXXXX")).unwrap();
        let path = file.path().unwrap();
        let mut data = defaults();
        data["wallpaper_path"] = json!(path.to_string_lossy());
        let cmd = build_swaylock_cmd(&data);
        fs::remove_file(&path).unwrap();
        assert_eq!(&cmd[1..3], ["--image", path.to_str().unwrap()]);
        assert_eq!(sh_quote("JetBrains Mono"), "'JetBrains Mono'");
        assert_eq!(
            sh_quote("/tmp/it's a wallpaper.png"),
            "'/tmp/it'\\''s a wallpaper.png'"
        );
        assert_eq!(build_swaylock_cmd(&data), build_swaylock_cmd(&defaults()));
    }

    #[test]
    fn preview_waits_for_daemon_confirmation_without_starting_a_real_lock() {
        let mut command = Command::new("sh");
        command.args(["-c", "test \"$1\" = --daemonize", "swaylock-test"]);
        assert_eq!(run_preview(&mut command), Ok(()));
    }

    #[test]
    fn preview_returns_exit_status_and_stderr() {
        let mut command = Command::new("sh");
        command.args(["-c", "printf 'compositor unavailable\\n' >&2; exit 2"]);
        let error = run_preview(&mut command).unwrap_err();
        assert!(error.contains("exit status: 2"), "{error}");
        assert!(error.contains("compositor unavailable"), "{error}");
    }

    #[test]
    fn preview_reports_spawn_failure() {
        let mut command = Command::new("/nonexistent/churros-swaylock-test");
        assert!(
            run_preview(&mut command)
                .unwrap_err()
                .contains("No se pudo iniciar swaylock")
        );
    }
}

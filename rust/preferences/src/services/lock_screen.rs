// ==========================================
// LockScreenService — ~/.config/churros/lock_screen.json
// swaylock + swayidle
// (equivalente a services/lock_screen.py)
// ==========================================

use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::process::{Command, Stdio};

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
        "screenshot": false,
        "fade_in": 200,
        "grace": 0,
        "font": "JetBrains Mono",
        "font_size": 24,
        "ring_color": "7aa2f7ff",
        "inside_color": "00000088",
        "key_hl_color": "bb9af7ff",
        "bs_color": "f7768eff",
        "separator_color": "00000000",
    })
}

pub const INDICATORS: [&str; 5] = ["none", "ring", "bar", "dots", "auto"];

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
    let _ = fs::write(config_file(), serde_json::to_string_pretty(data).unwrap_or_default());
}

/// ¿Existe el binario en PATH? (como shutil.which)
fn which(bin: &str) -> bool {
    Command::new("sh")
        .args(["-c", &format!("command -v {bin} >/dev/null 2>&1")])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Construye el comando swaylock a partir de la config (equivalente a _build_swaylock_cmd).
fn build_swaylock_cmd(data: &Value) -> Vec<String> {
    let mut cmd = vec!["swaylock".to_string()];

    // swaylock (stock) no tiene "--indicator <tipo>": el anillo es el
    // indicador por defecto y "none" se consigue con -u. "bar"/"dots"
    // tampoco existen en stock, caen al anillo por defecto.
    let indicator = data.get("indicator").and_then(|v| v.as_str()).unwrap_or("auto");
    if indicator == "none" {
        cmd.push("-u".to_string());
    }

    let wp = data.get("wallpaper_path").and_then(|v| v.as_str()).unwrap_or("");
    if !wp.is_empty() && PathBuf::from(wp).is_file() {
        cmd.push("-i".to_string());
        cmd.push(wp.to_string());
    }

    if data.get("screenshot").and_then(|v| v.as_bool()).unwrap_or(false) {
        cmd.push("-f".to_string());
    }

    if let Some(fade_in) = data.get("fade_in").and_then(|v| v.as_i64()) {
        if fade_in != 0 {
            cmd.push("-F".to_string());
            cmd.push(fade_in.to_string());
        }
    }

    if let Some(grace) = data.get("grace").and_then(|v| v.as_i64()) {
        if grace != 0 {
            cmd.push("-g".to_string());
            cmd.push(grace.to_string());
        }
    }

    let font = data.get("font").and_then(|v| v.as_str()).unwrap_or("");
    let font_size = data
        .get("font_size")
        .and_then(|v| v.as_i64())
        .unwrap_or(24);

    if !font.is_empty() {
        cmd.push("--font".to_string());
        cmd.push(font.to_string());
    }
    if font_size != 0 {
        cmd.push("--font-size".to_string());
        cmd.push(font_size.to_string());
    }

    for (key, flag) in [
        ("ring_color", "-r"),
        ("inside_color", "-s"),
        ("key_hl_color", "-k"),
        ("bs_color", "-b"),
        ("separator_color", "-n"),
    ] {
        let val = data.get(key).and_then(|v| v.as_str()).unwrap_or("");
        if !val.is_empty() {
            cmd.push(flag.to_string());
            cmd.push(val.trim_start_matches('#').to_string());
        }
    }

    cmd
}

/// Cita un argumento para sh (swayidle ejecuta el comando con sh -c).
fn sh_quote(arg: &str) -> String {
    if arg.chars().all(|c| c.is_ascii_alphanumeric() || "/._-+@%:".contains(c)) {
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
        which("swaylock")
    }

    pub fn is_idle_available() -> bool {
        which("swayidle")
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

    /// Lanza swaylock con la configuracion actual.
    pub fn preview() -> bool {
        if !Self::is_available() {
            return false;
        }
        let cmd = build_swaylock_cmd(&read_data());
        let mut command = Command::new(&cmd[0]);
        command.args(&cmd[1..]);
        command.stdout(Stdio::null()).stderr(Stdio::null());
        match command.spawn() {
            Ok(_) => true,
            Err(_) => false,
        }
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

        if !data.get("enabled").and_then(|v| v.as_bool()).unwrap_or(false) {
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
        cmd.stdout(Stdio::null()).stderr(Stdio::null());

        let uid = Command::new("id")
            .arg("-u")
            .output()
            .ok()
            .and_then(|o| String::from_utf8_lossy(&o.stdout).trim().parse::<u32>().ok())
            .unwrap_or(0);
        let xrd = std::env::var("XDG_RUNTIME_DIR")
            .unwrap_or_else(|_| format!("/run/user/{uid}"));
        if PathBuf::from(&xrd).is_dir() {
            cmd.env("XDG_RUNTIME_DIR", xrd);
        }

        let _ = cmd.spawn();
    }

    /// Wallpapers disponibles (equivalente a get_wallpapers).
    pub fn get_wallpapers() -> Vec<String> {
        crate::services::wallpaper::WallpaperService::list()
            .into_iter()
            .map(|p| p.to_string_lossy().to_string())
            .collect()
    }
}

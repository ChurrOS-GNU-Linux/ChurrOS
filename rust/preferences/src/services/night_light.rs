// ==========================================
// NightLightService — wlsunset: temperatura de color y gamma
// (equivalente a services/night_light.py)
// ==========================================

use std::fs;
use std::path::PathBuf;
use std::process::{Command, Stdio};

use serde_json::{json, Value};

fn config_dir() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home).join(".config").join("churros")
}

fn config_file() -> PathBuf {
    config_dir().join("night_light.json")
}

fn defaults() -> Value {
    json!({
        "enabled": false,
        "temp_day": 6500,
        "temp_night": 4500,
        "gamma": 1.0,
        "manual_lat": Value::Null,
        "manual_lng": Value::Null,
    })
}

/// Lee el JSON de ~/.config/churros/night_light.json y lo fusiona con los
/// defaults ({**DEFAULTS, **data} del Python). Ante cualquier error -> defaults.
fn read() -> Value {
    let default = defaults();
    let Ok(content) = fs::read_to_string(config_file()) else {
        return default;
    };
    let Ok(data) = serde_json::from_str::<Value>(&content) else {
        return default;
    };
    if let (Value::Object(mut merged), Value::Object(data)) = (default, data) {
        for (k, v) in data {
            merged.insert(k, v);
        }
        return Value::Object(merged);
    }
    defaults()
}

fn save(data: &Value) {
    if let Some(dir) = config_file().parent() {
        let _ = fs::create_dir_all(dir);
    }
    if let Ok(json) = serde_json::to_string_pretty(data) {
        let _ = fs::write(config_file(), json);
    }
}

/// pkill -x wlsunset (equivalente a _stop)
fn stop() {
    let _ = Command::new("pkill")
        .args(["-x", "wlsunset"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

/// Arranca/para wlsunset según el estado guardado (equivalente a _apply_state)
fn apply_state() {
    let data = read();

    let enabled = data.get("enabled").and_then(|v| v.as_bool()).unwrap_or(false);
    if !enabled {
        stop();
        return;
    }

    if !NightLightService::is_available() {
        return;
    }

    stop();

    let temp_day = data.get("temp_day").and_then(|v| v.as_i64()).unwrap_or(6500);
    let temp_night = data.get("temp_night").and_then(|v| v.as_i64()).unwrap_or(4500);
    let gamma = data.get("gamma").and_then(|v| v.as_f64()).unwrap_or(1.0);

    let t = temp_day.to_string();
    let t_n = temp_night.to_string();
    let g = gamma.to_string();

    let mut cmd = Command::new("wlsunset");
    cmd.arg("-t").arg(&t).arg("-T").arg(&t_n).arg("-g").arg(&g);

    let lat = data.get("manual_lat").and_then(|v| v.as_f64());
    let lng = data.get("manual_lng").and_then(|v| v.as_f64());

    if let (Some(lat), Some(lng)) = (lat, lng) {
        let lat_s = lat.to_string();
        let lng_s = lng.to_string();
        cmd.arg("-l").arg(&lat_s).arg("-L").arg(&lng_s);
    }

    if let Err(exc) = cmd.stdout(Stdio::null()).stderr(Stdio::null()).spawn() {
        println!("[night-light] spawn fallo: {exc}");
    }
}

pub struct NightLightService;

impl NightLightService {
    /// wlsunset instalado en /usr/bin o /usr/local/bin
    pub fn is_available() -> bool {
        PathBuf::from("/usr/bin/wlsunset").exists()
            || PathBuf::from("/usr/local/bin/wlsunset").exists()
    }

    pub fn is_enabled() -> bool {
        read().get("enabled").and_then(|v| v.as_bool()).unwrap_or(false)
    }

    pub fn set_enabled(enabled: bool) {
        let mut data = read();
        data["enabled"] = json!(enabled);
        save(&data);
        apply_state();
    }

    /// Temperatura de día en Kelvin (default 6500)
    pub fn get_temp_day() -> f64 {
        read()
            .get("temp_day")
            .and_then(|v| v.as_i64())
            .unwrap_or(6500) as f64
    }

    /// Temperatura de noche en Kelvin (default 4500)
    pub fn get_temp_night() -> f64 {
        read()
            .get("temp_night")
            .and_then(|v| v.as_i64())
            .unwrap_or(4500) as f64
    }

    /// int(day)/int(night) como en el Python
    pub fn set_temps(day: f64, night: f64) {
        let mut data = read();
        data["temp_day"] = json!(day as i64);
        data["temp_night"] = json!(night as i64);
        save(&data);
        apply_state();
    }

    pub fn get_gamma() -> f64 {
        read().get("gamma").and_then(|v| v.as_f64()).unwrap_or(1.0)
    }

    pub fn set_gamma(gamma: f64) {
        let mut data = read();
        data["gamma"] = json!(gamma);
        save(&data);
        apply_state();
    }

    /// (manual_lat, manual_lng) — Option<f64>, None si no configuradas
    pub fn get_location() -> (Option<f64>, Option<f64>) {
        let data = read();
        (
            data.get("manual_lat").and_then(|v| v.as_f64()),
            data.get("manual_lng").and_then(|v| v.as_f64()),
        )
    }

    pub fn set_location(lat: Option<f64>, lng: Option<f64>) {
        let mut data = read();
        data["manual_lat"] = json!(lat);
        data["manual_lng"] = json!(lng);
        save(&data);
        apply_state();
    }

    /// pgrep -x wlsunset -> returncode == 0
    pub fn is_running() -> bool {
        Command::new("pgrep")
            .args(["-x", "wlsunset"])
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }
}

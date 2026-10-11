// ==========================================
// SettingsService — ~/.config/churros/settings.json
// (equivalente a services/settings.py)
// ==========================================

use std::fs;
use std::path::PathBuf;

use serde_json::{Map, Value};

pub struct SettingsService;

fn config_dir() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home).join(".config").join("churros")
}

fn config_file() -> PathBuf {
    config_dir().join("settings.json")
}

fn defaults() -> Value {
    // El modo de fábrica es oscuro, igual que Noctalia `[theme].mode` y el
    // prefer-dark del skel. dynamic_colors arranca apagado: pywal recolorea
    // el acento GTK y pierde el naranja de ChurrOS.
    serde_json::json!({
        "theme": { "dark": true, "dynamic_colors": false },
        "accent": { "color": "Orange" },
        "wallpaper": { "path": "" },
        "icons": { "theme": "Papirus" },
        "cursor": { "theme": "Adwaita" },
        "fonts": { "family": "Inter", "scale": 1.0 }
    })
}

fn ensure() {
    let dir = config_dir();
    let file = config_file();
    if !dir.exists() {
        let _ = fs::create_dir_all(&dir);
    }
    if !file.exists() {
        let _ = fs::write(&file, serde_json::to_string_pretty(&defaults()).unwrap());
    }
}

pub fn load() -> Value {
    ensure();
    let Ok(content) = fs::read_to_string(config_file()) else {
        return defaults();
    };
    match serde_json::from_str::<Value>(&content) {
        Ok(v @ Value::Object(_)) => v,
        // JSON válido pero con raíz no-objeto ([] , "x", 42...): recuperarse
        // con defaults en vez de paniquear dentro de set().
        _ => defaults(),
    }
}

pub fn save(data: &Value) {
    ensure();
    let _ = fs::write(config_file(), serde_json::to_string_pretty(data).unwrap());
}

/// get("theme.dark") — navega por claves separadas por puntos
pub fn get(key: &str, default: Value) -> Value {
    let data = load();
    let mut current = &data;
    for part in key.split('.') {
        match current {
            Value::Object(map) => match map.get(part) {
                Some(v) => current = v,
                None => return default,
            },
            _ => return default,
        }
    }
    current.clone()
}

/// get_string("accent.color", "Orange")
pub fn get_string(key: &str, default: &str) -> String {
    match get(key, Value::String(default.to_string())) {
        Value::String(s) => s,
        Value::Bool(b) => b.to_string(),
        Value::Number(n) => n.to_string(),
        _ => default.to_string(),
    }
}

pub fn get_bool(key: &str, default: bool) -> bool {
    match get(key, Value::Bool(default)) {
        Value::Bool(b) => b,
        Value::String(s) => s == "1" || s.eq_ignore_ascii_case("true"),
        _ => default,
    }
}

pub fn set(key: &str, value: Value) {
    let mut data = load();
    let Some(mut current) = data.as_object_mut() else {
        // load() garantiza una raíz objeto, pero nunca paniquear aquí.
        return;
    };

    // Rechazar claves vacías o con segmentos vacíos ("a..b", ".a", ""):
    // si no, se insertarían claves "" en settings.json.
    if key.is_empty() || key.split('.').any(|s| s.is_empty()) {
        eprintln!("settings::set: clave inválida {key:?}");
        return;
    }

    let mut parts: Vec<&str> = key.split('.').collect();
    let last = parts.pop().unwrap();

    for part in &parts {
        let entry = current
            .entry(part.to_string())
            .or_insert_with(|| Value::Object(Map::new()));
        match entry {
            Value::Object(map) => current = map,
            _ => {
                *entry = Value::Object(Map::new());
                current = entry.as_object_mut().unwrap();
            }
        }
    }

    current.insert(last.to_string(), value);
    save(&data);
}

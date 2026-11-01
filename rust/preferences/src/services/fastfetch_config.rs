// ==========================================
// FastfetchConfig — ~/.config/fastfetch/config.jsonc
// Reads and writes the fastfetch JSONC configuration.
// ==========================================

use std::fs;
use std::path::PathBuf;

use serde_json::{json, Map, Value};

// ---- paths ----------------------------------------------------------------

fn config_dir() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home).join(".config").join("fastfetch")
}

fn config_path() -> PathBuf {
    config_dir().join("config.jsonc")
}

// ---- JSONC helpers --------------------------------------------------------

/// Strip `//` and `/* … */` comments from a JSONC string so that serde_json
/// can parse it.  Handles quoted strings correctly (no stripping inside them).
fn strip_jsonc_comments(src: &str) -> String {
    let bytes = src.as_bytes();
    let len = bytes.len();
    let mut out = String::with_capacity(len);
    let mut i = 0;
    let mut in_string = false;

    while i < len {
        if in_string {
            out.push(bytes[i] as char);
            if bytes[i] == b'\\' && i + 1 < len {
                i += 1;
                out.push(bytes[i] as char);
            } else if bytes[i] == b'"' {
                in_string = false;
            }
            i += 1;
            continue;
        }

        if bytes[i] == b'"' {
            in_string = true;
            out.push('"');
            i += 1;
            continue;
        }

        // line comment
        if i + 1 < len && bytes[i] == b'/' && bytes[i + 1] == b'/' {
            while i < len && bytes[i] != b'\n' {
                i += 1;
            }
            continue;
        }

        // block comment
        if i + 1 < len && bytes[i] == b'/' && bytes[i + 1] == b'*' {
            i += 2;
            while i + 1 < len && !(bytes[i] == b'*' && bytes[i + 1] == b'/') {
                i += 1;
            }
            i += 2; // skip */
            continue;
        }

        out.push(bytes[i] as char);
        i += 1;
    }
    out
}

// ---- read / write ---------------------------------------------------------

fn read_config() -> Value {
    let path = config_path();
    match fs::read_to_string(&path) {
        Ok(raw) => {
            let clean = strip_jsonc_comments(&raw);
            serde_json::from_str(&clean).unwrap_or_else(|_| json!({}))
        }
        Err(_) => json!({}),
    }
}

fn write_config(value: &Value) {
    let path = config_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    let serialized = serde_json::to_string_pretty(value).unwrap_or_default();
    let tmp = path.with_extension("jsonc.tmp");
    if fs::write(&tmp, &serialized).is_ok() {
        let _ = fs::rename(&tmp, &path);
    }
}

// ---- public API -----------------------------------------------------------

pub struct FastfetchConfig;

/// All known fastfetch module types that we allow the user to toggle.
pub const ALL_MODULES: &[(&str, &str)] = &[
    ("os", "Sistema operativo"),
    ("kernel", "Kernel"),
    ("packages", "Paquetes"),
    ("shell", "Shell"),
    ("wm", "Gestor de ventanas"),
    ("terminal", "Terminal"),
    ("cpu", "CPU"),
    ("gpu", "GPU"),
    ("memory", "Memoria"),
    ("disk", "Disco (/)"),
    ("uptime", "Tiempo encendido"),
    ("battery", "Batería"),
    ("display", "Pantalla"),
    ("de", "Entorno de escritorio"),
    ("theme", "Tema"),
    ("icons", "Iconos"),
    ("cursor", "Cursor"),
    ("locale", "Idioma"),
    ("users", "Usuarios"),
    ("host", "Equipo"),
    ("bios", "BIOS"),
    ("board", "Placa base"),
    ("datetime", "Fecha y hora"),
    ("localip", "IP local"),
    ("publicip", "IP pública"),
    ("wifi", "WiFi"),
    ("swap", "Swap"),
    ("processes", "Procesos"),
    ("sound", "Audio"),
    ("player", "Reproductor"),
    ("media", "Multimedia"),
    ("cpuusage", "Uso de CPU"),
    ("colors", "Paleta de colores"),
];

/// Logo source types for the combo box.
pub const LOGO_TYPES: &[(&str, &str)] = &[
    ("file", "Archivo ASCII / imagen"),
    ("builtin", "Logo integrado de fastfetch"),
    ("none", "Sin logo"),
];

impl FastfetchConfig {
    // ---- Logo ----

    /// Get the current logo source path (or empty).
    pub fn get_logo_source() -> String {
        let cfg = read_config();
        cfg.get("logo")
            .and_then(|l| l.get("source"))
            .and_then(|s| s.as_str())
            .unwrap_or("")
            .to_string()
    }

    /// Get the logo type: "file", "builtin", or "none".
    pub fn get_logo_type() -> String {
        let cfg = read_config();
        let logo = cfg.get("logo");
        match logo {
            None => "file".to_string(),
            Some(l) => {
                if let Some(t) = l.get("type").and_then(|v| v.as_str()) {
                    match t {
                        "none" | "disabled" => "none".to_string(),
                        "builtin" => "builtin".to_string(),
                        _ => "file".to_string(),
                    }
                } else if l
                    .get("source")
                    .and_then(|s| s.as_str())
                    .map_or(false, |s| s.is_empty())
                {
                    "none".to_string()
                } else {
                    "file".to_string()
                }
            }
        }
    }

    /// Get the four logo color overrides (color1..color4).
    pub fn get_logo_colors() -> [String; 4] {
        let cfg = read_config();
        let colors = cfg
            .get("logo")
            .and_then(|l| l.get("color"))
            .and_then(|c| c.as_object());
        let mut result = [
            String::new(),
            String::new(),
            String::new(),
            String::new(),
        ];
        if let Some(map) = colors {
            for i in 0..4 {
                let key = format!("{}", i + 1);
                if let Some(c) = map.get(&key).and_then(|v| v.as_str()) {
                    result[i] = c.to_string();
                }
            }
        }
        result
    }

    /// Get logo top padding.
    pub fn get_logo_padding_top() -> i64 {
        let cfg = read_config();
        cfg.get("logo")
            .and_then(|l| l.get("padding"))
            .and_then(|p| p.get("top"))
            .and_then(|v| v.as_i64())
            .unwrap_or(1)
    }

    /// Set the logo source path and type.
    pub fn set_logo_source(source: &str, logo_type: &str) {
        let mut cfg = read_config();
        let logo = cfg
            .as_object_mut()
            .unwrap()
            .entry("logo")
            .or_insert_with(|| json!({}));
        let obj = logo.as_object_mut().unwrap();

        match logo_type {
            "none" => {
                obj.insert("type".to_string(), json!("none"));
                obj.remove("source");
            }
            "builtin" => {
                obj.insert("type".to_string(), json!("builtin"));
                obj.insert("source".to_string(), json!(source));
            }
            _ => {
                // file — no explicit type needed (fastfetch auto-detects)
                obj.remove("type");
                obj.insert("source".to_string(), json!(source));
            }
        }
        write_config(&cfg);
    }

    /// Set logo color overrides.
    pub fn set_logo_colors(colors: &[String; 4]) {
        let mut cfg = read_config();
        let logo = cfg
            .as_object_mut()
            .unwrap()
            .entry("logo")
            .or_insert_with(|| json!({}));
        let obj = logo.as_object_mut().unwrap();
        let mut color_map = Map::new();
        for (i, c) in colors.iter().enumerate() {
            if !c.is_empty() {
                color_map.insert(format!("{}", i + 1), json!(c));
            }
        }
        if color_map.is_empty() {
            obj.remove("color");
        } else {
            obj.insert("color".to_string(), Value::Object(color_map));
        }
        write_config(&cfg);
    }

    /// Set logo top padding.
    pub fn set_logo_padding_top(val: i64) {
        let mut cfg = read_config();
        let logo = cfg
            .as_object_mut()
            .unwrap()
            .entry("logo")
            .or_insert_with(|| json!({}));
        let obj = logo.as_object_mut().unwrap();
        let padding = obj
            .entry("padding")
            .or_insert_with(|| json!({}));
        padding
            .as_object_mut()
            .unwrap()
            .insert("top".to_string(), json!(val));
        write_config(&cfg);
    }

    // ---- Display ----

    pub fn get_separator() -> String {
        let cfg = read_config();
        cfg.get("display")
            .and_then(|d| d.get("separator"))
            .and_then(|s| s.as_str())
            .unwrap_or(" 󰁔 ")
            .to_string()
    }

    pub fn get_key_width() -> i64 {
        let cfg = read_config();
        cfg.get("display")
            .and_then(|d| d.get("key"))
            .and_then(|k| k.get("width"))
            .and_then(|w| w.as_i64())
            .unwrap_or(12)
    }

    pub fn set_separator(sep: &str) {
        let mut cfg = read_config();
        let display = cfg
            .as_object_mut()
            .unwrap()
            .entry("display")
            .or_insert_with(|| json!({}));
        display
            .as_object_mut()
            .unwrap()
            .insert("separator".to_string(), json!(sep));
        write_config(&cfg);
    }

    pub fn set_key_width(width: i64) {
        let mut cfg = read_config();
        let display = cfg
            .as_object_mut()
            .unwrap()
            .entry("display")
            .or_insert_with(|| json!({}));
        let disp_obj = display.as_object_mut().unwrap();
        let key = disp_obj
            .entry("key")
            .or_insert_with(|| json!({}));
        key.as_object_mut()
            .unwrap()
            .insert("width".to_string(), json!(width));
        write_config(&cfg);
    }

    // ---- Modules ----

    /// Return the list of module type names currently enabled (in order).
    pub fn get_enabled_modules() -> Vec<String> {
        let cfg = read_config();
        let modules = match cfg.get("modules").and_then(|m| m.as_array()) {
            Some(arr) => arr,
            None => return Vec::new(),
        };
        let mut result = Vec::new();
        for m in modules {
            let type_str = m
                .get("type")
                .and_then(|t| t.as_str())
                .unwrap_or("");
            // Skip decorative modules (custom banners, separators)
            if type_str == "custom" || type_str == "separator" || type_str.is_empty() {
                continue;
            }
            result.push(type_str.to_lowercase());
        }
        result
    }

    /// Replace the modules list entirely. Preserves the header (custom banner)
    /// and footer (separator) if present in the original config.
    pub fn set_enabled_modules(modules: &[&str]) {
        let mut cfg = read_config();
        let old_modules = cfg
            .get("modules")
            .and_then(|m| m.as_array())
            .cloned()
            .unwrap_or_default();

        // Extract header lines (custom/separator at the beginning)
        let mut header: Vec<Value> = Vec::new();
        for m in &old_modules {
            let t = m.get("type").and_then(|t| t.as_str()).unwrap_or("");
            if t == "custom" || t == "separator" {
                header.push(m.clone());
            } else {
                break;
            }
        }

        // Extract footer lines (custom/separator at the end)
        let mut footer: Vec<Value> = Vec::new();
        for m in old_modules.iter().rev() {
            let t = m.get("type").and_then(|t| t.as_str()).unwrap_or("");
            if t == "custom" || t == "separator" {
                footer.insert(0, m.clone());
            } else {
                break;
            }
        }

        // Build a map of existing module definitions so we preserve custom
        // format strings, keyColor, etc. when re-enabling a module.
        let mut old_defs: std::collections::HashMap<String, Value> =
            std::collections::HashMap::new();
        for m in &old_modules {
            if let Some(t) = m.get("type").and_then(|t| t.as_str()) {
                let key = t.to_lowercase();
                if key != "custom" && key != "separator" {
                    old_defs.insert(key, m.clone());
                }
            }
        }

        let mut new_modules: Vec<Value> = header;
        for mod_type in modules {
            let key = mod_type.to_lowercase();
            if let Some(existing) = old_defs.get(&key) {
                new_modules.push(existing.clone());
            } else {
                // Build a minimal module entry
                let mut entry = Map::new();
                entry.insert("type".to_string(), json!(*mod_type));
                // Capitalize the key label
                let label = capitalize(mod_type);
                entry.insert("key".to_string(), json!(label));
                entry.insert("keyColor".to_string(), json!("yellow"));
                new_modules.push(Value::Object(entry));
            }
        }
        new_modules.extend(footer);

        cfg.as_object_mut()
            .unwrap()
            .insert("modules".to_string(), Value::Array(new_modules));
        write_config(&cfg);
    }

    /// Copy a file (ASCII art or image) into the fastfetch config dir and set
    /// it as the logo source.
    pub fn import_logo_file(src_path: &str) -> Result<String, String> {
        let src = std::path::Path::new(src_path);
        if !src.is_file() {
            return Err(format!("El archivo no existe: {src_path}"));
        }
        let dest_dir = config_dir();
        let _ = fs::create_dir_all(&dest_dir);
        let file_name = src
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| "custom-logo".to_string());
        let dest = dest_dir.join(&file_name);
        fs::copy(src, &dest).map_err(|e| format!("Error al copiar: {e}"))?;

        // Use ~ shorthand so the config is portable
        let rel = format!("~/.config/fastfetch/{file_name}");
        Self::set_logo_source(&rel, "file");
        Ok(rel)
    }

    /// Reset to the ChurrOS default config by copying from skel (if available)
    /// or writing a hardcoded default.
    pub fn reset_to_default() {
        let defaults_cfg = PathBuf::from("/usr/share/churros/defaults/fastfetch/config.jsonc");
        let skel_cfg = PathBuf::from("/etc/skel/.config/fastfetch/config.jsonc");
        let dest = config_path();
        let _ = fs::create_dir_all(config_dir());

        if defaults_cfg.is_file() {
            let _ = fs::copy(&defaults_cfg, &dest);
        } else if skel_cfg.is_file() {
            let _ = fs::copy(&skel_cfg, &dest);
        } else {
            let default = default_config();
            write_config(&default);
        }

        let defaults_logo = PathBuf::from("/usr/share/churros/defaults/fastfetch/churros-logo");
        let skel_logo = PathBuf::from("/etc/skel/.config/fastfetch/churros-logo");
        let dest_logo = config_dir().join("churros-logo");
        if defaults_logo.is_file() {
            let _ = fs::copy(&defaults_logo, &dest_logo);
        } else if skel_logo.is_file() {
            let _ = fs::copy(&skel_logo, &dest_logo);
        }
    }
}

fn capitalize(s: &str) -> String {
    let mut c = s.chars();
    match c.next() {
        None => String::new(),
        Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
    }
}

fn default_config() -> Value {
    json!({
        "$schema": "https://github.com/fastfetch-cli/fastfetch/raw/dev/doc/json_schema.json",
        "logo": {
            "source": "~/.config/fastfetch/churros-logo",
            "color": { "1": "red", "2": "yellow", "3": "green", "4": "white" },
            "padding": { "top": 1 }
        },
        "display": {
            "separator": " 󰁔 ",
            "key": { "width": 12 }
        },
        "modules": [
            { "type": "custom", "format": "┌──────────────────────────┐" },
            { "type": "custom", "format": "│       ChurrOS 1.4        │" },
            { "type": "custom", "format": "└──────────────────────────┘" },
            { "type": "separator" },
            { "type": "os",       "key": "OS",       "keyColor": "yellow" },
            { "type": "kernel",   "key": "Kernel",   "keyColor": "yellow" },
            { "type": "packages", "key": "Packages", "keyColor": "yellow" },
            { "type": "shell",    "key": "Shell",    "keyColor": "yellow" },
            { "type": "wm",       "key": "WM",       "keyColor": "yellow" },
            { "type": "terminal", "key": "Terminal",  "keyColor": "yellow" },
            { "type": "cpu", "format": "{name} ({cores-physical}C/{cores-logical}T) @ {freq-max}" },
            { "type": "gpu", "format": "{name} @ {frequency}" },
            { "type": "memory",  "key": "Memory",      "keyColor": "yellow", "format": "{used} / {total} ({percentage})" },
            { "type": "disk",    "key": "Disk (/)",     "keyColor": "yellow", "folders": "/", "format": "{size-used} / {size-total} ({size-percentage})" },
            { "type": "disk",    "key": "Disk (/home)", "keyColor": "yellow", "folders": "/home", "format": "{size-used} / {size-total} ({size-percentage})" },
            { "type": "uptime",  "key": "Uptime",      "keyColor": "yellow" },
            { "type": "separator" }
        ]
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_strip_jsonc_comments() {
        let input = r#"{
            // line comment
            "key": "value // not a comment",
            /* block comment */
            "nested": {
                "url": "http://example.com/*not comment*/"
            }
        }"#;
        let stripped = strip_jsonc_comments(input);
        assert!(!stripped.contains("// line comment"));
        assert!(!stripped.contains("/* block comment */"));
        assert!(stripped.contains("value // not a comment"));
        assert!(stripped.contains("http://example.com/*not comment*/"));

        let val: Value = serde_json::from_str(&stripped).expect("valid json after stripping");
        assert_eq!(val["key"], "value // not a comment");
    }

    #[test]
    fn test_default_config_structure() {
        let def = default_config();
        assert!(def.get("logo").is_some());
        assert!(def.get("display").is_some());
        assert!(def.get("modules").is_some());

        let logo = &def["logo"];
        assert_eq!(logo["source"], "~/.config/fastfetch/churros-logo");
        assert_eq!(logo["color"]["1"], "red");
        assert_eq!(logo["color"]["2"], "yellow");

        let modules = def["modules"].as_array().expect("modules is array");
        assert!(modules.len() > 5);
    }

    #[test]
    fn test_capitalize() {
        assert_eq!(capitalize("kernel"), "Kernel");
        assert_eq!(capitalize("os"), "Os");
        assert_eq!(capitalize(""), "");
    }

    #[test]
    fn test_all_modules_list_has_no_duplicates() {
        let mut seen = std::collections::HashSet::new();
        for (id, label) in ALL_MODULES {
            assert!(!id.is_empty());
            assert!(!label.is_empty());
            assert!(seen.insert(id), "duplicate module id: {id}");
        }
    }
}

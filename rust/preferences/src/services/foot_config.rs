// ==========================================
// FootConfig — ~/.config/foot/foot.ini
// (equivalente a services/dotfiles/foot_config.py)
// ==========================================

use std::fs;
use std::path::PathBuf;
use std::process::Command;

pub struct FootConfig;

fn config_path() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home).join(".config").join("foot").join("foot.ini")
}

fn read_lines() -> Vec<String> {
    match fs::read_to_string(config_path()) {
        Ok(content) => content.lines().map(|s| s.to_string()).collect(),
        Err(_) => Vec::new(),
    }
}

fn write_atomic(lines: &[String]) {
    let path = config_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    // Escritura atómica: tmp + rename
    let tmp = path.with_extension("ini.tmp");
    let content = lines.join("\n");
    if fs::write(&tmp, content).is_ok() {
        let _ = fs::rename(&tmp, &path);
    }
}

fn find_section(lines: &[String], section: &str) -> isize {
    for (i, line) in lines.iter().enumerate() {
        if line.trim() == format!("[{section}]") {
            return i as isize;
        }
    }
    -1
}

/// Actualiza o inserta `key=value` dentro de la sección (equivalente a _set_key).
fn set_key(lines: &mut Vec<String>, section: &str, key: &str, value: &str) {
    let mut section_idx = find_section(lines, section);
    if section_idx == -1 {
        lines.push(format!("\n[{section}]\n"));
        section_idx = (lines.len() - 1) as isize;
    }

    let mut end = lines.len();
    for j in (section_idx as usize + 1)..lines.len() {
        let stripped = lines[j].trim();
        if stripped.starts_with('[') && stripped.ends_with(']') {
            end = j;
            break;
        }
    }

    for j in (section_idx as usize + 1)..end {
        let stripped = lines[j].trim();
        if stripped.starts_with(&format!("{key}=")) || stripped.starts_with(&format!("{key} ")) {
            let prefix: String = lines[j]
                .chars()
                .take_while(|c| *c == ' ' || *c == '\t')
                .collect();
            lines[j] = format!("{prefix}{key}={value}");
            return;
        }
    }

    let insert = format!("    {key}={value}");
    lines.insert(end, insert);
}

fn get_key(section: &str, key: &str, default: &str) -> String {
    let lines = read_lines();
    let idx = find_section(&lines, section);
    if idx < 0 {
        return default.to_string();
    }
    for j in (idx as usize + 1)..lines.len() {
        let stripped = lines[j].trim();
        if stripped.starts_with('[') && stripped.ends_with(']') {
            break;
        }
        if let Some(rest) = stripped.strip_prefix(&format!("{key}=")) {
            return rest.trim().to_string();
        }
    }
    default.to_string()
}

fn get_key_bool(section: &str, key: &str, default: bool) -> bool {
    let v = get_key(section, key, if default { "yes" } else { "no" });
    let v = v.to_lowercase();
    v == "yes" || v == "true" || v == "1"
}

impl FootConfig {
    // ------------------------------------------------------------ Getters

    pub fn get_font() -> String {
        get_key("main", "font", "JetBrains Mono:size=10")
    }

    pub fn get_pad() -> String {
        get_key("main", "pad", "8x8")
    }

    pub fn get_cursor_style() -> String {
        get_key("cursor", "style", "beam")
    }

    pub fn get_cursor_blink() -> bool {
        get_key_bool("cursor", "blink", true)
    }

    pub fn get_bell() -> bool {
        get_key_bool("bell", "urgent", true)
    }

    pub fn get_hide_when_typing() -> bool {
        get_key_bool("mouse", "hide-when-typing", true)
    }

    // ------------------------------------------------------------- Setters

    pub fn set_font(font: &str) {
        let mut lines = read_lines();
        set_key(&mut lines, "main", "font", font);
        write_atomic(&lines);
    }

    /// Solo crea la sección [colors-dark]/[colors-light] si falta (como set_dark).
    #[allow(dead_code)] // portado por paridad; sin uso en las páginas actuales
    pub fn set_dark(dark: bool) {
        let mut lines = read_lines();
        let target_section = if dark { "colors-dark" } else { "colors-light" };
        let existing_dark = find_section(&lines, "colors-dark") != -1;
        let existing_light = find_section(&lines, "colors-light") != -1;

        if find_section(&lines, target_section) == -1 {
            if dark && !existing_dark {
                lines.push("[colors-dark]\n".to_string());
            } else if !dark && !existing_light {
                lines.push("[colors-light]\n".to_string());
            }
        }
        write_atomic(&lines);
    }

    pub fn set_pad(pad: &str) {
        let mut lines = read_lines();
        set_key(&mut lines, "main", "pad", pad);
        write_atomic(&lines);
    }

    pub fn set_cursor(style: &str, blink: bool) {
        let mut lines = read_lines();
        set_key(&mut lines, "cursor", "style", style);
        set_key(&mut lines, "cursor", "blink", if blink { "yes" } else { "no" });
        write_atomic(&lines);
    }

    pub fn set_bell(urgent: bool) {
        let mut lines = read_lines();
        let v = if urgent { "yes" } else { "no" };
        set_key(&mut lines, "bell", "urgent", v);
        set_key(&mut lines, "bell", "notify", v);
        write_atomic(&lines);
    }

    pub fn set_hide_when_typing(hide: bool) {
        let mut lines = read_lines();
        set_key(
            &mut lines,
            "mouse",
            "hide-when-typing",
            if hide { "yes" } else { "no" },
        );
        write_atomic(&lines);
    }

    /// pkill -SIGUSR1 foot (recarga la config en las terminales abiertas)
    pub fn reload() {
        // status() recoge el proceso: spawn() sin wait deja un zombi por cada pywal.
        // pkill sale distinto de 0 si no hay ninguna terminal; se ignora.
        let _ = Command::new("pkill")
            .args(["-SIGUSR1", "foot"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();
    }

    pub fn apply_pywal(colors: &serde_json::Map<String, serde_json::Value>, special: &serde_json::Map<String, serde_json::Value>) {
        let mut lines = read_lines();
        
        if let Some(bg) = special.get("background").and_then(|v| v.as_str()) {
            let bg = bg.trim_start_matches('#');
            set_key(&mut lines, "colors-dark", "background", bg);
            set_key(&mut lines, "colors-light", "background", bg);
        }
        if let Some(fg) = special.get("foreground").and_then(|v| v.as_str()) {
            let fg = fg.trim_start_matches('#');
            set_key(&mut lines, "colors-dark", "foreground", fg);
            set_key(&mut lines, "colors-light", "foreground", fg);
        }
        for i in 0..8 {
            if let Some(c) = colors.get(&format!("color{i}")).and_then(|v| v.as_str()) {
                let c = c.trim_start_matches('#');
                set_key(&mut lines, "colors-dark", &format!("regular{i}"), c);
                set_key(&mut lines, "colors-light", &format!("regular{i}"), c);
            }
        }
        for i in 8..16 {
            if let Some(c) = colors.get(&format!("color{i}")).and_then(|v| v.as_str()) {
                let c = c.trim_start_matches('#');
                set_key(&mut lines, "colors-dark", &format!("bright{}", i - 8), c);
                set_key(&mut lines, "colors-light", &format!("bright{}", i - 8), c);
            }
        }
        write_atomic(&lines);
        Self::reload();
    }
}

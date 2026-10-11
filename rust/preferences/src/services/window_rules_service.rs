// ==========================================
// WindowRulesService — window-rule de ~/.config/niri/config.kdl
// (equivalente a services/window_rules_service.py)
// ==========================================

use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;

pub struct WindowRulesService;

const INDENT: &str = "    ";

fn config_path() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home).join(".config").join("niri").join("config.kdl")
}

fn read() -> String {
    fs::read_to_string(config_path()).unwrap_or_default()
}

fn write_atomic(content: &str) {
    let path = config_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    // Escritura atómica: tmp + rename
    let tmp = path.with_extension("kdl.tmp");
    if fs::write(&tmp, content).is_ok() {
        let _ = fs::rename(&tmp, &path);
    }
}

/// Encuentra cada bloque top-level llamado `name`.
/// Devuelve (start_idx, end_idx) sobre lines() (la linea de cierre incluida).
fn find_all_blocks(content: &str, name: &str) -> (Vec<(usize, usize)>, Vec<String>) {
    let lines: Vec<String> = content.lines().map(|s| s.to_string()).collect();
    let mut stack: Vec<(usize, String, usize)> = Vec::new();
    let mut blocks: Vec<(usize, usize)> = Vec::new();

    for (i, raw) in lines.iter().enumerate() {
        let stripped = raw.trim();
        if stripped.is_empty() || stripped.starts_with("//") {
            continue;
        }
        if stripped.ends_with('{') {
            let head = stripped.trim_end_matches('{').trim();
            let head_name = head
                .split('=')
                .next()
                .unwrap_or("")
                .trim()
                .trim_matches('"')
                .to_string();
            stack.push((i, head_name, stack.len()));
        } else if stripped == "}" || stripped.starts_with('}') {
            if let Some((start_idx, head_name, depth)) = stack.pop() {
                if depth == 0 && head_name == name {
                    blocks.push((start_idx, i));
                }
            }
        }
    }

    (blocks, lines)
}

/// Regla vacía con todos los campos posibles.
fn empty_rule(index: usize) -> Value {
    json!({
        "index": index,
        "app_id": "",
        "title": "",
        "opacity": Value::Null,
        "open_floating": Value::Null,
        "corner_radius": Value::Null,
        "clip_to_geometry": Value::Null,
        "blur": Value::Null,
    })
}

/// Primera cadena entre comillas de la línea.
fn first_quoted(line: &str) -> Option<String> {
    let start = line.find('"')? + 1;
    let rest = &line[start..];
    let end = rest.find('"')?;
    Some(rest[..end].to_string())
}

/// Serializa una regla a KDL (equivalente a _serialize_rule).
fn serialize_rule(rule: &Value) -> String {
    let mut lines = vec!["window-rule {".to_string()];

    if let Some(app_id) = rule.get("app_id").and_then(|v| v.as_str()) {
        if !app_id.is_empty() {
            lines.push(format!("{INDENT}match app-id=\"{app_id}\""));
        }
    }
    if let Some(title) = rule.get("title").and_then(|v| v.as_str()) {
        if !title.is_empty() {
            lines.push(format!("{INDENT}match title=\"{title}\""));
        }
    }
    if let Some(opacity) = rule.get("opacity").and_then(|v| v.as_f64()) {
        lines.push(format!("{INDENT}opacity {opacity}"));
    }
    if let Some(open_floating) = rule.get("open_floating").and_then(|v| v.as_bool()) {
        lines.push(format!("{INDENT}open-floating {open_floating}"));
    }
    if let Some(corner_radius) = rule.get("corner_radius").and_then(|v| v.as_f64()) {
        lines.push(format!("{INDENT}geometry-corner-radius {corner_radius}"));
    }
    if let Some(clip) = rule.get("clip_to_geometry").and_then(|v| v.as_bool()) {
        lines.push(format!("{INDENT}clip-to-geometry {clip}"));
    }
    if let Some(blur) = rule.get("blur").and_then(|v| v.as_bool()) {
        lines.push(format!("{INDENT}background-effect {{"));
        lines.push(format!("{INDENT}{INDENT}blur {blur}"));
        lines.push(format!("{INDENT}}}"));
    }

    lines.push("}".to_string());
    lines.join("\n") + "\n"
}

/// Reescribe todas las reglas (equivalente a _rewrite_all).
///
/// Reemplaza SOLO los bloques window-rule, conservando el contenido que haya
/// entre ellos (comentarios, marcadores [CHURROS-GLASS-*], otros bloques).
/// La versión anterior descartaba todo lo que hubiera entre el primer y el
/// último bloque.
fn rewrite_all(rules: &[Value]) {
    let content = read();
    let (blocks, lines) = find_all_blocks(&content, "window-rule");
    if blocks.is_empty() {
        return;
    }

    let mut out: Vec<String> = Vec::new();
    let mut cursor = 0usize;
    for (i, (start, end)) in blocks.iter().enumerate() {
        for l in &lines[cursor..*start] {
            out.push(l.clone());
        }
        if let Some(rule) = rules.get(i) {
            for l in serialize_rule(rule).lines() {
                out.push(l.to_string());
            }
        }
        cursor = end + 1;
    }
    for l in &lines[cursor..] {
        out.push(l.clone());
    }

    write_atomic(&(out.join("\n") + "\n"));
}

impl WindowRulesService {
    /// Lista las window-rule del config (equivalente a list_rules).
    pub fn list_rules() -> Vec<Value> {
        let content = read();
        let (blocks, lines) = find_all_blocks(&content, "window-rule");
        let mut rules = Vec::new();

        for (idx, (start, end)) in blocks.iter().enumerate() {
            let mut rule = empty_rule(idx);

            for j in start + 1..*end {
                let stripped = lines[j].trim().to_string();

                if stripped.starts_with("match app-id") {
                    if let Some(m) = first_quoted(&stripped) {
                        rule["app_id"] = json!(m);
                        continue;
                    }
                }
                if stripped.starts_with("match title") {
                    if let Some(m) = first_quoted(&stripped) {
                        rule["title"] = json!(m);
                        continue;
                    }
                }

                if stripped.starts_with("opacity") {
                    if let Some(v) = stripped.split_whitespace().nth(1).and_then(|v| v.parse::<f64>().ok()) {
                        rule["opacity"] = json!(v);
                    }
                } else if stripped.starts_with("open-floating") {
                    if let Some(v) = stripped.split_whitespace().nth(1) {
                        rule["open_floating"] = json!(v == "true");
                    }
                } else if stripped.starts_with("geometry-corner-radius") {
                    if let Some(v) = stripped.split_whitespace().nth(1).and_then(|v| v.parse::<f64>().ok()) {
                        rule["corner_radius"] = json!(v);
                    }
                } else if stripped.starts_with("clip-to-geometry") {
                    if let Some(v) = stripped.split_whitespace().nth(1) {
                        rule["clip_to_geometry"] = json!(v == "true");
                    }
                } else if stripped.starts_with("background-effect") {
                    // Bloque background-effect { ... blur true ... }
                    let mut inner_end = None;
                    for k in j + 1..*end {
                        let s = lines[k].trim();
                        if s == "}" || s.starts_with('}') {
                            inner_end = Some(k);
                            break;
                        }
                    }
                    if let Some(inner_end) = inner_end {
                        for k in j + 1..inner_end {
                            let s = lines[k].trim();
                            if s.starts_with("blur") {
                                let parts: Vec<&str> = s.split_whitespace().collect();
                                if parts.len() == 2 {
                                    rule["blur"] = json!(parts[1] == "true");
                                }
                            }
                        }
                    }
                }
            }

            rules.push(rule);
        }

        rules
    }

    /// Añade una regla al final del config (equivalente a add_rule).
    pub fn add_rule(
        app_id: &str,
        title: &str,
        opacity: Option<f64>,
        open_floating: Option<bool>,
        corner_radius: Option<f64>,
        clip_to_geometry: Option<bool>,
        blur: Option<bool>,
    ) -> usize {
        let rule = json!({
            "app_id": app_id,
            "title": title,
            "opacity": opacity,
            "open_floating": open_floating,
            "corner_radius": corner_radius,
            "clip_to_geometry": clip_to_geometry,
            "blur": blur,
        });

        let rule_str = serialize_rule(&rule);

        let mut content = read();
        if !content.is_empty() && !content.ends_with('\n') {
            content.push('\n');
        }
        content += &format!("\n// Window rule (custom)\n{rule_str}");

        write_atomic(&content);

        let (blocks, _) = find_all_blocks(&content, "window-rule");
        blocks.len() - 1
    }

    /// Actualiza la regla `index` (equivalente a update_rule).
    pub fn update_rule(index: usize, updates: &Value) -> Result<(), String> {
        let mut rules = Self::list_rules();
        if index >= rules.len() {
            return Err(format!("window-rule index out of range: {index}"));
        }
        if let Some(obj) = updates.as_object() {
            if let Some(rule) = rules[index].as_object_mut() {
                for (k, v) in obj {
                    rule.insert(k.clone(), v.clone());
                }
            }
        }
        rewrite_all(&rules);
        Ok(())
    }

    /// Borra la regla `index` (equivalente a delete_rule).
    pub fn delete_rule(index: usize) -> Result<(), String> {
        let mut rules = Self::list_rules();
        if index >= rules.len() {
            return Err(format!("window-rule index out of range: {index}"));
        }
        rules.remove(index);
        rewrite_all(&rules);
        Ok(())
    }
}

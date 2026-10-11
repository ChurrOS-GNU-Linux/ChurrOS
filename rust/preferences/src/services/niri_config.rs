// ==========================================
// NiriConfig — lee/edita ~/.config/niri/config.kdl
// (equivalente a services/dotfiles/niri_config.py, subset: animations + csd)
// ==========================================

use std::fs;
use std::path::PathBuf;
use std::process::Command;

pub struct NiriConfig;

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

/// Encuentra [start, end) de un bloque `name { ... }` (líneas, 0-indexado)
fn find_block(content: &str, names: &[&str]) -> Option<(usize, usize)> {
    let lines: Vec<&str> = content.lines().collect();
    let mut depth = 0i32;
    let mut start = None;

    for (i, raw) in lines.iter().enumerate() {
        let stripped = raw.trim();

        if let Some(s) = start {
            depth += stripped.matches('{').count() as i32;
            depth -= stripped.matches('}').count() as i32;
            if depth <= 0 {
                return Some((s, i + 1));
            }
            continue;
        }

        // Buscar "name {" al inicio de la línea
        for name in names {
            if stripped == format!("{name} {{") || stripped.starts_with(&format!("{name} {{")) {
                start = Some(i);
                depth = 1;
                // Si el bloque abre y cierra en la misma línea
                if stripped.matches('{').count() > stripped.matches('}').count() {
                    // sigue en la misma línea; se procesa en la siguiente iteración
                } else {
                    return Some((i, i + 1));
                }
                break;
            }
        }
    }
    None
}

// ============================================================
// Helpers para bloques anidados (layout > border, animations > name)
// (equivalentes a _find_block / _update_value_in_block / _create_block
//  y _extract_value de services/dotfiles/niri_config.py)
// ============================================================

/// Encuentra (start, end) de un bloque anidado `path` (p.ej. ["layout", "border"]).
/// Devuelve indices sobre lines(); incluye la linea de apertura y la de cierre.
fn find_nested_block(content: &str, path: &[&str]) -> Option<(usize, usize)> {
    let lines: Vec<&str> = content.lines().collect();
    let mut stack: Vec<(usize, String)> = Vec::new();

    for (i, raw) in lines.iter().enumerate() {
        let stripped = raw.trim();
        if stripped.is_empty() || stripped.starts_with("//") {
            continue;
        }
        if stripped.ends_with('{') {
            let mut name = stripped.trim_end_matches('{').trim().to_string();
            // Quitar posibles comillas finales y el lado "valor" de `name = "x" {`
            name = name.trim_end_matches('"').to_string();
            if let Some(eq) = name.find('=') {
                name.truncate(eq);
            }
            let name = name.trim().trim_matches('"').to_string();
            stack.push((i, name));
        } else if stripped == "}" || stripped.starts_with('}') {
            if let Some((start, _name)) = stack.last() {
                let full_path: Vec<&str> = stack.iter().map(|(_, n)| n.as_str()).collect();
                if full_path == path {
                    return Some((*start, i));
                }
                stack.pop();
            }
        }
    }
    None
}

/// Actualiza o inserta `key value` dentro del bloque `path`.
/// Devuelve None si el bloque no existe (el caller debe crearlo).
fn update_value_in_block(content: &str, path: &[&str], key: &str, value: &str) -> Option<String> {
    let mut lines: Vec<String> = content.lines().map(|s| s.to_string()).collect();
    let (start, end) = find_nested_block(content, path)?;

    let base_indent: String = lines[start]
        .chars()
        .take_while(|c| *c == ' ' || *c == '\t')
        .collect();
    let inner_indent = format!("{base_indent}    ");

    for j in start + 1..end {
        let stripped = lines[j].trim().to_string();
        if stripped.starts_with(&format!("{key} ")) || stripped.starts_with(&format!("{key}=")) {
            lines[j] = format!("{inner_indent}{key} {value}");
            return Some(lines.join("\n"));
        }
    }

    let insert = format!("{inner_indent}{key} {value}");
    lines.insert(end, insert);
    Some(lines.join("\n"))
}

/// Crea el bloque `path` al final del config, creando los padres que falten.
/// Crea el bloque `path` (y los padres que falten), con `body_lines` como
/// contenido del bloque más profundo. Si algún padre ya existe, el bloque
/// nuevo se anida dentro de él; si no existe ninguno, se añade al final.
/// (La versión anterior creaba el padre vacío y perdía el hijo.)
fn create_block(content: &str, path: &[&str], body_lines: &[&str]) -> String {
    // Profundidad del prefijo que ya existe.
    let mut existing_depth = 0usize;
    for i in 1..=path.len() {
        if find_nested_block(content, &path[..i]).is_some() {
            existing_depth = i;
        } else {
            break;
        }
    }

    if existing_depth == path.len() {
        return content.to_string();
    }

    // Construir los bloques que faltan, de adentro hacia afuera.
    let mut inner = String::new();
    let deepest_indent = "    ".repeat(path.len());
    for ln in body_lines {
        inner.push_str(&format!("{deepest_indent}{ln}\n"));
    }
    for i in (existing_depth..path.len()).rev() {
        let indent = "    ".repeat(i);
        let head = path[i];
        inner = format!("{indent}{head} {{\n{inner}{indent}}}\n");
    }

    if existing_depth > 0 {
        // Anidar justo antes del cierre del padre existente.
        let (_, parent_end) = find_nested_block(content, &path[..existing_depth]).unwrap();
        let lines: Vec<&str> = content.lines().collect();
        let mut out: Vec<String> = lines[..parent_end].iter().map(|s| s.to_string()).collect();
        for l in inner.lines() {
            out.push(l.to_string());
        }
        out.extend(lines[parent_end..].iter().map(|s| s.to_string()));
        out.join("\n")
    } else {
        let mut c = content.to_string();
        if !c.is_empty() && !c.ends_with('\n') {
            c.push('\n');
        }
        c.push_str(&inner);
        c
    }
}

/// Extrae el valor de `key` dentro del bloque `block_path` (getters).
fn extract_value(content: &str, block_path: &[&str], key: &str) -> Option<String> {
    let lines: Vec<&str> = content.lines().collect();
    let target_depth = block_path.len();
    let mut stack: Vec<String> = Vec::new();
    let mut depth = 0usize;

    for raw in lines {
        let stripped = raw.trim();
        if stripped.is_empty() || stripped.starts_with("//") {
            continue;
        }
        if stripped.ends_with('{') {
            let mut name = stripped.trim_end_matches('{').trim().to_string();
            if let Some(eq) = name.find('=') {
                name.truncate(eq);
            }
            let name = name.trim().trim_matches('"').to_string();
            stack.push(name);
            depth += 1;
        } else if stripped == "}" || stripped.starts_with('}') {
            if !stack.is_empty() {
                stack.pop();
                depth -= 1;
            }
        }

        if depth == target_depth
            && stack.iter().map(|s| s.as_str()).collect::<Vec<_>>() == block_path
            && (stripped.starts_with(&format!("{key} ")) || stripped.starts_with(&format!("{key}=")))
        {
            let value = stripped[key.len()..].trim().trim_start_matches('=').trim();
            return Some(value.trim_end_matches(';').trim().to_string());
        }
    }
    None
}

/// str(float) estilo Python: 2.0 -> "2.0", 1.2 -> "1.2", 0.05 -> "0.05"
fn py_float_str(v: f64) -> String {
    if v.fract() == 0.0 {
        format!("{v:.1}")
    } else {
        format!("{v}")
    }
}

impl NiriConfig {
    /// Actualiza `input { keyboard { xkb { layout "..." } } }` (o lo crea).
    /// La versión anterior usaba una clave plana `xkb-layout` que no existe
    /// en el config y además rompía con sub-bloques anidados.
    pub fn set_keyboard_layout(layout: &str) {
        let content = read();

        // Editar `layout "..."` dentro de input > keyboard > xkb.
        if let Some(updated) = update_value_in_block(
            &content,
            &["input", "keyboard", "xkb"],
            "layout",
            &format!("\"{layout}\""),
        ) {
            write_atomic(&updated);
            return;
        }

        // No existe el bloque xkb: crearlo anidado (con sus padres).
        let result = create_block(
            &content,
            &["input", "keyboard", "xkb"],
            &[&format!("layout \"{layout}\"")],
        );
        write_atomic(&result);
    }

    /// Recarga la config de niri en vivo (equivalente a reload()).
    /// OJO: NO usar pkill -HUP niri — SIGHUP reinicia la sesión entera
    /// del compositor (mata todas las apps); la forma correcta es
    /// `niri msg action load-config-file`.
    pub fn reload() {
        let _ = Command::new("niri")
            .args(["msg", "action", "load-config-file"])
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null())
            .status();
    }

    // -------------------------------------------------------- Animations

    pub fn get_animations() -> bool {
        let content = read();
        let Some((start, end)) = find_block(&content, &["animations"]) else {
            return true;
        };

        let lines: Vec<&str> = content.lines().collect();
        for j in start + 1..end {
            let stripped = lines[j].trim();
            if stripped == "off" {
                return false;
            }
            if stripped == "on" {
                return true;
            }
        }
        true
    }

    pub fn set_animations(on: bool) {
        let content = read();
        let block = find_block(&content, &["animations"]);
        let (start, end) = match block {
            Some(b) => b,
            None => {
                if !on {
                    let mut content = content;
                    if !content.ends_with('\n') {
                        content.push('\n');
                    }
                    content.push_str("animations {\n    off\n}\n");
                    write_atomic(&content);
                }
                return;
            }
        };

        let mut lines: Vec<String> = content.lines().map(|s| s.to_string()).collect();

        if !on {
            // Asegurar que hay una línea "off" dentro del bloque
            let has_off = (start + 1..end).any(|j| lines[j].trim() == "off");
            if !has_off {
                let mut insert_idx = end;
                for j in start + 1..end {
                    if !lines[j].trim().is_empty() {
                        insert_idx = j;
                        break;
                    }
                }
                lines.insert(insert_idx, "    off".to_string());
                write_atomic(&lines.join("\n"));
            }
        } else {
            // Quitar "off" (y líneas vacías) del bloque
            let new_inner: Vec<String> = lines[start + 1..end]
                .iter()
                .filter(|l| !l.trim().is_empty() && l.trim() != "off")
                .cloned()
                .collect();

            if new_inner.is_empty() {
                // Bloque vacío -> eliminar el bloque entero
                lines.drain(start..=end);
                write_atomic(&lines.join("\n"));
            } else {
                lines.drain(start + 1..end);
                for (k, l) in new_inner.iter().enumerate() {
                    lines.insert(start + 1 + k, l.clone());
                }
                write_atomic(&lines.join("\n"));
            }
        }
    }

    // ------------------------------------------------------- prefer-no-csd

    pub fn get_prefer_no_csd() -> bool {
        let content = read();
        content
            .lines()
            .any(|l| l.trim() == "prefer-no-csd")
    }

    pub fn set_prefer_no_csd(on: bool) {
        let content = read();
        let mut lines: Vec<String> = content.lines().map(|s| s.to_string()).collect();

        for i in 0..lines.len() {
            if lines[i].trim() == "prefer-no-csd" {
                if !on {
                    lines.remove(i);
                    write_atomic(&lines.join("\n"));
                }
                return;
            }
        }

        // No existe
        if on {
            if !content.ends_with('\n') {
                if let Some(last) = lines.last_mut() {
                    last.push('\n');
                }
            }
            lines.push("prefer-no-csd".to_string());
            write_atomic(&lines.join("\n"));
        }
    }
}

impl NiriConfig {
    // --------------------------------------------------------------- Gaps

    pub fn get_gaps() -> i64 {
        let content = read();
        match extract_value(&content, &["layout"], "gaps") {
            Some(v) => v.parse().unwrap_or(16),
            None => 16,
        }
    }

    pub fn set_gaps(gaps: i64) {
        let content = read();
        let result = match update_value_in_block(&content, &["layout"], "gaps", &gaps.to_string()) {
            Some(updated) => updated,
            None => create_block(&content, &["layout"], &[&format!("gaps {gaps}")]),
        };
        write_atomic(&result);
    }

    // --------------------------------------------------------------- Border

    pub fn get_border() -> serde_json::Value {
        let content = read();
        let Some((start, end)) = find_nested_block(&content, &["layout", "border"]) else {
            return serde_json::json!({
                "on": false, "width": 0, "active_color": "", "inactive_color": ""
            });
        };

        let lines: Vec<&str> = content.lines().collect();
        let mut width = 0i64;
        let mut active_color = String::new();
        let mut inactive_color = String::new();

        for j in start + 1..end {
            let stripped = lines[j].trim();
            if stripped.starts_with("width") {
                if let Some(w) = stripped.split_whitespace().nth(1).and_then(|v| v.parse().ok()) {
                    width = w;
                }
            } else if stripped.starts_with("active-color") {
                if let Some(m) = first_quoted(stripped) {
                    active_color = m;
                }
            } else if stripped.starts_with("inactive-color") {
                if let Some(m) = first_quoted(stripped) {
                    inactive_color = m;
                }
            }
        }

        serde_json::json!({
            "on": true, "width": width,
            "active_color": active_color, "inactive_color": inactive_color
        })
    }

    #[allow(clippy::too_many_arguments)]
    pub fn set_border(on: bool, width: i64, active_color: &str, inactive_color: &str) {
        let content = read();
        let block = find_nested_block(&content, &["layout", "border"]);

        if !on {
            if let Some((start, end)) = block {
                let mut lines: Vec<&str> = content.lines().collect();
                lines.drain(start..=end);
                write_atomic(&lines.join("\n"));
            }
            return;
        }

        let Some((start, end)) = block else {
            // Crear el bloque (dentro de layout si existe, si no al final)
            let mut body: Vec<String> = Vec::new();
            body.push(format!("width {width}"));
            body.push(format!("active-color \"{active_color}\""));
            body.push(format!("inactive-color \"{inactive_color}\""));

            let result = match find_nested_block(&content, &["layout"]) {
                Some((_, parent_end)) => {
                    let mut lines: Vec<String> = content.lines().map(|s| s.to_string()).collect();
                    let mut block_str = String::from("    border {\n");
                    for ln in &body {
                        block_str += &format!("        {ln}\n");
                    }
                    block_str += "    }";
                    lines.insert(parent_end, block_str);
                    lines.join("\n")
                }
                None => {
                    let body_refs: Vec<&str> = body.iter().map(|s| s.as_str()).collect();
                    create_block(&content, &["layout", "border"], &body_refs)
                }
            };
            write_atomic(&result);
            return;
        };

        // Bloque existente: actualizar cada valor
        let mut lines: Vec<String> = content.lines().map(|s| s.to_string()).collect();
        let base_indent: String = lines[start]
            .chars()
            .take_while(|c| *c == ' ' || *c == '\t')
            .collect();
        let inner = format!("{base_indent}    ");

        let updates: [(&str, String); 3] = [
            ("width", width.to_string()),
            ("active-color", format!("\"{active_color}\"")),
            ("inactive-color", format!("\"{inactive_color}\"")),
        ];

        for (key, value) in updates {
            for j in start + 1..end {
                let stripped = lines[j].trim().to_string();
                if stripped.starts_with(&format!("{key} ")) || stripped.starts_with(&format!("{key}="))
                {
                    lines[j] = format!("{inner}{key} {value}");
                    break;
                }
            }
        }
        write_atomic(&lines.join("\n"));
    }

    // ----------------------------------------------------------- Focus ring

    pub fn get_focus_ring() -> bool {
        let content = read();
        let Some((start, end)) = find_nested_block(&content, &["layout", "focus-ring"]) else {
            return false;
        };
        let lines: Vec<&str> = content.lines().collect();
        for j in start + 1..end {
            let stripped = lines[j].trim();
            if stripped == "off" {
                return false;
            }
            if stripped == "on" {
                return true;
            }
        }
        true
    }

    pub fn set_focus_ring(on: bool) {
        let content = read();
        let block = find_nested_block(&content, &["layout", "focus-ring"]);

        if !on {
            if let Some((start, end)) = block {
                let mut lines: Vec<&str> = content.lines().collect();
                lines.drain(start..=end);
                write_atomic(&lines.join("\n"));
            } else {
                let result = match find_nested_block(&content, &["layout"]) {
                    Some((_, parent_end)) => {
                        let mut lines: Vec<String> =
                            content.lines().map(|s| s.to_string()).collect();
                        lines.insert(parent_end, "    focus-ring {\n        off\n    }".to_string());
                        lines.join("\n")
                    }
                    None => create_block(&content, &["layout", "focus-ring"], &["off"]),
                };
                write_atomic(&result);
            }
            return;
        }

        if let Some((start, end)) = block {
            let mut lines: Vec<String> = content.lines().map(|s| s.to_string()).collect();
            let has_on = (start + 1..end).any(|j| lines[j].trim() == "on");
            if !has_on {
                let mut insert_idx = end;
                for j in start + 1..end {
                    if !lines[j].trim().is_empty() {
                        insert_idx = j;
                        break;
                    }
                }
                lines.insert(insert_idx, "        on".to_string());
                write_atomic(&lines.join("\n"));
            }
            return;
        }

        let result = match find_nested_block(&content, &["layout"]) {
            Some((_, parent_end)) => {
                let mut lines: Vec<String> = content.lines().map(|s| s.to_string()).collect();
                lines.insert(parent_end, "    focus-ring {\n        on\n    }".to_string());
                lines.join("\n")
            }
            None => create_block(&content, &["layout", "focus-ring"], &["on"]),
        };
        write_atomic(&result);
    }

    // ---------------------------------------------------------------- Blur

    pub fn get_blur_enabled() -> bool {
        let content = read();
        find_nested_block(&content, &["blur"]).is_some()
    }

    pub fn set_blur_enabled(on: bool) {
        let content = read();
        if !on {
            if let Some((start, end)) = find_nested_block(&content, &["blur"]) {
                let mut lines: Vec<&str> = content.lines().collect();
                lines.drain(start..=end);
                write_atomic(&lines.join("\n"));
            }
        } else {
            // Re-enable with defaults
            let result = match find_nested_block(&content, &["blur"]) {
                Some(_) => content,
                None => create_block(
                    &content,
                    &["blur"],
                    &["passes 3", "offset 3.0", "noise 0.0", "saturation 1.3"],
                ),
            };
            write_atomic(&result);
        }
    }

    pub fn get_blur() -> serde_json::Value {
        let content = read();
        let Some((start, end)) = find_nested_block(&content, &["blur"]) else {
            return serde_json::json!({
                "passes": 0, "offset": 0.0, "noise": 0.0, "saturation": 1.0
            });
        };

        let lines: Vec<&str> = content.lines().collect();
        let mut passes = 0i64;
        let mut offset = 0.0f64;
        let mut noise = 0.0f64;
        let mut saturation = 1.0f64;

        for j in start + 1..end {
            let parts: Vec<&str> = lines[j].trim().split_whitespace().collect();
            if parts.len() == 2 {
                match parts[0] {
                    "passes" => {
                        if let Ok(v) = parts[1].parse() {
                            passes = v;
                        }
                    }
                    "offset" => {
                        if let Ok(v) = parts[1].parse() {
                            offset = v;
                        }
                    }
                    "noise" => {
                        if let Ok(v) = parts[1].parse() {
                            noise = v;
                        }
                    }
                    "saturation" => {
                        if let Ok(v) = parts[1].parse() {
                            saturation = v;
                        }
                    }
                    _ => {}
                }
            }
        }

        serde_json::json!({
            "passes": passes, "offset": offset, "noise": noise, "saturation": saturation
        })
    }

    pub fn set_blur(passes: i64, offset: f64, noise: f64, saturation: f64) {
        let content = read();
        // str(int) / str(float) estilo Python
        let changes: [(&str, String); 4] = [
            ("passes", passes.to_string()),
            ("offset", py_float_str(offset)),
            ("noise", py_float_str(noise)),
            ("saturation", py_float_str(saturation)),
        ];

        let Some((start, end)) = find_nested_block(&content, &["blur"]) else {
            let body: Vec<String> = changes
                .iter()
                .map(|(k, v)| format!("{k} {v}"))
                .collect();
            let body_refs: Vec<&str> = body.iter().map(|s| s.as_str()).collect();
            let result = create_block(&content, &["blur"], &body_refs);
            write_atomic(&result);
            return;
        };

        let mut lines: Vec<String> = content.lines().map(|s| s.to_string()).collect();
        let base_indent: String = lines[start]
            .chars()
            .take_while(|c| *c == ' ' || *c == '\t')
            .collect();
        let inner = format!("{base_indent}    ");

        for (key, value) in changes {
            let mut found = false;
            for j in start + 1..end {
                let stripped = lines[j].trim().to_string();
                if stripped.starts_with(&format!("{key} ")) || stripped.starts_with(&format!("{key}="))
                {
                    lines[j] = format!("{inner}{key} {value}");
                    found = true;
                    break;
                }
            }
            if !found {
                lines.insert(end, format!("{inner}{key} {value}"));
            }
        }
        write_atomic(&lines.join("\n"));
    }

    // ------------------------------------------------- Performance mode

    /// Marcadores del bloque de blur de las apps ChurrOS en config.kdl
    /// (ver archiso/airootfs/etc/skel/.config/niri/config.kdl).
    const GLASS_START: &'static str = "[CHURROS-GLASS-START]";
    const GLASS_END: &'static str = "[CHURROS-GLASS-END]";

    /// Byte bounds de la región entre las líneas de marcador (exclusivas).
    /// Se busca el marcador como LÍNEA completa para que las menciones
    /// en comentarios descriptivos no confundan el matcher.
    fn glass_bounds(content: &str) -> Option<(usize, usize)> {
        let start_marker = "\n// [CHURROS-GLASS-START]\n";
        let end_marker = "\n// [CHURROS-GLASS-END]";
        let start = content.find(start_marker)? + start_marker.len();
        let end = start + content[start..].find(end_marker)?;
        Some((start, end))
    }

    /// Devuelve si el blur de las window rules de ChurrOS está activo
    /// (None si el config no tiene los marcadores).
    fn get_glass_blur(content: &str) -> Option<bool> {
        let (start, end) = Self::glass_bounds(content)?;
        for line in content[start..end].lines() {
            match line.trim() {
                "blur true" => return Some(true),
                "blur false" => return Some(false),
                _ => {}
            }
        }
        Some(false)
    }

    /// Toggle blur true <-> blur false SOLO en líneas exactas dentro del
    /// bloque marcado (los comentarios que mencionen blur no se tocan).
    fn set_glass_blur(content: &str, enabled: bool) -> Option<String> {
        let (start, end) = Self::glass_bounds(content)?;
        let region = &content[start..end];
        let had_trailing_nl = region.ends_with('\n');
        let mut new_region: String = region
            .lines()
            .map(|line| {
                let stripped = line.trim();
                if !enabled && stripped == "blur true" {
                    line.replacen("blur true", "blur false", 1)
                } else if enabled && stripped == "blur false" {
                    line.replacen("blur false", "blur true", 1)
                } else {
                    line.to_string()
                }
            })
            .collect::<Vec<_>>()
            .join("\n");
        if had_trailing_nl {
            new_region.push('\n');
        }
        Some(format!(
            "{}{}{}",
            &content[..start],
            new_region,
            &content[end..]
        ))
    }

    /// Modo rendimiento: desactiva blur (window rules de ChurrOS) + animaciones.
    pub fn get_performance_mode() -> bool {
        let content = read();
        let glass_off = match Self::get_glass_blur(&content) {
            Some(active) => !active,
            // Config sin marcadores: criterio antiguo (bloque blur ausente)
            None => !Self::get_blur_enabled(),
        };
        !Self::get_animations() && glass_off
    }

    pub fn set_performance_mode(on: bool) {
        // El blur real de las apps vive en las window rules (marcadas con
        // [CHURROS-GLASS-*]): quitarlo ahí es lo que lo desactiva de verdad.
        let content = read();
        if let Some(new_content) = Self::set_glass_blur(&content, !on) {
            write_atomic(&new_content);
        }
        // El bloque global `blur { ... }` solo es tuning; se conserva el
        // comportamiento anterior (borrar al activar, restaurar al quitar).
        Self::set_blur_enabled(!on);
        Self::set_animations(!on);
    }

    // ------------------------------------------------- Animation durations

    pub fn get_animation_duration(name: &str, default: i64) -> i64 {
        let content = read();
        match extract_value(&content, &["animations", name], "duration-ms") {
            Some(v) => v.parse().unwrap_or(default),
            None => default,
        }
    }

    pub fn set_animation_duration(name: &str, duration: i64) {
        let content = read();
        let result = match update_value_in_block(&content, &["animations", name], "duration-ms", &duration.to_string()) {
            Some(updated) => updated,
            None => create_block(&content, &["animations", name], &[&format!("duration-ms {}", duration)]),
        };
        write_atomic(&result);
    }
}

/// Primera cadena entre comillas de la línea (como re.search(r'"(.+?)"'))
fn first_quoted(line: &str) -> Option<String> {
    let start = line.find('"')? + 1;
    let rest = &line[start..];
    let end = rest.find('"')?;
    Some(rest[..end].to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// config.kdl real de la ISO (skel): debe tener los marcadores de glass.
    fn real_config() -> &'static str {
        const PATH: &str = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../archiso/airootfs/etc/skel/.config/niri/config.kdl"
        );
        let content = fs::read_to_string(PATH).expect("leer config.kdl del skel");
        Box::leak(content.into_boxed_str())
    }

    #[test]
    fn real_config_has_glass_markers() {
        let content = real_config();
        assert!(content.contains(NiriConfig::GLASS_START), "falta [CHURROS-GLASS-START]");
        assert!(content.contains(NiriConfig::GLASS_END), "falta [CHURROS-GLASS-END]");
        assert_eq!(NiriConfig::get_glass_blur(content), Some(true));
    }

    #[test]
    fn glass_blur_toggle_roundtrip() {
        let content = real_config();
        let off = NiriConfig::set_glass_blur(content, false).expect("toggle off");
        assert_eq!(NiriConfig::get_glass_blur(&off), Some(false));
        assert!(off.contains("blur false"));

        let on = NiriConfig::set_glass_blur(&off, true).expect("toggle on");
        assert_eq!(NiriConfig::get_glass_blur(&on), Some(true));
        assert!(on.contains("blur true"));

        // Idempotente
        assert_eq!(off, NiriConfig::set_glass_blur(&off, false).unwrap());
        // El resto del config no cambia
        assert_eq!(on.lines().count(), content.lines().count());
    }

    #[test]
    fn create_block_nested_preserves_parent_and_child() {
        let content = "layout {\n    gaps 8\n}\n";
        // El padre "layout" existe; se debe anidar "border" dentro con su cuerpo.
        let out = create_block(content, &["layout", "border"], &["on"]);
        assert!(out.contains("layout {"), "falta layout: {out}");
        assert!(out.contains("    border {"), "border no anidado: {out}");
        assert!(out.contains("        on"), "falta cuerpo on: {out}");
        assert!(out.contains("gaps 8"), "se perdio gaps: {out}");
    }

    #[test]
    fn create_block_creates_full_path_when_missing() {
        let content = "";
        let out = create_block(content, &["input", "keyboard", "xkb"], &["layout \"us\""]);
        assert!(out.contains("input {"));
        assert!(out.contains("    keyboard {"));
        assert!(out.contains("        xkb {"));
        assert!(out.contains("            layout \"us\""));
    }

    #[test]
    fn update_value_in_block_updates_nested_xkb() {
        let content =
            "input {\n    keyboard {\n        xkb {\n            layout \"us\"\n        }\n    }\n}\n";
        let updated = update_value_in_block(content, &["input", "keyboard", "xkb"], "layout", "\"es\"")
            .expect("actualizar layout");
        assert!(updated.contains("layout \"es\""), "no actualizo layout: {updated}");
        assert!(!updated.contains("layout \"us\""), "no quito el layout viejo: {updated}");
    }
}

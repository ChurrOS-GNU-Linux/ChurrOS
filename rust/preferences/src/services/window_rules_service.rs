// ==========================================
// WindowRulesService — window-rule de ~/.config/niri/config.kdl
// (equivalente a services/window_rules_service.py)
// ==========================================

use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;

use super::niri_config::py_float_str;

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

/// Cadena KDL con `value` dentro. app-id y title son regex: una como
/// `^org\.churros\.popup` entre comillas normales tiene un escape inválido
/// (`\.`) y niri rechaza el config entero. Si el valor lleva `\` o `"` se
/// escribe raw (`r#"…"#`, como en el skel) con los `#` que hagan falta.
fn kdl_string(value: &str) -> String {
    if !value.contains(['\\', '"']) {
        return format!("\"{value}\"");
    }
    let mut hashes = "#".to_string();
    while value.contains(&format!("\"{hashes}")) {
        hashes.push('#');
    }
    format!("r{hashes}\"{value}\"{hashes}")
}

/// Lee la cadena KDL (normal con escapes, o raw `r#"…"#`) al principio de
/// `s`. Devuelve el valor y los bytes que ocupa en `s`.
fn parse_kdl_string(s: &str) -> Option<(String, usize)> {
    if let Some(rest) = s.strip_prefix('r') {
        let hashes = rest.len() - rest.trim_start_matches('#').len();
        let body = rest[hashes..].strip_prefix('"')?;
        let close = format!("\"{}", &rest[..hashes]);
        let end = body.find(&close)?;
        return Some((body[..end].to_string(), 1 + hashes + 1 + end + close.len()));
    }
    let body = s.strip_prefix('"')?;
    let mut value = String::new();
    let mut chars = body.char_indices();
    while let Some((i, c)) = chars.next() {
        match c {
            '"' => return Some((value, 1 + i + 1)),
            '\\' => match chars.next()?.1 {
                'n' => value.push('\n'),
                'r' => value.push('\r'),
                't' => value.push('\t'),
                'b' => value.push('\u{8}'),
                'f' => value.push('\u{c}'),
                'u' => {
                    if chars.next()?.1 != '{' {
                        return None;
                    }
                    let mut hex = String::new();
                    loop {
                        match chars.next()?.1 {
                            '}' => break,
                            h => hex.push(h),
                        }
                    }
                    value.push(char::from_u32(u32::from_str_radix(&hex, 16).ok()?)?);
                }
                other => value.push(other), // \\ \" \/
            },
            _ => value.push(c),
        }
    }
    None
}

/// Propiedad `key=<cadena>` de la línea: (inicio, fin) en bytes y su valor.
fn string_prop(line: &str, key: &str) -> Option<(usize, usize, String)> {
    let marker = format!("{key}=");
    let mut from = 0;
    while let Some(pos) = line[from..].find(&marker) {
        let at = from + pos;
        if line[..at].ends_with(char::is_whitespace) {
            let value_start = at + marker.len();
            let (value, len) = parse_kdl_string(&line[value_start..])?;
            return Some((at, value_start + len, value));
        }
        from = at + marker.len();
    }
    None
}

/// La línea `match …` con `key` cambiado a `value`; None si queda vacía
/// (`value` vacío y `key` era lo único que comprobaba).
fn set_string_prop(line: &str, key: &str, value: &str) -> Option<String> {
    let (start, end, _) = string_prop(line, key)?;
    if !value.is_empty() {
        return Some(format!("{}{key}={}{}", &line[..start], kdl_string(value), &line[end..]));
    }
    let rest = format!("{}{}", line[..start].trim_end(), &line[end..]);
    (rest.trim() != "match").then_some(rest)
}

/// Serializa una regla a KDL (equivalente a _serialize_rule).
fn serialize_rule(rule: &Value) -> String {
    let mut lines = vec!["window-rule {".to_string()];
    lines.extend(match_lines(rule, INDENT));
    lines.extend(property_lines(rule, INDENT));
    lines.push("}".to_string());
    lines.join("\n") + "\n"
}

/// Líneas `match app-id=…` / `match title=…` de la regla.
fn match_lines(rule: &Value, indent: &str) -> Vec<String> {
    MATCHES
        .iter()
        .filter_map(|(key, field)| {
            let value = rule.get(*field)?.as_str()?;
            (!value.is_empty()).then(|| format!("{indent}match {key}={}", kdl_string(value)))
        })
        .collect()
}

/// Propiedades de la regla que escribe Ajustes, en el orden de siempre.
fn property_lines(rule: &Value, indent: &str) -> Vec<String> {
    let mut lines: Vec<String> = PROPERTIES
        .iter()
        .filter_map(|(key, field)| Some(format!("{indent}{key} {}", property_value(rule, field)?)))
        .collect();
    if let Some(blur) = property_value(rule, "blur") {
        lines.push(format!("{indent}background-effect {{"));
        lines.push(format!("{indent}{INDENT}blur {blur}"));
        lines.push(format!("{indent}}}"));
    }
    lines
}

/// (propiedad KDL, campo de la regla) de los `match` que modela Ajustes.
const MATCHES: [(&str, &str); 2] = [("app-id", "app_id"), ("title", "title")];

/// (nodo KDL, campo de la regla) de las propiedades que modela Ajustes,
/// salvo `blur`, que vive dentro de `background-effect { }`.
const PROPERTIES: [(&str, &str); 4] = [
    ("opacity", "opacity"),
    ("open-floating", "open_floating"),
    ("geometry-corner-radius", "corner_radius"),
    ("clip-to-geometry", "clip_to_geometry"),
];

/// Valor KDL del campo `field` de la regla (None: la propiedad no va).
/// niri lee opacity como decimal: `opacity 0` (entero) lo rechaza.
fn property_value(rule: &Value, field: &str) -> Option<String> {
    let value = rule.get(field)?;
    match field {
        "opacity" => value.as_f64().map(py_float_str),
        "corner_radius" => value.as_f64().map(|v| v.to_string()),
        _ => value.as_bool().map(|v| v.to_string()),
    }
}

/// Reescribe el bloque window-rule `block` (líneas de apertura a cierre,
/// ambas incluidas) con los valores de `rule`, en su sitio: solo cambian
/// las líneas de lo que modela Ajustes y cuyo valor cambia. Lo demás
/// (draw-border-with-background, exclude, comentarios, otros match) y el
/// orden se quedan como estaban.
///
/// Un campo a null no borra un valor que el formulario también manda como
/// null (`false`, opacidad 1, radio 0): no distingue "apagado" de "sin
/// definir", y Modo rendimiento necesita que los `blur false` de las
/// reglas de ChurrOS sigan ahí para volver a encenderlos.
fn update_block(block: &[String], rule: &Value) -> Vec<String> {
    let indent = format!("{}{INDENT}", leading_space(&block[0]));
    let last = block.len() - 1;
    let mut out = vec![block[0].clone()];
    // Nodos ya tratados: solo se edita la primera aparición, como lee list_rules.
    let mut seen: Vec<&str> = Vec::new();
    // Los match que falten van tras el último que haya.
    let mut match_end = 1;
    let mut depth = 0usize;
    let mut i = 1;

    while i < last {
        let line = &block[i];
        let stripped = line.trim();
        let name = stripped.split_whitespace().next().unwrap_or("");
        i += 1;

        if depth == 0 {
            let matched = MATCHES
                .into_iter()
                .find(|(key, _)| stripped.starts_with(&format!("match {key}=")) && !seen.contains(key));
            if let Some((key, field)) = matched {
                seen.push(key);
                let new = rule.get(field).and_then(|v| v.as_str()).unwrap_or("");
                match string_prop(line, key) {
                    Some((_, _, old)) if old != new => out.extend(set_string_prop(line, key, new)),
                    _ => out.push(line.clone()),
                }
                match_end = out.len();
                continue;
            }

            if let Some((key, field)) = PROPERTIES.into_iter().find(|(key, _)| *key == name && !seen.contains(key)) {
                seen.push(key);
                out.extend(updated_property(line, key, property_value(rule, field)));
                continue;
            }

            if name == "background-effect"
                && stripped.ends_with('{')
                && !seen.contains(&"blur")
                && let Some(close) = closing_line(block, i - 1).filter(|close| *close < last)
            {
                seen.push("blur");
                // Del sub-bloque solo se toca su `blur`.
                let mut inner: Vec<String> = Vec::new();
                let mut found = false;
                for l in &block[i..close] {
                    if !found && l.split_whitespace().next() == Some("blur") {
                        found = true;
                        inner.extend(updated_property(l, "blur", property_value(rule, "blur")));
                    } else {
                        inner.push(l.clone());
                    }
                }
                if let (false, Some(new)) = (found, property_value(rule, "blur")) {
                    inner.push(format!("{indent}{INDENT}blur {new}"));
                }
                // Sin nada dentro, el bloque sobra.
                if inner.iter().any(|l| !l.trim().is_empty() && !l.trim().starts_with("//")) {
                    out.push(line.clone());
                    out.extend(inner);
                    out.push(block[close].clone());
                }
                i = close + 1;
                continue;
            }
        }

        let top_level_match = depth == 0 && name == "match";
        if stripped.ends_with('{') {
            depth += 1;
        } else if stripped.starts_with('}') {
            depth = depth.saturating_sub(1);
        }
        out.push(line.clone());
        if top_level_match {
            match_end = out.len();
        }
    }

    // Lo que la regla no tenía: los match con los demás, el resto al final.
    let mut missing = rule.clone();
    for (key, field) in MATCHES {
        if seen.contains(&key) {
            missing[field] = json!("");
        }
    }
    for (key, field) in PROPERTIES.into_iter().chain([("blur", "blur")]) {
        if seen.contains(&key) {
            missing[field] = Value::Null;
        }
    }
    out.splice(match_end..match_end, match_lines(&missing, &indent));
    out.extend(property_lines(&missing, &indent));
    out.push(block[last].clone());
    out
}

/// La línea `key valor` con el valor nuevo: igual si no cambia, ninguna si
/// `new` es None (salvo lo que el formulario ya manda como None).
fn updated_property(line: &str, key: &str, new: Option<String>) -> Option<String> {
    let old = line.split_whitespace().nth(1).unwrap_or("");
    match new {
        Some(new) if same_value(old, &new) => Some(line.to_string()),
        Some(new) => Some(format!("{}{key} {new}", leading_space(line))),
        None if form_sends_null(key, old) => Some(line.to_string()),
        None => None,
    }
}

/// ¿El formulario de pages/window_rules.rs manda null para `key old`?
/// (opacidad 1 o más, radio 0, interruptor apagado.)
fn form_sends_null(key: &str, old: &str) -> bool {
    match key {
        "opacity" => old.parse::<f64>().is_ok_and(|v| v >= 1.0),
        "geometry-corner-radius" => old.parse::<f64>().is_ok_and(|v| v == 0.0),
        _ => old == "false",
    }
}

/// ¿El valor escrito `old` es el mismo que `new` (20 == 20.0)?
fn same_value(old: &str, new: &str) -> bool {
    old == new || matches!((old.parse::<f64>(), new.parse::<f64>()), (Ok(a), Ok(b)) if a == b)
}

fn leading_space(line: &str) -> &str {
    &line[..line.len() - line.trim_start().len()]
}

/// Índice de la línea que cierra el bloque que abre `lines[open]`.
fn closing_line(lines: &[String], open: usize) -> Option<usize> {
    let mut depth = 0usize;
    for (k, l) in lines.iter().enumerate().skip(open + 1) {
        let l = l.trim();
        if l.starts_with('}') {
            if depth == 0 {
                return Some(k);
            }
            depth -= 1;
        } else if l.ends_with('{') {
            depth += 1;
        }
    }
    None
}

/// Reescribe solo la regla `index`: `Some` la actualiza en su sitio
/// (update_block), `None` la borra (con el comentario que pone add_rule).
/// El resto del fichero queda byte a byte igual. (La versión anterior
/// reserializaba todas las reglas: perdía lo que no modela, como
/// draw-border-with-background, y escribía las regex del skel con un
/// escape inválido que niri rechazaba.)
fn rewrite_rule(index: usize, rule: Option<&Value>) {
    let content = read();
    let (blocks, lines) = find_all_blocks(&content, "window-rule");
    let Some(&(start, end)) = blocks.get(index) else {
        return;
    };

    let replacement = match rule {
        Some(rule) => update_block(&lines[start..=end], rule),
        None => Vec::new(),
    };
    let mut start = start;
    if rule.is_none() && start > 0 && lines[start - 1].trim() == CUSTOM_RULE_COMMENT {
        start -= 1;
        if start > 0 && lines[start - 1].trim().is_empty() {
            start -= 1;
        }
    }

    let mut out: Vec<String> = lines[..start].to_vec();
    out.extend(replacement);
    out.extend_from_slice(&lines[end + 1..]);
    let mut text = out.join("\n");
    if content.ends_with('\n') {
        text.push('\n');
    }
    write_atomic(&text);
}

/// Comentario que add_rule pone encima de cada regla nueva.
const CUSTOM_RULE_COMMENT: &str = "// Window rule (custom)";

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
                    if let Some((_, _, m)) = string_prop(&stripped, "app-id") {
                        rule["app_id"] = json!(m);
                        continue;
                    }
                }
                if stripped.starts_with("match title") {
                    if let Some((_, _, m)) = string_prop(&stripped, "title") {
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
        content += &format!("\n{CUSTOM_RULE_COMMENT}\n{rule_str}");

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
        rewrite_rule(index, Some(&rules[index]));
        Ok(())
    }

    /// Borra la regla `index` (equivalente a delete_rule).
    pub fn delete_rule(index: usize) -> Result<(), String> {
        let rules = Self::list_rules();
        if index >= rules.len() {
            return Err(format!("window-rule index out of range: {index}"));
        }
        rewrite_rule(index, None);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::services::test_support::{rule_form, skel_niri_config, TempHome};

    /// La regla de los popups del skel: su app-id es una regex en cadena raw.
    const POPUP: &str = r"^org\.churros\.popup";
    const POPUP_LINE: &str = r##"    match app-id=r#"^org\.churros\.popup"#"##;

    fn app_ids() -> Vec<String> {
        WindowRulesService::list_rules()
            .iter()
            .map(|rule| rule["app_id"].as_str().unwrap_or("").to_string())
            .collect()
    }

    #[test]
    fn kdl_string_roundtrip() {
        for value in ["foot", POPUP, r#"di "hola""#, r##"a"#b"##, r"C:\ruta\", ""] {
            let written = kdl_string(value);
            assert_eq!(
                parse_kdl_string(&written),
                Some((value.to_string(), written.len())),
                "la regex del app-id no vuelve igual: {value:?} se escribe {written}"
            );
        }
        assert_eq!(kdl_string(POPUP), r##"r#"^org\.churros\.popup"#"##);
        assert_eq!(kdl_string("foot"), "\"foot\"");
        // Cadena normal con escapes, seguida de otra propiedad.
        assert_eq!(
            parse_kdl_string(r#""a\\.b\"c\u{e9}" title="x""#),
            Some(("a\\.b\"c\u{e9}".to_string(), 16))
        );
    }

    #[test]
    fn list_rules_reads_the_skel_regex() {
        let _home = TempHome::new("rules-list", &skel_niri_config());
        assert!(app_ids().contains(&POPUP.to_string()), "list_rules no lee la regex raw del skel: {:?}", app_ids());
    }

    #[test]
    fn saving_a_rule_unchanged_keeps_the_skel_byte_for_byte() {
        let skel = skel_niri_config();
        let home = TempHome::new("rules-noop", &skel);
        let rules = WindowRulesService::list_rules();
        assert!(rules.len() > 5, "el skel debería tener varias window-rule: {rules:?}");
        for (index, rule) in rules.iter().enumerate() {
            WindowRulesService::update_rule(index, &rule_form(rule)).unwrap();
            let after = home.read();
            assert_eq!(after, skel, "guardar sin cambios la regla {index} ({}) cambia config.kdl", rule["app_id"]);
        }
    }

    #[test]
    fn update_and_delete_rule_0_keep_the_other_rules() {
        // El fallo que encontró una revisión: update_rule(0) y delete_rule(0)
        // reescribían todas las reglas, y la del popup salía como
        // `match app-id="^org\.churros\.popup"` (escape inválido: niri
        // rechaza el config) y sin draw-border-with-background.
        let skel = skel_niri_config();
        let home = TempHome::new("rules-first", &skel);
        let first = WindowRulesService::list_rules()[0].clone();
        assert_eq!(first["app_id"], "pavucontrol");

        let mut form = rule_form(&first);
        form["opacity"] = json!(0.8);
        WindowRulesService::update_rule(0, &form).unwrap();
        let expected = skel.replacen(
            "    match app-id=\"pavucontrol\"\n    open-floating true\n}",
            "    match app-id=\"pavucontrol\"\n    open-floating true\n    opacity 0.8\n}",
            1,
        );
        assert_eq!(home.read(), expected, "update_rule(0) tocó algo más que la opacidad de la regla 0");
        assert!(home.read().contains(POPUP_LINE));

        home.write(&skel);
        let before = app_ids();
        WindowRulesService::delete_rule(0).unwrap();
        let expected = skel.replacen("window-rule {\n    match app-id=\"pavucontrol\"\n    open-floating true\n}\n", "", 1);
        assert_eq!(home.read(), expected, "delete_rule(0) tocó algo más que la regla 0");
        assert_eq!(app_ids(), before[1..].to_vec());
    }

    #[test]
    fn delete_rule_removes_only_that_block() {
        let skel = skel_niri_config();
        let home = TempHome::new("rules-delete", &skel);
        let (blocks, lines) = find_all_blocks(&skel, "window-rule");
        for (index, (start, end)) in blocks.iter().enumerate() {
            home.write(&skel);
            WindowRulesService::delete_rule(index).unwrap();
            let expected: Vec<&str> =
                lines.iter().enumerate().filter(|(i, _)| i < start || i > end).map(|(_, l)| l.as_str()).collect();
            assert_eq!(home.read(), expected.join("\n"), "delete_rule({index}) tocó otras líneas");
        }
    }

    #[test]
    fn editing_the_popup_rule_keeps_what_settings_does_not_model() {
        let skel = skel_niri_config();
        let home = TempHome::new("rules-popup", &skel);
        let index = app_ids().iter().position(|id| id == POPUP).unwrap();
        let rule = WindowRulesService::list_rules()[index].clone();

        // Modo rendimiento puesto: blur false. El formulario lo manda como null.
        home.write(&skel.replace("        blur true", "        blur false"));
        let mut form = rule_form(&rule);
        form["blur"] = Value::Null;
        form["corner_radius"] = json!(12.0);
        WindowRulesService::update_rule(index, &form).unwrap();
        let after = home.read();
        let (blocks, lines) = find_all_blocks(&after, "window-rule");
        let (start, end) = blocks[index];
        assert_eq!(
            lines[start..=end].join("\n"),
            [
                "window-rule {",
                POPUP_LINE,
                "    open-floating true",
                "    opacity 0.9",
                "    draw-border-with-background false",
                "    background-effect {",
                "        blur false",
                "    }",
                "    geometry-corner-radius 12",
                "    clip-to-geometry true",
                "}",
            ]
            .join("\n")
        );
    }

    #[test]
    fn regex_app_id_written_by_settings_reads_back() {
        let skel = skel_niri_config();
        let home = TempHome::new("rules-regex", &skel);
        let app_id = r#"^org\.gnome\."Calc"#;
        let index = WindowRulesService::add_rule(app_id, "", Some(0.0), Some(true), None, None, Some(true));
        let rules = WindowRulesService::list_rules();
        assert_eq!(rules[index]["app_id"], app_id, "la regex del app-id no vuelve igual tras add_rule");
        assert_eq!(rules[index]["opacity"], 0.0);
        let text = home.read();
        assert!(text.contains(r##"    match app-id=r#"^org\.gnome\."Calc"#"##), "{text}");
        assert!(text.contains("    opacity 0.0\n"), "niri rechaza una opacidad entera (`opacity 0`):\n{text}");
        assert!(text.contains(POPUP_LINE));

        WindowRulesService::update_rule(index, &json!({"app_id": r"^a\.b$", "title": r#"x "y""#})).unwrap();
        let rule = &WindowRulesService::list_rules()[index];
        assert_eq!(rule["app_id"], r"^a\.b$", "la regex del app-id no vuelve igual tras update_rule");
        assert_eq!(rule["title"], r#"x "y""#);

        // Borrar la regla añadida deja el config como estaba (más el salto
        // de línea final que añade add_rule).
        WindowRulesService::delete_rule(index).unwrap();
        assert_eq!(home.read(), format!("{skel}\n"));
    }
}

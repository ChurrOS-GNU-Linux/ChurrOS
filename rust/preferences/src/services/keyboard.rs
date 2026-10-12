// ==========================================
// KeyboardService (equivalente a services/keyboard.py)
// Porta el parseo de config.kdl SIN regex (el workspace no tiene crate regex).
// ==========================================

use std::fs;
use std::path::PathBuf;

fn config_path() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home).join(".config").join("niri").join("config.kdl")
}

fn backup_path() -> PathBuf {
    let home = churros_services::home_dir();
    PathBuf::from(home)
        .join(".config")
        .join("niri")
        .join("config.kdl.bak")
}

/// Un atajo de teclado parseado de config.kdl
#[derive(Clone)]
pub struct Bind {
    pub key: String,
    pub allow_when_locked: bool,
    /// "spawn" | "spawn-sh" | "builtin"
    pub kind: String,
    pub command: String,
    pub args: String,
}

/// ¿La clave coincide con el patrón del regex Python
/// `(Mod\S*|Print|Ctrl\+Print|Alt\+Print|XF86\S*)`?
pub fn is_valid_key(key: &str) -> bool {
    key.starts_with("Mod") || key == "Print" || key == "Ctrl+Print" || key == "Alt+Print" || key.starts_with("XF86")
}

/// Extrae el contenido desde el inicio de `s` hasta el siguiente '"'
/// (s NO incluye la comilla de apertura: los callers hacen strip_prefix('"')).
/// Devuelve (contenido, resto tras la comilla de cierre).
fn split_quote(s: &str) -> (String, String) {
    let bytes = s.as_bytes();
    let mut end = 0usize;
    let mut escaped = false;
    for (i, &b) in bytes.iter().enumerate() {
        if escaped {
            escaped = false;
            continue;
        }
        if b == b'\\' {
            escaped = true;
            continue;
        }
        if b == b'"' {
            end = i;
            break;
        }
    }
    if end == 0 {
        return (String::new(), String::new());
    }
    (s[..end].to_string(), s[end + 1..].to_string())
}

/// Equivalente a _parse_action: "spawn \"cmd\" \"args\"" | "spawn-sh \"cmd\"" | builtin.
fn parse_action(raw: &str) -> (String, String, String) {
    let action = raw.trim().trim_end_matches(';');

    // spawn-sh "cmd"
    if let Some(rest) = action.strip_prefix("spawn-sh") {
        if let Some(q) = rest.trim_start().strip_prefix('"') {
            let (cmd, _) = split_quote(q);
            return ("spawn-sh".to_string(), cmd, String::new());
        }
    }

    // spawn "cmd" ["args"]
    if let Some(rest) = action.strip_prefix("spawn") {
        if rest.starts_with(|c: char| c.is_whitespace()) {
            if let Some(q) = rest.trim_start().strip_prefix('"') {
                let (cmd, tail) = split_quote(q);
                if !cmd.is_empty() {
                    if let Some(q2) = tail.trim_start().strip_prefix('"') {
                        let (args, _) = split_quote(q2);
                        return ("spawn".to_string(), cmd, args);
                    }
                    return ("spawn".to_string(), cmd, String::new());
                }
            }
        }
    }

    // builtin: primer token + resto
    let mut parts = action.split_whitespace();
    let func = parts.next().unwrap_or("").to_string();
    let args = parts.collect::<Vec<_>>().join(" ");
    ("builtin".to_string(), func, args)
}

/// Escapa un string para meterlo entre comillas en KDL.
fn kdl_escape(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"")
}

/// Equivalente a _make_action_line.
fn make_action_line(bind_type: &str, command: &str, args: &str) -> String {
    match bind_type {
        "spawn" => {
            let cmd = kdl_escape(command);
            if !args.is_empty() {
                format!("spawn \"{cmd}\" \"{}\"", kdl_escape(args))
            } else {
                format!("spawn \"{cmd}\"")
            }
        }
        "spawn-sh" => format!("spawn-sh \"{}\"", kdl_escape(command)),
        _ => {
            if !args.is_empty() {
                format!("{command} {args}")
            } else {
                command.to_string()
            }
        }
    }
}

/// ¿La línea (ya trimmeada) empieza por `key` seguido de espacio/fin/{/(?
/// (equivalente al regex de set_keybind: ^\s*KEY(\s|$|\s*{|\s*\()
fn line_matches_key(stripped: &str, key: &str) -> bool {
    if let Some(rest) = stripped.strip_prefix(key) {
        rest.is_empty()
            || rest.starts_with(|c: char| c.is_whitespace())
            || rest.starts_with('{')
            || rest.starts_with('(')
    } else {
        false
    }
}

/// Conserva `hotkey-overlay-title="…"` o `=null` al reescribir un atajo
/// desde Ajustes. Sin esto, el overlay de Niri perdería el título.
fn hotkey_overlay_property(head: &str) -> Option<String> {
    let marker = "hotkey-overlay-title=";
    let start = head.find(marker)?;
    let rest = &head[start + marker.len()..];
    if let Some(quoted) = rest.strip_prefix('"') {
        let end = quoted.find('"')?;
        return Some(format!("hotkey-overlay-title=\"{}\"", &quoted[..end]));
    }
    if rest.starts_with("null") {
        return Some("hotkey-overlay-title=null".to_string());
    }
    None
}

/// Parsea una línea de bind "    Mod+X { spawn \"foot\"; }".
fn parse_bind_line(line: &str) -> Option<Bind> {
    let stripped = line.trim();
    let open = stripped.find('{')?;
    let close = stripped.rfind('}')?;
    if close < open {
        return None;
    }

    let head = stripped[..open].trim();
    let action = stripped[open + 1..close].trim();

    let mut tokens = head.split_whitespace();
    let key = tokens.next()?;
    if !is_valid_key(key) {
        return None;
    }
    let allow_when_locked = tokens.any(|t| t.starts_with("allow-when-locked"));

    let (kind, command, args) = parse_action(action);
    Some(Bind {
        key: key.to_string(),
        allow_when_locked,
        kind,
        command,
        args,
    })
}

pub struct KeyboardService;

impl KeyboardService {
    /// Lee todos los atajos del bloque `binds` de config.kdl.
    pub fn get_keybinds() -> Vec<Bind> {
        let path = config_path();
        if !path.exists() {
            return Vec::new();
        }
        let content = match fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => return Vec::new(),
        };

        let mut binds = Vec::new();
        let mut in_binds = false;
        for line in content.lines() {
            let stripped = line.trim();
            if stripped.starts_with("binds") {
                in_binds = true;
                continue;
            }
            if in_binds && stripped == "}" {
                break;
            }
            if !in_binds {
                continue;
            }
            if let Some(bind) = parse_bind_line(stripped) {
                binds.push(bind);
            }
        }
        binds
    }

    /// Sustituye la acción del atajo `key` (la tecla no cambia).
    /// FIX vs Python: el Python escribía "indent + new_action" perdiendo la tecla
    /// (config.kdl inválido); aquí se escribe la línea completa "key { action; }",
    /// que es lo que el propio Python construye en `new_line` (y usa add_keybind).
    pub fn set_keybind(key: &str, action_type: &str, command: &str, args: &str) -> bool {
        let path = config_path();
        if !path.exists() {
            return false;
        }
        // copia de seguridad previa (shutil.copyfile)
        let _ = fs::copy(&path, backup_path());

        let content = match fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => return false,
        };

        let new_action = make_action_line(action_type, command, args);
        // Sin indent aquí: se conserva el indent original de la línea
        // reemplazada (el Python duplicaba la indentación).
        let new_line = format!("{key} {{ {new_action}; }}");

        let mut out = String::new();
        let mut in_binds = false;
        let mut replaced = false;

        for line in content.lines() {
            let stripped = line.trim();
            if stripped.starts_with("binds") {
                in_binds = true;
                out.push_str(line);
                out.push('\n');
                continue;
            }
            if in_binds && stripped == "}" {
                out.push_str(line);
                out.push('\n');
                in_binds = false;
                continue;
            }
            if in_binds && !replaced && line_matches_key(stripped, key) {
                let indent: String = line.chars().take_while(|c| c.is_whitespace()).collect();
                let titled = match hotkey_overlay_property(stripped) {
                    Some(prop) => format!("{key} {prop} {{ {new_action}; }}"),
                    None => new_line.clone(),
                };
                out.push_str(&indent);
                out.push_str(&titled);
                out.push('\n');
                replaced = true;
                continue;
            }
            out.push_str(line);
            out.push('\n');
        }

        if !replaced {
            return false;
        }
        fs::write(&path, out).is_ok()
    }

    /// Inserta un atajo nuevo justo antes del cierre del bloque `binds`.
    pub fn add_keybind(key: &str, action_type: &str, command: &str, args: &str) -> bool {
        let path = config_path();
        if !path.exists() {
            return false;
        }
        let _ = fs::copy(&path, backup_path());

        let content = match fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => return false,
        };

        let new_line = format!(
            "{key} {{ {}; }}",
            make_action_line(action_type, command, args)
        );

        let mut out_lines: Vec<String> = Vec::new();
        let mut in_binds = false;
        let mut insert_pos: Option<usize> = None;

        for line in content.lines() {
            out_lines.push(line.to_string());
            let stripped = line.trim();
            if stripped.starts_with("binds") {
                in_binds = true;
                continue;
            }
            if in_binds && stripped == "}" {
                insert_pos = Some(out_lines.len() - 1);
                break;
            }
        }

        if let Some(pos) = insert_pos {
            out_lines.insert(pos, format!("    {new_line}"));
        } else {
            // Sin bloque binds: crear uno al final (el Python insertaba
            // la línea suelta fuera de cualquier bloque -> KDL inválido).
            out_lines.push(String::new());
            out_lines.push("binds {".to_string());
            out_lines.push(format!("    {new_line}"));
            out_lines.push("}".to_string());
        }

        let mut result = out_lines.join("\n");
        result.push('\n');
        fs::write(&path, result).is_ok()
    }

    /// Elimina el atajo `key` del bloque `binds` de config.kdl.
    pub fn remove_keybind(key: &str) -> bool {
        let path = config_path();
        if !path.exists() {
            return false;
        }
        let _ = fs::copy(&path, backup_path());

        let content = match fs::read_to_string(&path) {
            Ok(c) => c,
            Err(_) => return false,
        };

        let mut out = String::new();
        let mut in_binds = false;
        let mut removed = false;

        for line in content.lines() {
            let stripped = line.trim();
            if stripped.starts_with("binds") {
                in_binds = true;
                out.push_str(line);
                out.push('\n');
                continue;
            }
            if in_binds && stripped == "}" {
                out.push_str(line);
                out.push('\n');
                in_binds = false;
                continue;
            }
            if in_binds && !removed && line_matches_key(stripped, key) {
                removed = true;
                continue;
            }
            out.push_str(line);
            out.push('\n');
        }

        if removed {
            fs::write(&path, out).is_ok()
        } else {
            false
        }
    }

    /// Restaura config.kdl desde la copia de seguridad (config.kdl.bak).
    #[allow(dead_code)] // presente por paridad con services/keyboard.py (restore_backup)
    pub fn restore_backup() -> bool {
        let bak = backup_path();
        if bak.exists() {
            fs::copy(&bak, config_path()).is_ok()
        } else {
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn split_quote_keeps_first_char() {
        // Los callers ya quitan la comilla de apertura antes de llamar.
        let (content, rest) = split_quote("churros-welcome\"");
        assert_eq!(content, "churros-welcome");
        assert!(rest.is_empty());

        let (content, rest) = split_quote("foot\" \"--flag\"");
        assert_eq!(content, "foot");
        assert_eq!(rest, " \"--flag\"");
    }

    #[test]
    fn parse_spawn_bind_keeps_command() {
        let bind = parse_bind_line("    Mod+W { spawn \"churros-welcome\"; }").unwrap();
        assert_eq!(bind.key, "Mod+W");
        assert_eq!(bind.kind, "spawn");
        assert_eq!(bind.command, "churros-welcome");
        assert_eq!(bind.args, "");

        let bind = parse_bind_line("    Mod+Shift+N { spawn \"churros-popup\" \"network\"; }").unwrap();
        assert_eq!(bind.command, "churros-popup");
        assert_eq!(bind.args, "network");

        let bind = parse_bind_line(
            "    Mod+Space hotkey-overlay-title=\"Abrir el lanzador\" { spawn-sh \"noctalia msg panel-toggle launcher\"; }",
        )
        .unwrap();
        assert_eq!(bind.key, "Mod+Space");
        assert_eq!(bind.kind, "spawn-sh");
        assert_eq!(bind.command, "noctalia msg panel-toggle launcher");
    }

    #[test]
    fn overlay_title_roundtrip() {
        assert_eq!(
            hotkey_overlay_property(
                "Mod+Space hotkey-overlay-title=\"Abrir el lanzador\" { spawn-sh \"noctalia msg panel-toggle launcher\"; }"
            )
            .as_deref(),
            Some("hotkey-overlay-title=\"Abrir el lanzador\"")
        );
        assert_eq!(
            hotkey_overlay_property("Mod+Q hotkey-overlay-title=null { close-window; }").as_deref(),
            Some("hotkey-overlay-title=null")
        );
    }

    #[test]
    fn parse_spawn_sh_keeps_command() {
        let bind = parse_bind_line("    Mod+T { spawn-sh \"foot\"; }").unwrap();
        assert_eq!(bind.kind, "spawn-sh");
        assert_eq!(bind.command, "foot");
    }

    #[test]
    fn make_action_line_escapes_quotes() {
        assert_eq!(make_action_line("spawn", "foot", ""), "spawn \"foot\"");
        assert_eq!(make_action_line("spawn", "cmd", "a b"), "spawn \"cmd\" \"a b\"");
        assert_eq!(
            make_action_line("spawn", "say", "\"hi\""),
            "spawn \"say\" \"\\\"hi\\\"\""
        );
        assert_eq!(make_action_line("builtin", "close-window", ""), "close-window");
    }

    #[test]
    fn write_path_roundtrip() {
        // HOME temporal para no tocar la config real del usuario.
        let tmp = std::env::temp_dir().join(format!("churros-kbd-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&tmp);
        let niri_dir = tmp.join(".config").join("niri");
        fs::create_dir_all(&niri_dir).unwrap();
        let config = niri_dir.join("config.kdl");
        fs::write(
            &config,
            "layout {\n    gaps 8\n}\n\nbinds {\n    Mod+Return { spawn \"foot\"; }\n}\n",
        )
        .unwrap();
        // Solo este test toca HOME (los demás no leen config_path), así que
        // no hace falta serializar.
        unsafe { std::env::set_var("HOME", &tmp) };

        // add: debe insertarse dentro de binds con indent correcto
        assert!(KeyboardService::add_keybind("Mod+W", "spawn", "churros-welcome", ""));
        let content = fs::read_to_string(&config).unwrap();
        assert!(content.contains("    Mod+W { spawn \"churros-welcome\"; }"), "add: {content}");

        // set: reemplaza la acción conservando el indent (sin doble indent)
        assert!(KeyboardService::set_keybind("Mod+W", "spawn", "churros-settings", ""));
        let content = fs::read_to_string(&config).unwrap();
        assert!(content.contains("    Mod+W { spawn \"churros-settings\"; }"), "set: {content}");
        assert!(!content.contains("        Mod+W"), "set: indent duplicado: {content}");

        // remove: desaparece la línea
        assert!(KeyboardService::remove_keybind("Mod+W"));
        let content = fs::read_to_string(&config).unwrap();
        assert!(!content.contains("Mod+W"), "remove: {content}");
        assert!(content.contains("Mod+Return"), "remove: borró otro bind: {content}");

        // sin bloque binds: add crea el bloque en vez de escribir KDL inválido
        let config2 = niri_dir.join("config.kdl");
        fs::write(&config2, "layout {\n    gaps 8\n}\n").unwrap();
        assert!(KeyboardService::add_keybind("Mod+T", "builtin", "close-window", ""));
        let content = fs::read_to_string(&config2).unwrap();
        assert!(
            content.contains("binds {") && content.contains("    Mod+T { close-window; }"),
            "sin binds: {content}"
        );

        fs::write(
            &config,
            "binds {\n    Mod+Space hotkey-overlay-title=\"Abrir el lanzador\" { spawn-sh \"noctalia msg panel-toggle launcher\"; }\n}\n",
        )
        .unwrap();
        assert!(KeyboardService::set_keybind(
            "Mod+Space",
            "spawn-sh",
            "noctalia msg panel-toggle launcher",
            ""
        ));
        let content = fs::read_to_string(&config).unwrap();
        assert!(
            content.contains(
                "Mod+Space hotkey-overlay-title=\"Abrir el lanzador\" { spawn-sh \"noctalia msg panel-toggle launcher\"; }"
            ),
            "set conserva el título del overlay: {content}"
        );

        let _ = fs::remove_dir_all(&tmp);
    }
}

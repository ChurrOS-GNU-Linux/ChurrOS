// Sesión Noctalia: qué componentes opcionales (Waybar, Mako) siguen en uso,
// y qué wallpaper tiene puesto el shell. Sin GTK, para poder testearlo.

use std::path::PathBuf;

/// Programas que Noctalia sustituye en la sesión Niri.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OptionalShell {
    Waybar,
    Mako,
}

/// Procesos vistos en `/proc`. Los tests lo construyen a mano.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct RunningShells {
    pub waybar: bool,
    pub mako: bool,
    pub noctalia: bool,
}

/// `true` si `config.kdl` arranca `binary` con `spawn-at-startup` o
/// `spawn-sh-at-startup`. Las líneas `//` no cuentan.
pub fn niri_autostart_has(config: &str, binary: &str) -> bool {
    for line in config.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with("//") {
            continue;
        }
        let code = strip_kdl_comment(trimmed);
        let args = quoted_strings(code);
        if code.starts_with("spawn-at-startup") && args.iter().any(|arg| command_is(arg, binary)) {
            return true;
        }
        if code.starts_with("spawn-sh-at-startup")
            && args.iter().any(|arg| shell_invokes(arg, binary))
        {
            return true;
        }
    }
    false
}

/// Noctalia es el shell si ya corre o si el autostart de Niri lo va a lanzar.
pub fn noctalia_is_shell(running: RunningShells, niri_config: &str) -> bool {
    running.noctalia || niri_autostart_has(niri_config, "noctalia")
}

/// La página de Ajustes de Waybar o Mako solo tiene sentido si esa sesión
/// los usa de verdad. Con Noctalia en marcha (y el otro programa apagado)
/// se ocultan: aplicar Waybar lanzaría una segunda barra.
pub fn session_uses(which: OptionalShell, running: RunningShells, niri_config: &str) -> bool {
    let (is_running, binary) = match which {
        OptionalShell::Waybar => (running.waybar, "waybar"),
        OptionalShell::Mako => (running.mako, "mako"),
    };
    if is_running {
        return true;
    }
    if running.noctalia {
        return false;
    }
    niri_autostart_has(niri_config, binary) && !niri_autostart_has(niri_config, "noctalia")
}

/// Lee `/proc` y el `config.kdl` del usuario. En la ISO de Niri, Noctalia
/// está en el autostart y Waybar/Mako no, así que las páginas quedan ocultas
/// aunque Ajustes se abra antes de que el proceso arranque.
pub fn uses_waybar() -> bool {
    session_uses(OptionalShell::Waybar, running_shells(), &read_user_niri())
}

pub fn uses_mako() -> bool {
    session_uses(OptionalShell::Mako, running_shells(), &read_user_niri())
}

pub fn running_shells() -> RunningShells {
    RunningShells {
        waybar: comm_running("waybar"),
        mako: comm_running("mako"),
        noctalia: comm_running("noctalia"),
    }
}

/// Noctalia es el shell de esta sesión (proceso en marcha o autostart de Niri).
pub fn shell_active() -> bool {
    noctalia_is_shell(running_shells(), &read_user_niri())
}

/// `mode` de la tabla `[theme]` (no de `[theme.templates]` ni otras).
pub fn theme_mode_in_toml(text: &str) -> Option<String> {
    let mut in_theme = false;
    for raw in text.lines() {
        let line = strip_toml_comment(raw).trim();
        if line.is_empty() {
            continue;
        }
        if line.starts_with('[') && line.ends_with(']') {
            let name = line[1..line.len() - 1].trim().trim_matches('"');
            in_theme = name == "theme";
            continue;
        }
        if !in_theme {
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        if key.trim() != "mode" {
            continue;
        }
        return unquote(value.trim());
    }
    None
}

/// Modo oscuro según Noctalia. `settings.toml` gana sobre `config.toml`.
/// `auto` y un modo desconocido no se inventan.
pub fn preferred_dark(state_toml: Option<&str>, config_toml: Option<&str>) -> Option<bool> {
    let mode = state_toml
        .and_then(theme_mode_in_toml)
        .or_else(|| config_toml.and_then(theme_mode_in_toml))?;
    match mode.as_str() {
        "dark" => Some(true),
        "light" => Some(false),
        _ => None,
    }
}

/// Ruta de wallpaper declarada en un TOML de Noctalia.
///
/// Prioridad, la misma que usa el shell: `[wallpaper.default].path`, luego
/// `[wallpaper.last].path`, luego el primer `[wallpaper.monitors.*].path`.
pub fn wallpaper_path_in_toml(text: &str) -> Option<String> {
    let mut section: Vec<String> = Vec::new();
    let mut default_path = None;
    let mut last_path = None;
    let mut monitor_path = None;

    for raw in text.lines() {
        let line = strip_toml_comment(raw).trim().to_string();
        if line.is_empty() {
            continue;
        }
        if line.starts_with('[') && line.ends_with(']') {
            section = line[1..line.len() - 1]
                .split('.')
                .map(|part| part.trim().trim_matches('"').to_string())
                .collect();
            continue;
        }
        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        if key.trim() != "path" {
            continue;
        }
        let Some(path) = unquote(value.trim()) else {
            continue;
        };
        if path.is_empty() {
            continue;
        }
        match section.as_slice() {
            [wallpaper, name] if wallpaper == "wallpaper" && name == "default" => {
                default_path = Some(path);
            }
            [wallpaper, name] if wallpaper == "wallpaper" && name == "last" => {
                last_path = Some(path);
            }
            [wallpaper, name, _]
                if wallpaper == "wallpaper" && name == "monitors" && monitor_path.is_none() =>
            {
                monitor_path = Some(path);
            }
            _ => {}
        }
    }

    default_path.or(last_path).or(monitor_path)
}

/// Candidatos, de más vivo a más antiguo. El llamador se queda con el
/// primero que exista en disco.
///
/// Si Noctalia es el shell, gana `settings.toml` (lo que acaba de aplicar),
/// luego el `config.toml` de fábrica, y `settings.json` solo si esos no
/// dicen nada. Sin Noctalia, solo cuenta `settings.json`.
pub fn wallpaper_candidates(
    settings_path: &str,
    state_toml: Option<&str>,
    config_toml: Option<&str>,
    noctalia_is_shell: bool,
) -> Vec<String> {
    let mut out = Vec::new();
    if noctalia_is_shell {
        if let Some(path) = state_toml.and_then(wallpaper_path_in_toml) {
            out.push(path);
        }
        if let Some(path) = config_toml.and_then(wallpaper_path_in_toml) {
            out.push(path);
        }
    }
    if !settings_path.is_empty() {
        out.push(settings_path.to_string());
    }
    out
}

fn read_user_niri() -> String {
    let path = PathBuf::from(crate::home_dir()).join(".config/niri/config.kdl");
    std::fs::read_to_string(path).unwrap_or_default()
}

fn comm_running(name: &str) -> bool {
    let Ok(entries) = std::fs::read_dir("/proc") else {
        return false;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Some(pid) = path.file_name().and_then(|n| n.to_str()) else {
            continue;
        };
        if !pid.bytes().all(|b| b.is_ascii_digit()) {
            continue;
        }
        if std::fs::read_to_string(path.join("comm"))
            .map(|comm| comm.trim() == name)
            .unwrap_or(false)
        {
            return true;
        }
    }
    false
}

fn command_is(arg: &str, binary: &str) -> bool {
    arg == binary || arg.rsplit('/').next() == Some(binary)
}

fn shell_invokes(script: &str, binary: &str) -> bool {
    script
        .split(|c: char| {
            c.is_whitespace()
                || matches!(
                    c,
                    ';' | '&' | '|' | '(' | ')' | '"' | '\'' | '`' | '{' | '}'
                )
        })
        .any(|token| command_is(token, binary))
}

fn quoted_strings(line: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut chars = line.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch != '"' {
            continue;
        }
        let mut value = String::new();
        while let Some(next) = chars.next() {
            if next == '\\' {
                if let Some(escaped) = chars.next() {
                    value.push(escaped);
                }
                continue;
            }
            if next == '"' {
                break;
            }
            value.push(next);
        }
        out.push(value);
    }
    out
}

fn strip_kdl_comment(line: &str) -> &str {
    let bytes = line.as_bytes();
    let mut in_string = false;
    let mut i = 0;
    while i + 1 < bytes.len() {
        if bytes[i] == b'"' {
            in_string = !in_string;
        } else if !in_string && bytes[i] == b'/' && bytes[i + 1] == b'/' {
            return line[..i].trim_end();
        }
        i += 1;
    }
    line
}

fn strip_toml_comment(line: &str) -> &str {
    let bytes = line.as_bytes();
    let mut in_string = false;
    let mut quote = b'"';
    let mut i = 0;
    while i < bytes.len() {
        let ch = bytes[i];
        if in_string {
            if ch == b'\\' {
                i += 2;
                continue;
            }
            if ch == quote {
                in_string = false;
            }
        } else if ch == b'"' || ch == b'\'' {
            in_string = true;
            quote = ch;
        } else if ch == b'#' {
            return line[..i].trim_end();
        }
        i += 1;
    }
    line
}

fn unquote(value: &str) -> Option<String> {
    let mut chars = value.chars();
    let quote = chars.next()?;
    if quote != '"' && quote != '\'' {
        return None;
    }
    let mut out = String::new();
    while let Some(ch) = chars.next() {
        if ch == '\\' {
            if let Some(escaped) = chars.next() {
                out.push(escaped);
            }
            continue;
        }
        if ch == quote {
            break;
        }
        out.push(ch);
    }
    Some(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    const SHIPPED_NIRI: &str =
        include_str!("../../../archiso/airootfs/etc/skel/.config/niri/config.kdl");
    const SHIPPED_NOCTALIA: &str =
        include_str!("../../../archiso/airootfs/etc/skel/.config/noctalia/config.toml");

    #[test]
    fn shipped_niri_session_hides_waybar_and_mako() {
        assert!(niri_autostart_has(SHIPPED_NIRI, "noctalia"));
        assert!(!niri_autostart_has(SHIPPED_NIRI, "waybar"));
        assert!(!niri_autostart_has(SHIPPED_NIRI, "mako"));
        assert!(!niri_autostart_has(SHIPPED_NIRI, "swaybg"));

        let up = RunningShells {
            noctalia: true,
            ..RunningShells::default()
        };
        assert!(noctalia_is_shell(up, SHIPPED_NIRI));
        assert!(!session_uses(OptionalShell::Waybar, up, SHIPPED_NIRI));
        assert!(!session_uses(OptionalShell::Mako, up, SHIPPED_NIRI));

        // Ajustes abierto antes de que el proceso exista: el autostart basta.
        let idle = RunningShells::default();
        assert!(noctalia_is_shell(idle, SHIPPED_NIRI));
        assert!(!session_uses(OptionalShell::Waybar, idle, SHIPPED_NIRI));
        assert!(!session_uses(OptionalShell::Mako, idle, SHIPPED_NIRI));
    }

    #[test]
    fn waybar_and_mako_sessions_keep_their_pages() {
        let replaced = "spawn-at-startup \"waybar\"\nspawn-at-startup \"mako\"\n";
        let idle = RunningShells::default();
        assert!(!noctalia_is_shell(idle, replaced));
        assert!(session_uses(OptionalShell::Waybar, idle, replaced));
        assert!(session_uses(OptionalShell::Mako, idle, replaced));

        // Los dos en el autostart: Noctalia es el shell y las páginas siguen
        // ocultas hasta que waybar o mako estén realmente en marcha.
        let both = "spawn-at-startup \"noctalia\"\nspawn-at-startup \"waybar\"\n";
        assert!(!session_uses(OptionalShell::Waybar, idle, both));
        let alongside = RunningShells {
            waybar: true,
            noctalia: true,
            mako: false,
        };
        assert!(session_uses(OptionalShell::Waybar, alongside, both));
        assert!(!session_uses(OptionalShell::Mako, alongside, both));
    }

    #[test]
    fn comments_and_other_commands_do_not_count_as_autostart() {
        let config = "\
// spawn-at-startup \"waybar\"
spawn-at-startup \"churros-portal-start\"
spawn-sh-at-startup \"[ -f ~/.config/autostart/churros-tour.desktop ] && churros-tour\"
spawn-at-startup \"/usr/bin/noctalia\" // barra
";
        assert!(!niri_autostart_has(config, "waybar"));
        assert!(niri_autostart_has(config, "churros-tour"));
        assert!(niri_autostart_has(config, "noctalia"));
        assert!(niri_autostart_has(config, "churros-portal-start"));
    }

    #[test]
    fn spawn_sh_can_opt_into_waybar() {
        let config = "spawn-sh-at-startup \"waybar -c ~/.config/waybar/config.jsonc\"\n";
        assert!(niri_autostart_has(config, "waybar"));
        assert!(!niri_autostart_has(config, "noctalia"));
        assert!(session_uses(
            OptionalShell::Waybar,
            RunningShells::default(),
            config
        ));
    }

    #[test]
    fn kde_without_niri_config_hides_both() {
        let idle = RunningShells::default();
        assert!(!noctalia_is_shell(idle, ""));
        assert!(!session_uses(OptionalShell::Waybar, idle, ""));
        assert!(!session_uses(OptionalShell::Mako, idle, ""));
    }

    #[test]
    fn shipped_noctalia_config_is_dark_and_state_overrides_it() {
        assert_eq!(
            theme_mode_in_toml(SHIPPED_NOCTALIA).as_deref(),
            Some("dark")
        );
        assert_eq!(preferred_dark(None, Some(SHIPPED_NOCTALIA)), Some(true));
        let state = "\
[theme]
mode = \"light\"

[theme.templates]
mode = \"dark\"
";
        assert_eq!(
            preferred_dark(Some(state), Some(SHIPPED_NOCTALIA)),
            Some(false)
        );
        assert_eq!(
            preferred_dark(Some("[theme]\nmode = \"auto\"\n"), Some(SHIPPED_NOCTALIA)),
            None
        );
    }

    #[test]
    fn shipped_noctalia_config_points_at_the_default_wallpaper() {
        assert_eq!(
            wallpaper_path_in_toml(SHIPPED_NOCTALIA).as_deref(),
            Some("/usr/share/churros/wallpapers/default.png")
        );
    }

    #[test]
    fn live_state_wins_over_the_shipped_default_and_settings_json() {
        let state = "\
[wallpaper.default]
path = \"/tmp/nuevo.png\" # lo acaba de poner la UI

[wallpaper.last]
path = \"/tmp/viejo.png\"
";
        let config = "[wallpaper.default]\npath = \"/usr/share/churros/wallpapers/default.png\"\n";
        let candidates =
            wallpaper_candidates("/home/churros/otro.png", Some(state), Some(config), true);
        assert_eq!(
            candidates,
            vec![
                "/tmp/nuevo.png".to_string(),
                "/usr/share/churros/wallpapers/default.png".to_string(),
                "/home/churros/otro.png".to_string(),
            ]
        );
    }

    #[test]
    fn without_noctalia_only_settings_json_counts() {
        let config = "[wallpaper.default]\npath = \"/usr/share/churros/wallpapers/default.png\"\n";
        let candidates = wallpaper_candidates("/home/kde/fondo.png", None, Some(config), false);
        assert_eq!(candidates, vec!["/home/kde/fondo.png".to_string()]);
        assert!(wallpaper_candidates("", None, Some(config), false).is_empty());
    }

    #[test]
    fn falls_back_to_last_or_a_monitor_when_default_is_missing() {
        let last_only = "[wallpaper.last]\npath = \"/tmp/last.png\"\n";
        assert_eq!(
            wallpaper_path_in_toml(last_only).as_deref(),
            Some("/tmp/last.png")
        );
        let monitor = "\
[theme]
path = \"/tmp/no-es-un-fondo.png\"

[wallpaper.monitors.eDP-1]
path = '/tmp/monitor.png'
";
        assert_eq!(
            wallpaper_path_in_toml(monitor).as_deref(),
            Some("/tmp/monitor.png")
        );
    }
}

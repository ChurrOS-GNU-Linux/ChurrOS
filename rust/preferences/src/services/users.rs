// ==========================================
// UsersService — cuenta del sistema y autologin de greetd / LightDM
// ==========================================

use std::fs;
use std::process::{Command, Stdio};

pub struct UsersService;

const GREETD_CONFIG_PATH: &str = "/etc/greetd/config.toml";
const REGREET_CONFIG_PATH: &str = "/etc/greetd/regreet.toml";
const LIGHTDM_AUTOLOGIN_PATH: &str = "/etc/lightdm/lightdm.conf.d/autologin.conf";
const LIGHTDM_MAIN_PATH: &str = "/etc/lightdm/lightdm.conf";

/// Helper root que aplica estos ajustes de /etc. Recibe operaciones acotadas
/// (`greetd-autologin on|off`, `regreet-wallpaper <ruta>`...), nunca el
/// contenido del fichero, y decide él el usuario (quien invoca pkexec) y la
/// sesión (la de la edición instalada). La regla polkit lo autoriza por esta
/// ruta y con estos argv: si cambian, cambia también
/// 50-churros-store.rules y scripts/test-polkit-rules.js.
const WRITE_ROOT_CONFIG: &str = "/usr/local/bin/churros-write-root-config";

fn getuid() -> u32 {
    Command::new("id")
        .arg("-u")
        .output()
        .ok()
        .and_then(|o| String::from_utf8_lossy(&o.stdout).trim().parse().ok())
        .unwrap_or(1000) // fallo → no-root, nunca intentar escritura privilegiada
}

/// Campos de /etc/passwd para el uid actual: (name, uid, gid, gecos, shell)
fn passwd_entry() -> Option<(String, String, String, String, String)> {
    let content = fs::read_to_string("/etc/passwd").ok()?;
    let uid = getuid().to_string();
    for line in content.lines() {
        let fields: Vec<&str> = line.split(':').collect();
        if fields.len() >= 7 && fields[2] == uid {
            return Some((
                fields[0].to_string(),
                fields[2].to_string(),
                fields[3].to_string(),
                fields[4].to_string(),
                fields[6].to_string(),
            ));
        }
    }
    None
}

/// Valor de una clave TOML de una línea: cadena básica ("..." con escapes
/// \" y \\, que es como la escribe el helper), literal ('...') o desnudo.
fn toml_value(raw: &str) -> String {
    let raw = raw.trim();
    if let Some(inner) = raw.strip_prefix('"').and_then(|r| r.strip_suffix('"')) {
        let mut out = String::with_capacity(inner.len());
        let mut chars = inner.chars();
        while let Some(c) = chars.next() {
            if c == '\\' {
                match chars.next() {
                    Some('"') => out.push('"'),
                    Some('\\') => out.push('\\'),
                    Some(other) => {
                        out.push('\\');
                        out.push(other);
                    }
                    None => out.push('\\'),
                }
            } else {
                out.push(c);
            }
        }
        return out;
    }
    if let Some(inner) = raw.strip_prefix('\'').and_then(|r| r.strip_suffix('\'')) {
        return inner.to_string();
    }
    raw.to_string()
}

/// ¿La línea inicia una sección `[nombre]`? Devuelve el nombre.
fn section_name(line: &str) -> Option<&str> {
    let t = line.trim();
    if t.starts_with('[') && t.ends_with(']') {
        Some(&t[1..t.len() - 1])
    } else {
        None
    }
}

/// Verifica si greetd tiene `[initial_session]` configurado
fn check_greetd_autologin() -> bool {
    let Ok(content) = fs::read_to_string(GREETD_CONFIG_PATH) else {
        return false;
    };
    let mut in_initial = false;
    for line in content.lines() {
        let trimmed = line.trim();
        if let Some(sec) = section_name(trimmed) {
            in_initial = sec.eq_ignore_ascii_case("initial_session");
            continue;
        }
        if in_initial && trimmed.starts_with("user") {
            if let Some((_, val)) = trimmed.split_once('=') {
                let user_val = val.trim().trim_matches('"').trim_matches('\'');
                if !user_val.is_empty() {
                    return true;
                }
            }
        }
    }
    false
}

/// Verifica si un archivo INI tiene `autologin-user=<usuario>` no vacío
fn check_ini_autologin(path: &str) -> bool {
    let Ok(content) = fs::read_to_string(path) else {
        return false;
    };
    let mut in_seat = false;
    for line in content.lines() {
        let trimmed = line.trim();
        if let Some(sec) = section_name(trimmed) {
            in_seat = sec.to_lowercase().starts_with("seat");
            continue;
        }
        if (in_seat || !trimmed.starts_with('[')) && trimmed.to_lowercase().starts_with("autologin-user") {
            if let Some((key, val)) = trimmed.split_once('=') {
                if key.trim().eq_ignore_ascii_case("autologin-user") {
                    let user_val = val.trim();
                    if !user_val.is_empty() && user_val != "false" {
                        return true;
                    }
                }
            }
        }
    }
    false
}

impl UsersService {
    pub fn username() -> String {
        std::env::var("USER").unwrap_or_else(|_| {
            passwd_entry()
                .map(|(name, _, _, _, _)| name)
                .unwrap_or_else(|| "Desconocido".to_string())
        })
    }

    pub fn full_name() -> String {
        if let Some((_, _, _, gecos, _)) = passwd_entry() {
            let name = gecos.split(',').next().unwrap_or("").trim();
            if !name.is_empty() {
                return name.to_string();
            }
        }
        Self::username()
    }

    pub fn home() -> String {
        std::env::var("HOME").unwrap_or_default()
    }

    pub fn shell() -> String {
        passwd_entry()
            .map(|(_, _, _, _, shell)| shell)
            .unwrap_or_else(|| "Desconocido".to_string())
    }

    pub fn uid() -> String {
        getuid().to_string()
    }

    pub fn gid() -> String {
        Command::new("id")
            .arg("-g")
            .output()
            .ok()
            .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "0".to_string())
    }

    pub fn hostname() -> String {
        fs::read_to_string("/proc/sys/kernel/hostname")
            .map(|s| s.trim().to_string())
            .unwrap_or_else(|_| "Desconocido".to_string())
    }

    /// ¿Hay autologin configurado en greetd o LightDM?
    pub fn auto_login() -> bool {
        if std::path::Path::new(GREETD_CONFIG_PATH).exists() {
            check_greetd_autologin()
        } else {
            check_ini_autologin(LIGHTDM_AUTOLOGIN_PATH) || check_ini_autologin(LIGHTDM_MAIN_PATH)
        }
    }

    /// Activa/desactiva el autologin del Display Manager activo.
    ///
    /// Usuario y sesión los decide el helper: el usuario es quien invoca
    /// pkexec y la sesión, la de /etc/churros-edition con la misma tabla que
    /// usa la instalación (`churros-niri-session` en Niri). Aquí solo se elige
    /// el gestor y el estado.
    pub fn set_auto_login(value: bool) -> bool {
        let current = Self::auto_login();
        if value == current {
            return true;
        }

        let state = if value { "on" } else { "off" };
        if std::path::Path::new("/etc/greetd").exists() || std::path::Path::new(GREETD_CONFIG_PATH).exists() {
            Self::write_root_config(&["greetd-autologin", state])
        } else {
            Self::write_root_config(&["lightdm-autologin", state])
        }
    }

    /// Obtiene el fondo de pantalla configurado en ReGreet
    pub fn regreet_wallpaper() -> String {
        let Ok(content) = fs::read_to_string(REGREET_CONFIG_PATH) else {
            return "/usr/share/churros/wallpapers/default.png".to_string();
        };
        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with("path") && trimmed.contains('=') {
                if let Some((_, val)) = trimmed.split_once('=') {
                    let p = toml_value(val);
                    if !p.is_empty() {
                        return p;
                    }
                }
            }
        }
        "/usr/share/churros/wallpapers/default.png".to_string()
    }

    /// Pone `wallpaper_path` de fondo en ReGreet.
    ///
    /// El helper solo acepta fondos del sistema (/usr/share/churros/wallpapers,
    /// /usr/share/backgrounds, /usr/share/wallpapers) que el greeter pueda
    /// leer: uno del home no lo podría mostrar.
    pub fn set_regreet_wallpaper(wallpaper_path: &str) -> bool {
        Self::write_root_config(&["regreet-wallpaper", wallpaper_path])
    }

    /// Obtiene el mensaje de bienvenida de ReGreet
    pub fn regreet_greeting() -> String {
        let Ok(content) = fs::read_to_string(REGREET_CONFIG_PATH) else {
            return "Bienvenido a ChurrOS".to_string();
        };
        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with("greeting_msg") && trimmed.contains('=') {
                if let Some((_, val)) = trimmed.split_once('=') {
                    let msg = toml_value(val);
                    if !msg.is_empty() {
                        return msg;
                    }
                }
            }
        }
        "Bienvenido a ChurrOS".to_string()
    }

    /// Cambia el mensaje de bienvenida de ReGreet (máximo 80 caracteres, sin
    /// saltos de línea; lo valida y escapa el helper).
    pub fn set_regreet_greeting(greeting: &str) -> bool {
        Self::write_root_config(&["regreet-greeting", greeting])
    }

    /// Aplica un ajuste de /etc con churros-write-root-config como root.
    ///
    /// Pasa por churros-pkexec, que pide la contraseña de administrador (la
    /// regla polkit da auth_admin_keep a estas operaciones) o, si ya somos
    /// root, lo ejecuta directamente.
    fn write_root_config(args: &[&str]) -> bool {
        Command::new("churros-pkexec")
            .arg(WRITE_ROOT_CONFIG)
            .args(args)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::toml_value;

    #[test]
    fn toml_value_reads_what_the_helper_writes() {
        assert_eq!(
            toml_value(r#" "Bienvenido a ChurrOS" "#),
            "Bienvenido a ChurrOS"
        );
        assert_eq!(
            toml_value(r#""¡Hola, \"ana\"! \\o/""#),
            r#"¡Hola, "ana"! \o/"#
        );
        assert_eq!(toml_value("'literal'"), "literal");
        assert_eq!(toml_value("desnudo"), "desnudo");
    }
}

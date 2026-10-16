// ==========================================
// Acciones: abrir URLs y lanzar el instalador
// (equivalente a utils/browser.py + utils/desktop.py)
// ==========================================

use gtk::prelude::*;

use std::path::PathBuf;
use std::process::Command;

const REPOSITORY: &str = "https://github.com/ChurrOS-GNU-Linux/ChurrOS";
const DISCORD: &str = "https://discord.gg/tkzAnsVs3";
const WIKI: &str = "https://github.com/ChurrOS-GNU-Linux/ChurrOS/wiki";
const WEBSITE: &str = "https://github.com/ChurrOS-GNU-Linux/ChurrOS";

fn open_url(url: &str) {
    if let Err(e) = gio::AppInfo::launch_default_for_uri(url, None::<&gio::AppLaunchContext>) {
        eprintln!("[welcome] error abriendo {url}: {e}");
    }
}

#[allow(dead_code)]
pub fn open_wiki() {
    open_url(WIKI);
}

#[allow(dead_code)]
pub fn open_website() {
    open_url(WEBSITE);
}

// Callbacks de las cards (reciben el botón que las lanzó)

pub fn github_clicked(_button: &gtk::Button) {
    open_url(REPOSITORY);
}

pub fn discord_clicked(_button: &gtk::Button) {
    open_url(DISCORD);
}

pub fn install_clicked(button: &gtk::Button) {
    launch_installer(button);
}

// ==========================================
// Lanzador de .desktop (sustituye a Gio.DesktopAppInfo,
// que no está expuesto en gio-rs 0.22)
// ==========================================

fn find_desktop_file(app_id: &str) -> Option<PathBuf> {
    let mut dirs: Vec<PathBuf> = std::env::var("XDG_DATA_DIRS")
        .unwrap_or_else(|_| "/usr/local/share:/usr/share".to_string())
        .split(':')
        .map(PathBuf::from)
        .collect();

    if let Ok(home) = std::env::var("HOME") {
        dirs.insert(0, PathBuf::from(home).join(".local/share"));
    }

    for dir in dirs {
        let candidate = dir.join("applications").join(app_id);
        if candidate.is_file() {
            return Some(candidate);
        }
    }

    None
}

/// Tokeniza una línea `Exec=` de un .desktop al estilo de la especificación:
/// comillas dobles y barras invertidas escapan, las comillas simples no son
/// especiales. Devuelve None si queda una comilla sin cerrar.
///
/// Se usa en lugar de `sh -c`: pasar la línea a un shell convierte cualquier
/// .desktop escrito por el usuario (basta con crear
/// ~/.local/share/applications/calamares.desktop) en ejecución de órdenes.
fn tokenize_exec(line: &str) -> Option<Vec<String>> {
    let mut out: Vec<String> = Vec::new();
    let mut cur = String::new();
    let mut has_token = false;
    let mut in_quotes = false;
    let mut escaped = false;

    for ch in line.chars() {
        if escaped {
            cur.push(ch);
            escaped = false;
            has_token = true;
            continue;
        }
        match ch {
            '\\' if !in_quotes => escaped = true,
            '"' => {
                in_quotes = !in_quotes;
                has_token = true;
            }
            c if c.is_whitespace() && !in_quotes => {
                if has_token {
                    out.push(std::mem::take(&mut cur));
                    has_token = false;
                }
            }
            c => {
                cur.push(c);
                has_token = true;
            }
        }
    }

    if escaped || in_quotes {
        return None;
    }
    if has_token {
        out.push(cur);
    }
    if out.is_empty() {
        None
    } else {
        Some(out)
    }
}

/// Programas que el welcome app puede lanzar. El lanzador del instalador es
/// una superficie privilegiada: no se ejecuta cualquier .desktop que aparezca
/// en el XDG_DATA_HOME del usuario.
const ALLOWED_LAUNCHERS: &[&str] = &["/usr/local/bin/calamares", "/usr/bin/calamares"];

fn desktop_exec(app_id: &str) -> Option<String> {
    let path = find_desktop_file(app_id)?;
    let content = std::fs::read_to_string(path).ok()?;

    let mut in_entry = false;
    for line in content.lines() {
        let line = line.trim();
        if line.starts_with('[') && line.ends_with(']') {
            in_entry = line == "[Desktop Entry]";
            continue;
        }
        if !in_entry {
            continue;
        }
        if let Some(exec) = line.strip_prefix("Exec=") {
            // Los field codes (%f, %u, %F, %U, %i, %c, %k) se descartan,
            // igual que hace GLib al expandir el campo Exec.
            let cleaned: String = exec
                .split(" %")
                .next()
                .unwrap_or(exec)
                .to_string();
            return Some(cleaned);
        }
    }

    None
}

fn launch_installer(parent: &gtk::Button) {
    if std::env::var("CHURROS_DEV").ok().as_deref() == Some("1") {
        eprintln!("[churros-dev] blocked: launch calamares");
        let dialog = gtk::AlertDialog::builder()
            .message("Preview: the installer is not launched on the host.")
            .modal(true)
            .build();
        if let Some(root) = parent.root().and_downcast::<gtk::Window>() {
            dialog.show(Some(&root));
        } else {
            dialog.show(None::<&gtk::Window>);
        }
        return;
    }

    match desktop_exec("calamares.desktop").as_deref().and_then(tokenize_exec) {
        Some(argv) => {
            let launched = if ALLOWED_LAUNCHERS.contains(&argv[0].as_str()) {
                // Sin shell: el Exec se pasa como argv a execvp.
                Command::new(&argv[0])
                    .args(&argv[1..])
                    .spawn()
                    .map(|_| ())
                    .is_ok()
            } else {
                eprintln!(
                    "[welcome] launcher no permitido: {}",
                    argv.first().map(|s| s.as_str()).unwrap_or("")
                );
                false
            };

            if !launched {
                show_alert(parent);
            }
        }
        None => show_alert(parent),
    }
}

fn show_alert(parent: &gtk::Button) {
    let dialog = gtk::AlertDialog::builder()
        .message("Installer not available on this system.")
        .modal(true)
        .build();

    if let Some(root) = parent.root().and_downcast::<gtk::Window>() {
        dialog.show(Some(&root));
    } else {
        dialog.show(None::<&gtk::Window>);
    }
}

#[cfg(test)]
mod tests {
    use super::tokenize_exec;

    #[test]
    fn tokenizes_plain_command() {
        assert_eq!(
            tokenize_exec("/usr/local/bin/calamares"),
            Some(vec!["/usr/local/bin/calamares".to_string()])
        );
    }

    #[test]
    fn keeps_quoted_argument_together() {
        assert_eq!(
            tokenize_exec("\"/usr/local/bin/calamares\" --plain"),
            Some(vec![
                "/usr/local/bin/calamares".to_string(),
                "--plain".to_string()
            ])
        );
    }

    #[test]
    fn honours_backslash_escapes() {
        assert_eq!(
            tokenize_exec("/usr/local/bin/calamares a\\ b"),
            Some(vec![
                "/usr/local/bin/calamares".to_string(),
                "a b".to_string()
            ])
        );
    }

    #[test]
    fn rejects_unterminated_quote() {
        assert_eq!(tokenize_exec("/usr/local/bin/calamares \"unclosed"), None);
    }

    #[test]
    fn does_not_split_on_shell_metacharacters() {
        // Antes esto pasaba por `sh -c` y era ejecución de órdenes.
        assert_eq!(
            tokenize_exec("/usr/local/bin/calamares; id"),
            Some(vec![
                "/usr/local/bin/calamares;".to_string(),
                "id".to_string()
            ])
        );
    }

    #[test]
    fn rejects_empty() {
        assert_eq!(tokenize_exec("   "), None);
    }
}

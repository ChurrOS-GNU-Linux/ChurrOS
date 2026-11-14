//! Transparencia de las ventanas ChurrOS (efecto vidrio).
//!
//! Las apps pintan su fondo con `--bg-window` (rgba ~0.6) para que el
//! compositor deje ver y desenfoque lo de detrás. En XFCE no existe el
//! «Modo rendimiento» de Niri, así que la única forma de quitarlo es esta:
//! con la marca `~/.config/churros/solid-windows` cada app carga encima
//! `/usr/share/churros/styles/solid.css`, que vuelve opacos esos tokens.
//! Sin dependencia de GTK: cada crate añade el CssProvider.

use std::path::PathBuf;

/// Prioridad del CSS sólido: por encima del style.css de cada app
/// (APPLICATION + 1) y por debajo del accent.css y del gtk.css del usuario.
pub const SOLID_CSS_PRIORITY_OFFSET: u32 = 10;

const SOLID_CSS: &str = "/usr/share/churros/styles/solid.css";

/// Marca: si existe, las ventanas ChurrOS van sin transparencia.
pub fn solid_flag() -> PathBuf {
    PathBuf::from(crate::home_dir()).join(".config/churros/solid-windows")
}

/// ¿El usuario quitó la transparencia?
pub fn solid_windows() -> bool {
    solid_flag().exists()
}

/// Guarda la preferencia (crea o borra la marca).
pub fn set_solid_windows(solid: bool) -> std::io::Result<()> {
    let flag = solid_flag();
    if solid {
        if let Some(parent) = flag.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&flag, "1\n")
    } else {
        match std::fs::remove_file(&flag) {
            Err(error) if error.kind() != std::io::ErrorKind::NotFound => Err(error),
            _ => Ok(()),
        }
    }
}

/// solid.css instalado o, en desarrollo, el del árbol del repo.
pub fn solid_css_path() -> Option<PathBuf> {
    let dev = PathBuf::from(concat!(
        env!("CARGO_MANIFEST_DIR"),
        "/../../archiso/airootfs/usr/share/churros/styles/solid.css"
    ));
    [PathBuf::from(SOLID_CSS), dev].into_iter().find(|p| p.is_file())
}

/// Ruta de solid.css que la app tiene que cargar ahora, si la hay.
pub fn solid_css_to_load() -> Option<PathBuf> {
    if solid_windows() { solid_css_path() } else { None }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shipped_solid_css_makes_window_tokens_opaque() {
        let path = solid_css_path().expect("falta usr/share/churros/styles/solid.css");
        let css = std::fs::read_to_string(path).unwrap();
        for token in ["--bg-window", "--bg-sidebar", "--bg-surface", "--popover-bg"] {
            let lines: Vec<&str> = css.lines().filter(|l| l.trim_start().starts_with(token)).collect();
            assert!(lines.len() >= 2, "{token}: falta en modo oscuro o claro");
            for line in lines {
                assert!(!line.contains("rgba"), "{token} sigue con alfa: {line}");
            }
        }
        assert!(css.contains("window.light"), "solid.css sin variante clara");
    }
}

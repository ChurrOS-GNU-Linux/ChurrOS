// ==========================================
// dotfiles — copia y restauración de directorios de configuración
//
// Vive aquí, y no en churros-settings, porque es la parte con efectos
// destructivos (borra el directorio del usuario antes de copiar) y así se
// puede probar sin un entorno gráfico.
//
// La regla: nunca destruir antes de saber que la copia va a funcionar. Se
// copia a un directorio temporal hermano y se intercambia al final; si algo
// falla, el original sigue intacto y el error se devuelve.
// ==========================================

use std::fs;
use std::io;
use std::path::{Path, PathBuf};

/// Copia recursiva de directorio (equivalente a shutil.copytree).
pub fn copy_dir_all(src: &Path, dst: &Path) -> io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let target = dst.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_dir_all(&entry.path(), &target)?;
        } else {
            fs::copy(entry.path(), target)?;
        }
    }
    Ok(())
}

/// Restaura `src` sobre `dst` sin ventana en la que `dst` no exista.
///
/// 1. Copia `src` a `<dst>.churros-new` (mismo sistema de archivos, rename
///    atómico después).
/// 2. Si `dst` existe, lo mueve a `<dst>.churros-old`.
/// 3. Mueve `<dst>.churros-new` a `dst`.
/// 4. Borra `<dst>.churros-old`.
///
/// Si falla cualquier paso, se deshace lo hecho y `dst` conserva su
/// contenido anterior. Un fallo de copia nunca deja al usuario sin config.
pub fn replace_dir(src: &Path, dst: &Path) -> io::Result<()> {
    let staged = sibling(dst, "churros-new");
    let backup = sibling(dst, "churros-old");

    // Restos de una ejecución anterior interrumpida.
    let _ = fs::remove_dir_all(&staged);
    let _ = fs::remove_dir_all(&backup);

    if let Err(error) = copy_dir_all(src, &staged) {
        let _ = fs::remove_dir_all(&staged);
        return Err(error);
    }

    let had_previous = dst.exists();
    if had_previous {
        if let Err(error) = fs::rename(dst, &backup) {
            let _ = fs::remove_dir_all(&staged);
            return Err(error);
        }
    }

    if let Err(error) = fs::rename(&staged, dst) {
        // Devolver el original a su sitio antes de propagar el error.
        if had_previous {
            let _ = fs::rename(&backup, dst);
        }
        let _ = fs::remove_dir_all(&staged);
        return Err(error);
    }

    if had_previous {
        let _ = fs::remove_dir_all(&backup);
    }
    Ok(())
}

/// `<dst>.churros-new`: hermano del destino, para que el rename no cruce
/// sistemas de archivos (fallaría con EXDEV).
fn sibling(dst: &Path, suffix: &str) -> PathBuf {
    let mut name = dst.file_name().unwrap_or_default().to_os_string();
    name.push(".");
    name.push(suffix);
    dst.with_file_name(name)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn tmp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "churros-dotfiles-{}-{}-{name}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn replace_dir_copies_contents() {
        let base = tmp("copies");
        let src = base.join("defaults");
        let dst = base.join("config");
        fs::create_dir_all(src.join("sub")).unwrap();
        fs::write(src.join("config.kdl"), "nuevo").unwrap();
        fs::write(src.join("sub/extra"), "x").unwrap();

        replace_dir(&src, &dst).unwrap();

        assert_eq!(fs::read_to_string(dst.join("config.kdl")).unwrap(), "nuevo");
        assert_eq!(fs::read_to_string(dst.join("sub/extra")).unwrap(), "x");
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn replace_dir_overwrites_previous_contents() {
        let base = tmp("overwrite");
        let src = base.join("defaults");
        let dst = base.join("config");
        fs::create_dir_all(&src).unwrap();
        fs::create_dir_all(&dst).unwrap();
        fs::write(src.join("config.toml"), "[bar.default]\n").unwrap();
        fs::write(dst.join("config.toml"), "editado").unwrap();
        fs::write(dst.join("sobra.toml"), "viejo").unwrap();

        replace_dir(&src, &dst).unwrap();

        assert_eq!(
            fs::read_to_string(dst.join("config.toml")).unwrap(),
            "[bar.default]\n"
        );
        assert!(!dst.join("sobra.toml").exists());
        let _ = fs::remove_dir_all(&base);
    }

    /// El caso que provocaba la pérdida de datos: si la copia falla, el
    /// directorio del usuario tiene que seguir exactamente como estaba.
    #[test]
    fn replace_dir_keeps_the_original_when_the_copy_fails() {
        let base = tmp("fails");
        let missing = base.join("defaults-no-existe");
        let dst = base.join("config");
        fs::create_dir_all(&dst).unwrap();
        fs::write(dst.join("config.toml"), "del usuario").unwrap();

        let error = replace_dir(&missing, &dst).unwrap_err();

        assert_eq!(error.kind(), io::ErrorKind::NotFound);
        assert_eq!(
            fs::read_to_string(dst.join("config.toml")).unwrap(),
            "del usuario",
            "un fallo de copia no puede dejar al usuario sin su config"
        );
        let _ = fs::remove_dir_all(&base);
    }

    #[test]
    fn replace_dir_leaves_no_temporary_directories() {
        let base = tmp("clean");
        let src = base.join("defaults");
        let dst = base.join("config");
        fs::create_dir_all(&src).unwrap();
        fs::create_dir_all(&dst).unwrap();
        fs::write(src.join("a"), "1").unwrap();
        fs::write(dst.join("a"), "2").unwrap();

        replace_dir(&src, &dst).unwrap();

        assert!(!sibling(&dst, "churros-new").exists());
        assert!(!sibling(&dst, "churros-old").exists());
        let _ = fs::remove_dir_all(&base);
    }

    /// Restos de una ejecución interrumpida no pueden romper la siguiente.
    #[test]
    fn replace_dir_recovers_from_leftovers() {
        let base = tmp("leftovers");
        let src = base.join("defaults");
        let dst = base.join("config");
        fs::create_dir_all(&src).unwrap();
        fs::create_dir_all(sibling(&dst, "churros-new")).unwrap();
        fs::create_dir_all(sibling(&dst, "churros-old")).unwrap();
        fs::write(sibling(&dst, "churros-old").join("basura"), "x").unwrap();
        fs::write(src.join("a"), "1").unwrap();

        replace_dir(&src, &dst).unwrap();

        assert_eq!(fs::read_to_string(dst.join("a")).unwrap(), "1");
        assert!(!sibling(&dst, "churros-old").exists());
        let _ = fs::remove_dir_all(&base);
    }
}

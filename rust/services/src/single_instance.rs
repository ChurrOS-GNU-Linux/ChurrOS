// ==========================================
// single_instance — bloqueo exclusivo para el estado del popup
//
// Contexto (auditoría, issue A5): los popups decidían si ya había otro
// corriendo leyendo un pidfile, y solo después lo escribían. Entre leer y
// escribir (check-then-act) dos clics seguidos en Waybar lanzaban dos apps
// GTK, la segunda sobrescribía el pid y, al salir, la primera borraba el
// pidfile de la segunda: popups huérfanos y toggles que no apagan.
//
// La solución es un flock(LOCK_EX | LOCK_NB) sobre un fichero del runtime.
// El que consigue el lock es la instancia viva y escribe el pid; los demás
// fallan al instante (WouldBlock) y no tocan nada.
// ==========================================

use std::fs::{File, OpenOptions};
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::OpenOptionsExt;
use std::path::{Path, PathBuf};

/// Lock exclusivo tomado por el popup vivo.
#[derive(Debug)]
pub struct InstanceLock {
    file: File,
    path: PathBuf,
}

impl InstanceLock {
    /// Intenta quedarse con el lock de `path`.
    ///
    /// `Ok(Some(lock))` — no había dueño, este proceso lo es.
    /// `Ok(None)` — otro proceso tiene el lock: hay un popup vivo.
    /// `Err(_)` — no se pudo abrir el fichero.
    ///
    /// El lock se libera al soltar `InstanceLock` o al morir el proceso: el
    /// kernel lo hace por nosotros, así que un SIGKILL no deja el estado
    /// bloqueado para siempre. Eso es justo lo que un pidfile no daba.
    pub fn acquire(path: &Path) -> io::Result<Option<Self>> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .mode(0o600)
            .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
            .open(path)?;
        // LOCK_NB: no esperar. Si otro lo tiene, no somos la instancia viva.
        let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
        if rc != 0 {
            let error = io::Error::last_os_error();
            return match error.raw_os_error() {
                Some(libc::EWOULDBLOCK) => Ok(None),
                _ => Err(error),
            };
        }
        Ok(Some(Self {
            file,
            path: path.to_path_buf(),
        }))
    }

    /// Escribe `contents` en el fichero bloqueado, reemplazando lo anterior.
    pub fn write(&mut self, contents: &str) -> io::Result<()> {
        use std::io::{Seek, SeekFrom, Write};
        self.file.set_len(0)?;
        self.file.seek(SeekFrom::Start(0))?;
        self.file.write_all(contents.as_bytes())?;
        self.file.flush()
    }

    pub fn path(&self) -> &Path {
        &self.path
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "churros-lock-{}-{}-{name}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ));
        std::fs::create_dir_all(&dir).unwrap();
        dir.join("popup.lock")
    }

    #[test]
    fn first_acquire_wins() {
        let path = tmp("first");
        let lock = InstanceLock::acquire(&path).unwrap();
        assert!(lock.is_some(), "el primero tiene que quedarse con el lock");
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }

    /// El caso de A5: dos instancias a la vez, solo una puede creerse viva.
    #[test]
    fn second_acquire_reports_an_instance_already_running() {
        let path = tmp("second");
        let _first = InstanceLock::acquire(&path).unwrap().expect("primero");
        let second = InstanceLock::acquire(&path).unwrap();
        assert!(
            second.is_none(),
            "con un popup vivo, el segundo intento tiene que devolver None en vez de \
             lanzar otra ventana"
        );
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn dropping_the_lock_lets_the_next_one_in() {
        let path = tmp("release");
        {
            let _lock = InstanceLock::acquire(&path).unwrap().expect("primero");
        }
        let again = InstanceLock::acquire(&path).unwrap();
        assert!(again.is_some(), "al soltar el lock, la siguiente instancia entra");
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }

    #[test]
    fn write_replaces_previous_contents() {
        let path = tmp("write");
        let mut lock = InstanceLock::acquire(&path).unwrap().expect("lock");
        lock.write("1234\n").unwrap();
        lock.write("999\n").unwrap();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "999\n");
        let _ = std::fs::remove_dir_all(path.parent().unwrap());
    }
}

// ==========================================
// churros-services — capa de servicios de ChurrOS
// (port Rust de usr/share/churros/services/*.py)
// ==========================================

pub mod appearance;
pub mod audio;
pub mod battery;
pub mod bluetooth;
pub mod brightness;
pub mod dev;
pub mod ethernet;
pub mod jsonc;
pub mod noctalia;
pub mod power;
pub mod theme;
pub mod version;
pub mod waybar_style;
pub mod wifi;

use std::ffi::CStr;
use std::fs::{File, OpenOptions};
use std::io::{self, Read};
use std::os::fd::AsRawFd;
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

fn runtime_dir_at(base: &Path) -> io::Result<PathBuf> {
    let dir = base.join("churros");
    match std::fs::symlink_metadata(&dir) {
        Ok(meta) if !meta.file_type().is_dir() => {
            return Err(io::Error::other("el runtime de ChurrOS no es un directorio"));
        }
        Ok(_) => {}
        Err(error) if error.kind() == io::ErrorKind::NotFound => std::fs::create_dir(&dir)?,
        Err(error) => return Err(error),
    }
    let meta = std::fs::symlink_metadata(&dir)?;
    if meta.uid() != unsafe { libc::geteuid() } {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "el runtime de ChurrOS pertenece a otro usuario",
        ));
    }
    std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o700))?;
    Ok(dir)
}

/// Directorio privado de estado efímero para la sesión gráfica actual.
pub fn runtime_dir() -> io::Result<PathBuf> {
    let base = std::env::var_os("XDG_RUNTIME_DIR")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .ok_or_else(|| io::Error::other("XDG_RUNTIME_DIR no está definido"))?;
    runtime_dir_at(&base)
}

/// Abre un fichero privado del runtime sin seguir enlaces simbólicos.
pub fn open_runtime_file(name: &str, append: bool) -> io::Result<(PathBuf, File)> {
    if name.is_empty() || name.contains('/') || name == "." || name == ".." {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "nombre de estado inválido"));
    }
    let path = runtime_dir()?.join(name);
    let file = OpenOptions::new()
        .write(true)
        .create(true)
        .append(append)
        .truncate(!append)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(&path)?;
    Ok((path, file))
}

/// HOME del usuario efectivo; si la variable no existe o está vacía, se consulta
/// la base de datos de usuarios (passwd) por el UID efectivo mediante libc::getpwuid
/// en vez de asumir "/root" directamente.
pub fn home_dir() -> String {
    if let Ok(h) = std::env::var("HOME") {
        if !h.is_empty() {
            return h;
        }
    }
    let uid = unsafe { libc::getuid() };
    let pwd = unsafe { libc::getpwuid(uid) };
    if !pwd.is_null() {
        let dir = unsafe { CStr::from_ptr((*pwd).pw_dir) };
        if let Ok(s) = dir.to_str() {
            let s = s.trim();
            if !s.is_empty() {
                return s.to_string();
            }
        }
    }
    if let Ok(user) = std::env::var("USER") {
        let user = user.trim();
        if !user.is_empty() {
            if let Ok(out) = Command::new("getent").args(["passwd", user]).output() {
                if out.status.success() {
                    let line = String::from_utf8_lossy(&out.stdout);
                    if let Some(home) = line.split(':').nth(5) {
                        let home = home.trim();
                        if !home.is_empty() {
                            return home.to_string();
                        }
                    }
                }
            }
        }
    }
    "/root".to_string()
}

/// Directorio HOME como PathBuf.
pub fn home_path() -> PathBuf {
    PathBuf::from(home_dir())
}

/// UID del usuario efectivo actual (getuid(2)).
pub fn uid() -> u32 {
    unsafe { libc::getuid() }
}

/// Resultado de ejecutar un comando: (returncode, stdout, stderr).
pub type RunOut = (i32, String, String);

// Una sola lectura por turno: un escritor continuo no debe impedir atender
// el otro pipe, recoger el hijo ni comprobar el plazo.
fn read_capture(pipe: &mut impl Read, output: &mut Vec<u8>) -> io::Result<bool> {
    let mut buffer = [0; 16384];
    match pipe.read(&mut buffer) {
        Ok(0) => Ok(true),
        Ok(n) => {
            output.extend_from_slice(&buffer[..n]);
            Ok(false)
        }
        Err(e)
            if matches!(
                e.kind(),
                io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
            ) =>
        {
            Ok(false)
        }
        Err(e) => Err(e),
    }
}

/// Ejecuta un comando capturando stdout/stderr, con timeout opcional.
/// El plazo cubre el hijo y ambos EOF (también pipes heredados por descendientes).
/// Con timeout 0 espera sin límite. Devuelve None ante errores de ejecución,
/// captura, UTF-8 o timeout; en esos casos mata el grupo y recoge el hijo.
pub fn run(cmd: &[&str], timeout_ms: u64) -> Option<RunOut> {
    let (program, args) = cmd.split_first()?;
    if dev::enabled() && dev::is_mutation(cmd) {
        dev::log_blocked(cmd);
        return Some((0, String::new(), String::new()));
    }

    let started = Instant::now();
    let timeout = (timeout_ms > 0).then(|| Duration::from_millis(timeout_ms));
    let mut child = Command::new(program)
        .args(args)
        .process_group(0)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .ok()?;

    let result = (|| {
        let mut out_pipe = child.stdout.take()?;
        let mut err_pipe = child.stderr.take()?;
        for fd in [out_pipe.as_raw_fd(), err_pipe.as_raw_fd()] {
            // Los descriptores siguen siendo propiedad de ChildStdout/Stderr;
            // fcntl solo cambia sus flags, y Drop los cierra en todas las salidas.
            let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
            if flags == -1
                || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } == -1
            {
                return None;
            }
        }

        let (mut stdout, mut stderr) = (Vec::new(), Vec::new());
        let (mut out_eof, mut err_eof) = (false, false);
        let mut status = None;
        loop {
            // No se reinicia el plazo al salir el hijo ni al recibir datos.
            let poll_ms = if let Some(timeout) = timeout {
                let remaining = timeout.saturating_sub(started.elapsed());
                if remaining.is_zero() {
                    return None;
                }
                remaining.as_millis().clamp(1, 10) as i32
            } else {
                10
            };
            if status.is_none() {
                status = child.try_wait().ok()?;
            }
            if status.is_some() && out_eof && err_eof {
                return Some((
                    status?.code().unwrap_or(1),
                    String::from_utf8(stdout).ok()?,
                    String::from_utf8(stderr).ok()?,
                ));
            }

            // poll también despierta por HUP: todavía puede haber datos que leer.
            // El intervalo acotado permite observar la salida del hijo aunque
            // haya cerrado ambos pipes o los retenga un descendiente inactivo.
            let mut pipes = [
                libc::pollfd {
                    fd: if out_eof { -1 } else { out_pipe.as_raw_fd() },
                    events: libc::POLLIN,
                    revents: 0,
                },
                libc::pollfd {
                    fd: if err_eof { -1 } else { err_pipe.as_raw_fd() },
                    events: libc::POLLIN,
                    revents: 0,
                },
            ];
            if unsafe { libc::poll(pipes.as_mut_ptr(), pipes.len() as libc::nfds_t, poll_ms) } == -1
            {
                if io::Error::last_os_error().kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return None;
            }
            if pipes[0].revents != 0 {
                out_eof = read_capture(&mut out_pipe, &mut stdout).ok()?;
            }
            if pipes[1].revents != 0 {
                err_eof = read_capture(&mut err_pipe, &mut stderr).ok()?;
            }
        }
    })();

    if result.is_none() {
        unsafe {
            libc::kill(-(child.id() as i32), libc::SIGKILL);
        }
        let _ = child.wait();
    }
    result
}

/// Ejecuta un comando al vuelo y recoge el hijo al terminar para no dejar zombis.
pub fn spawn(cmd: &[&str]) -> Option<u32> {
    let Some((program, args)) = cmd.split_first() else {
        eprintln!("churros-services: comando vacío");
        return None;
    };
    if dev::enabled() {
        dev::log_blocked(cmd);
        return None;
    }

    match Command::new(program)
        .args(args)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(mut child) => {
            let pid = child.id();
            std::thread::spawn(move || {
                let _ = child.wait();
            });
            Some(pid)
        }
        Err(error) => {
            eprintln!("churros-services: no se pudo lanzar {:?}: {}", cmd, error);
            None
        }
    }
}

/// Comprueba si un binario existe en el PATH (equivale a shutil.which).
pub fn which(bin: &str) -> bool {
    std::env::var_os("PATH")
        .map(|paths| {
            std::env::split_paths(&paths).any(|d| d.join(bin).is_file())
        })
        .unwrap_or(false)
}

/// Entorno enriquecido para sesiones gráficas Wayland, garantizando
/// XDG_RUNTIME_DIR y WAYLAND_DISPLAY (si existe socket en tiempo de ejecución).
pub fn session_env() -> Vec<(String, String)> {
    let mut env: Vec<(String, String)> = std::env::vars().collect();
    let u = uid();
    let xrd = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| format!("/run/user/{u}"));

    if !env.iter().any(|(k, _)| k == "XDG_RUNTIME_DIR") {
        env.push(("XDG_RUNTIME_DIR".to_string(), xrd.clone()));
    }

    if !env.iter().any(|(k, _)| k == "WAYLAND_DISPLAY") {
        if Path::new(&xrd).is_dir() {
            if let Ok(entries) = std::fs::read_dir(&xrd) {
                let mut valid_socks: Vec<(std::time::SystemTime, String)> = entries
                    .flatten()
                    .filter_map(|e| {
                        let name = e.file_name().to_string_lossy().to_string();
                        if name.starts_with("wayland-") && !name.ends_with(".lock") {
                            let mtime = e
                                .metadata()
                                .and_then(|m| m.modified())
                                .unwrap_or(std::time::SystemTime::UNIX_EPOCH);
                            Some((mtime, name))
                        } else {
                            None
                        }
                    })
                    .collect();
                valid_socks.sort_by(|a, b| b.0.cmp(&a.0));
                if let Some((_, sock)) = valid_socks.first() {
                    env.push(("WAYLAND_DISPLAY".to_string(), sock.clone()));
                }
            }
        }
    }

    env
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assert_run_deadline(script: &str) {
        let started = Instant::now();
        assert!(run(&["sh", "-c", script], 100).is_none());
        assert!(started.elapsed() < Duration::from_secs(1));
    }

    #[test]
    fn test_run_deadline_inherited_stdout() {
        // El shell sale enseguida; solo el descendiente retiene stdout.
        assert_run_deadline("sleep 2 2>/dev/null & printf ready");
    }

    #[test]
    fn test_run_deadline_inherited_stderr() {
        assert_run_deadline("sleep 2 >/dev/null & printf ready >&2");
    }

    #[test]
    fn test_run_deadline_child_with_closed_pipes() {
        assert_run_deadline("exec >/dev/null 2>&1; exec sleep 2");
    }

    #[test]
    fn test_run_deadline_child_with_inherited_pipes() {
        assert_run_deadline("sleep 2 & wait");
    }

    #[test]
    fn test_run_deadline_kills_descendants() {
        let pid_file = std::env::temp_dir().join(format!("churros-run-child-{}", std::process::id()));
        let _ = std::fs::remove_file(&pid_file);
        let script = format!("sleep 30 & echo $! > '{}'; wait", pid_file.display());
        assert!(run(&["sh", "-c", &script], 100).is_none());
        let pid: i32 = std::fs::read_to_string(&pid_file).unwrap().trim().parse().unwrap();
        for _ in 0..100 {
            let alive = unsafe { libc::kill(pid, 0) } == 0;
            let zombie = std::fs::read_to_string(format!("/proc/{pid}/stat"))
                .ok()
                .and_then(|stat| stat.rsplit_once(") ").map(|(_, rest)| rest.starts_with('Z')))
                .unwrap_or(false);
            if !alive || zombie {
                let _ = std::fs::remove_file(pid_file);
                return;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        let _ = std::fs::remove_file(pid_file);
        panic!("el descendiente {pid} sobrevivió al timeout");
    }

    #[test]
    fn test_run_deadline_continuous_output() {
        assert_run_deadline("while :; do printf 'continuous output'; done");
    }

    #[test]
    fn test_run_zero_timeout_captures_descendants() {
        let result = run(
            &[
                "sh",
                "-c",
                "(sleep 0.15; printf late; printf error >&2) & printf early; exit 7",
            ],
            0,
        );
        assert_eq!(result, Some((7, "earlylate".into(), "error".into())));
    }

    #[test]
    fn test_run_large_concurrent_output() {
        let result = run(
            &[
                "sh",
                "-c",
                "(i=0; while [ \"$i\" -lt 8192 ]; do printf 'abcdefghijklmnopqrstuvwxyz012345'; i=$((i+1)); done) & \
                 (i=0; while [ \"$i\" -lt 8192 ]; do printf 'ABCDEFGHIJKLMNOPQRSTUVWXYZ543210' >&2; i=$((i+1)); done) & wait",
            ],
            5000,
        );
        assert_eq!(
            result,
            Some((
                0,
                "abcdefghijklmnopqrstuvwxyz012345".repeat(8192),
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ543210".repeat(8192),
            ))
        );
    }

    #[test]
    fn test_run_invalid_utf8_is_failure() {
        assert!(run(&["sh", "-c", "printf '\\377'"], 1000).is_none());
    }

    #[test]
    fn test_uid_matches_libc() {
        assert_eq!(uid(), unsafe { libc::getuid() });
    }

    #[test]
    fn test_home_path_non_empty() {
        assert!(!home_path().as_os_str().is_empty());
    }

    #[test]
    fn test_home_dir_resolves_valid_path() {
        let home = home_dir();
        assert!(!home.is_empty());
        assert!(home.starts_with('/'));
    }

    #[test]
    fn test_home_dir_getpwuid_matches_uid() {
        let uid = unsafe { libc::getuid() };
        let pwd = unsafe { libc::getpwuid(uid) };
        if !pwd.is_null() {
            let dir = unsafe { CStr::from_ptr((*pwd).pw_dir) };
            if let Ok(s) = dir.to_str() {
                assert!(!s.trim().is_empty());
            }
        }
    }

    #[test]
    fn test_which_existing_and_missing() {
        assert!(which("sh"));
        assert!(!which("nonexistent_binary_xyz_123"));
    }

    #[test]
    fn test_session_env_contains_runtime_dir() {
        let env = session_env();
        assert!(env.iter().any(|(k, _)| k == "XDG_RUNTIME_DIR"));
    }

    #[test]
    fn runtime_state_is_private_and_scoped_to_the_session() {
        let base = std::env::temp_dir().join(format!("churros-runtime-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        std::fs::create_dir(&base).unwrap();
        let dir = runtime_dir_at(&base).unwrap();
        assert_eq!(dir, base.join("churros"));
        assert_eq!(std::fs::metadata(&dir).unwrap().permissions().mode() & 0o777, 0o700);
        std::fs::remove_dir_all(base).unwrap();
    }

    #[test]
    fn runtime_state_rejects_a_symlink() {
        use std::os::unix::fs::symlink;

        let base = std::env::temp_dir().join(format!("churros-runtime-link-test-{}", std::process::id()));
        let target = std::env::temp_dir().join(format!("churros-runtime-target-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&base);
        let _ = std::fs::remove_dir_all(&target);
        std::fs::create_dir(&base).unwrap();
        std::fs::create_dir(&target).unwrap();
        symlink(&target, base.join("churros")).unwrap();
        assert!(runtime_dir_at(&base).is_err());
        std::fs::remove_dir_all(base).unwrap();
        std::fs::remove_dir_all(target).unwrap();
    }

    #[test]
    fn spawned_short_command_is_reaped() {
        let pid = spawn(&["sh", "-c", "exit 0"]).unwrap();
        let proc_path = PathBuf::from(format!("/proc/{pid}"));
        for _ in 0..100 {
            if !proc_path.exists() {
                return;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        panic!("el proceso {pid} terminó pero no fue recogido");
    }
}

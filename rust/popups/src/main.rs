// ==========================================
// churros-popup — popups de ChurrOS (port Rust)
// Reemplaza al wrapper bash churros-popup y a los 6 popups de Python.
// Toggle/reemplazo: mismo comportamiento que el wrapper bash.
// ==========================================

mod audio;
mod battery;
mod bluetooth;
mod brightness;
mod network;
mod popup;
mod power;

use std::fs;
use std::io::Write;
use std::os::fd::{AsRawFd, FromRawFd};
use std::path::PathBuf;
use std::process::exit;

use gtk::prelude::*;

const POPUPS: [&str; 7] = ["network", "audio", "volume", "bluetooth", "power", "brightness", "battery"];
fn pid_file() -> Option<PathBuf> {
    churros_services::runtime_dir().ok().map(|dir| dir.join("popup.pid"))
}

fn name_file() -> Option<PathBuf> {
    churros_services::runtime_dir().ok().map(|dir| dir.join("popup.name"))
}

fn lock_file() -> Option<PathBuf> {
    churros_services::runtime_dir().ok().map(|dir| dir.join("popup.lock"))
}

fn read_file(path: &PathBuf) -> Option<String> {
    fs::read_to_string(path)
        .ok()
        .map(|s| s.trim().to_string())
}

fn process_alive(pid: i32) -> bool {
    if pid <= 0 {
        return false;
    }
    unsafe { libc::kill(pid, 0) == 0 }
}

/// Verifica que el pid del pidfile es realmente un churros-popup antes de
/// matarlo: un pid reutilizado por otro proceso no debe ser objetivo de
/// SIGTERM/SIGKILL.
///
/// Compara el ejecutable real (/proc/<pid>/exe) con el nuestro, no una
/// subcadena de la línea de comandos: antes, cualquier proceso cuya cmdline
/// mencionara "churros-popup" (un `sh -c`, un grep, un editor) pasaba el
/// filtro y recibía SIGKILL si su pid quedaba en un pidfile obsoleto
/// (auditoría V4).
fn process_is_popup(pid: i32) -> bool {
    if !process_alive(pid) {
        return false;
    }
    const DEPLOYED: &str = "/usr/bin/churros-popup";
    let Ok(theirs) = fs::read_link(format!("/proc/{pid}/exe")) else {
        return false;
    };
    if theirs == std::path::Path::new(DEPLOYED) {
        return true;
    }
    // En desarrollo (cargo run, scripts de prueba) el ejecutable es otro: se
    // acepta si es exactamente el nuestro. La ruta resultante lleva el sufijo
    // " (deleted)" cuando el binario se reemplazó, y entonces no coincide.
    std::env::current_exe().is_ok_and(|mine| mine == theirs)
}

fn running_pid() -> Option<i32> {
    let pid_path = pid_file()?;
    let name_path = name_file()?;
    let pid = read_file(&pid_path)?.parse::<i32>().ok()?;
    if process_is_popup(pid) {
        Some(pid)
    } else {
        let _ = fs::remove_file(pid_path);
        let _ = fs::remove_file(name_path);
        None
    }
}

fn current_name() -> Option<String> {
    read_file(&name_file()?)
}

/// Nombre del popup corriendo: solo si su pid sigue vivo.
/// Un pidfile obsoleto (SIGKILL/crash) no debe bloquear el lanzamiento.
fn running_name() -> Option<String> {
    if running_pid().is_some() {
        current_name()
    } else {
        None
    }
}

/// pidfd del proceso (fd estable aunque el PID se reutilice después).
/// pidfd_open = 434 en x86_64, aarch64 e i686 (syscall unificado desde 5.3).
fn open_pidfd(pid: i32) -> Option<std::os::fd::OwnedFd> {
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if fd < 0 {
        return None;
    }
    Some(unsafe { std::os::fd::OwnedFd::from_raw_fd(fd as std::os::fd::RawFd) })
}

/// Señaliza por pidfd: apunta al proceso original aunque el PID se reutilice.
/// pidfd_send_signal = 424. Si el kernel no soporta pidfd, vuelve a kill(2),
/// que es lo que había antes (menos seguro, pero funcional).
fn signal_pidfd(pidfd: Option<&std::os::fd::OwnedFd>, pid: i32, sig: i32) {
    match pidfd {
        Some(fd) => unsafe {
            libc::syscall(libc::SYS_pidfd_send_signal, fd.as_raw_fd(), sig, std::ptr::null::<libc::c_void>(), 0);
        },
        None => unsafe {
            libc::kill(pid, sig);
        },
    }
}

fn kill_process(pid: i32) {
    if !process_is_popup(pid) {
        return;
    }
    let pidfd = open_pidfd(pid);
    signal_pidfd(pidfd.as_ref(), pid, libc::SIGTERM);
    for _ in 0..10 {
        std::thread::sleep(std::time::Duration::from_millis(50));
        if !process_alive(pid) {
            return;
        }
    }
    signal_pidfd(pidfd.as_ref(), pid, libc::SIGKILL);
}

fn kill_popup() {
    if let Some(pid) = running_pid() {
        kill_process(pid);
    }
    if let Some(path) = pid_file() {
        let _ = fs::remove_file(path);
    }
    if let Some(path) = name_file() {
        let _ = fs::remove_file(path);
    }
}

fn launch(name: &str, lock: churros_services::single_instance::InstanceLock) -> i32 {
    let app = gtk::Application::builder()
        .application_id(format!("org.churros.popup.{name}"))
        .build();

    let popup = name.to_string();
    app.connect_activate(move |app| {
        let window = build_window(app, &popup);
        window.present();
    });

    // El lock ya está tomado: este proceso es la instancia viva. Escribir el
    // pid ahora no compite con nadie (antes se comprobaba y luego se escribía,
    // y entre las dos cosas cabía otra instancia).
    let Ok((_, mut pid)) = churros_services::open_runtime_file("popup.pid", false) else {
        eprintln!("churros-popup: no se pudo crear el estado privado de la sesión");
        return 1;
    };
    let Ok((_, mut popup_name)) = churros_services::open_runtime_file("popup.name", false) else {
        eprintln!("churros-popup: no se pudo crear el estado privado de la sesión");
        return 1;
    };
    if writeln!(pid, "{}", std::process::id()).is_err() || writeln!(popup_name, "{name}").is_err() {
        eprintln!("churros-popup: no se pudo guardar el estado de la sesión");
        return 1;
    }
    // El fichero del lock tiene que seguir vivo mientras la ventana exista:
    // soltarlo antes dejaría entrar a otra instancia con esta aún abierta.
    let _lock = lock;

    // run() pasaría std::env::args() a GApplication ("audio" = fichero a abrir).
    // Sin argumentos extra: solo la activación normal.
    app.run_with_args(&[] as &[&str]).into()
}

fn build_window(app: &gtk::Application, name: &str) -> popup::PopupWindow {
    match name {
        "audio" | "volume" => audio::build(app),
        "battery" => battery::build(app),
        "bluetooth" => bluetooth::build(app),
        "brightness" => brightness::build(app),
        "network" => network::build(app),
        "power" => power::build(app),
        _ => unreachable!(),
    }
}

fn main() {
    let name = std::env::args().nth(1).unwrap_or_default();

    if !POPUPS.contains(&name.as_str()) {
        eprintln!("churros-popup: popup desconocido '{name}'");
        eprintln!("Usage: churros-popup {{network|audio|volume|bluetooth|power|brightness|battery}}");
        exit(64);
    }

    // Un solo popup a la vez, decidido por un flock y no leyendo un pidfile:
    // entre leer y escribir cabía otra instancia (auditoría A5). El lock lo
    // libera el kernel si el proceso muere, así que un crash no deja el
    // estado bloqueado.
    let Some(lock_path) = lock_file() else {
        eprintln!("churros-popup: no se pudo resolver el estado privado de la sesión");
        exit(1);
    };
    let held = match churros_services::single_instance::InstanceLock::acquire(&lock_path) {
        Ok(Some(lock)) => lock,
        Ok(None) => {
            // Ya hay un popup vivo. Mismo popup -> toggle off; otro popup ->
            // se apaga para dejar sitio al pedido. Los dos casos matan y salen.
            let same = running_name().as_deref() == Some(name.as_str());
            kill_popup();
            if same {
                clear_state();
                return;
            }
            // Otro popup: el lock se libera cuando el proceso muere, y acaba
            // de recibir SIGTERM. Reintentar con un límite.
            for _ in 0..40 {
                std::thread::sleep(std::time::Duration::from_millis(25));
                match churros_services::single_instance::InstanceLock::acquire(&lock_path) {
                    Ok(Some(lock)) => {
                        let code = launch(&name, lock);
                        clear_state();
                        exit(code);
                    }
                    Ok(None) => continue,
                    Err(_) => break,
                }
            }
            eprintln!("churros-popup: el popup anterior no terminó");
            clear_state();
            return;
        }
        Err(error) => {
            eprintln!("churros-popup: no se pudo tomar el estado de la sesión: {error}");
            exit(1);
        }
    };

    let code = launch(&name, held);
    clear_state();
    exit(code);
}

/// Borra el pid y el nombre del popup. El lock se suelta solo al salir.
fn clear_state() {
    if let Some(path) = pid_file() {
        let _ = fs::remove_file(path);
    }
    if let Some(path) = name_file() {
        let _ = fs::remove_file(path);
    }
}

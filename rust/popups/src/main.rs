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
use std::path::PathBuf;
use std::process::exit;

use gtk::prelude::*;

const POPUPS: [&str; 7] = ["network", "audio", "volume", "bluetooth", "power", "brightness", "battery"];
const PIDDIR: &str = "/tmp/churros";

fn pid_file() -> PathBuf {
    PathBuf::from(PIDDIR).join("popup.pid")
}

fn name_file() -> PathBuf {
    PathBuf::from(PIDDIR).join("popup.name")
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
fn process_is_popup(pid: i32) -> bool {
    if !process_alive(pid) {
        return false;
    }
    match fs::read_to_string(format!("/proc/{pid}/cmdline")) {
        Ok(cmdline) => cmdline.contains("churros-popup"),
        Err(_) => false,
    }
}

fn running_pid() -> Option<i32> {
    let pid = read_file(&pid_file())?.parse::<i32>().ok()?;
    if process_is_popup(pid) {
        Some(pid)
    } else {
        let _ = fs::remove_file(pid_file());
        let _ = fs::remove_file(name_file());
        None
    }
}

fn current_name() -> Option<String> {
    read_file(&name_file())
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

fn kill_process(pid: i32) {
    if !process_is_popup(pid) {
        return;
    }
    unsafe { libc::kill(pid, libc::SIGTERM) };
    for _ in 0..10 {
        std::thread::sleep(std::time::Duration::from_millis(50));
        if !process_alive(pid) {
            return;
        }
    }
    unsafe { libc::kill(pid, libc::SIGKILL) };
}

fn kill_popup() {
    if let Some(pid) = running_pid() {
        kill_process(pid);
    }
    let _ = fs::remove_file(pid_file());
    let _ = fs::remove_file(name_file());
}

fn launch(name: &str) -> i32 {
    let app = gtk::Application::builder()
        .application_id(format!("org.churros.popup.{name}"))
        .build();

    let popup = name.to_string();
    app.connect_activate(move |app| {
        let window = build_window(app, &popup);
        window.present();
    });

    let _ = fs::create_dir_all(PIDDIR);
    let _ = fs::write(pid_file(), std::process::id().to_string());
    let _ = fs::write(name_file(), name);

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

    // Mismo popup corriendo -> apagar (toggle off)
    if running_name().as_deref() == Some(name.as_str()) {
        kill_popup();
        return;
    }

    // Otro popup (o estado viejo) -> matar antes de lanzar
    kill_popup();

    let code = launch(&name);

    // Limpieza al cerrar la ventana
    let _ = fs::remove_file(pid_file());
    let _ = fs::remove_file(name_file());

    exit(code);
}

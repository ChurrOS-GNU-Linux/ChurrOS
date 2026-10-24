// ==========================================
// SystemPage — Información del sistema + acciones
// (equivalente a pages/system.py)
// ==========================================


use std::process::Command;

use crate::services::system::SystemService;
use crate::widgets::group::Group;
use crate::widgets::navigation_row;
use crate::widgets::page::Page;
use crate::widgets::row::Row;

pub fn build(navigator: gtk::Stack) -> Page {
    let page = Page::new(Some(navigator.clone()), "Sistema", Some("Información del sistema"), None);

    // Información
    let mut information = Group::new("Información");

    let version_label = format!("ChurrOS {}", SystemService::version());
    information.add(&Row::new(
        "Versión",
        None,
        Some("system.svg"),
        Some(&version_label),
        None,
        None,
    ));
    information.add(&Row::new(
        "Edición",
        None,
        Some("system.svg"),
        Some(&SystemService::edition()),
        None,
        None,
    ));
    information.add(&Row::new(
        "Hostname",
        None,
        Some("system.svg"),
        Some(&SystemService::hostname()),
        None,
        None,
    ));
    information.add(&Row::new(
        "Sesión",
        None,
        Some("system.svg"),
        Some(&SystemService::session()),
        None,
        None,
    ));

    page.add(information.widget());

    // Software
    let mut software = Group::new("Software");

    software.add(&Row::new(
        "Kernel",
        None,
        Some("applications.svg"),
        Some(&SystemService::kernel()),
        None,
        None,
    ));
    software.add(&Row::new(
        "Base",
        None,
        Some("applications.svg"),
        Some("Arch Linux"),
        None,
        None,
    ));
    software.add(&Row::new(
        "Gestor de paquetes",
        None,
        Some("applications.svg"),
        Some("Pacman"),
        None,
        None,
    ));

    page.add(software.widget());

    // Hardware
    let mut hardware = Group::new("Hardware");

    hardware.add(&Row::new(
        "Procesador",
        None,
        Some("about.svg"),
        Some(&SystemService::cpu()),
        None,
        None,
    ));
    hardware.add(&Row::new(
        "Memoria",
        None,
        Some("about.svg"),
        Some(&SystemService::memory()),
        None,
        None,
    ));
    hardware.add(&Row::new(
        "Gráficos",
        None,
        Some("display.svg"),
        Some(&SystemService::gpu()),
        None,
        None,
    ));
    let gpu_driver = SystemService::gpu_driver();
    if gpu_driver != "Desconocido" {
        hardware.add(&Row::new(
            "Controlador gráfico",
            None,
            Some("display.svg"),
            Some(&gpu_driver),
            None,
            None,
        ));
    }

    page.add(hardware.widget());

    // Acciones
    let mut actions = Group::new("Acciones");

    actions.add(&Row::new(
        "Actualizar sistema",
        Some("Ejecuta pacman -Syu en una terminal"),
        Some("system.svg"),
        None,
        None,
        Some(Box::new(|_| update_system())),
    ));

    actions.add(&navigation_row::new(
        navigator.clone(),
        "Copia de seguridad",
        "backup.svg",
        "backup",
        Some("Exportar, importar o restablecer la configuracion"),
    ));

    actions.add(&navigation_row::new(
        navigator.clone(),
        "Logs de Niri",
        "logs.svg",
        "logs",
        Some("Registros del compositor y validacion de config"),
    ));

    page.add(actions.widget());

    page
}

fn update_system() {
    let _ = Command::new("foot")
        .args(["-e", "sudo", "pacman", "-Syu"])
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn();
}

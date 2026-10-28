// Servicio de energía/sesión (equivalente a services/power.py)

use crate::{run, spawn};

fn has_swap() -> bool {
    match run(&["swapon", "--show", "--noheadings"], 2000) {
        Some((_, out, _)) => !out.trim().is_empty(),
        None => false,
    }
}

fn current_desktop() -> String {
    std::env::var("XDG_CURRENT_DESKTOP")
        .or_else(|_| std::env::var("XDG_SESSION_DESKTOP"))
        .or_else(|_| std::env::var("DESKTOP_SESSION"))
        .unwrap_or_default()
        .to_lowercase()
}

fn current_uid() -> String {
    crate::uid().to_string()
}

pub fn lock() {
    let desktop = current_desktop();
    if desktop.contains("xfce") {
        spawn(&["xflock4"]);
    } else {
        spawn(&["loginctl", "lock-session"]);
    }
}

pub fn logout() {
    let desktop = current_desktop();
    if desktop.contains("niri") {
        spawn(&["niri", "msg", "action", "quit"]);
    } else if desktop.contains("xfce") {
        spawn(&["xfce4-session-logout", "--logout", "--fast"]);
    } else if desktop.contains("hyprland") {
        spawn(&["hyprctl", "dispatch", "exit"]);
    } else if desktop.contains("sway") {
        spawn(&["swaymsg", "exit"]);
    } else {
        let uid = current_uid();
        if !uid.is_empty() {
            spawn(&["loginctl", "terminate-user", &uid]);
        }
    }
}

pub fn suspend() {
    spawn(&["systemctl", "suspend"]);
}

pub fn can_hibernate() -> bool {
    has_swap()
}

pub fn hibernate() {
    spawn(&["systemctl", "hibernate"]);
}

pub fn restart() {
    spawn(&["systemctl", "reboot"]);
}

pub fn shutdown() {
    spawn(&["systemctl", "poweroff"]);
}

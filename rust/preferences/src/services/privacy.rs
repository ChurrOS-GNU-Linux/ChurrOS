// ==========================================
// PrivacyService — permisos, firewall (ufw) y telemetria
// (equivalente a services/privacy.py)
// ==========================================

use serde_json::json;
use std::process::Command;

use crate::services::settings;

pub struct PrivacyService;

fn getuid() -> u32 {
    Command::new("id")
        .arg("-u")
        .output()
        .ok()
        .and_then(|o| String::from_utf8_lossy(&o.stdout).trim().parse().ok())
        .unwrap_or(1000) // fallo → no-root, nunca intentar escritura privilegiada
}

impl PrivacyService {
    pub fn location() -> bool {
        settings::get_bool("privacy.location", false)
    }

    pub fn set_location(value: bool) {
        settings::set("privacy.location", json!(value));
    }

    pub fn camera() -> bool {
        settings::get_bool("privacy.camera", true)
    }

    pub fn set_camera(value: bool) {
        settings::set("privacy.camera", json!(value));
    }

    pub fn microphone() -> bool {
        settings::get_bool("privacy.microphone", true)
    }

    pub fn set_microphone(value: bool) {
        settings::set("privacy.microphone", json!(value));
    }

    pub fn telemetry() -> bool {
        settings::get_bool("privacy.telemetry", false)
    }

    pub fn set_telemetry(value: bool) {
        settings::set("privacy.telemetry", json!(value));
    }

    /// ¿Está activo el servicio ufw? (systemctl is-active --quiet)
    pub fn firewall() -> bool {
        Command::new("systemctl")
            .args(["is-active", "--quiet", "ufw"])
            .status()
            .map(|s| s.success())
            .unwrap_or(false)
    }

    /// Activa/desactiva ufw (con pkexec si no somos root).
    pub fn set_firewall(value: bool) -> bool {
        let action = if value { "enable" } else { "disable" };
        let ufw_action = if value { "enable" } else { "disable" };

        let (mut cmd_systemctl, mut cmd_ufw) = if getuid() == 0 {
            (
                Command::new("systemctl"),
                Command::new("ufw"),
            )
        } else {
            (Command::new("pkexec"), Command::new("pkexec"))
        };
        let systemctl_ok = cmd_systemctl
            .args(if getuid() == 0 {
                vec![action, "ufw.service"]
            } else {
                vec!["systemctl", action, "ufw.service"]
            })
            .status()
            .map(|s| s.success())
            .unwrap_or(false);
        let ufw_ok = cmd_ufw
            .args(if getuid() == 0 {
                vec!["--force", ufw_action]
            } else {
                vec!["ufw", "--force", ufw_action]
            })
            .status()
            .map(|s| s.success())
            .unwrap_or(false);

        systemctl_ok && ufw_ok
    }

    #[allow(dead_code)] // portado por paridad; sin uso en las páginas actuales
    pub fn screen_lock() -> bool {
        settings::get_bool("privacy.screen_lock", true)
    }

    #[allow(dead_code)] // portado por paridad; sin uso en las páginas actuales
    pub fn history() -> bool {
        settings::get_bool("privacy.history", true)
    }

    #[allow(dead_code)] // portado por paridad; sin uso en las páginas actuales
    pub fn crash_reports() -> bool {
        settings::get_bool("privacy.crash_reports", false)
    }
}

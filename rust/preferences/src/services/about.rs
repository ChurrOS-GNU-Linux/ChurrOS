// ==========================================
// AboutService (equivalente a services/about.py)
// ==========================================

pub struct AboutService;

impl AboutService {
    pub fn distro() -> &'static str {
        "ChurrOS"
    }

    pub fn version() -> &'static str {
        churros_services::version::distro()
    }

    pub fn edition() -> &'static str {
        "Developer Preview"
    }

    pub fn kernel() -> String {
        std::fs::read_to_string("/proc/sys/kernel/osrelease")
            .map(|s| s.trim().to_string())
            .unwrap_or_else(|_| "Desconocido".to_string())
    }

    pub fn base() -> &'static str {
        "Arch Linux"
    }

    pub fn session() -> String {
        std::env::var("XDG_CURRENT_DESKTOP").unwrap_or_else(|_| "Desconocida".to_string())
    }

    pub fn developer() -> &'static str {
        "Equipo ChurrOS"
    }

    pub fn license() -> &'static str {
        "GPL-3.0-only"
    }
}

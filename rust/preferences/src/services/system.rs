// ==========================================
// SystemService (equivalente a services/system.py)
// ==========================================

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::OnceLock;

static CPU_CACHE: OnceLock<String> = OnceLock::new();
static MEMORY_CACHE: OnceLock<String> = OnceLock::new();
static GPU_CACHE: OnceLock<String> = OnceLock::new();
static GPU_DRIVER_CACHE: OnceLock<String> = OnceLock::new();
static EDITION_CACHE: OnceLock<String> = OnceLock::new();
static HOSTNAME_CACHE: OnceLock<String> = OnceLock::new();
static KERNEL_CACHE: OnceLock<String> = OnceLock::new();

pub struct SystemService;

impl SystemService {
    pub fn distro() -> &'static str {
        "ChurrOS"
    }

    pub fn version() -> &'static str {
        churros_services::version::distro()
    }

    /// Edición instalada, legible: "Niri Edition", "XFCE Edition"...
    pub fn edition() -> String {
        EDITION_CACHE
            .get_or_init(|| format_edition(&churros_services::version::edition()))
            .clone()
    }

    pub fn session() -> String {
        std::env::var("XDG_CURRENT_DESKTOP").unwrap_or_else(|_| "Desconocida".to_string())
    }

    pub fn hostname() -> String {
        HOSTNAME_CACHE
            .get_or_init(|| {
                std::fs::read_to_string("/proc/sys/kernel/hostname")
                    .map(|s| s.trim().to_string())
                    .unwrap_or_else(|_| "Desconocido".to_string())
            })
            .clone()
    }

    pub fn username() -> String {
        std::env::var("USER").unwrap_or_else(|_| "Desconocido".to_string())
    }

    pub fn kernel() -> String {
        KERNEL_CACHE
            .get_or_init(|| {
                std::fs::read_to_string("/proc/sys/kernel/osrelease")
                    .map(|s| s.trim().to_string())
                    .unwrap_or_else(|_| "Desconocido".to_string())
            })
            .clone()
    }

    pub fn package_manager() -> &'static str {
        "Pacman"
    }

    pub fn base() -> &'static str {
        "Arch Linux"
    }

    pub fn cpu() -> String {
        CPU_CACHE
            .get_or_init(|| {
                if let Ok(content) = std::fs::read_to_string("/proc/cpuinfo") {
                    for line in content.lines() {
                        if let Some(rest) = line.strip_prefix("model name") {
                            if let Some((_, value)) = rest.split_once(':') {
                                return value.trim().to_string();
                            }
                        }
                    }
                }
                "Desconocido".to_string()
            })
            .clone()
    }

    pub fn memory() -> String {
        MEMORY_CACHE
            .get_or_init(|| {
                if let Ok(content) = std::fs::read_to_string("/proc/meminfo") {
                    for line in content.lines() {
                        if let Some(rest) = line.strip_prefix("MemTotal:") {
                            if let Some(kib) = rest.split_whitespace().next().and_then(|v| v.parse::<f64>().ok()) {
                                return format!("{:.1} GB", kib / 1024.0 / 1024.0);
                            }
                        }
                    }
                }
                "Desconocida".to_string()
            })
            .clone()
    }

    /// Tarjetas gráficas: nombre desde sysfs + pci.ids, o `lspci` si no hay sysfs.
    pub fn gpu() -> String {
        GPU_CACHE
            .get_or_init(|| {
                let names: Vec<String> = drm_devices().iter().filter_map(|d| gpu_name(d)).collect();
                if !names.is_empty() {
                    return dedup_join(names);
                }
                gpu_from_lspci().unwrap_or_else(|| "Desconocida".to_string())
            })
            .clone()
    }

    /// Controlador del kernel activo (i915, amdgpu, nvidia...) o "Desconocido".
    pub fn gpu_driver() -> String {
        GPU_DRIVER_CACHE
            .get_or_init(|| {
                let drivers: Vec<String> = drm_devices().iter().filter_map(|d| driver_name(d)).collect();
                if drivers.is_empty() {
                    "Desconocido".to_string()
                } else {
                    dedup_join(drivers)
                }
            })
            .clone()
    }
}

fn format_edition(raw: &str) -> String {
    let raw = raw.trim();
    if raw.is_empty() {
        return "Desconocida".to_string();
    }
    let words: Vec<String> = raw
        .split(['-', '_', ' '])
        .filter(|w| !w.is_empty() && !w.eq_ignore_ascii_case("edition"))
        .map(|w| match w.to_lowercase().as_str() {
            "xfce" | "kde" | "gnome" | "lxqt" => w.to_uppercase(),
            _ => {
                let mut c = w.chars();
                c.next()
                    .map(|f| f.to_uppercase().chain(c.flat_map(|x| x.to_lowercase())).collect())
                    .unwrap_or_default()
            }
        })
        .collect();
    format!("{} Edition", words.join(" "))
}

fn dedup_join(mut items: Vec<String>) -> String {
    let mut seen = std::collections::HashSet::new();
    items.retain(|i| seen.insert(i.clone()));
    items.join(" + ")
}

/// `device/` de cada /sys/class/drm/cardN (sin conectores como card1-eDP-1),
/// sin repetir el mismo dispositivo.
fn drm_devices() -> Vec<PathBuf> {
    let Ok(read) = std::fs::read_dir("/sys/class/drm") else {
        return Vec::new();
    };
    let mut cards: Vec<(u32, PathBuf)> = read
        .flatten()
        .filter_map(|e| {
            let name = e.file_name().to_string_lossy().into_owned();
            let n = name.strip_prefix("card")?.parse::<u32>().ok()?;
            Some((n, e.path().join("device")))
        })
        .collect();
    cards.sort();
    let mut seen = std::collections::HashSet::new();
    cards
        .into_iter()
        .filter_map(|(_, dev)| {
            let real = std::fs::canonicalize(&dev).ok()?;
            seen.insert(real.clone()).then_some(real)
        })
        .collect()
}

fn driver_name(device: &Path) -> Option<String> {
    let link = std::fs::read_link(device.join("driver")).ok()?;
    Some(link.file_name()?.to_string_lossy().into_owned())
}

fn read_hex(path: PathBuf) -> Option<String> {
    let s = std::fs::read_to_string(path).ok()?;
    Some(s.trim().trim_start_matches("0x").to_lowercase())
}

fn gpu_name(device: &Path) -> Option<String> {
    if let (Some(vendor), Some(dev)) = (read_hex(device.join("vendor")), read_hex(device.join("device"))) {
        if let Some((v, d)) = pci_ids_lookup(&vendor, &dev) {
            return Some(clean_gpu_name(&v, d.as_deref()));
        }
        return Some(format!("{} [{vendor}:{dev}]", short_vendor(&vendor_fallback(&vendor))));
    }
    // Sin PCI (ARM, SoC): el nombre del nodo del device tree
    let uevent = std::fs::read_to_string(device.join("uevent")).ok()?;
    uevent
        .lines()
        .find_map(|l| l.strip_prefix("OF_COMPATIBLE_0="))
        .map(|s| s.trim().to_string())
}

fn vendor_fallback(vendor: &str) -> String {
    match vendor {
        "8086" => "Intel",
        "1002" => "AMD",
        "10de" => "NVIDIA",
        "1af4" => "Virtio",
        "15ad" => "VMware",
        "80ee" => "VirtualBox",
        "1234" => "QEMU",
        _ => "GPU",
    }
    .to_string()
}

/// Busca vendor/device en pci.ids (hwdata).
fn pci_ids_lookup(vendor: &str, device: &str) -> Option<(String, Option<String>)> {
    let text = ["/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids"]
        .iter()
        .find_map(|p| std::fs::read_to_string(p).ok())?;
    let mut vendor_name = None;
    for line in text.lines() {
        if line.starts_with('#') || line.is_empty() {
            continue;
        }
        if !line.starts_with('\t') {
            if vendor_name.is_some() {
                break; // fin del bloque del fabricante
            }
            if let Some((id, name)) = line.split_once("  ")
                && id.eq_ignore_ascii_case(vendor)
            {
                vendor_name = Some(name.trim().to_string());
            }
        } else if vendor_name.is_some()
            && !line.starts_with("\t\t")
            && let Some((id, name)) = line[1..].split_once("  ")
            && id.eq_ignore_ascii_case(device)
        {
            return Some((vendor_name?, Some(name.trim().to_string())));
        }
    }
    vendor_name.map(|v| (v, None))
}

fn short_vendor(name: &str) -> String {
    let lower = name.to_lowercase();
    if lower.contains("intel") {
        "Intel".into()
    } else if lower.contains("advanced micro devices") || lower.contains("amd") {
        "AMD".into()
    } else if lower.contains("nvidia") {
        "NVIDIA".into()
    } else {
        name.trim_end_matches(", Inc.")
            .trim_end_matches(" Inc.")
            .trim_end_matches(" Corporation")
            .trim_end_matches(" Corp.")
            .to_string()
    }
}

/// "Intel Corporation" + "HD Graphics 620" -> "Intel HD Graphics 620";
/// "GA106 [GeForce RTX 3060]" -> "NVIDIA GeForce RTX 3060".
fn clean_gpu_name(vendor: &str, device: Option<&str>) -> String {
    let vendor = short_vendor(vendor);
    let Some(device) = device else { return vendor };
    let model = match (device.find('['), device.rfind(']')) {
        (Some(a), Some(b)) if b > a + 1 => &device[a + 1..b],
        _ => device,
    };
    if model.to_lowercase().starts_with(&vendor.to_lowercase()) {
        model.to_string()
    } else {
        format!("{vendor} {model}")
    }
}

fn gpu_from_lspci() -> Option<String> {
    let output = Command::new("lspci").output().ok()?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let names: Vec<String> = stdout
        .lines()
        .filter(|l| l.contains("VGA") || l.contains("3D controller") || l.contains("Display controller"))
        .filter_map(|l| l.split_once(": ").map(|(_, d)| d))
        .map(|d| d.split(" (rev ").next().unwrap_or(d).trim().to_string())
        .collect();
    (!names.is_empty()).then(|| dedup_join(names))
}


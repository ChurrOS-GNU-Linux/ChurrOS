// ==========================================
// DisplayService
// (equivalente a services/display.py + backends/niri.py + backends/hyprland.py)
// ==========================================

use std::fs;
use std::io::Read;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// Backend._run: subprocess.run(check=True) -> stdout, "" si falla.
fn run_checked(args: &[&str]) -> String {
    let mut child = match Command::new(args[0])
        .args(&args[1..])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
    {
        Ok(c) => c,
        Err(_) => return String::new(),
    };

    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break st,
            Ok(None) => {}
            Err(_) => {
                let _ = child.kill();
                return String::new();
            }
        }
        if start.elapsed() > Duration::from_secs(2) {
            let _ = child.kill();
            let _ = child.wait();
            return String::new();
        }
        std::thread::sleep(Duration::from_millis(20));
    };

    if !status.success() {
        return String::new();
    }
    let mut buf = String::new();
    if let Some(mut out) = child.stdout.take() {
        let _ = out.read_to_string(&mut buf);
    }
    buf
}

/// Comandos de cambio (niri msg / hyprctl). status() evita zombis.
fn run_no_output(args: &[&str]) {
    let _ = Command::new(args[0])
        .args(&args[1..])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

// ---------------------------------------------------------------- modelos

/// Un modo de vídeo (models/display_mode.py)
#[derive(Clone)]
pub struct DisplayMode {
    pub width: i64,
    pub height: i64,
    pub refresh: f64,
    pub current: bool,
    pub preferred: bool,
}

impl DisplayMode {
    /// label: "1920 × 1080 @ 60 Hz"
    pub fn label(&self) -> String {
        format!("{} × {} @ {:.0} Hz", self.width, self.height, self.refresh)
    }

    /// mode: "1920x1080@60.000"
    pub fn mode(&self) -> String {
        format!("{}x{}@{:.3}", self.width, self.height, self.refresh)
    }
}

/// Monitor (models/monitor.py)
#[derive(Clone)]
pub struct Monitor {
    pub name: String,
    pub description: String,
    pub width: i64,
    pub height: i64,
    pub refresh: f64,
    pub scale: f64,
    pub transform: String,
    pub focused: bool,
    pub modes: Vec<DisplayMode>,
    pub vrr: bool,
}

impl Monitor {
    /// scale_percent: int(scale * 100)
    pub fn scale_percent(&self) -> i64 {
        (self.scale * 100.0) as i64
    }

    /// rotation: mapea transform a etiqueta ("Normal", "90°", ...)
    pub fn rotation(&self) -> String {
        match self.transform.as_str() {
            "normal" => "Normal".to_string(),
            "90" => "90°".to_string(),
            "180" => "180°".to_string(),
            "270" => "270°".to_string(),
            "flipped" => "Volteado".to_string(),
            "flipped-90" => "Volteado 90°".to_string(),
            "flipped-180" => "Volteado 180°".to_string(),
            "flipped-270" => "Volteado 270°".to_string(),
            _ => "Normal".to_string(),
        }
    }
}

// ---------------------------------------------------------------- backend

#[derive(Clone, Copy, PartialEq)]
enum DisplayBackend {
    Niri,
    Hyprland,
}

#[derive(Clone)]
pub struct DisplayService {
    backend: DisplayBackend,
}

impl DisplayService {
    /// Selecciona backend según XDG_CURRENT_DESKTOP / XDG_SESSION_DESKTOP /
    /// DESKTOP_SESSION (igual que DisplayService.backend() del Python).
    pub fn new() -> Self {
        let desktop = std::env::var("XDG_CURRENT_DESKTOP")
            .or_else(|_| std::env::var("XDG_SESSION_DESKTOP"))
            .or_else(|_| std::env::var("DESKTOP_SESSION"))
            .unwrap_or_default()
            .to_lowercase();
        let backend = if desktop.contains("niri") {
            DisplayBackend::Niri
        } else {
            DisplayBackend::Hyprland
        };
        Self { backend }
    }

    pub fn supports_resolution(&self) -> bool {
        self.backend == DisplayBackend::Niri
    }

    pub fn supports_vrr(&self) -> bool {
        self.backend == DisplayBackend::Niri
    }

    /// Monitor actual: niri -> el primero; hyprland -> el enfocado.
    pub fn current_monitor(&self) -> Option<Monitor> {
        match self.backend {
            DisplayBackend::Niri => niri_monitors().into_iter().next(),
            DisplayBackend::Hyprland => {
                hyprland_monitors().into_iter().find(|m| m.focused)
            }
        }
    }

    pub fn set_resolution(&self, monitor: &Monitor, mode: &DisplayMode) {
        match self.backend {
            DisplayBackend::Niri => {
                run_no_output(&[
                    "niri",
                    "msg",
                    "output",
                    &monitor.name,
                    "mode",
                    &mode.mode(),
                ]);
            }
            DisplayBackend::Hyprland => {}
        }
    }

    pub fn set_scale(&self, monitor: &Monitor, scale: f64) {
        match self.backend {
            DisplayBackend::Niri => {
                let s = scale.to_string();
                run_no_output(&["niri", "msg", "output", &monitor.name, "scale", &s]);
            }
            DisplayBackend::Hyprland => {
                let arg = format!("{},preferred,{}", monitor.name, scale);
                run_no_output(&["hyprctl", "keyword", "monitor", &arg]);
            }
        }
    }

    pub fn set_rotation(&self, monitor: &Monitor, rotation: &str) {
        match self.backend {
            DisplayBackend::Niri => {
                run_no_output(&[
                    "niri",
                    "msg",
                    "output",
                    &monitor.name,
                    "transform",
                    rotation,
                ]);
            }
            DisplayBackend::Hyprland => {
                let arg = format!("{},preferred,auto,{}", monitor.name, rotation);
                run_no_output(&["hyprctl", "keyword", "monitor", &arg]);
            }
        }
    }

    pub fn set_vrr(&self, monitor: &Monitor, enabled: bool) {
        match self.backend {
            DisplayBackend::Niri => {
                let flag = if enabled { "on" } else { "off" };
                run_no_output(&["niri", "msg", "output", &monitor.name, "vrr", flag]);
            }
            DisplayBackend::Hyprland => {}
        }
    }

    pub fn has_brightness() -> bool {
        Path::new("/sys/class/backlight").is_dir()
    }

    /// Brillo actual en % (current/max_brightness * 100); 100 si falla.
    pub fn brightness() -> f64 {
        let Some(device) = first_backlight_device() else {
            return 100.0;
        };
        let current = fs::read_to_string(format!("/sys/class/backlight/{device}/brightness"))
            .ok()
            .and_then(|s| s.trim().parse::<f64>().ok());
        let maximum = fs::read_to_string(format!("/sys/class/backlight/{device}/max_brightness"))
            .ok()
            .and_then(|s| s.trim().parse::<f64>().ok());
        match (current, maximum) {
            (Some(c), Some(m)) if m > 0.0 => (c / m) * 100.0,
            _ => 100.0,
        }
    }

    pub fn set_brightness(&self, value: f64) {
        match self.backend {
            DisplayBackend::Niri => {
                let v = format!("{}%", value as i64);
                run_no_output(&["brightnessctl", "set", &v]);
            }
            DisplayBackend::Hyprland => {
                // hyprland.py: brightness = int(max * value / 100); brightnessctl set N
                let Some(device) = first_backlight_device() else {
                    return;
                };
                let maximum = fs::read_to_string(format!(
                    "/sys/class/backlight/{device}/max_brightness"
                ))
                .ok()
                .and_then(|s| s.trim().parse::<f64>().ok());
                if let Some(max) = maximum {
                    let brightness = (max * value / 100.0) as i64;
                    let b = brightness.to_string();
                    run_no_output(&["brightnessctl", "set", &b]);
                }
            }
        }
    }
}

impl Default for DisplayService {
    fn default() -> Self {
        Self::new()
    }
}

// ---------------------------------------------------------------- parsers

fn first_backlight_device() -> Option<String> {
    let entries = fs::read_dir("/sys/class/backlight").ok()?;
    if let Some(entry) = entries.flatten().next() {
        return Some(entry.file_name().to_string_lossy().to_string());
    }
    None
}

/// `Output "desc" (nombre):` -> desc = texto entre comillas; nombre = entre paréntesis
fn second_quoted(s: &str) -> Option<String> {
    let mut it = s.split('"');
    it.next()?;
    it.next().map(|x| x.to_string())
}

fn between_parens(s: &str) -> Option<String> {
    // El último paréntesis: la descripción entre comillas puede contener
    // paréntesis propios (`Output "PNP(XXX)" (HDMI-A-2)`); el nombre del
    // monitor es siempre el paréntesis final de la línea.
    let start = s.rfind('(')?;
    let end = s.rfind(')')?;
    if end < start {
        return None;
    }
    Some(s[start + 1..end].to_string())
}

/// Parsea "1920x1080 @ 60.000" (espacios opcionales alrededor del @):
/// equivalente a las regex `(\d+)x(\d+) @ ([0-9.]+)` y `(\d+)x(\d+)@([0-9.]+)`.
fn parse_wxh_at(s: &str) -> Option<(i64, i64, f64)> {
    let b = s.as_bytes();
    let n = b.len();

    let mut i = 0;
    while i < n && !b[i].is_ascii_digit() {
        i += 1;
    }
    let wstart = i;
    while i < n && b[i].is_ascii_digit() {
        i += 1;
    }
    if wstart == i {
        return None;
    }
    let w = s[wstart..i].parse::<i64>().ok()?;

    if i >= n || b[i] != b'x' {
        return None;
    }
    i += 1;
    let hstart = i;
    while i < n && b[i].is_ascii_digit() {
        i += 1;
    }
    if hstart == i {
        return None;
    }
    let h = s[hstart..i].parse::<i64>().ok()?;

    while i < n && b[i].is_ascii_whitespace() {
        i += 1;
    }
    if i >= n || b[i] != b'@' {
        return None;
    }
    i += 1;
    while i < n && b[i].is_ascii_whitespace() {
        i += 1;
    }
    let fstart = i;
    while i < n && (b[i].is_ascii_digit() || b[i] == b'.') {
        i += 1;
    }
    if fstart == i {
        return None;
    }
    let r = s[fstart..i].parse::<f64>().ok()?;
    Some((w, h, r))
}

/// NiriBackend.monitors(): parsea `niri msg outputs`.
fn niri_monitors() -> Vec<Monitor> {
    let text = run_checked(&["niri", "msg", "outputs"]);

    let mut monitors: Vec<Monitor> = Vec::new();
    let mut current: Option<Monitor> = None;
    let mut modes: Vec<DisplayMode> = Vec::new();

    for raw in text.lines() {
        let line = raw.trim_end();

        if line.starts_with("Output") {
            if let Some(mut m) = current.take() {
                m.modes = std::mem::take(&mut modes);
                monitors.push(m);
            }
            let name = between_parens(line).unwrap_or_default();
            let description = second_quoted(line).unwrap_or_default();
            current = Some(Monitor {
                name,
                description,
                width: 0,
                height: 0,
                refresh: 60.0,
                scale: 1.0,
                transform: "normal".to_string(),
                focused: true,
                modes: Vec::new(),
                vrr: false,
            });
            continue;
        }

        let Some(m) = current.as_mut() else {
            continue;
        };

        if line.contains("Current mode:") {
            if let Some((w, h, r)) = parse_wxh_at(line) {
                m.width = w;
                m.height = h;
                m.refresh = r;
            }
            continue;
        }
        if line.contains("Scale:") {
            if let Some((_, v)) = line.split_once(':') {
                if let Ok(s) = v.trim().parse::<f64>() {
                    m.scale = s;
                }
            }
            continue;
        }
        if line.contains("Transform:") {
            if let Some((_, v)) = line.split_once(':') {
                m.transform = v.trim().to_string();
            }
            continue;
        }
        if line.contains("Variable refresh rate:") {
            // "not supported" también contiene "supported"
            m.vrr = line.contains("supported") && !line.contains("not supported");
            continue;
        }

        // modo: "  1920x1080@60.000 (current preferred)"
        if let Some((w, h, r)) = parse_wxh_at(line.trim()) {
            modes.push(DisplayMode {
                width: w,
                height: h,
                refresh: r,
                current: line.contains("current"),
                preferred: line.contains("preferred"),
            });
        }
    }

    if let Some(mut m) = current {
        m.modes = modes;
        monitors.push(m);
    }
    monitors
}

/// HyprlandBackend.monitors(): parsea `hyprctl monitors -j` (JSON).
fn hyprland_monitors() -> Vec<Monitor> {
    let text = run_checked(&["hyprctl", "monitors", "-j"]);
    let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) else {
        return Vec::new();
    };
    let Some(entries) = value.as_array() else {
        return Vec::new();
    };

    let mut monitors = Vec::new();
    for output in entries {
        let name = output.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string();
        let description = output
            .get("description")
            .and_then(|v| v.as_str())
            .unwrap_or(&name)
            .to_string();
        let width = output.get("width").and_then(|v| v.as_i64()).unwrap_or(0);
        let height = output.get("height").and_then(|v| v.as_i64()).unwrap_or(0);
        let refresh = output
            .get("refreshRate")
            .and_then(|v| v.as_f64())
            .unwrap_or(60.0);
        let scale = output.get("scale").and_then(|v| v.as_f64()).unwrap_or(1.0);
        let transform = output
            .get("transform")
            .map(|v| v.to_string())
            .unwrap_or_else(|| "0".to_string());
        let focused = output.get("focused").and_then(|v| v.as_bool()).unwrap_or(false);
        let vrr = output.get("vrr").and_then(|v| v.as_bool()).unwrap_or(false);

        let mode = DisplayMode {
            width,
            height,
            refresh,
            current: true,
            preferred: true,
        };

        monitors.push(Monitor {
            name,
            description,
            width,
            height,
            refresh,
            scale,
            transform,
            focused,
            modes: vec![mode],
            vrr,
        });
    }
    monitors
}

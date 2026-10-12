// ==========================================
// AudioService (equivalente a services/audio.py + backends/pipewire.py)
// ==========================================

use std::io::Read;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

/// PipeWireBackend._run: subprocess.run(check=True) -> stdout, "" si falla.
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

/// Comandos de cambio: subprocess.run sin captura. status() evita zombis.
fn run_no_output(args: &[&str]) {
    let _ = Command::new(args[0])
        .args(&args[1..])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

fn which(cmd: &str) -> bool {
    std::env::var_os("PATH").map_or(false, |paths| {
        std::env::split_paths(&paths).any(|dir| dir.join(cmd).is_file())
    })
}

/// Dispositivo de audio (models/audio_device.py)
#[derive(Clone)]
pub struct AudioDevice {
    pub id: u32,
    pub name: String,
    pub default: bool,
}

pub struct AudioService;

impl AudioService {
    /// True si wpctl (PipeWire) está disponible.
    pub fn available() -> bool {
        which("wpctl")
    }

    /// Sinks (salidas).
    pub fn outputs() -> Vec<AudioDevice> {
        devices("Sinks")
    }

    /// Sources (entradas).
    pub fn inputs() -> Vec<AudioDevice> {
        devices("Sources")
    }

    /// Volumen de salida (0-100).
    pub fn output_volume() -> f64 {
        volume("@DEFAULT_AUDIO_SINK@")
    }

    /// Volumen de entrada (0-100).
    pub fn input_volume() -> f64 {
        volume("@DEFAULT_AUDIO_SOURCE@")
    }

    pub fn output_muted() -> bool {
        muted("@DEFAULT_AUDIO_SINK@")
    }

    pub fn input_muted() -> bool {
        muted("@DEFAULT_AUDIO_SOURCE@")
    }

    pub fn set_output_volume(value: f64) {
        let v = format!("{}%", value as i64);
        run_no_output(&["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", &v]);
    }

    pub fn set_input_volume(value: f64) {
        let v = format!("{}%", value as i64);
        run_no_output(&["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", &v]);
    }

    pub fn set_output_mute(muted: bool) {
        let flag = if muted { "1" } else { "0" };
        run_no_output(&["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", flag]);
    }

    pub fn set_input_mute(muted: bool) {
        let flag = if muted { "1" } else { "0" };
        run_no_output(&["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", flag]);
    }

    /// Cambia el dispositivo por defecto (wpctl set-default <id>).
    pub fn set_output(device: &AudioDevice) {
        let id = device.id.to_string();
        run_no_output(&["wpctl", "set-default", &id]);
    }

    pub fn set_input(device: &AudioDevice) {
        let id = device.id.to_string();
        run_no_output(&["wpctl", "set-default", &id]);
    }
}

/// Parsea la sección "Sinks"/"Sources" de `wpctl status`.
/// (equivalente a PipeWireBackend._devices)
fn devices(section: &str) -> Vec<AudioDevice> {
    let text = run_checked(&["wpctl", "status"]);
    let mut result = Vec::new();
    let mut inside = false;

    for line in text.lines() {
        if line.contains(section) {
            inside = true;
            continue;
        }
        if !inside {
            continue;
        }
        if line.trim().is_empty() {
            break;
        }

        // wpctl antepone caracteres de árbol (│ ├ └ ─) al margen; el trim
        // normal no los elimina y el parser fallaba con PipeWire moderno.
        let t = line.trim_start_matches(['│', '├', '└', '─', ' ', '\t']);
        let (is_default, rest) = match t.strip_prefix('*') {
            Some(r) => (true, r.trim_start()),
            None => (false, t.trim_start()),
        };

        // regex Python: (\*?)\s*([0-9]+)\.\s+(.*)
        let digits: String = rest
            .chars()
            .take_while(|c| c.is_ascii_digit())
            .collect();
        if digits.is_empty() {
            continue;
        }
        let after_digits = &rest[digits.len()..];
        let Some(after_dot) = after_digits.strip_prefix('.') else {
            continue;
        };
        // \s+ obligatorio tras el punto (paridad con la regex)
        if !after_dot.starts_with(char::is_whitespace) {
            continue;
        }
        let mut name = after_dot.trim_start();
        // Quitar el sufijo "[vol: ...]" (mismo comportamiento que el
        // crate churros-services de los popups).
        if let Some(idx) = name.find(" [vol:") {
            name = &name[..idx];
        }
        let name = name.trim_end();
        if name.is_empty() {
            continue;
        }
        let id = digits.parse::<u32>().unwrap_or(0);
        result.push(AudioDevice {
            id,
            name: name.to_string(),
            default: is_default,
        });
    }
    result
}

/// Volumen en % del target (regex Python: primer [0-9.]+ * 100).
fn volume(target: &str) -> f64 {
    let text = run_checked(&["wpctl", "get-volume", target]);
    for line in text.lines() {
        if let Some(idx) = line.find(|c: char| c.is_ascii_digit()) {
            let rest = &line[idx..];
            let num: String = rest
                .chars()
                .take_while(|c| c.is_ascii_digit() || *c == '.')
                .collect();
            if let Ok(v) = num.parse::<f64>() {
                return v * 100.0;
            }
        }
    }
    100.0
}

/// True si el target está muteado (la salida de get-volume contiene "MUTED").
fn muted(target: &str) -> bool {
    run_checked(&["wpctl", "get-volume", target]).contains("MUTED")
}

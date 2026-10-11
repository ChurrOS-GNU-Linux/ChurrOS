// ==========================================
// ConnectivityService
// (equivalente a services/connectivity.py + backends/networkmanager.py +
//  backends/bluetooth.py + services/wifi.py)
// ==========================================

use std::io::Read;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

// ---------------------------------------------------------------- helpers

/// NetworkManagerBackend._run: check_output con stderr devnull; None si falla.
fn nm_run(args: &[&str]) -> Option<String> {
    let mut child = Command::new(args[0])
        .args(&args[1..])
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;

    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break st,
            Ok(None) => {}
            Err(_) => {
                let _ = child.kill();
                return None;
            }
        }
        if start.elapsed() > Duration::from_secs(2) {
            let _ = child.kill();
            let _ = child.wait();
            return None;
        }
        std::thread::sleep(Duration::from_millis(20));
    };
    if !status.success() {
        return None;
    }
    let mut buf = String::new();
    if let Some(mut out) = child.stdout.take() {
        let _ = out.read_to_string(&mut buf);
    }
    Some(buf.trim().to_string())
}

/// WifiService._run: devuelve (returncode, stdout, stderr) con timeout 5s.
fn wifi_run(args: &[&str]) -> (i32, String, String) {
    let mut child = match Command::new(args[0])
        .args(&args[1..])
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(c) => c,
        Err(_) => return (1, String::new(), "execution error".to_string()),
    };

    let start = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break st,
            Ok(None) => {}
            Err(_) => {
                let _ = child.kill();
                return (1, String::new(), "execution error".to_string());
            }
        }
        if start.elapsed() > Duration::from_secs(5) {
            let _ = child.kill();
            let _ = child.wait();
            return (1, String::new(), "execution error".to_string());
        }
        std::thread::sleep(Duration::from_millis(20));
    };

    let mut stdout = String::new();
    if let Some(mut s) = child.stdout.take() {
        let _ = s.read_to_string(&mut stdout);
    }
    let mut stderr = String::new();
    if let Some(mut s) = child.stderr.take() {
        let _ = s.read_to_string(&mut stderr);
    }
    (
        status.code().unwrap_or(1),
        stdout.trim().to_string(),
        stderr.trim().to_string(),
    )
}

/// Comandos de cambio (nmcli radio / bluetoothctl power). status() evita zombis.
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

// ---------------------------------------------------------------- modelos

/// Red Wi-Fi con los campos que usa la página (services/wifi.py get()).
pub struct NetworkInfo {
    pub ssid: String,
    pub signal: i64,
    pub security: String,
    pub connected: bool,
    pub saved: bool,
}

pub struct BluetoothDevice {
    pub mac: String,
    pub name: String,
}

// ---------------------------------------------------------------- servicio

pub struct ConnectivityService;

impl ConnectivityService {
    // ------------------------------- Wi-Fi (NetworkManagerBackend)

    /// True si NetworkManager está activo y hay un dispositivo wifi.
    pub fn wifi_available() -> bool {
        if !Self::nm_running() {
            return false;
        }
        match nm_run(&["nmcli", "-t", "-f", "TYPE", "device"]) {
            Some(out) => out.lines().any(|l| l.contains("wifi")),
            None => false,
        }
    }

    fn nm_running() -> bool {
        if !which("nmcli") {
            return false;
        }
        nm_run(&["systemctl", "is-active", "NetworkManager"]) == Some("active".to_string())
    }

    /// True si la radio wifi está encendida.
    pub fn wifi_enabled() -> bool {
        if !Self::wifi_available() {
            return false;
        }
        match nm_run(&["nmcli", "radio", "wifi"]) {
            Some(out) => out.eq_ignore_ascii_case("enabled"),
            None => false,
        }
    }

    pub fn set_wifi(enabled: bool) {
        run_no_output(&["nmcli", "radio", "wifi", if enabled { "on" } else { "off" }]);
    }

    /// Fuerza un reescaneo de redes Wi-Fi (nmcli device wifi rescan).
    pub fn rescan_wifi() {
        run_no_output(&["nmcli", "device", "wifi", "rescan"]);
    }

    /// SSID de la red activa, si hay.
    pub fn current_network() -> Option<String> {
        if !Self::wifi_available() {
            return None;
        }
        let out = nm_run(&["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"])?;
        for line in out.lines() {
            let mut parts = line.splitn(2, ':');
            let active = parts.next().unwrap_or("");
            let ssid = parts.next().unwrap_or("");
            if active == "yes" {
                return Some(ssid.to_string());
            }
        }
        None
    }

    /// Lista de redes con ssid/signal/security/connected/saved
    /// (equivalente a WifiService.get()["networks"]; el Python hace fallback al
    /// backend básico solo si no puede importar services/wifi.py — en Rust el
    /// parser completo está siempre disponible, así que se usa siempre).
    pub fn wifi_networks_full() -> Vec<NetworkInfo> {
        let (code, out, _) = wifi_run(&[
            "nmcli",
            "--escape",
            "yes",
            "-t",
            "-f",
            "ACTIVE,SSID,SIGNAL,SECURITY",
            "device",
            "wifi",
            "list",
            "--rescan",
            "no",
        ]);
        if code != 0 {
            return Vec::new();
        }

        let saved = Self::saved_networks();

        let mut networks = Vec::new();
        for line in out.lines() {
            if line.is_empty() {
                continue;
            }
            let fields = parse_escaped_fields(line);
            let mut fields = fields.into_iter();
            let active = fields.next().unwrap_or_default();
            let ssid = fields.next().unwrap_or_default();
            let signal = fields.next().unwrap_or_default();
            let security = fields.next().unwrap_or_default();

            let ssid = ssid;
            let ssid_final = if ssid.is_empty() { "Hidden Network".to_string() } else { ssid };
            let signal = parse_signal(&signal);

            let network = NetworkInfo {
                connected: active == "yes",
                saved: saved.contains(&ssid_final),
                ssid: ssid_final,
                signal,
                security,
            };
            networks.push(network);
        }

        // Dedup por ssid + orden: conectadas, guardadas, señal descendente
        let mut seen = std::collections::HashSet::new();
        let mut deduped: Vec<NetworkInfo> = Vec::new();
        for n in networks {
            if seen.contains(&n.ssid) {
                continue;
            }
            seen.insert(n.ssid.clone());
            deduped.push(n);
        }
        deduped.sort_by(|a, b| {
            b.connected
                .cmp(&a.connected)
                .then(b.saved.cmp(&a.saved))
                .then(b.signal.cmp(&a.signal))
        });
        deduped
    }

    /// Nombres de conexiones wifi guardadas (802-11-wireless).
    fn saved_networks() -> std::collections::HashSet<String> {
        let mut saved = std::collections::HashSet::new();
        let (code, out, _) = wifi_run(&[
            "nmcli",
            "--escape",
            "yes",
            "-t",
            "-f",
            "NAME,TYPE",
            "connection",
            "show",
        ]);
        if code != 0 {
            return saved;
        }
        for line in out.lines() {
            let fields = parse_escaped_fields(line);
            if fields.len() >= 2 && fields[1] == "802-11-wireless" {
                saved.insert(fields[0].clone());
            }
        }
        saved
    }

    /// Conecta a una red (con o sin contraseña). (ok, mensaje de error en inglés
    /// — paridad con services/wifi.py connect()).
    pub fn wifi_connect(ssid: &str, password: Option<&str>) -> (bool, String) {
        let mut args = vec!["nmcli", "device", "wifi", "connect", ssid];
        if let Some(pw) = password {
            args.extend(["password", pw]);
        }
        let (code, _, err) = wifi_run(&args);
        if code == 0 {
            return (true, String::new());
        }
        let err = err.to_lowercase();
        if err.contains("secrets were required") {
            return (false, "Password required.".to_string());
        }
        if err.contains("invalid") {
            return (false, "Incorrect password.".to_string());
        }
        if err.contains("activation") {
            return (false, "Unable to connect.".to_string());
        }
        (false, "Unknown error.".to_string())
    }

    /// Desconecta el dispositivo wifi (si hay).
    pub fn wifi_disconnect() {
        let (code, out, _) = wifi_run(&["nmcli", "-t", "-f", "DEVICE,TYPE", "device"]);
        if code != 0 {
            return;
        }
        for line in out.lines() {
            let mut parts = line.splitn(2, ':');
            let device = parts.next().unwrap_or("");
            let dev_type = parts.next().unwrap_or("");
            if dev_type == "wifi" {
                let _ = wifi_run(&["nmcli", "device", "disconnect", device]);
                break;
            }
        }
    }

    /// Olvida una red guardada.
    pub fn wifi_forget(ssid: &str) {
        let _ = wifi_run(&["nmcli", "connection", "delete", ssid]);
    }

    // ------------------------------- Bluetooth (BluetoothBackend)

    /// True si bluetoothctl existe, el servicio está activo y hay adaptador.
    pub fn bluetooth_available() -> bool {
        if !Self::bt_running() {
            return false;
        }
        match nm_run(&["bluetoothctl", "list"]) {
            Some(out) => !out.is_empty(),
            None => false,
        }
    }

    fn bt_running() -> bool {
        if !which("bluetoothctl") {
            return false;
        }
        nm_run(&["systemctl", "is-active", "bluetooth"]) == Some("active".to_string())
    }

    /// True si el adaptador está encendido (Powered: yes).
    pub fn bluetooth_enabled() -> bool {
        if !Self::bluetooth_available() {
            return false;
        }
        let out = match nm_run(&["bluetoothctl", "show"]) {
            Some(o) => o,
            None => return false,
        };
        for line in out.lines() {
            let t = line.trim();
            if let Some(rest) = t.strip_prefix("Powered:") {
                return rest.trim().eq_ignore_ascii_case("yes");
            }
        }
        false
    }

    pub fn set_bluetooth(enabled: bool) {
        if !Self::bluetooth_available() {
            return;
        }
        run_no_output(&["bluetoothctl", "power", if enabled { "on" } else { "off" }]);
    }

    /// Dispositivos emparejados conocidos (bluetoothctl devices).
    pub fn bluetooth_devices() -> Vec<BluetoothDevice> {
        if !Self::bluetooth_available() {
            return Vec::new();
        }
        let out = match nm_run(&["bluetoothctl", "devices"]) {
            Some(o) => o,
            None => return Vec::new(),
        };
        let mut devices = Vec::new();
        for line in out.lines() {
            if !line.starts_with("Device") {
                continue;
            }
            let mut parts = line.split_whitespace();
            parts.next(); // "Device"
            let mac = parts.next().unwrap_or("").to_string();
            let name = parts.collect::<Vec<_>>().join(" ");
            if mac.is_empty() {
                continue;
            }
            devices.push(BluetoothDevice { mac, name });
        }
        devices
    }
}

// ---------------------------------------------------------------- parsers

/// Parsea una línea nmcli con escaping activado (--escape yes):
/// `\:` -> `:`, `\\` -> `\`, `:` separa campos.
fn parse_escaped_fields(line: &str) -> Vec<String> {
    let mut fields = Vec::new();
    let mut current = String::new();
    let mut chars = line.chars();
    while let Some(ch) = chars.next() {
        if ch == '\\' {
            if let Some(n) = chars.next() {
                current.push(n);
            }
        } else if ch == ':' {
            fields.push(std::mem::take(&mut current));
        } else {
            current.push(ch);
        }
    }
    fields.push(current);
    fields
}

/// int(signal) si es numérico (permite "-80"); si no, 0.
fn parse_signal(signal: &str) -> i64 {
    let s = signal.trim_start_matches('-');
    if !s.is_empty() && s.chars().all(|c| c.is_ascii_digit()) {
        signal.parse::<i64>().unwrap_or(0)
    } else {
        0
    }
}

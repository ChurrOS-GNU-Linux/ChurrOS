// Servicio de wifi vía nmcli (equivalente a services/wifi.py)

use crate::{run, spawn};

fn unescape(s: &str) -> String {
    s.replace("\\:", ":")
}

#[derive(Debug, Clone, PartialEq)]
pub struct Network {
    pub ssid: String,
    pub signal: u8,
    pub security: String,
    pub connected: bool,
    pub saved: bool,
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct WifiInfo {
    pub available: bool,
    pub enabled: bool,
    pub connected: Option<String>,
    pub networks: Vec<Network>,
}

fn run_stdout(command: &[&str]) -> Option<(i32, String)> {
    let (code, out, _) = run(command, 5000)?;
    Some((code, out))
}

pub fn available() -> bool {
    if let Ok(entries) = std::fs::read_dir("/sys/class/net") {
        for entry in entries.flatten() {
            if entry.path().join("wireless").is_dir() {
                return true;
            }
        }
    }
    let (code, out) = run_stdout(&["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
        .unwrap_or((1, String::new()));
    if code != 0 {
        return false;
    }
    out.lines().any(|line| {
        line.splitn(2, ':').nth(1) == Some("wifi")
    })
}

pub fn enabled() -> bool {
    let (code, out) = run_stdout(&["nmcli", "radio", "wifi"])
        .unwrap_or((1, String::new()));
    code == 0 && out.trim().to_lowercase() == "enabled"
}

pub fn scan() {
    if available() {
        spawn(&["nmcli", "device", "wifi", "rescan"]);
    }
}

/// Parsea una línea de nmcli --escape yes -t: respeta los `\:` escapados.
fn parse_escaped(line: &str) -> Vec<String> {
    let mut fields = Vec::new();
    let mut current = String::new();
    let mut escape = false;

    for ch in line.chars() {
        if escape {
            current.push(ch);
            escape = false;
        } else if ch == '\\' {
            escape = true;
        } else if ch == ':' {
            fields.push(std::mem::take(&mut current));
        } else {
            current.push(ch);
        }
    }
    fields.push(current);

    fields
}

fn saved_networks() -> Vec<String> {
    let mut saved = Vec::new();
    let (code, out) = run_stdout(&["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
        .unwrap_or((1, String::new()));
    if code != 0 {
        return saved;
    }
    for line in out.lines() {
        if let Some((name, conn_type)) = line.split_once(':') {
            if conn_type == "802-11-wireless" {
                saved.push(name.to_string());
            }
        }
    }
    saved
}

pub fn get() -> WifiInfo {
    let mut data = WifiInfo {
        available: available(),
        enabled: enabled(),
        ..Default::default()
    };

    if !data.available || !data.enabled {
        return data;
    }

    let (code, out) = run_stdout(&[
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
    ])
    .unwrap_or((1, String::new()));

    if code != 0 {
        return data;
    }

    let saved = saved_networks();

    for line in out.lines() {
        if line.is_empty() {
            continue;
        }

        let fields = parse_escaped(line);
        let active = fields.first().map(|s| s.as_str()).unwrap_or("");
        let ssid = fields.get(1).map(|s| unescape(s)).unwrap_or_default();
        let signal = fields
            .get(2)
            .and_then(|s| s.trim_start_matches('-').parse::<u8>().ok())
            .unwrap_or(0);
        let security = unescape(fields.get(3).map(|s| s.as_str()).unwrap_or(""));

        let network = Network {
            ssid: if ssid.is_empty() {
                "Hidden Network".to_string()
            } else {
                ssid.clone()
            },
            signal,
            security,
            connected: active == "yes",
            saved: saved.contains(&ssid),
        };

        if network.connected {
            data.connected = Some(network.ssid.clone());
        }

        data.networks.push(network);
    }

    let mut seen = std::collections::HashSet::new();
    data.networks.retain(|n| seen.insert(n.ssid.clone()));

    data.networks.sort_by_key(|n| {
        (
            !n.connected,
            !n.saved,
            std::cmp::Reverse(n.signal),
        )
    });

    data
}

fn connect_error(code: i32, err: &str) -> (bool, String) {
    if code == 0 {
        return (true, String::new());
    }
    let err = err.to_lowercase();
    if err.contains("secrets were required") {
        (false, "Password required.".to_string())
    } else if err.contains("invalid") {
        (false, "Incorrect password.".to_string())
    } else if err.contains("activation") {
        (false, "Unable to connect.".to_string())
    } else {
        (false, "Unknown error.".to_string())
    }
}

pub fn connect(ssid: &str, password: Option<&str>) -> (bool, String) {
    let mut command = vec![
        "nmcli".to_string(),
        "device".to_string(),
        "wifi".to_string(),
        "connect".to_string(),
        ssid.to_string(),
    ];
    if let Some(pw) = password {
        command.extend(["password".to_string(), pw.to_string()]);
    }
    let args: Vec<&str> = command.iter().map(|s| s.as_str()).collect();
    let (code, _, err) = run(&args, 5000).unwrap_or((1, String::new(), "execution error".to_string()));
    connect_error(code, &err)
}

pub fn connect_hidden(ssid: &str, password: Option<&str>) -> (bool, String) {
    let (code, _, _err) = run(
        &[
            "nmcli",
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            "wlan0",
            "con-name",
            ssid,
            "ssid",
            ssid,
            "hidden",
            "yes",
        ],
        5000,
    )
    .unwrap_or((1, String::new(), "execution error".to_string()));

    if code != 0 {
        return (false, "Failed to create hidden profile.".to_string());
    }

    let mut command = vec![
        "nmcli".to_string(),
        "connection".to_string(),
        "up".to_string(),
        ssid.to_string(),
    ];
    if let Some(pw) = password {
        command.extend(["password".to_string(), pw.to_string()]);
    }
    let args: Vec<&str> = command.iter().map(|s| s.as_str()).collect();
    let (code, _, err) = run(&args, 5000).unwrap_or((1, String::new(), "execution error".to_string()));
    connect_error(code, &err)
}

pub fn disconnect() {
    let (code, out) = run_stdout(&["nmcli", "-t", "-f", "DEVICE,TYPE", "device"])
        .unwrap_or((1, String::new()));
    if code != 0 {
        return;
    }
    for line in out.lines() {
        if let Some((device, dev_type)) = line.split_once(':') {
            if dev_type == "wifi" {
                let _ = run(&["nmcli", "device", "disconnect", device], 5000);
                break;
            }
        }
    }
}

pub fn forget(ssid: &str) {
    let _ = run(&["nmcli", "connection", "delete", ssid], 5000);
}

pub fn enable() {
    let _ = run(&["nmcli", "radio", "wifi", "on"], 5000);
}

pub fn disable() {
    let _ = run(&["nmcli", "radio", "wifi", "off"], 5000);
}

pub fn toggle() {
    if enabled() {
        disable();
    } else {
        enable();
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct ActiveWifiInfo {
    pub connected: bool,
    pub ssid: String,
    pub signal: u8,
    pub speed: String,
    pub device: String,
}

pub fn get_active() -> ActiveWifiInfo {
    let mut wifi_device = String::new();
    if let Ok(entries) = std::fs::read_dir("/sys/class/net") {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.join("wireless").is_dir() {
                wifi_device = entry.file_name().to_string_lossy().to_string();
                break;
            }
        }
    }

    if wifi_device.is_empty() {
        if !available() {
            return ActiveWifiInfo::default();
        }
        wifi_device = "wlan0".to_string();
    }

    // 1. Try `iw dev <dev> link` first (fastest, ~4ms)
    if crate::which("iw") {
        if let Some((0, out, _)) = crate::run(&["iw", "dev", &wifi_device, "link"], 1000) {
            if !out.contains("Not connected") && out.contains("SSID:") {
                let mut ssid = String::new();
                let mut signal = 0u8;
                let mut speed = String::new();

                for line in out.lines() {
                    let line = line.trim();
                    if let Some(rest) = line.strip_prefix("SSID: ") {
                        ssid = rest.to_string();
                    } else if let Some(rest) = line.strip_prefix("signal: ") {
                        if let Some(dbm_str) = rest.split_whitespace().next() {
                            if let Ok(dbm) = dbm_str.parse::<i32>() {
                                let pct = if dbm <= -100 {
                                    0
                                } else if dbm >= -50 {
                                    100
                                } else {
                                    2 * (dbm + 100)
                                };
                                signal = pct as u8;
                            }
                        }
                    } else if line.contains("bitrate:") {
                        if speed.is_empty() || line.starts_with("tx bitrate:") {
                            if let Some(idx) = line.find("bitrate:") {
                                let rest = line[idx + 8..].trim();
                                let parts: Vec<&str> = rest.split_whitespace().collect();
                                if parts.len() >= 2 {
                                    speed = format!("{} {}", parts[0], parts[1]);
                                }
                            }
                        }
                    }
                }

                if !ssid.is_empty() {
                    return ActiveWifiInfo {
                        connected: true,
                        ssid,
                        signal,
                        speed,
                        device: wifi_device,
                    };
                }
            }
        }
    }

    // 2. Fallback to nmcli fast wifi query
    if let Some((0, out, _)) = crate::run(
        &[
            "nmcli",
            "-t",
            "-f",
            "IN-USE,SSID,SIGNAL,RATE,DEVICE",
            "device",
            "wifi",
            "list",
            "--rescan",
            "no",
        ],
        1500,
    ) {
        for line in out.lines() {
            if line.starts_with('*') || line.starts_with("sí:") || line.starts_with("yes:") {
                let fields = parse_escaped(line);
                let ssid = fields.get(1).map(|s| unescape(s)).unwrap_or_default();
                let signal = fields
                    .get(2)
                    .and_then(|s| s.parse::<u8>().ok())
                    .unwrap_or(0);
                let speed = fields.get(3).map(|s| unescape(s)).unwrap_or_default();
                let dev = fields.get(4).cloned().unwrap_or_else(|| wifi_device.clone());
                return ActiveWifiInfo {
                    connected: true,
                    ssid,
                    signal,
                    speed,
                    device: dev,
                };
            }
        }
    }

    ActiveWifiInfo::default()
}

#[derive(Debug, Clone, Copy, Default)]
pub struct NetThroughput {
    pub rx_bytes: u64,
    pub tx_bytes: u64,
}

pub fn read_interface_bytes(device: &str) -> Option<NetThroughput> {
    let content = std::fs::read_to_string("/proc/net/dev").ok()?;
    for line in content.lines() {
        if let Some((iface, stats)) = line.split_once(':') {
            if iface.trim() == device {
                let parts: Vec<&str> = stats.split_whitespace().collect();
                let rx_bytes = parts.get(0)?.parse::<u64>().ok()?;
                let tx_bytes = parts.get(8)?.parse::<u64>().ok()?;
                return Some(NetThroughput { rx_bytes, tx_bytes });
            }
        }
    }
    None
}

pub fn format_bytes_rate(bytes_per_sec: u64) -> String {
    if bytes_per_sec >= 1_000_000 {
        format!("{:.1} MB/s", bytes_per_sec as f64 / 1_000_000.0)
    } else if bytes_per_sec >= 1_000 {
        format!("{:.0} KB/s", bytes_per_sec as f64 / 1_000.0)
    } else {
        format!("{} B/s", bytes_per_sec)
    }
}


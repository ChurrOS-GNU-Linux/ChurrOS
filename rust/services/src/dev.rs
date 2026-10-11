// Host-preview dry-run (CHURROS_DEV=1). Reads stay live; writes are logged
// and skipped so ./churros apps cannot change the developer machine.

pub fn enabled() -> bool {
    matches!(std::env::var("CHURROS_DEV").as_deref(), Ok("1"))
}

pub fn log_blocked(cmd: &[&str]) {
    eprintln!("[churros-dev] blocked: {}", cmd.join(" "));
}

fn bin_name(cmd: &str) -> &str {
    std::path::Path::new(cmd)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or(cmd)
}

fn has_arg(args: &[&str], needle: &str) -> bool {
    args.iter().any(|a| *a == needle)
}

fn nmcli_mutates(args: &[&str]) -> bool {
    let mut i = 0;
    while i < args.len() {
        let a = args[i];
        if a == "-f" || a == "--fields" || a == "-g" || a == "--get-values" {
            i += 2;
            continue;
        }
        if a.starts_with('-') {
            i += 1;
            continue;
        }
        match a {
            "connect" | "disconnect" | "delete" | "modify" | "add" | "edit" | "up" | "down"
            | "rescan" | "reload" | "on" | "off" => return true,
            _ => i += 1,
        }
    }
    false
}

fn systemctl_mutates(args: &[&str]) -> bool {
    const READS: &[&str] = &[
        "is-active",
        "is-enabled",
        "is-failed",
        "status",
        "show",
        "cat",
        "list-units",
        "list-unit-files",
        "list-timers",
        "show-environment",
        "--version",
        "help",
    ];
    !args.iter().any(|a| READS.contains(a))
}

fn bluetoothctl_mutates(args: &[&str]) -> bool {
    const READS: &[&str] = &["show", "devices", "info", "list", "paired-devices", "help"];
    let mut i = 0;
    while i < args.len() {
        let a = args[i];
        if a == "--timeout" {
            i += 2;
            continue;
        }
        if a.starts_with('-') {
            i += 1;
            continue;
        }
        return !READS.contains(&a);
    }
    false
}

/// True when running the command would change this machine.
pub fn is_mutation(cmd: &[&str]) -> bool {
    if cmd.is_empty() {
        return true;
    }
    let bin = bin_name(cmd[0]);
    let args = &cmd[1..];
    match bin {
        "nmcli" => nmcli_mutates(args),
        "wpctl" => args.iter().any(|a| a.starts_with("set-")),
        "brightnessctl" => has_arg(args, "set") || has_arg(args, "s"),
        "bluetoothctl" => bluetoothctl_mutates(args),
        "rfkill" => has_arg(args, "block") || has_arg(args, "unblock"),
        "systemctl" => systemctl_mutates(args),
        "loginctl" => args.iter().any(|a| {
            a.starts_with("lock") || a.starts_with("terminate") || a.starts_with("kill")
        }),
        "gsettings" => matches!(args.first().copied(), Some("set") | Some("reset")),
        "dconf" => matches!(args.first().copied(), Some("write") | Some("reset")),
        "timedatectl" => args.iter().any(|a| a.starts_with("set-")),
        "ufw" => !has_arg(args, "status"),
        "pacman" => !args.iter().any(|a| *a == "-Q" || a.starts_with("-Q")),
        "flatpak" => has_arg(args, "update") || has_arg(args, "install") || has_arg(args, "remove"),
        "swapon" => !args.iter().any(|a| *a == "--show"),
        "niri" => has_arg(args, "action") || has_arg(args, "quit"),
        "hyprctl" => has_arg(args, "dispatch"),
        "id" | "date" | "pgrep" | "fc-list" | "lspci" | "curl" | "notify-send" => false,
        // Sincroniza una copia temporal de las bases de pacman, sin root.
        "checkupdates" => false,
        "xdg-open" | "thunar" => false,
        "sh" | "bash" => !args.iter().any(|a| a.contains("command -v")),
        "pkill" | "kill" | "killall" | "pkexec" | "sudo" | "churros-pkexec" | "calamares"
        | "wal" | "makoctl" | "swaymsg" | "swaybg" | "swaylock" | "swayidle" | "wlsunset"
        | "waybar" | "install" | "foot" | "churros-apply-wallpaper" | "waypaper"
        | "churros-update-utils" | "churros-pick-image" => true,
        _ => true,
    }
}

#[cfg(test)]
mod tests {
    use super::is_mutation;

    #[test]
    fn reads_are_live() {
        assert!(!is_mutation(&["nmcli", "-t", "-f", "DEVICE,TYPE", "device"]));
        assert!(!is_mutation(&["nmcli", "radio", "wifi"]));
        assert!(!is_mutation(&["wpctl", "status"]));
        assert!(!is_mutation(&["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]));
        assert!(!is_mutation(&["brightnessctl", "g"]));
        assert!(!is_mutation(&["bluetoothctl", "show"]));
        assert!(!is_mutation(&["bluetoothctl", "devices"]));
        assert!(!is_mutation(&["systemctl", "is-active", "NetworkManager"]));
        assert!(!is_mutation(&[
            "systemctl",
            "--user",
            "is-enabled",
            "churros-update.timer"
        ]));
        assert!(!is_mutation(&[
            "gsettings",
            "get",
            "org.gnome.desktop.interface",
            "gtk-theme"
        ]));
        assert!(!is_mutation(&["id", "-u"]));
        assert!(!is_mutation(&["swapon", "--show", "--noheadings"]));
        assert!(!is_mutation(&["rfkill", "list", "bluetooth"]));
        assert!(!is_mutation(&["pacman", "-Q"]));
        assert!(!is_mutation(&["checkupdates"]));
        assert!(!is_mutation(&[
            "sh",
            "-c",
            "command -v swaylock >/dev/null 2>&1"
        ]));
    }

    #[test]
    fn writes_are_dummy() {
        assert!(is_mutation(&["nmcli", "radio", "wifi", "off"]));
        assert!(is_mutation(&["nmcli", "device", "disconnect", "wlan0"]));
        assert!(is_mutation(&["nmcli", "device", "wifi", "connect", "x"]));
        assert!(is_mutation(&["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "50%"]));
        assert!(is_mutation(&["brightnessctl", "set", "50%"]));
        assert!(is_mutation(&["bluetoothctl", "power", "off"]));
        assert!(is_mutation(&["bluetoothctl", "connect", "AA:BB"]));
        assert!(is_mutation(&["systemctl", "poweroff"]));
        assert!(is_mutation(&["systemctl", "--user", "enable", "--now", "x.timer"]));
        assert!(is_mutation(&[
            "gsettings",
            "set",
            "org.gnome.desktop.interface",
            "color-scheme",
            "prefer-dark"
        ]));
        assert!(is_mutation(&["pkill", "waybar"]));
        assert!(is_mutation(&["pkexec", "calamares"]));
        assert!(is_mutation(&["loginctl", "lock-session"]));
        assert!(is_mutation(&["niri", "msg", "action", "quit"]));
        assert!(is_mutation(&[
            "sh",
            "-c",
            "for pid in $(pgrep -x gnome-shell); do kill -USR1 $pid; done"
        ]));
        assert!(is_mutation(&["foot", "-e", "sudo", "pacman", "-Syu"]));
        assert!(is_mutation(&["churros-apply-wallpaper", "/tmp/wp.jpg"]));
    }
}
